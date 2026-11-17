"""
The second lab: the course's wheel as the body, ideas from outside the course
as the parts.

    python -m gearwheel.lab2        ->  docs/gear/lab2.json

Bases (from the first lab, gearwheel/lab.py):
    wheel       1.4's wheel
    earn        + the earnings blackout
    live        + the earnings blackout + the OI strike  (what trades now)

New parts, none from the course (gearwheel/external.py has the signals):
    vix         no new put while VIX > VIX3M (CBOE term structure inverted)
    credit      no new put while the Baa-Treasury spread (FRED) is above its
                200-day average
    size        puts scaled by min(1, 1-year median vol / today's vol)
                (Moreira & Muir 2017)
    defend      roll a put down and out at delta -0.70 instead of taking
                assignment (a desk habit)

3 x 2^4 = 48 candidates.

The selection rule, fixed before the run
----------------------------------------
The new parts are mostly risk controls, so this lab judges on Sharpe, not on
return:
1. Rank the 48 by Sharpe on 1.4's window (3 Jan 2022 - 30 Sep 2025).
2. Take the top five. Each must beat the rule that trades now ("live", all
   new parts off) (a) on Sharpe over the new tape (1 Oct 2025 on), and (b) on
   full-period Sharpe in at least 6 of the 9 delta x fill robustness cells.
3. The winner is the highest-ranked finalist that passes both. If none does,
   the live rule stays.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from wheel.book import HEADLINE, perf, run

from . import external as ex
from .backtest import KAPPA, SPLIT, signal_px
from .lab import ROBUST, Lab

OUT = Path(__file__).resolve().parents[1] / "docs" / "gear" / "lab2.json"
BASES = {
    "wheel": {"earnings": "none", "gear": "off", "ivrv": "off", "oi": "off"},
    "earn": {"earnings": "both", "gear": "off", "ivrv": "off", "oi": "off"},
    "live": {"earnings": "both", "gear": "off", "ivrv": "off", "oi": "on"},
}
NEW = ("vix", "credit", "size", "defend")
DEFEND = 0.70
TOP, NEED = 5, 6
BASE_LABEL = {"wheel": "1.4 wheel", "earn": "wheel + earnings", "live": "live (wheel + earnings + OI)"}
PART_LABEL = {"vix": "VIX pause", "credit": "credit pause", "size": "vol sizing", "defend": "defend roll"}


def key(c: dict) -> str:
    return c["base"] + "|" + "|".join(f"{p}={'on' if c[p] else 'off'}" for p in NEW)


def label(c: dict) -> str:
    on = [PART_LABEL[p] for p in NEW if c[p]]
    return BASE_LABEL[c["base"]] + ("" if not on else " + " + " + ".join(on))


class Lab2(Lab):
    def __init__(self):
        super().__init__()
        self.ext = ex.snapshot()
        sessions = [d for d in self.m.calendar]
        self.pauses = {(v, c): ex.pause_map(self.ext, sessions, v, c)
                       for v in (False, True) for c in (False, True) if v or c}
        self.scale = ex.size_map(signal_px(self.raw))

    def run2(self, c: dict, delta: float = 0.30, kappa: float = KAPPA):
        b = BASES[c["base"]]
        p = replace(HEADLINE, kappa=kappa, put_delta=delta, call_delta=delta)
        return run(self.m, p,
                   earnings=None if b["earnings"] == "none" else self.earn,
                   oi_wall=b["oi"] == "on",
                   pause=self.pauses.get((c["vix"], c["credit"])),
                   size_scale=self.scale if c["size"] else None,
                   defend=DEFEND if c["defend"] else None)


def main() -> dict:
    lab = Lab2()
    combos = [{"base": b, **dict(zip(NEW, flags))}
              for b in BASES for flags in itertools.product((False, True), repeat=len(NEW))]
    rows = []
    for c in combos:
        r = lab.run2(c)
        led = pd.DataFrame(r.ledger)
        rows.append({"key": key(c), "label": label(c), **c, "stats": lab.windows(led),
                     "defends": sum(1 for t in r.trades if t["rule"] == "DEFEND"),
                     "idle_pct": round(float((led["phase"] == "cash").mean() * 100), 1)})
    by = {r["key"]: r for r in rows}
    live_c = {"base": "live", **{p: False for p in NEW}}
    live = by[key(live_c)]

    ranked = sorted(rows, key=lambda r: -(r["stats"]["found"]["sharpe"] or -9))
    for i, r in enumerate(ranked, 1):
        r["rank_found"] = i

    live_cells = {(d, k): perf(lab.m, pd.DataFrame(lab.run2(live_c, d, k).ledger))["sharpe"]
                  for d, k in ROBUST}
    finalists = []
    for r in ranked[:TOP]:
        c = {"base": r["base"], **{p: r[p] for p in NEW}}
        cells = []
        for d, k in ROBUST:
            sh = perf(lab.m, pd.DataFrame(lab.run2(c, d, k).ledger))["sharpe"]
            cells.append({"delta": d, "kappa": k, "sharpe": sh, "live": live_cells[(d, k)],
                          "beats": bool(sh > live_cells[(d, k)])})
        wins = sum(x["beats"] for x in cells)
        oos = (r["stats"]["new"]["sharpe"] or -9) > (live["stats"]["new"]["sharpe"] or -9)
        finalists.append({"key": r["key"], "label": r["label"], "rank_found": r["rank_found"],
                          "found_sharpe": r["stats"]["found"]["sharpe"],
                          "new_sharpe": r["stats"]["new"]["sharpe"], "new_ret": r["stats"]["new"]["ret_pct"],
                          "full_sharpe": r["stats"]["full"]["sharpe"], "full_mdd": r["stats"]["full"]["max_dd_pct"],
                          "beats_new": bool(oos), "robust_wins": wins, "cells": cells,
                          "passes": bool(oos and wins >= NEED)})
    passing = [f for f in finalists if f["passes"]]
    winner = passing[0]["key"] if passing else live["key"]

    effects = {}
    for part in NEW:
        diffs = []
        for r in rows:
            if r[part]:
                continue
            twin = by[key({"base": r["base"], **{p: r[p] for p in NEW}, part: True})]
            diffs.append({w: (twin["stats"][w][m] or 0) - (r["stats"][w][m] or 0)
                          for w in ("found", "new") for m in ("sharpe",)} |
                         {"mdd_" + w: twin["stats"][w]["max_dd_pct"] - r["stats"][w]["max_dd_pct"]
                          for w in ("found", "full")})
        effects[part] = {
            "found": round(float(np.mean([x["found"] for x in diffs])), 3),
            "new": round(float(np.mean([x["new"] for x in diffs])), 3),
            "helps_found": sum(x["found"] > 0 for x in diffs),
            "helps_new": sum(x["new"] > 0 for x in diffs),
            "mdd_full": round(float(np.mean([x["mdd_full"] for x in diffs])), 2),
            "of": len(diffs)}

    out = {"generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "split": str(SPLIT),
           "end": str(lab.m.end), "kappa": KAPPA, "defend": DEFEND,
           "rule": {"rank_on": "found sharpe", "top": TOP, "robust": ROBUST, "need": NEED,
                    "beat": "live", "metric": "sharpe"},
           "rows": sorted(rows, key=lambda r: r["rank_found"]), "live": live["key"],
           "finalists": finalists, "winner": winner, "winner_label": by[winner]["label"],
           "effects": effects,
           "signals": {"vix_days": len(lab.pauses[(True, False)]),
                       "credit_days": len(lab.pauses[(False, True)]),
                       "sessions": len(lab.m.sessions()),
                       "size_mean": round(float(np.mean([lab.scale.get(d, 1.0) for d in lab.m.sessions()])), 3)}}
    OUT.write_text(json.dumps(out, separators=(",", ":"), default=str))

    show = pd.DataFrame([{"rank": r["rank_found"], "candidate": r["label"],
                          "found_SR": r["stats"]["found"]["sharpe"], "new_SR": r["stats"]["new"]["sharpe"],
                          "new_ret": r["stats"]["new"]["ret_pct"], "full_CAGR": r["stats"]["full"]["cagr_pct"],
                          "full_SR": r["stats"]["full"]["sharpe"], "mdd": r["stats"]["full"]["max_dd_pct"],
                          "defends": r["defends"], "idle%": r["idle_pct"]} for r in out["rows"]])
    print(show.to_string(index=False))
    print("\nfinalists (must beat live: new-tape Sharpe "
          f"{live['stats']['new']['sharpe']}, full Sharpe {live['stats']['full']['sharpe']}):")
    for f in finalists:
        print(f"  #{f['rank_found']} {f['label']}: new SR {f['new_sharpe']} ({'beats' if f['beats_new'] else 'no'}), "
              f"robust {f['robust_wins']}/9 -> {'PASS' if f['passes'] else 'fail'}")
    print("winner:", out["winner_label"])
    print("effects:", json.dumps(effects))
    return out


if __name__ == "__main__":
    main()
