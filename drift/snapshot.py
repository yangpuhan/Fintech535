"""
Cut the research pull down to what the page and the nightly job need.

    python -m drift.snapshot /path/to/earncache

The pull itself (Nov 2026, LSEG Workspace) priced, for every earnings report
of every company in each year's top 20, the at-the-money call and put on the
first weekly expiring after the report, plus daily bars for those companies
and SPY. It is a few thousand small files; this keeps:

    drift/data/universe.json   {year: [RIC, ...]} top 20 by market cap on the
                               year's first session (one line per company)
    drift/data/events.csv      one row per report: when, the implied move
                               (straddle / spot at the last close before the
                               report), the reaction-day move
    drift/data/bars.csv.gz     daily open and close, split-adjusted, for every
                               company that was ever in the top 20, and SPY
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .core import DATA, tick

BODY = re.compile(r"^([A-Z]+?)([A-Xa-x])(\d{2})(\d{2})(\d{5})\.U")
YEARS = {2022: "2022-01-03", 2023: "2023-01-03", 2024: "2024-01-02", 2025: "2025-01-02", 2026: "2026-01-02"}


def _load(cache: Path, key: str) -> pd.DataFrame:
    d = pd.read_pickle(cache / f"{key}.pkl")
    d.index = pd.DatetimeIndex(d.index).normalize()
    return d.apply(pd.to_numeric, errors="coerce").astype(float)


def _mid(x: pd.DataFrame, t) -> float:
    if t not in x.index or not (x.loc[t, "ASK"] > 0):
        return np.nan
    b = x.loc[t, "BID"] if x.loc[t, "BID"] > 0 else 0.0   # no bid after a gap: worth ~0, not missing
    return (x.loc[t, "ASK"] + b) / 2


def implied_move(opt: pd.DataFrame, t0, spot: float) -> tuple[float, float]:
    """(strike, straddle mid / spot in %) from the strike nearest spot with both legs quoted."""
    by_k: dict[float, dict[str, pd.DataFrame]] = {}
    for r in set(opt.columns.get_level_values(0)):
        m = BODY.match(r.split("^")[0])
        if not m:
            continue
        c, s = m.group(2), m.group(5)
        k = int(s) / (10 if c.islower() else 100)
        by_k.setdefault(k, {})["C" if c.upper() <= "L" else "P"] = \
            opt[r].apply(pd.to_numeric, errors="coerce").astype(float)
    for k, legs in sorted(by_k.items(), key=lambda kv: abs(kv[0] - spot)):
        if set(legs) == {"C", "P"}:
            v = _mid(legs["C"], t0) + _mid(legs["P"], t0)
            if np.isfinite(v):
                return k, v / spot * 100
    return np.nan, np.nan


def main(cache: Path) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    universe = {}
    for y, d in YEARS.items():
        m = pd.read_pickle(cache / f"univ_{y}.pkl").dropna().sort_values("mcap", ascending=False)
        m = m.drop_duplicates("mcap")            # two share classes carry one company cap
        universe[str(y)] = m["ric"].head(20).tolist()
    json.dump({"as_of": YEARS, "top20": universe}, open(DATA / "universe.json", "w"), indent=1)
    rank = {(int(y), tick(r)): i + 1 for y, rics in universe.items() for i, r in enumerate(rics)}
    names = sorted({tick(r) for rics in universe.values() for r in rics})

    ev = json.load(open(cache / "events2.json"))
    rows = []
    for e in ev:
        n, t0, t1 = e["name"], pd.Timestamp(e["t0"]), pd.Timestamp(e["t1"])
        if (t1.year, n) not in rank:
            continue
        raw = _load(cache, f"{n}_raw")["TRDPRC_1"]
        opt = pd.read_pickle(cache / e["file"]); opt.index = pd.DatetimeIndex(opt.index).normalize()
        k, imp = implied_move(opt, t0, raw.loc[t0])
        if not np.isfinite(imp):
            continue
        rows.append(dict(name=n, rank=rank[(t1.year, n)], report=e["report"], timing=e["timing"],
                         t0=t0.date(), t1=t1.date(), strike=k, implied=round(imp, 4),
                         move=round((raw.loc[t1] / raw.loc[t0] - 1) * 100, 4)))
    E = pd.DataFrame(rows).sort_values(["t1", "name"])
    E.to_csv(DATA / "events.csv", index=False)

    bars = []
    for n in names + ["SPY"]:
        a = _load(cache, f"{n}_adj")[["OPEN_PRC", "TRDPRC_1"]].rename(columns={"OPEN_PRC": "open", "TRDPRC_1": "close"})
        a["name"] = n
        bars.append(a.loc["2021-12-01":])
    B = pd.concat(bars).reset_index().rename(columns={"index": "date", "Date": "date"})
    B["date"] = pd.to_datetime(B["date"]).dt.date
    last = min(B.groupby("name")["date"].max())    # a common last session
    B = B[B["date"] <= last].dropna()
    B.to_csv(DATA / "bars.csv.gz", index=False, float_format="%.4f")
    # the 3-month T-bill yield (LSEG US3MT=RR), already pulled for the Final Cycle
    rt = pd.read_pickle(Path(__file__).resolve().parents[1] / "gearwheel" / "data.pkl")["rate"]
    y = rt["MID_YLD_1"].astype(float).fillna(rt["B_YLD_1"].astype(float))
    y.index = pd.DatetimeIndex(y.index).normalize()
    y.loc["2021-12-01":].rename("yield").rename_axis("date").to_frame().to_csv(DATA / "rate.csv", float_format="%.4f")
    print(f"universe {len(names)} names; events {len(E)} ({int((E.move.abs() > E.implied).sum())} surprises); "
          f"bars {len(B)} rows through {last}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
