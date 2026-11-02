"""
Bake the PMCC book into docs/1.3/pmcc.js, which is all the published page loads.

    python -m pmcc.build

Same arrangement as 1.2: Python computes the whole run once and writes one
JSON blob on `window.PMCC`; the page is hand-written HTML/JS and only draws.
Every number on the page is an object in this file.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from .book import (CONTRACT, HEADLINE, STRATEGIES, Market, Params, _r2, _r4,
                   account, delta_check, load, lookahead_test, perf, run, unit_stats)
from .greeks import call_price, implied_vol

# 1.3 lives in its own folder now that 1.4 has the site root
SITE = Path(__file__).resolve().parents[1] / "docs"
DOCS = SITE / "1.3"

# Truncation points for the look-ahead test: mid-bear, a year-end, the
# bottom of the April 2025 crash, and a recent date.
TRUNCATE_AT = [dt.date(2022, 6, 30), dt.date(2023, 12, 29),
               dt.date(2025, 4, 8), dt.date(2026, 6, 30)]

GRID_LONG = [0.70, 0.80, 0.90]
GRID_SHORT = [0.20, 0.30, 0.40]


def _clean(obj):
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (dt.date, pd.Timestamp)):
        return str(obj)[:10] if not isinstance(obj, pd.Timestamp) or \
            obj == obj.normalize() else str(obj)[:16]
    if obj is pd.NaT:
        return None
    return obj


def account_size(caps: dict[str, float]) -> float:
    """The largest capital requirement of the four, rounded up to $1,000."""
    return float(np.ceil(max(caps.values()) / 1000.0) * 1000.0)


def cycles_table(m: Market, res, unit: dict[str, pd.DataFrame],
                 earnings: list[pd.Timestamp]) -> list[dict]:
    """
    One row per short call, with the timeline tiled so the rows add up:
    cycle k owns (close of k-1, close of k]. Long-leg and stock P&L are
    the change in those legs' per-unit NAV over the same span.
    """
    nav = {k: dict(zip(unit[k]["date"], unit[k]["nav"])) for k in unit}
    out, prev = [], None
    for c in res.cycles:
        end = c["closed"] or m.end
        a = (lambda k: nav[k][prev]) if prev else (lambda k: 0.0)
        long_pnl = nav["leaps"][end] - a("leaps")
        stock_pnl = nav["stock"][end] - a("stock")
        hit = [t for t in earnings if c["opened"] <= t.date() < end]
        out.append({
            "opened": c["opened"], "expiry": c["expiry"], "closed": c["closed"],
            "spot": _r2(c["spot"]), "strike": c["strike"],
            "long_strike": c["long_strike"],
            "otm_pct": _r2(c["otm_pct"]), "delta": _r4(c["delta"]),
            "premium": _r4(c["premium"]), "half_spread": _r4(c["half_spread"]),
            "free_strike": c["free_strike"], "bound": c["bound"],
            "outcome": c["outcome"], "settle": _r2(c["settle"]) if c["settle"] else None,
            "intrinsic": _r4(c["intrinsic"]) if c["intrinsic"] is not None else None,
            "short_pnl": _r2(c["pnl"]),
            "long_pnl": _r2(long_pnl), "stock_pnl": _r2(stock_pnl),
            "pmcc_pnl": _r2(long_pnl + c["pnl"]), "cc_pnl": _r2(stock_pnl + c["pnl"]),
            "earnings": str(hit[0].date()) if hit else None,
        })
        prev = end
    return out


def payoff(m: Market, res) -> dict:
    """
    P&L at the first short call's expiry, per unit, against AAPL's price
    there. The LEAPS is revalued with Black-Scholes at the implied vol it
    was bought at — the one model-made number on the page, labelled as such.
    """
    c, lot = res.cycles[0], res.lots[0]
    d0, exp = c["opened"], c["expiry"]
    S0 = m.px[d0]
    r, q = m.r[d0], m.q[d0]
    T0 = (lot["expiry"] - d0).days / 365.0
    iv = float(implied_vol(lot["price"], S0, lot["strike"], T0, r, q))
    T1 = (lot["expiry"] - exp).days / 365.0
    grid = np.round(np.linspace(S0 * 0.65, S0 * 1.30, 131), 2)
    long_v = call_price(grid, lot["strike"], T1, r, q, iv)
    short_v = np.maximum(grid - c["strike"], 0.0)
    prem = c["premium"]
    return {
        "opened": d0, "expiry": exp, "spot": S0, "settle": m.px.get(exp),
        "long_strike": lot["strike"], "long_price": lot["price"], "long_expiry": lot["expiry"],
        "short_strike": c["strike"], "short_price": prem, "iv": _r4(iv),
        "S": grid.tolist(),
        "pmcc": ((long_v - lot["price"] - short_v + prem) * CONTRACT).round(2).tolist(),
        "cc": ((grid - S0 - short_v + prem) * CONTRACT).round(2).tolist(),
        "debit": _r2((lot["price"] - prem) * CONTRACT),
        "cc_cost": _r2((S0 - prem) * CONTRACT),
    }


def lots_table(m: Market, res) -> list[dict]:
    """
    Each LEAPS held, with what it charged for financing the strike against
    what the cash it freed would have earned in T-bills over the same days.
    """
    out = []
    for lot in res.lots:
        end = lot["closed"] or m.end
        days = [d for d in m.calendar if lot["opened"] < d <= end]
        freed = (lot["spot"] - lot["price"]) * CONTRACT
        prev, earned = lot["opened"], 0.0
        for d in days:
            earned += freed * m.r[prev] * (d - prev).days / 360.0
            prev = d
        # the part of that financing charge used up while this lot was held,
        # at the entry rate: carry(T at entry) - carry(T at exit)
        t0 = (lot["expiry"] - lot["opened"]).days / 365.0
        t1 = (lot["expiry"] - end).days / 365.0
        held = lot["strike"] * (np.exp(-lot["rate"] * t1) - np.exp(-lot["rate"] * t0))
        out.append({
            "carry_held": _r2(held * CONTRACT),
            "ric": lot["ric"], "strike": lot["strike"], "expiry": lot["expiry"],
            "opened": lot["opened"], "closed": lot["closed"], "open": lot["open"],
            "dte": lot["dte"], "spot": _r2(lot["spot"]), "itm_pct": _r2(lot["itm_pct"]),
            "delta": _r4(lot["delta"]), "price": _r4(lot["price"]),
            "intrinsic": _r4(lot["intrinsic"]), "extrinsic": _r4(lot["extrinsic"]),
            "rate_pct": _r2(lot["rate"] * 100), "carry": _r4(lot["carry"]),
            "exit": _r4(lot["exit"]), "exit_spot": _r2(lot["exit_spot"]),
            "pnl": _r2(lot["pnl"]),
            "freed": _r2(freed), "tbill_on_freed": _r2(earned),
        })
    return out


def grid(m: Market) -> list[dict]:
    rows = []
    variants = [Params(long_delta=a, short_delta=b) for a in GRID_LONG for b in GRID_SHORT]
    variants.append(Params(gap_rule=False))
    for p in variants:
        r = run(m, p)
        u = {k: account(m, r, k) for k in ("stock", "cc", "leaps", "pmcc")}
        s = {k: unit_stats(m, r, k, u[k]) for k in u}
        rows.append({
            "long_delta": p.long_delta, "short_delta": p.short_delta,
            "gap_rule": p.gap_rule, "headline": p == HEADLINE,
            "pmcc_pnl": s["pmcc"]["pnl"], "pmcc_natural": s["pmcc"]["pnl_natural"],
            "pmcc_capital": s["pmcc"]["capital"], "pmcc_roc": s["pmcc"]["roc_pct"],
            "pmcc_max_dd": s["pmcc"]["max_dd"],
            "cc_pnl": s["cc"]["pnl"], "leaps_pnl": s["leaps"]["pnl"],
            "overlay_pnl": _r2(s["cc"]["pnl"] - s["stock"]["pnl"]),
            "cycles": len(r.cycles),
            "assigned": sum(1 for c in r.cycles if c["outcome"] in ("ASSIGNED", "EARLY")),
            "bound": sum(1 for c in r.cycles if c["bound"]),
        })
    return rows


def band_check(raw: dict, res) -> dict:
    """Did any pick land on the edge of what was pulled? Then the band cut it."""
    band = {(c["leg"], c["expiry"]): (c["lo"], c["hi"]) for c in raw["chain"]}
    short_edge = [c["ric"] for c in res.cycles
                  if c["strike"] >= band[("short", c["expiry"])][1]]
    long_edge = [l["ric"] for l in res.lots
                 if l["strike"] <= band[("long", l["expiry"])][0]]
    return {"short_at_top": short_edge, "long_at_bottom": long_edge}


def ledger_rows(led: pd.DataFrame) -> list[dict]:
    keep = ["date", "spot", "shares", "long", "long_mark", "short", "short_mark",
            "cash", "stock_mv", "long_mv", "short_mv", "nav", "delta"]
    out = []
    for r in led[keep].itertuples(index=False):
        out.append({
            "date": str(r.date), "spot": _r2(r.spot), "shares": int(r.shares),
            "long": r.long, "long_mark": _r4(r.long_mark) if r.long_mark else None,
            "short": r.short, "short_mark": _r4(r.short_mark) if r.short_mark else None,
            "cash": _r2(r.cash), "stock_mv": _r2(r.stock_mv),
            "long_mv": _r2(r.long_mv), "short_mv": _r2(r.short_mv),
            "nav": _r2(r.nav), "delta": _r2(r.delta),
        })
    return out


def bundle() -> dict:
    raw = load()
    m = Market(raw)
    res = run(m)

    unit = {k: account(m, res, k) for k in STRATEGIES}
    ustats = {k: unit_stats(m, res, k, unit[k]) for k in STRATEGIES}
    caps = {k: ustats[k]["capital"] for k in STRATEGIES}
    X = account_size(caps)
    same = {k: account(m, res, k, opening=X, interest=True) for k in STRATEGIES}
    # take the "less capital" pitch literally: as many PMCCs as the account
    # funds without borrowing
    n_lev = int(X // caps["pmcc"])
    same["pmcc_lev"] = account(m, res, "pmcc", opening=X, interest=True, scale=n_lev)
    sstats = {k: perf(m, same[k], X) for k in same}
    for k in same:
        sstats[k]["interest"] = _r2(same[k]["nav"].iloc[-1] - X
                                    - (unit[k if k in unit else "pmcc"]["nav"].iloc[-1]
                                       * (n_lev if k == "pmcc_lev" else 1)))

    cycles = cycles_table(m, res, unit, raw["earnings"])
    attributed = sum(c["pmcc_pnl"] for c in cycles)
    sess = m.sessions()
    first = res.first_fill

    dc = delta_check(m)
    look = lookahead_test(raw, res, TRUNCATE_AT)
    bands = band_check(raw, res)
    g = grid(m)

    n_sessions = sum(1 for d in sess if d >= first)
    fills = [t for t in res.trades if t["side"] in ("BUY", "SELL")]
    spread_pct = {
        leg: _r2(float(np.median([t["half_spread"] * 2 / t["price"] * 100
                                  for t in fills if t["leg"] == leg])))
        for leg in ("long", "short")}

    lots = lots_table(m, res)
    closed = [l for l in lots if not l["open"]]
    cyc = [c for c in cycles if c["outcome"] != "OPEN"]
    summary = {
        "overlay_pnl": _r2(ustats["cc"]["pnl"] - ustats["stock"]["pnl"]),
        "premium": _r2(sum(c["premium"] for c in cycles) * CONTRACT),
        "intrinsic": _r2(sum(c["intrinsic"] for c in cyc) * CONTRACT),
        "n_cycles": len(cycles),
        "n_expired": sum(c["outcome"] == "EXPIRED" for c in cycles),
        "n_assigned": sum(c["outcome"] == "ASSIGNED" for c in cycles),
        "n_early": sum(c["outcome"] == "EARLY" for c in cycles),
        "n_bound": sum(c["bound"] for c in cycles),
        "mean_delta": _r4(float(np.mean([c["delta"] for c in cycles]))),
        "median_otm": _r2(float(np.median([c["otm_pct"] for c in cycles]))),
        "worst_cycle": min(cycles, key=lambda c: c["short_pnl"]),
        "earn_n": sum(1 for c in cycles if c["earnings"]),
        "earn_short": _r2(sum(c["short_pnl"] for c in cycles if c["earnings"])),
        "noearn_short": _r2(sum(c["short_pnl"] for c in cycles if not c["earnings"])),
        "stock_move_pct": _r2((m.px[m.end] / m.px[first] - 1) * 100),
        "capital_ratio_pct": _r2(caps["pmcc"] / caps["cc"] * 100),
        "leaps_capture_pct": _r2(ustats["leaps"]["pnl"] / ustats["stock"]["pnl"] * 100),
        "carry_held": _r2(sum(l["carry_held"] for l in closed)),
        "tbill_freed": _r2(sum(l["tbill_on_freed"] for l in closed)),
        "extrinsic_paid": _r2(sum(l["extrinsic"] for l in lots) * CONTRACT),
        "mean_pmcc_delta": _r2(float(unit["pmcc"]["delta"].mean())),
        "mean_cc_delta": _r2(float(unit["cc"]["delta"].mean())),
        "years": _r2((m.end - first).days / 365.25),
    }

    return {
        "summary": summary,
        "meta": {
            "ticker": raw["ticker"], "stock_ric": raw["stock_ric"],
            "rate_ric": raw["rate_ric"], "start": raw["start"], "end": m.end,
            "first_fill": first, "sessions": n_sessions,
            "fetched_at": raw["fetched_at"], "synthetic": raw["synthetic"],
            "n_contracts": int(raw["options"]["ric"].nunique()),
            "n_option_rows": int(len(raw["options"])),
            "chain": [{k: c[k] for k in ("leg", "expiry", "requested", "resolved",
                                         "lo", "hi")} for c in raw["chain"]],
            "params": asdict(HEADLINE),
            "account": X, "n_lev": n_lev,
            "dividends": [{"ex": str(r.ex_date), "amount": float(r.amount)}
                          for r in m.divs.itertuples()
                          if first <= r.ex_date <= m.end],
            "earnings": [str(t)[:16] for t in raw["earnings"]
                         if first <= t.date() <= m.end],
            "spread_pct": spread_pct,
        },
        "unit": ustats,
        "same": sstats,
        "curves": {
            "date": [str(d) for d in same["pmcc"]["date"]],
            "spot": [_r2(v) for v in same["pmcc"]["spot"]],
            **{k: [_r2(v) for v in same[k]["nav"]] for k in same},
            # per-unit position value: what each book has at work
            "cc_mv": [_r2(a + b) for a, b in zip(unit["cc"]["stock_mv"], unit["cc"]["short_mv"])],
            "pmcc_mv": [_r2(a + b) for a, b in zip(unit["pmcc"]["long_mv"], unit["pmcc"]["short_mv"])],
            "pmcc_delta": [_r2(v) for v in unit["pmcc"]["delta"]],
            "cc_delta": [_r2(v) for v in unit["cc"]["delta"]],
        },
        "cycles": cycles,
        "lots": lots,
        "trades": res.trades,
        "ledger": {"pmcc": ledger_rows(unit["pmcc"]), "cc": ledger_rows(unit["cc"])},
        "payoff": payoff(m, res),
        "grid": g,
        "checks": {
            "lookahead": look,
            "delta": dc,
            "bands": bands,
            "attribution_gap": _r2(attributed - ustats["pmcc"]["pnl"]),
            "overlay_identical": _r2((ustats["cc"]["pnl"] - ustats["stock"]["pnl"])
                                     - (ustats["pmcc"]["pnl"] - ustats["leaps"]["pnl"])),
            "carried_marks": carried_marks(m, res),
        },
    }


def carried_marks(m: Market, res) -> dict:
    """Held-contract sessions with no two-sided close, so the mark is stale."""
    n = stale = 0
    for st in res.state:
        for leg in ("long", "short"):
            ric = st[leg]
            if ric:
                n += 1
                q = m.quote.get((st["date"], ric))
                if q is None or not np.isfinite(q[0]):
                    stale += 1
    return {"held": n, "stale": stale}


def main() -> Path:
    data = bundle()
    DOCS.mkdir(parents=True, exist_ok=True)
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    out = DOCS / "pmcc.js"
    out.write_text(
        "/* Generated by `python -m pmcc.build` — do not edit. */\n"
        f"window.PMCC = {json.dumps(_clean(data), separators=(',', ':'))};\n",
        encoding="utf-8")

    u, s, c = data["unit"], data["same"], data["checks"]
    print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB)")
    print(f"  per unit   " + "  ".join(f"{k} {u[k]['pnl']:+,.0f} on {u[k]['capital']:,.0f}"
                                     for k in u))
    print(f"  account {data['meta']['account']:,.0f}: " +
          "  ".join(f"{k} {s[k]['final']:,.0f} ({s[k]['cagr_pct']:+.2f}%/yr, "
                    f"dd {s[k]['max_dd_pct']:.1f}%)" for k in s))
    print(f"  look-ahead {[x['identical'] for x in c['lookahead']]}  "
          f"attribution gap {c['attribution_gap']}  overlay gap {c['overlay_identical']}")
    print(f"  bands {c['bands']}  stale marks {c['carried_marks']}")
    return out


if __name__ == "__main__":
    main()
