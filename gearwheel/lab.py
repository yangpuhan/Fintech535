"""
The combination lab: cross the semester's parts, compare, pick one.

    python -m gearwheel.lab        ->  docs/gear/lab.json

Every candidate is 1.4's wheel (0.30-delta puts on cash, 0.30-delta calls at
or above the basis, profit-take at 50%, the measured fill) with four
switchable parts, each taken from something this course already did:

    earnings   none | both | calls      1.2's 31 July call; 1.3 and 1.4 found
                                        the call leg is the one that loses
    gear       off | B | A              the in-class realised-vol pipeline and
                                        the 1.2-1.4 finding that calls cap
                                        rallies (gearwheel/signals.py)
    iv>rv      off | on                 1.4: the put was priced above realised
                                        vol in 32 of 43 months; sell only then
    oi         off | on                 this week's OI clusters: the strike
                                        with the most open interest inside
                                        0.20-0.40 |delta|

3 x 3 x 2 x 2 = 36 candidates; the all-off one is 1.4's wheel. Controls:
put-write, buy-write, puts-then-hold (sell puts until assigned, then own the
shares and never write a call), buy & hold, T-bills.

The selection rule, fixed before the lab was run
-------------------------------------------------
1. Rank the 36 by Sharpe on 1.4's window only (3 Jan 2022 - 30 Sep 2025).
2. Take the top five. For each: (a) its return on the new tape (1 Oct 2025
   on, pulled after every part was written) must beat 1.4's wheel's; (b) on
   a 3 x 3 robustness grid - delta 0.25/0.30/0.35 x fill k 0.30/0.57/0.80 -
   its full-period Sharpe must beat the wheel's in the same cell at least 6
   times in 9.
3. The winner is the highest-ranked of the five that passes both. If none
   does, the answer is 1.4's wheel, unchanged.

Disclosure: two of the parts (earnings both-sides, gear A/B) had already
been run on the new tape before this lab existed. The rule above still
picks on 1.4's window, so that look could not move the ranking, but it did
shape which parts are in the lab.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from wheel.book import HEADLINE, Market, buy_and_hold, perf, run, tbills

from .backtest import KAPPA, SPLIT, load, signal_px
from .signals import gear_map, gears

OUT = Path(__file__).resolve().parents[1] / "docs" / "gear" / "lab.json"

PARTS = {
    "earnings": ("none", "both", "calls"),
    "gear": ("off", "B", "A"),
    "ivrv": ("off", "on"),
    "oi": ("off", "on"),
}
TOP = 5
ROBUST = [(d, k) for d in (0.25, 0.30, 0.35) for k in (0.30, 0.57, 0.80)]
NEED = 6


def key(c: dict) -> str:
    return "|".join(f"{p}={c[p]}" for p in PARTS)


def label(c: dict) -> str:
    bits = []
    if c["earnings"] != "none":
        bits.append("earnings" + ("" if c["earnings"] == "both" else " (calls)"))
    if c["gear"] != "off":
        bits.append(f"gear {c['gear']}")
    if c["ivrv"] == "on":
        bits.append("IV>RV")
    if c["oi"] == "on":
        bits.append("OI strike")
    return "1.4 wheel" + ("" if not bits else " + " + " + ".join(bits))


class Lab:
    def __init__(self):
        self.raw = load()
        self.m = Market(self.raw)
        px = signal_px(self.raw)
        g = gears(px)
        self.gm = gear_map(px)
        self.rv = {t.date(): (v / 100.0 if np.isfinite(v) else None) for t, v in g["rv"].items()}
        self.earn = self.raw["earnings"]
        self.hold_all = {d: "hold" for d in self.m.calendar}

    def run(self, c: dict, delta: float = 0.30, kappa: float = KAPPA):
        p = replace(HEADLINE, kappa=kappa, put_delta=delta, call_delta=delta)
        return run(self.m, p,
                   gear=None if c["gear"] == "off" else self.gm,
                   hold_buys=c["gear"] == "A",
                   earnings=None if c["earnings"] == "none" else self.earn,
                   earn_side=c["earnings"] if c["earnings"] != "none" else "both",
                   iv_rv=self.rv if c["ivrv"] == "on" else None,
                   oi_wall=c["oi"] == "on")

    def windows(self, led: pd.DataFrame) -> dict:
        out = {}
        for w, (a, b) in {"full": (None, None), "found": (None, SPLIT),
                          "new": (SPLIT + dt.timedelta(days=1), None)}.items():
            x = led
            if a is not None:
                before = led[led["date"] < a]
                x = pd.concat([before.tail(1), led[led["date"] >= a]])
            if b is not None:
                x = x[x["date"] <= b]
            x = x.reset_index(drop=True)
            s = perf(self.m, x, opening=float(x["nav"].iloc[0]))
            out[w] = {k: s[k] for k in ("ret_pct", "cagr_pct", "vol_pct", "sharpe", "max_dd_pct")}
        return out


def main() -> dict:
    lab = Lab()
    combos = [dict(zip(PARTS, v)) for v in itertools.product(*PARTS.values())]
    base = {"earnings": "none", "gear": "off", "ivrv": "off", "oi": "off"}

    rows = []
    for c in combos:
        r = lab.run(c)
        led = pd.DataFrame(r.ledger)
        rows.append({"key": key(c), "label": label(c), **c, "stats": lab.windows(led),
                     "shorts": len(r.shorts),
                     "idle_pct": round(float((led["phase"] == "cash").mean() * 100), 1)})
    by = {r["key"]: r for r in rows}
    wheel = by[key(base)]

    ranked = sorted(rows, key=lambda r: -(r["stats"]["found"]["sharpe"] or -9))
    for i, r in enumerate(ranked, 1):
        r["rank_found"] = i

    # step 2: the top five against the wheel, out of sample and off-centre
    wheel_cells = {}
    for d, k in ROBUST:
        led = pd.DataFrame(lab.run(base, d, k).ledger)
        wheel_cells[(d, k)] = perf(lab.m, led)["sharpe"]
    finalists = []
    for r in ranked[:TOP]:
        c = {p: r[p] for p in PARTS}
        cells = []
        for d, k in ROBUST:
            sh = perf(lab.m, pd.DataFrame(lab.run(c, d, k).ledger))["sharpe"]
            cells.append({"delta": d, "kappa": k, "sharpe": sh, "wheel": wheel_cells[(d, k)],
                          "beats": bool(sh > wheel_cells[(d, k)])})
        wins = sum(x["beats"] for x in cells)
        oos = r["stats"]["new"]["ret_pct"] > wheel["stats"]["new"]["ret_pct"]
        finalists.append({"key": r["key"], "label": r["label"], "rank_found": r["rank_found"],
                          "found_sharpe": r["stats"]["found"]["sharpe"],
                          "new_ret": r["stats"]["new"]["ret_pct"],
                          "new_sharpe": r["stats"]["new"]["sharpe"],
                          "beats_new": bool(oos), "robust_wins": wins, "cells": cells,
                          "passes": bool(oos and wins >= NEED)})
    passing = [f for f in finalists if f["passes"]]
    winner = passing[0]["key"] if passing else key(base)

    # controls
    controls = {}
    p = replace(HEADLINE, kappa=KAPPA)
    for name, kw in {"putwrite": dict(p=replace(p, mode="putwrite")),
                     "buywrite": dict(p=replace(p, mode="buywrite")),
                     "puts_then_hold": dict(p=p, gear=lab.hold_all, hold_buys=False)}.items():
        controls[name] = lab.windows(pd.DataFrame(run(lab.m, kw.pop("p"), **kw).ledger))
    first = run(lab.m, p).first_fill
    controls["hold"] = lab.windows(buy_and_hold(lab.m, first))
    controls["tbills"] = lab.windows(tbills(lab.m))

    # how much each part moves Sharpe on 1.4's window, averaged over the rest
    effects = {}
    for part, opts in PARTS.items():
        effects[part] = {}
        for o in opts[1:]:
            diffs = []
            for r in rows:
                if r[part] != opts[0]:
                    continue
                twin = by[key({**{q: r[q] for q in PARTS}, part: o})]
                diffs.append({w: (twin["stats"][w]["sharpe"] or 0) - (r["stats"][w]["sharpe"] or 0)
                              for w in ("found", "new")})
            effects[part][o] = {w: round(float(np.mean([x[w] for x in diffs])), 3) for w in ("found", "new")}
            effects[part][o]["helps_found"] = sum(x["found"] > 0 for x in diffs)
            effects[part][o]["helps_new"] = sum(x["new"] > 0 for x in diffs)
            effects[part][o]["of"] = len(diffs)

    out = {"generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
           "split": str(SPLIT), "end": str(lab.m.end), "kappa": KAPPA,
           "parts": {k: list(v) for k, v in PARTS.items()},
           "rule": {"rank_on": "found", "top": TOP, "robust": ROBUST, "need": NEED},
           "rows": sorted(rows, key=lambda r: r["rank_found"]),
           "wheel": key(base), "finalists": finalists, "winner": winner,
           "winner_label": by[winner]["label"], "controls": controls, "effects": effects}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":"), default=str))

    show = pd.DataFrame([{"rank": r["rank_found"], "candidate": r["label"],
                          "found_SR": r["stats"]["found"]["sharpe"],
                          "found_CAGR": r["stats"]["found"]["cagr_pct"],
                          "new_ret": r["stats"]["new"]["ret_pct"], "new_SR": r["stats"]["new"]["sharpe"],
                          "full_CAGR": r["stats"]["full"]["cagr_pct"], "full_SR": r["stats"]["full"]["sharpe"],
                          "mdd": r["stats"]["full"]["max_dd_pct"], "idle%": r["idle_pct"]}
                         for r in out["rows"]])
    print(show.to_string(index=False))
    print("\nfinalists:")
    for f in finalists:
        print(f"  #{f['rank_found']} {f['label']}: new {f['new_ret']:+.1f}% (wheel "
              f"{wheel['stats']['new']['ret_pct']:+.1f}%), robust {f['robust_wins']}/9 -> "
              f"{'PASS' if f['passes'] else 'fail'}")
    print("winner:", out["winner_label"])
    print("controls:", {k: (v["full"]["cagr_pct"], v["full"]["sharpe"], v["new"]["ret_pct"]) for k, v in controls.items()})
    print("effects:", json.dumps(effects))
    return out


if __name__ == "__main__":
    main()
