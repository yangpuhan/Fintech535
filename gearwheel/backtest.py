"""
The gear wheel, backtested on 1.4's engine and tape, carried forward to the
last session before the pull.

    python -m gearwheel.backtest        ->  docs/gear/backtest.json

Every variant runs on wheel.book.run: same chain, same monthly expiries, the
same 0.30 deltas, profit-take at 50%, basis rule, and the fill 1.4 measured
on the hourly tape (sell at mid - 0.57 x half-spread, buy at mid + 0.57 x).
$100,000, cash in T-bills.

    wheel       1.4's rule, unchanged
    gear_a      hold gear: flat -> buy the shares; long -> no calls
    gear_b      hold gear: long -> no calls; flat -> the put anyway, so shares
                only ever arrive by assignment (1.4's edge)
    + earnings  no new short whose life spans a report date (1.2's lesson)

Two windows. 1.4's own, 3 Jan 2022 - 30 Sep 2025, is where the wheel rule
was found; the gear and both variants were written down after looking at
it, so it is in-sample for them. The new tape, Oct 2025 on, was pulled after
every rule here was fixed: none of them saw it.
"""

from __future__ import annotations

import datetime as dt
import json
import pickle
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from wheel import book
from wheel.book import CONTRACT, HEADLINE, OPENING, Market, buy_and_hold, perf, run, tbills

from .signals import gear_map, gears

HERE = Path(__file__).resolve().parent
DATA = HERE / "data.pkl"
OUT = HERE.parent / "docs" / "gear" / "backtest.json"
KAPPA = 0.57            # 1.4's measured share of the half-spread given up
SPLIT = dt.date(2025, 9, 30)

VARIANTS = {
    "winner":      dict(label="the nightly wheel", kw={"earn": True, "credit": True}),
    "wheel":       dict(label="1.4 wheel", kw={}),
    "wheel_earn":  dict(label="wheel + earnings", kw={"earn": True}),
    "gear_a":      dict(label="gear A (hold buys)", kw={"gear": True, "hold_buys": True}),
    "gear_b":      dict(label="gear B (put entry)", kw={"gear": True, "hold_buys": False}),
    "gear_b_earn": dict(label="gear B + earnings", kw={"gear": True, "hold_buys": False,
                                                       "earn": True}),
    "putwrite":    dict(label="put-write", kw={"mode": "putwrite"}),
    "buywrite":    dict(label="buy-write", kw={"mode": "buywrite"}),
}


def load() -> dict:
    with (DATA if DATA.exists() else book.DATA_FILE).open("rb") as f:
        return pickle.load(f)


def signal_px(raw: dict) -> pd.Series:
    s = raw.get("signal_px")
    if s is None:
        s = raw["stock"]["TRDPRC_1"]
    s = pd.to_numeric(s, errors="coerce").dropna()
    s.index = pd.DatetimeIndex(s.index).normalize()
    return s.sort_index()


def run_variant(m: Market, raw: dict, key: str, gm: dict | None = None):
    kw = VARIANTS[key]["kw"]
    p = replace(HEADLINE, kappa=KAPPA, mode=kw.get("mode", "wheel"))
    return run(m, p,
               gear=(gm if gm is not None else gear_map(signal_px(raw))) if kw.get("gear") else None,
               earnings=raw["earnings"] if kw.get("earn") else None,
               hold_buys=kw.get("hold_buys", True),
               oi_wall=kw.get("oi", False),
               pause=_credit_pause(m) if kw.get("credit") else None)


def _credit_pause(m: Market) -> dict:
    from . import external as ex
    return ex.pause_map(ex.snapshot(), m.calendar, use_vix=False, use_credit=True)


def _window(m, led: pd.DataFrame, a: dt.date | None, b: dt.date | None, spot=None) -> dict:
    x = led
    if a is not None:
        # start from the last NAV before the window, so its first day's return counts
        before = led[led["date"] < a]
        x = pd.concat([before.tail(1), led[led["date"] >= a]]) if len(before) else led[led["date"] >= a]
    if b is not None:
        x = x[x["date"] <= b]
    x = x.reset_index(drop=True)
    if len(x) < 3:
        return None
    s = perf(m, x, opening=float(x["nav"].iloc[0]))
    return {k: s[k] for k in ("final", "ret_pct", "cagr_pct", "vol_pct", "sharpe",
                              "max_dd_pct", "years")}


def lookahead(raw: dict, full, key: str, dates: list[dt.date]) -> list[dict]:
    """1.4's test, with the gear recomputed from the truncated closes too."""
    keys = ("date", "action", "ric", "qty", "price")
    px = signal_px(raw)
    out = []
    for D in dates:
        m = Market(raw, upto=D)
        gm = gear_map(px[px.index.date <= D])
        r = run_variant(m, raw, key, gm)
        a = [tuple(t[k] for k in keys) for t in full.trades if t["date"] <= D]
        b = [tuple(t[k] for k in keys) for t in r.trades if t["date"] <= D]
        out.append({"upto": str(D), "trades": len(a), "identical": a == b})
    return out


def earnings_pnl(m: Market, raw: dict, r) -> list[dict]:
    """1.4's wheel, its shorts split by whether their life spanned a report."""
    reports = sorted({pd.Timestamp(e).date() for e in raw["earnings"]})
    out = {}
    for s in r.shorts:
        end = s["closed"] or s["expiry"]
        spans = any(s["opened"] < e < end for e in reports)
        k = (spans, s["right"])
        o = out.setdefault(k, {"spans": spans, "right": s["right"], "n": 0, "pnl": 0.0,
                               "contracts": 0, "assigned": 0})
        o["n"] += 1
        o["pnl"] += s["pnl"]
        o["contracts"] += s["qty"]
        o["assigned"] += s["outcome"] in ("ASSIGNED", "CALLED", "EARLY")
    return [dict(v, pnl=round(v["pnl"], 2)) for _, v in sorted(out.items())]


def build(live: str = "winner") -> dict:
    raw = load()
    m = Market(raw)
    spot = pd.Series(m.px)
    runs = {k: run_variant(m, raw, k) for k in VARIANTS}
    first = runs["wheel"].first_fill
    leds = {k: pd.DataFrame(r.ledger) for k, r in runs.items()}
    leds["hold"] = buy_and_hold(m, first)
    leds["tbills"] = tbills(m)
    labels = {**{k: v["label"] for k, v in VARIANTS.items()},
              "hold": "buy & hold", "tbills": "T-bills"}

    windows = {"full": (None, None), "found": (None, SPLIT),
               "new": (SPLIT + dt.timedelta(days=1), None),
               "since2023": (dt.date(2023, 1, 1), None)}
    stats = {k: {w: _window(m, led, a, b) for w, (a, b) in windows.items()}
             for k, led in leds.items()}

    g = gears(signal_px(raw))
    g = g[(g.index.date >= m.start) & (g.index.date <= m.end)]
    sessions = m.sessions()
    gm = gear_map(signal_px(raw))
    hold_days = sum(gm.get(d) == "hold" for d in sessions)
    switches = sum(1 for a, b in zip(sessions, sessions[1:]) if gm.get(a) != gm.get(b))

    # what the gear changed in the live variant: days it held shares with no call
    lv = leds[live]
    ran = int(((lv["shares"] > 0) & lv["short"].isna() &
               lv.get("gear", pd.Series(["wheel"] * len(lv))).eq("hold")).sum())

    cut = [sessions[int(len(sessions) * f)] for f in (0.25, 0.5, 0.75)] + [SPLIT]
    la = lookahead(raw, runs[live], live, sorted(set(c for c in cut if c <= m.end)))

    def series(led):
        return [round(float(v), 2) for v in led["nav"]]

    trades = [{k: (str(v) if isinstance(v, dt.date) else v) for k, v in t.items()}
              for t in runs[live].trades]
    out = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "start": str(m.start), "end": str(m.end), "split": str(SPLIT),
        "data_end_1_4": str(raw.get("extended_from", SPLIT)),
        "kappa": KAPPA, "opening": OPENING, "live": live,
        "labels": labels,
        "stats": stats,
        "gear": {"hold_days": hold_days, "sessions": len(sessions), "switches": switches,
                 "live_days_shares_no_call": ran},
        "lookahead": la,
        "dates": [str(d) for d in leds["wheel"]["date"]],
        "nav": {k: series(leds[k]) for k in ("wheel", live, "hold", "tbills")},
        "earnings_pnl": earnings_pnl(m, raw, runs["wheel"]),
        "timeline": {"close": [round(float(x), 2) for x in g["close"]],
                     "sma": [None if not np.isfinite(x) else round(float(x), 2) for x in g["sma"]],
                     "rv": [None if not np.isfinite(x) else round(float(x), 1) for x in g["rv"]],
                     "rv_median": [None if not np.isfinite(x) else round(float(x), 1)
                                   for x in g["rv_median"]],
                     "gear": list(g["gear"]),
                     "dates": [str(t.date()) for t in g.index]},
        "earnings": [str(pd.Timestamp(e).date()) for e in raw["earnings"]],
        "trades": trades,
        "shorts": [{k: (str(v) if isinstance(v, dt.date) else
                        (None if isinstance(v, float) and not np.isfinite(v) else v))
                    for k, v in s.items()} for s in runs[live].shorts],
    }
    return out


def main() -> None:
    out = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":"), default=str))
    rows = {out["labels"][k]: {"cagr": v["full"]["cagr_pct"], "sharpe": v["full"]["sharpe"],
                               "mdd": v["full"]["max_dd_pct"],
                               "new_ret": (v["new"] or {}).get("ret_pct"),
                               "new_sharpe": (v["new"] or {}).get("sharpe"),
                               **v["full"]["years"]}
            for k, v in out["stats"].items()}
    print(f"{out['start']} -> {out['end']}  (new tape from {out['split']})")
    print(pd.DataFrame(rows).T.to_string())
    print("gear:", out["gear"])
    print("look-ahead:", out["lookahead"])
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
