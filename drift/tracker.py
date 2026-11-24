"""
Nightly: bring the thesis tracker up to the last session.

    python -m drift.tracker            # LSEG: platform session in CI, Workspace locally
    python -m drift.tracker --offline  # rebuild docs/drift/tracker.json from drift/data only

Each run asks LSEG for (a) the last week of daily bars for this year's top 20,
any name with an open trade, and SPY; (b) the 3-month T-bill yield; (c) the
report dates of this year's top 20. For a report whose reaction day has
closed and is not yet in drift/data/events.csv, it prices the at-the-money
call and put on the first weekly after the reaction day at the last close
before the report (two requests, a neighbour strike or the monthly if
needed) and appends the row. About forty requests on a quiet night.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import numpy as np
import pandas as pd

from . import core
from .snapshot import implied_move

NOW = dt.datetime.now(dt.timezone.utc)


def _code(month: int, right: str, big: bool) -> str:
    c = chr((ord("A") if right == "C" else ord("M")) + month - 1)
    return c.lower() if big else c


def option_ric(root: str, exp: dt.date, k: float, right: str, today: dt.date) -> str:
    """OPRA RIC; strikes of $1000+ use a lower-case month code and strike x 10;
    expired contracts carry ^{call month}{yy}."""
    big = k >= 1000
    body = f"{root}{_code(exp.month, right, big)}{exp:%d}{exp:%y}{int(round(k * (10 if big else 100))):05d}.U"
    return body if exp >= today else f"{body}^{_code(exp.month, 'C', False)}{exp:%y}"


def step(px: float) -> float:
    return 1.0 if px < 25 else 2.5 if px < 100 else 5.0


def week_expiry(after: dt.date) -> dt.date:
    """The Friday of the first week ending after `after` (Thursday if the Friday is a holiday is
    left to the neighbour retry: a missing RIC costs two requests, not a wrong price)."""
    d = after + dt.timedelta(days=1)
    return d + dt.timedelta(days=(4 - d.weekday()) % 7)


def third_friday(after: dt.date) -> dt.date:
    d = dt.date(after.year, after.month, 1)
    while True:
        f = d + dt.timedelta(days=(4 - d.weekday()) % 7 + 14)
        if f > after:
            return f
        d = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def _retry(fn, tries: int = 3, wait: float = 20.0):
    """The platform endpoints time out now and then (24 Nov 2026: a report-date
    query read-timed-out in CI while the bars came back); try again."""
    import time
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"  LSEG: {str(e)[:80]}; retrying in {wait:.0f}s")
            time.sleep(wait)


def _hist(ld, rics, fields, start, end, tries: int = 3):
    df = _retry(lambda: ld.get_history(universe=rics, fields=fields, interval="1D", start=str(start), end=str(end)), tries)
    if df is None or df.empty:
        return pd.DataFrame()
    if not isinstance(df.columns, pd.MultiIndex):
        df.columns = pd.MultiIndex.from_product([[rics[0] if isinstance(rics, list) else rics], df.columns])
    df.index = pd.DatetimeIndex(df.index).normalize()
    return df.apply(pd.to_numeric, errors="coerce").astype(float)


def update(ld) -> str:
    u, ev, bars, rate = core.load()
    today = NOW.date()
    year = str(today.year)
    if year not in u["top20"]:                       # a new year: re-pick the top 20 on its first session
        first = (pd.Timestamp(f"{year}-01-01") + pd.offsets.BDay(0)).date()
        c = ld.get_data(".SPX", ["TR.IndexConstituentRIC"], {"SDate": str(first)})
        m = ld.get_data(c.iloc[:, 1].dropna().tolist(), ["TR.CompanyMarketCap"], {"SDate": str(first), "Curn": "USD"})
        m.columns = ["ric", "mcap"]
        m["mcap"] = pd.to_numeric(m["mcap"], errors="coerce")
        m = m.dropna().sort_values("mcap", ascending=False).drop_duplicates("mcap")
        u["top20"][year] = m["ric"].head(20).tolist()
        u["as_of"][year] = str(first)
        json.dump(u, open(core.DATA / "universe.json", "w"), indent=1)
    ric_of = {core.tick(r): r for y in sorted(u["top20"]) for r in u["top20"][y]}
    ric_of["SPY"] = "SPY"
    O, Cl = core.panel(bars, "open"), core.panel(bars, "close")
    open_names = [t["name"] for t in core.trades(ev, O, Cl, True) if not t["closed"]]
    names = sorted(set(core.tick(r) for r in u["top20"][year]) | set(open_names) | {"SPY"})
    last = pd.Timestamp(bars["date"].max())

    # (a) bars ------------------------------------------------------------
    start = (last - pd.Timedelta(days=10)).date()
    h = _hist(ld, [ric_of[n] for n in names], ["OPEN_PRC", "TRDPRC_1"], start, today)
    new = []
    for n in names:
        r = ric_of[n]
        if r not in h.columns.get_level_values(0):
            continue
        x = h[r].rename(columns={"OPEN_PRC": "open", "TRDPRC_1": "close"}).dropna()
        old = Cl[n].reindex(x.index).dropna() if n in Cl.columns else pd.Series(dtype=float)
        if len(old) and (x["close"].reindex(old.index) / old - 1).abs().max() > 0.2:
            # a split since the snapshot: take the whole adjusted history again
            full = _hist(ld, [r], ["OPEN_PRC", "TRDPRC_1"], bars["date"].min().date(), today)[r]
            x = full.rename(columns={"OPEN_PRC": "open", "TRDPRC_1": "close"}).dropna()
            bars = bars[bars["name"] != n]
        x = x.assign(name=n).rename_axis("date").reset_index()
        new.append(x)
    if new:
        add = pd.concat(new)
        key = set(zip(add["name"], add["date"]))
        bars = pd.concat([bars[[k not in key for k in zip(bars["name"], bars["date"])]], add])
        bars = bars.sort_values(["name", "date"])
    # sessions that SPY has (a holiday or a half-filled night must not add a ragged row)
    spy_days = set(bars.loc[bars["name"] == "SPY", "date"])
    bars = bars[bars["date"].isin(spy_days)]

    # (b) T-bill yield -------------------------------------------------------
    rt = _hist(ld, ["US3MT=RR"], ["MID_YLD_1", "B_YLD_1"], (pd.Timestamp(rate.index.max()) - pd.Timedelta(days=10)).date(), today)
    if not rt.empty:
        y = rt["US3MT=RR"]["MID_YLD_1"].fillna(rt["US3MT=RR"]["B_YLD_1"]).dropna().rename("yield")
        rate = pd.concat([rate[~rate.index.isin(y.index)], y]).sort_index()

    _save(ev, bars, rate)
    try:
        added = _reports(ld, u, ev, bars, ric_of, year, today)
    except Exception as e:                            # keep tonight's bars; try the reports again tomorrow
        print(f"  report dates unavailable tonight: {str(e)[:120]}")
        return f"report dates unavailable tonight; bars through {bars['date'].max().date()}"
    if added:
        ev = pd.concat([ev, pd.DataFrame(added)]).sort_values(["t1", "name"])
        _save(ev, bars, rate)
    return f"{len(added)} new report(s); bars through {bars['date'].max().date()}"


def _save(ev, bars, rate) -> None:
    ev.assign(t0=pd.to_datetime(ev["t0"]).dt.date, t1=pd.to_datetime(ev["t1"]).dt.date).to_csv(core.DATA / "events.csv", index=False)
    bars.assign(date=pd.to_datetime(bars["date"]).dt.date).to_csv(core.DATA / "bars.csv.gz", index=False, float_format="%.4f")
    rate.rename_axis("date").to_frame("yield").to_csv(core.DATA / "rate.csv", float_format="%.4f")


def _reports(ld, u, ev, bars, ric_of, year, today) -> list[dict]:
    """(c) reports whose reaction day has closed and that are not recorded yet."""
    rics = [ric_of[core.tick(r)] for r in u["top20"][year]]
    since = (pd.Timestamp(ev["t1"].max()) - pd.Timedelta(days=45)).date()
    rep = _retry(lambda: ld.get_data(rics, ["TR.EPSActReportDate"],
                                     {"SDate": str(since), "EDate": str(today), "Period": "FQ0", "Frq": "FQ"}))
    rep.columns = ["ric", "report"]
    O, Cl = core.panel(bars, "open"), core.panel(bars, "close")
    sess = Cl.index
    known = set(zip(ev["name"], ev["t1"].dt.date))
    added = []
    for _, row in rep.dropna().drop_duplicates().iterrows():
        n = core.tick(row["ric"]); ts = pd.Timestamp(row["report"])
        day, hm = ts.normalize(), ts.hour * 60 + ts.minute
        if hm >= 16 * 60:
            timing, a, b = "amc", sess[sess <= day], sess[sess > day]
        else:
            timing, a, b = ("bmo" if hm < 570 else "intraday"), sess[sess < day], sess[sess >= day]
        if not len(a) or not len(b) or n not in Cl.columns:
            continue                                  # reaction day not closed yet
        t0, t1 = a[-1], b[0]
        if (n, t1.date()) in known or pd.isna(Cl.at[t1, n]):
            continue
        px0 = float(Cl.at[t0, n]); st = step(px0)
        near = round(round(px0 / st) * st, 2); other = round(near + (st if px0 > near else -st), 2)
        root = n
        imp, k_used = np.nan, np.nan
        for exp in (week_expiry(t1.date()), third_friday(t1.date())):
            for k in (near, other):
                legs = [option_ric(root, exp, k, rt_, today) for rt_ in ("C", "P")]
                try:
                    opt = _hist(ld, legs, ["BID", "ASK"], (t0 - pd.Timedelta(days=5)).date(),
                               (t0 + pd.Timedelta(days=1)).date(), tries=1)   # a missing RIC is normal
                except Exception:
                    opt = pd.DataFrame()
                if not opt.empty and set(legs) <= set(opt.columns.get_level_values(0)):
                    k_used, imp = implied_move(opt, t0, px0)
                    if np.isfinite(imp):
                        break
            if np.isfinite(imp):
                break
        if not np.isfinite(imp):
            print(f"  {n} {t1.date()}: no option quote, skipped")
            continue
        rank = u["top20"][year].index(ric_of[n]) + 1 if ric_of[n] in u["top20"][year] else None
        added.append(dict(name=n, rank=rank, report=str(ts), timing=timing, t0=t0, t1=t1, strike=k_used,
                          implied=round(imp, 4), move=round((Cl.at[t1, n] / Cl.at[t0, n] - 1) * 100, 4)))
        print(f"  new report {n} reacted {t1.date()}: implied {imp:.2f}% move {added[-1]['move']:+.2f}%")
    return added


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    note = "offline rebuild"
    if not a.offline:
        import lseg.data as ld
        sys.path.insert(0, str(core.ROOT))
        from nightly.refresh import open_session
        session, kind = open_session(ld)
        try:
            ld.get_config()["http.request-timeout"] = 120
        except Exception:
            pass
        try:
            note = update(ld)
        finally:
            ld.close_session()
    u, ev, bars, rate = core.load()
    j = core.build_json(u, ev, bars, rate, NOW.strftime("%Y-%m-%d %H:%M UTC"), note)
    core.OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(j, open(core.OUT, "w"), separators=(",", ":"))
    s = j["status"]
    print(f"tracker through {j['through']}: {note}; open {len(j['open'])}; "
          f"short {s['short']['value']:+.2f}% ({'tripped' if s['short']['tripped'] else 'ok'}), "
          f"long {s['long']['value']:+.2f}% ({'tripped' if s['long']['tripped'] else 'ok'})")


if __name__ == "__main__":
    main()
