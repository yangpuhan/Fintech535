"""
Bake the wheel into docs/wheel.js, which is all the published page loads.

    python -m wheel.build

Same arrangement as 1.2 and 1.3: Python computes everything once and writes
one JSON blob on `window.WHEEL`; the page is hand-written HTML/JS and only
draws. Ledgers are column-oriented (one array per field) so the per-session
portfolio view can index any date without a second lookup.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

from .book import (CONTRACT, HEADLINE, OPENING, Market, Params, _r2, _r4,
                   buy_and_hold, first_expiry, load, lookahead_test, perf,
                   realized_vol, reconcile, run, select_call, select_put, tbills)
from .fills import at_fills, daily, fill_summary, hourly

DOCS = Path(__file__).resolve().parents[1] / "docs"

TRUNCATE_AT = [dt.date(2022, 6, 30), dt.date(2023, 12, 29),
               dt.date(2025, 4, 8), dt.date(2025, 8, 29)]
GRID = [0.20, 0.30, 0.40]


def _clean(obj):
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (dt.date, pd.Timestamp)):
        return str(obj)[:10]
    if obj is pd.NaT:
        return None
    return obj


def columns(rows: list[dict], spec: dict[str, int | None]) -> dict:
    """Row dicts -> {field: [values]}, rounded per field (None = as is)."""
    out = {}
    for k, nd in spec.items():
        vals = [r.get(k) for r in rows]
        if nd is not None:
            vals = [None if v is None or (isinstance(v, float) and not np.isfinite(v))
                    else round(float(v), nd) for v in vals]
        out[k] = vals
    return out


LEDGER = {"date": None, "spot": 2, "phase": None, "cash": 2, "shares": None, "basis": 4,
          "stock_mv": 2, "short": None, "short_id": None, "right": None, "strike": 2,
          "expiry": None, "qty": None, "entry": 4, "mark": 4, "short_delta": 4,
          "short_mv": 2, "collateral": 2, "nav": 2, "delta": 1, "interest": 2,
          "dividend": 2, "premium_cum": 2, "option_cum": 2}


def ledger_columns(res) -> dict:
    """The run's ledger, plus running premium and realised option P&L."""
    by_day: dict[dt.date, float] = {}
    for t in res.trades:
        if t["action"] == "SELL TO OPEN":
            by_day[t["date"]] = by_day.get(t["date"], 0.0) + t["cash"]
    realised: dict[dt.date, float] = {}
    for s in res.shorts:
        if s["closed"] is not None:
            realised[s["closed"]] = realised.get(s["closed"], 0.0) + s["pnl"]
    prem = opt = 0.0
    rows = []
    for r in res.ledger:
        prem += by_day.get(r["date"], 0.0)
        opt += realised.get(r["date"], 0.0)
        rows.append({**r, "premium_cum": prem, "option_cum": opt})
    return columns(rows, LEDGER)


def run_bundle(m: Market, res) -> dict:
    return {
        "trades": res.trades,
        "ledger": ledger_columns(res),
        "shorts": [{**s, "iv": _r4(s["iv"]), "premium": _r4(s["premium"]),
                    "exit": _r4(s["exit"]), "pnl": _r2(s["pnl"]),
                    "otm_pct": _r2(s["otm_pct"]), "delta": _r4(s["delta"]),
                    "rv": _r4(realized_vol(m, s["opened"], s["closed"] or m.end)),
                    "days": ((s["closed"] or m.end) - s["opened"]).days}
                   for s in res.shorts],
        "lots": [{**l, "basis": _r4(l["basis"]), "pnl": _r2(l["pnl"]),
                  "days": ((l["closed"] or m.end) - l["opened"]).days} for l in res.lots],
        "recon": reconcile(m, res),
        "first_fill": res.first_fill,
    }


def _exits(shorts: list[dict], which) -> float:
    """What was paid (or is owed) to end the options matching ``which``."""
    return sum((s["exit"] or 0.0) * s["qty"] for s in shorts if which(s)) * CONTRACT


def stats(m: Market, res, spot: pd.Series) -> dict:
    led = pd.DataFrame(res.ledger)
    out = perf(m, led, spot=spot)
    sh = res.shorts
    done = [s for s in sh if s["outcome"] != "OPEN"]
    out.update({
        "n_shorts": len(sh),
        "n_puts": sum(s["right"] == "P" for s in sh),
        "n_calls": sum(s["right"] == "C" for s in sh),
        "premium": _r2(sum(s["premium"] * s["qty"] for s in sh) * CONTRACT),
        "option_pnl": _r2(sum(s["pnl"] for s in sh)),
        # option P&L = premium - buyback - put intrinsic - call intrinsic - open mark
        "buyback": _r2(_exits(sh, lambda s: s["outcome"] in ("ROLLED", "CLOSED"))),
        "put_intrinsic": _r2(_exits(sh, lambda s: s["right"] == "P" and s["outcome"]
                                    in ("ASSIGNED", "EARLY", "SETTLED"))),
        "call_intrinsic": _r2(_exits(sh, lambda s: s["right"] == "C" and s["outcome"]
                                     in ("CALLED", "EARLY", "SETTLED"))),
        "open_mark": _r2(_exits(sh, lambda s: s["outcome"] == "OPEN")),
        "win_pct": _r2(sum(s["pnl"] > 0 for s in done) / len(done) * 100) if done else None,
        "outcomes": {k: sum(s["outcome"] == k for s in sh) for k in
                     ("EXPIRED", "ROLLED", "CLOSED", "ASSIGNED", "CALLED", "EARLY",
                      "SETTLED", "OPEN")},
        "assigned_puts": sum(s["right"] == "P" and s["outcome"] in ("ASSIGNED", "EARLY", "SETTLED")
                             for s in sh),
        "called": sum(s["right"] == "C" and s["outcome"] in ("CALLED", "EARLY", "SETTLED")
                      for s in sh),
        "n_trades": sum(t["action"] != "DIVIDEND" for t in res.trades),
        "option_fills": sum(t["action"] in ("SELL TO OPEN", "BUY TO CLOSE") for t in res.trades),
        "contracts": sum(abs(t["qty"]) for t in res.trades
                         if t["action"] in ("SELL TO OPEN", "BUY TO CLOSE")),
        "half_spread_paid": _r2(sum(abs(t["price"] - t["mid"]) * abs(t["qty"]) * CONTRACT
                                    for t in res.trades if t["mid"] is not None)),
        "phase_pct": {k: _r2(float((led["phase"] == k).mean() * 100))
                      for k in ("put", "call", "shares", "cash")},
        "mean_delta": _r2(float(led["delta"].mean())),
        "min_cash": _r2(float(led["cash"].min())),
        "first_fill": res.first_fill,
    })
    return out


def refill(m: Market, res, kappa: float, spot: pd.Series) -> dict:
    """
    The headline's own trades, every option fill re-priced at mid -/+ kappa x
    half-spread. Each fill's cash changes by (old - new) x half x contracts;
    the difference then earns the T-bill like any other cash. Decisions are
    held fixed, so this isolates what the fill assumption is worth.
    """
    k0 = res.params.kappa
    bump: dict[dt.date, float] = {}
    paid = 0.0
    for t in res.trades:
        if t["mid"] is None:
            continue
        n = abs(t["qty"]) * CONTRACT
        bump[t["date"]] = bump.get(t["date"], 0.0) - (min(kappa, 1.0) - k0) * t["half"] * n
        paid += min(kappa, 1.0) * t["half"] * n
    adj, prev, rows = 0.0, None, []
    for x in res.ledger:
        d = x["date"]
        if prev is not None:
            adj *= 1 + m.r[prev] * (d - prev).days / 360.0
        adj += bump.get(d, 0.0)
        rows.append({"date": d, "nav": x["nav"] + adj})
        prev = d
    out = perf(m, pd.DataFrame(rows), spot=spot)
    return {"final": out["final"], "cagr_pct": out["cagr_pct"], "sharpe": out["sharpe"],
            "max_dd_pct": out["max_dd_pct"], "half_spread_paid": _r2(paid)}


def diverge(a, b) -> dict | None:
    """The first trade where two runs part ways, and what each did there."""
    key = lambda t: (t["date"], t["action"], t["ric"], t["qty"])
    for x, y in zip(a.trades, b.trades):
        if key(x) != key(y):
            pick = lambda t: {"date": t["date"], "action": t["action"], "ric": t["ric"],
                              "strike": t["strike"], "right": t["right"], "price": t["price"],
                              "note": t["note"]}
            led = {r["date"]: r for r in a.ledger}
            prev = max(d for d in led if d < x["date"])
            return {"headline": pick(x), "mid": pick(y), "basis": _r4(led[prev]["basis"])}
    return None


def vrp_table(m: Market, p: Params) -> list[dict]:
    """
    The thesis on its own, path-free: on the first session after each monthly
    expiry, the rule's 0.30-delta put and call on the next monthly — their
    implied vol against the vol AAPL then realised to that expiry, and what
    selling one at the mid and holding it to expiry earned.
    """
    sess = m.sessions()
    out = []
    for prev_e, e in zip(m.monthlies, m.monthlies[1:]):
        d = next((s for s in sess if s > prev_e), None)
        if d is None or e > m.end or first_expiry(m, d, p) != e:
            continue
        put = select_put(m, d, p)
        call, _ = select_call(m, d, p, None)
        if put is None or call is None:
            continue
        S, SE = m.px[d], m.px[e]
        rv = realized_vol(m, d, e)
        out.append({
            "date": d, "expiry": e, "spot": _r2(S), "settle": _r2(SE),
            "put_k": float(put["strike"]), "put_iv": _r4(float(put["iv"])),
            "put_mid": _r4(float(put["mid"])),
            "put_pnl": _r4(float(put["mid"]) - max(0.0, float(put["strike"]) - SE)),
            "call_k": float(call["strike"]), "call_iv": _r4(float(call["iv"])),
            "call_mid": _r4(float(call["mid"])),
            "call_pnl": _r4(float(call["mid"]) - max(0.0, SE - float(call["strike"]))),
            "rv": _r4(rv),
        })
    return out


def vrp_summary(rows: list[dict]) -> dict:
    put_gap = [r["put_iv"] - r["rv"] for r in rows]
    call_gap = [r["call_iv"] - r["rv"] for r in rows]
    return {
        "n": len(rows),
        "put_iv": _r4(float(np.mean([r["put_iv"] for r in rows]))),
        "call_iv": _r4(float(np.mean([r["call_iv"] for r in rows]))),
        "rv": _r4(float(np.mean([r["rv"] for r in rows]))),
        "put_gap": _r4(float(np.mean(put_gap))),
        "call_gap": _r4(float(np.mean(call_gap))),
        "put_above": sum(g > 0 for g in put_gap),
        "call_above": sum(g > 0 for g in call_gap),
        "put_pnl": _r2(float(np.sum([r["put_pnl"] for r in rows])) * CONTRACT),
        "call_pnl": _r2(float(np.sum([r["call_pnl"] for r in rows])) * CONTRACT),
        "put_wins": sum(r["put_pnl"] > 0 for r in rows),
        "call_wins": sum(r["call_pnl"] > 0 for r in rows),
        "put_worst": min(rows, key=lambda r: r["put_pnl"]),
        "call_worst": min(rows, key=lambda r: r["call_pnl"]),
    }


def grid(m: Market, base: Params, spot: pd.Series) -> list[dict]:
    variants = [replace(base, put_delta=a, call_delta=b) for a in GRID for b in GRID]
    variants += [replace(base, take=None), replace(base, basis_rule=False),
                 replace(base, take=None, basis_rule=False)]
    rows = []
    for p in variants:
        r = run(m, p)
        s = stats(m, r, spot)
        rows.append({
            "put_delta": p.put_delta, "call_delta": p.call_delta, "take": p.take,
            "basis_rule": p.basis_rule, "headline": p == base,
            **{k: s[k] for k in ("final", "cagr_pct", "vol_pct", "sharpe", "max_dd_pct",
                                 "beta", "option_pnl", "n_shorts", "assigned_puts",
                                 "called", "phase_pct")},
        })
    return rows


def band_check(raw: dict, res) -> dict:
    band = {(c["right"], c["expiry"]): (c["lo"], c["hi"]) for c in raw["chain"]}
    lo_puts = [s["ric"] for s in res.shorts if s["right"] == "P"
               and s["strike"] <= band[("P", s["expiry"])][0]]
    hi_calls = [s["ric"] for s in res.shorts if s["right"] == "C"
                and s["strike"] >= band[("C", s["expiry"])][1]]
    return {"put_at_bottom": lo_puts, "call_at_top": hi_calls}


def delta_check(m: Market) -> dict:
    o = m.opts
    both = o[o["delta"].notna() & o["DELTA"].notna() & o["sellable"]]
    out = {}
    for right, g in both.groupby("right"):
        near = g[(g["delta"].abs() - 0.30).abs() < 0.1]
        out[right] = {"n": int(len(g)),
                      "median_abs": _r4(float((g["delta"] - g["DELTA"]).abs().median())),
                      "near_030": _r4(float((near["delta"] - near["DELTA"]).abs().median()))}
    out["lseg_missing"] = int((o["sellable"] & o["DELTA"].isna()).sum())
    out["mid_vs_mid_price"] = _r4(float((o["mid"] - o["MID_PRICE"]).abs().max()))
    return out


def carried_marks(m: Market, res) -> dict:
    n = stale = 0
    for r in res.ledger:
        if r["short"]:
            n += 1
            q = m.quote.get((r["date"], r["short"]))
            if q is None or not np.isfinite(q[0]):
                stale += 1
    return {"held": n, "stale": stale}


def bundle() -> dict:
    raw = load()
    m = Market(raw)
    spot = pd.Series([m.px[d] for d in m.sessions()])

    hz = hourly(raw)
    dz = daily(m)
    kappa = round(hz["k"], 2)
    base = replace(HEADLINE, kappa=kappa)

    res = run(m, base)
    first = res.first_fill
    runs = {
        "wheel": res,
        "expiry": run(m, replace(base, take=None)),
        "putwrite": run(m, replace(base, mode="putwrite")),
        "buywrite": run(m, replace(base, mode="buywrite")),
    }
    st = {k: stats(m, r, spot) for k, r in runs.items()}
    hold = buy_and_hold(m, first)
    bills = tbills(m)
    st["hold"] = perf(m, hold, spot=spot)
    n_sh = int(hold["shares"].iloc[-1])
    st["hold"].update({
        "dividends": _r2(hold["dividend"].sum()), "shares": n_sh,
        "share_pnl": _r2(n_sh * (m.px[m.end] - m.px[first])),
    })
    st["hold"]["interest"] = _r2(st["hold"]["final"] - OPENING - st["hold"]["share_pnl"]
                                 - st["hold"]["dividends"])
    st["tbill"] = perf(m, bills)

    # the fill assumption, swept two ways: the same trades at other prices
    # (what the assumption is worth), and the rule re-run at other prices
    # (how much the path itself moves when a fill changes by cents)
    sweep = [{"kappa": k, "label": label, **refill(m, res, k, spot)}
             for k, label in ((0.0, "mid"), (kappa, "measured"), (0.5, "half-way"),
                              (1.0, "natural"))]
    rerun, alt = [], {}
    for k in (0.0, 0.25, 0.5, kappa, 0.75, 1.0):
        r = res if k == kappa else run(m, replace(base, kappa=k))
        alt[k] = r
        s = stats(m, r, spot)
        rerun.append({"kappa": k, "headline": k == kappa,
                      **{f: s[f] for f in ("final", "cagr_pct", "sharpe", "max_dd_pct",
                                           "n_shorts", "assigned_puts", "called",
                                           "half_spread_paid")}})

    fills_rows = at_fills(m, res.trades)
    vrp = vrp_table(m, base)
    sess = m.sessions()

    curves = {"date": [str(d) for d in sess], "spot": [_r2(m.px[d]) for d in sess],
              "hold": [_r2(v) for v in hold["nav"]], "tbill": [_r2(v) for v in bills["nav"]]}
    for k, r in runs.items():
        curves[k] = [_r2(x["nav"]) for x in r.ledger]

    w = st["wheel"]
    turns = [l for l in res.lots if l["closed"] is not None]
    summary = {
        "years": _r2((m.end - first).days / 365.25),
        "stock_move_pct": _r2((m.px[m.end] / m.px[first] - 1) * 100),
        "turns": len(turns),
        "lot_days": int(np.median([((l["closed"]) - l["opened"]).days for l in turns])) if turns else None,
        "lot_pnl": _r2(sum(l["pnl"] for l in turns)),
        "bound": sum(1 for s in res.shorts if s["bound"]),
        "uncovered_days": sum(1 for x in res.ledger if x["uncovered"]),
    }

    return {
        "meta": {
            "ticker": raw["ticker"], "stock_ric": raw["stock_ric"], "rate_ric": raw["rate_ric"],
            "start": raw["start"], "end": m.end, "first_fill": first,
            "sessions": sum(1 for d in sess if d >= first),
            "fetched_at": raw["fetched_at"], "synthetic": raw["synthetic"],
            "n_contracts": int(raw["options"]["ric"].nunique()),
            "n_option_rows": int(len(raw["options"])),
            "n_hourly": int(len(raw["hourly"])),
            "n_hourly_contracts": int(raw["hourly"]["ric"].nunique()),
            "chain": raw["chain"], "hourly_chain": raw["hourly_chain"],
            "params": asdict(base), "opening": OPENING, "kappa": kappa,
            "dividends": [{"ex": str(r.ex_date), "amount": float(r.amount)}
                          for r in m.divs.itertuples() if first <= r.ex_date <= m.end],
            "earnings": [str(t)[:10] for t in raw["earnings"] if first <= t.date() <= m.end],
            "rate_lo": _r2(min(m.r[d] for d in sess) * 100),
            "rate_hi": _r2(max(m.r[d] for d in sess) * 100),
        },
        "summary": summary,
        "stats": st,
        "curves": curves,
        "runs": {k: run_bundle(m, runs[k]) for k in ("wheel", "expiry")},
        "fills": {"hourly": hz, "daily": dz, "at_fills": fills_rows,
                  "at_summary": fill_summary(fills_rows), "sweep": sweep, "rerun": rerun,
                  "diverge": diverge(res, alt[0.0])},
        "vrp": {"rows": vrp, "summary": vrp_summary(vrp)},
        "grid": grid(m, base, spot),
        "checks": {
            "lookahead": lookahead_test(raw, res, TRUNCATE_AT, base),
            "recon": {k: reconcile(m, r) for k, r in runs.items()},
            "bands": band_check(raw, res),
            "delta": delta_check(m),
            "carried": carried_marks(m, res),
        },
    }


def main() -> Path:
    data = bundle()
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    out = DOCS / "wheel.js"
    out.write_text(
        "/* Generated by `python -m wheel.build` — do not edit. */\n"
        f"window.WHEEL = {json.dumps(_clean(data), separators=(',', ':'))};\n",
        encoding="utf-8")
    s, c = data["stats"], data["checks"]
    print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB)  kappa {data['meta']['kappa']}")
    for k in ("wheel", "expiry", "putwrite", "buywrite", "hold", "tbill"):
        x = s[k]
        sh = "  —  " if x["sharpe"] is None else f"{x['sharpe']:5.2f}"
        print(f"  {k:9s} final {x['final']:>11,.0f}  cagr {x['cagr_pct']:6.2f}%  vol "
              f"{x['vol_pct']:5.1f}%  sharpe {sh}  dd {x['max_dd_pct']:6.1f}%"
              + (f"  beta {x['beta']:.2f}" if 'beta' in x else ""))
    print(f"  look-ahead {[x['identical'] for x in c['lookahead']]}")
    print(f"  recon {c['recon']}")
    print(f"  bands {c['bands']}  carried {c['carried']}")
    return out


if __name__ == "__main__":
    main()
