"""
Tonight's orders: the gear wheel, written in Sanji.

    python -m gearwheel.orders              # pull, decide, write the files
    python -m gearwheel.orders --dry-run    # pull, decide, print; write nothing

Run by .github/workflows/nightly.yml after the chart refresh. An algorithm is
a function from inputs to open orders; this is that function, once a night.

Inputs
    LSEG                AAPL.O daily closes (the gear signals and the spot),
                        US3MT=RR (r), a year of AAPL dividends (q), the next
                        earnings date, and the last session's closing quotes
                        on the one monthly expiry the rule would sell.
    mkt/positions.json  Sanji's book. Absent (Sanji does not resolve orders
                        yet) -> the opening book: $100,000 cash, nothing else.
    mkt/fills.json      Sanji's fills, for the premium behind a profit-take.

Outputs
    mkt/open_orders.json   what Sanji reads (his spec puts it under mkt/)
    open_orders.json       the same array at the repo root (the brief's wording)
    docs/gear/state.json   tonight's signals, book, decision and orders
    docs/gear/log.json     one row per decision date: the forward record

The rule is wheel.book.run with gearwheel.signals' gear, decided on the last
close, as in the backtest. Three things differ, all because Sanji is not the
backtest's tape: a fill is at the open or inside the day's range, not on the
close; a profit-take closes tonight and the next put or call is sold the
night after (the backtest rolls on one close); and the strike is chosen from
the last close's quotes, then sent as a bare number so Sanji needs no chain
to know the contract.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from covered_call.ric import build_option_ric
from pmcc.fetch import third_friday
from wheel import fetch as wf
from wheel.book import OI_BAND
from wheel.greeks import delta as bs_delta, implied_vol

from .signals import LOOKBACK, MA, RV, gears

ROOT = Path(__file__).resolve().parents[1]
MKT = ROOT / "mkt"
STATE_DIR = ROOT / "docs" / "gear"

CONID = 265598                 # AAPL, as in price_history.json
TICKER, STOCK_RIC, RATE_RIC = "AAPL", "AAPL.O", "US3MT=RR"
OPENING_CASH = 100_000.0       # 1.4's account, until Sanji writes a book
CONTRACT = 100
PUT_DELTA = CALL_DELTA = 0.30
MIN_DTE = 21
TAKE = 0.50
# Flat in the hold gear: False sells the put anyway, so shares only ever
# arrive by assignment (variant B); True buys them at the open (variant A).
# Chosen by the backtest, which tested both; see docs/gear/backtest.json.
HOLD_BUYS = False
# The parts the lab (gearwheel/lab.py) selected, by the rule fixed before it
# ran: 1.4's wheel + the earnings blackout + the open-interest strike. The
# gear lost in the lab; its signals are still computed and published, but
# with USE_GEAR False every night is the wheel.
USE_GEAR = False
EARNINGS_BLACKOUT = True
OI_STRIKE = True
HISTORY_DAYS = 800             # calendar days of closes: 200 + 252 + 21 sessions, padded
OPEN_NY = dt.time(9, 30)

# NYSE full-day closures. The order date must be a session, and so must an
# expiry (a holiday Friday moves the monthly to Thursday).
NYSE_HOLIDAYS = {
    dt.date(2026, 1, 1), dt.date(2026, 1, 19), dt.date(2026, 2, 16), dt.date(2026, 4, 3),
    dt.date(2026, 5, 25), dt.date(2026, 6, 19), dt.date(2026, 7, 3), dt.date(2026, 9, 7),
    dt.date(2026, 11, 26), dt.date(2026, 12, 25),
    dt.date(2027, 1, 1), dt.date(2027, 1, 18), dt.date(2027, 2, 15), dt.date(2027, 3, 26),
    dt.date(2027, 5, 31), dt.date(2027, 6, 18), dt.date(2027, 7, 5), dt.date(2027, 9, 6),
    dt.date(2027, 11, 25), dt.date(2027, 12, 24),
}


# ── calendar ──────────────────────────────────────────────────────────────

def is_session(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS


def coming_session(now_ny: dt.datetime) -> dt.date:
    """The next session whose open has not happened yet."""
    d = now_ny.date()
    if is_session(d) and now_ny.time() < OPEN_NY:
        return d
    d += dt.timedelta(days=1)
    while not is_session(d):
        d += dt.timedelta(days=1)
    return d


def monthly_expiry(year: int, month: int) -> dt.date:
    e = third_friday(year, month)
    while not is_session(e):
        e -= dt.timedelta(days=1)
    return e


def first_monthly(decided: dt.date, min_dte: int = MIN_DTE) -> dt.date:
    """1.4's expiry: the first standard monthly at least min_dte days out."""
    y, m = decided.year, decided.month
    while True:
        e = monthly_expiry(y, m)
        if (e - decided).days >= min_dte:
            return e
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


# ── the book Sanji wrote ──────────────────────────────────────────────────

@dataclass
class Book:
    cash: float
    shares: int
    short: dict | None        # {"right", "strike", "expiry", "qty"}
    basis: float | None       # per share, for the call floor
    premium: float | None     # per share, the open short's entry fill
    source: str


def _num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _records(data):
    if isinstance(data, list):
        return data, None
    if isinstance(data, dict):
        for k in ("positions", "book", "holdings"):
            if isinstance(data.get(k), list):
                return data[k], _num(data.get("cash"))
    return None, None


def read_fills() -> list[dict]:
    f = MKT / "fills.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text())
    except ValueError:
        return []
    rows = data if isinstance(data, list) else data.get("fills", []) if isinstance(data, dict) else []
    return [r for r in rows if isinstance(r, dict)]


def _fill_price(fills: list[dict], match) -> float | None:
    for r in reversed(fills):
        if str(r.get("status", "filled")).lower() != "filled":
            continue
        if match(str(r.get("id", ""))):
            for k in ("price", "fill_price", "fill", "px"):
                v = _num(r.get(k))
                if v is not None:
                    return v
    return None


def read_book() -> tuple[Book | None, str]:
    """
    Sanji's spec says what the book is, not how positions.json spells it,
    and he has not written one yet. Read the order schema's own words
    (contract, strike, expiry, qty; negative qty or a SHT action for a short)
    and refuse anything else: a book we cannot read must not be traded on.
    """
    f = MKT / "positions.json"
    if not f.exists():
        return Book(OPENING_CASH, 0, None, None, None,
                    "no mkt/positions.json yet: the opening book, $100,000 cash"), ""
    try:
        data = json.loads(f.read_text())
    except ValueError:
        return None, "mkt/positions.json is not valid JSON"
    rows, cash = _records(data)
    if rows is None:
        return None, "mkt/positions.json is not a shape this script knows"
    shares, short, basis = 0, None, None
    for r in rows:
        if not isinstance(r, dict):
            return None, "mkt/positions.json has a row that is not an object"
        if "underlying" in r and _num(r["underlying"]) not in (None, CONID):
            continue
        kind = str(r.get("contract", "")).lower()
        qty = _num(r.get("qty", r.get("quantity")))
        if qty is None or kind not in ("underlying", "put", "call"):
            return None, f"mkt/positions.json row not understood: {r}"
        if str(r.get("action", "")).upper() in ("SHT",) or str(r.get("side", "")).lower() == "short":
            qty = -abs(qty)
        if kind == "underlying":
            shares += int(qty)
            basis = _num(r.get("avg_cost", r.get("cost_basis", r.get("basis")))) or basis
        else:
            if qty >= 0:
                return None, "a long option in the book: not part of this rule"
            if short is not None:
                return None, "two short options in the book: not part of this rule"
            exp = r.get("expiry")
            try:
                exp = dt.date.fromisoformat(str(exp)[:10])
            except ValueError:
                return None, f"short option with an unreadable expiry: {r}"
            k = _num(r.get("strike"))
            if k is None:
                return None, f"short option with an unreadable strike: {r}"
            short = {"right": "P" if kind == "put" else "C", "strike": k,
                     "expiry": exp, "qty": int(abs(qty))}
    if cash is None:
        return None, "mkt/positions.json has no cash figure"
    fills = read_fills()
    premium = None
    if short is not None:
        tag = f"-sht-{short['right'].lower()}-{short['expiry']:%Y%m%d}-{short['strike']:g}-"
        premium = _fill_price(fills, lambda i: tag in i)
    if shares and basis is None:
        # assigned from our put: that put's strike less its premium, as 1.4.
        # Our ids carry the strike: aapl-sht-p-YYYYMMDD-<strike>-<for>.
        for r in reversed(fills):
            i = str(r.get("id", ""))
            if "-sht-p-" not in i:
                continue
            k = _num(i.split("-sht-p-")[1].split("-")[1])
            prem = _fill_price([r], lambda _: True)
            if k is not None and prem is not None:
                basis = k - prem
                break
    return Book(cash, shares, short, basis, premium, "mkt/positions.json"), ""


# ── LSEG ──────────────────────────────────────────────────────────────────

def _last(df, col):
    s = pd.to_numeric(df[col], errors="coerce").dropna() if df is not None and col in df else pd.Series(dtype=float)
    return float(s.iloc[-1]) if len(s) else None


def pull_market(ld, now_ny: dt.datetime) -> dict:
    from nightly.refresh import CLOSE_NY, closes

    today = now_ny.date()
    before_close = now_ny.time() < CLOSE_NY
    px = closes(ld, STOCK_RIC, today - dt.timedelta(days=HISTORY_DAYS), today, today,
                before_close)
    decided = px.index[-1].date()

    rate = ld.get_history(universe=RATE_RIC, fields=["MID_YLD_1", "B_YLD_1"],
                          start=(decided - dt.timedelta(days=14)).isoformat(),
                          end=today.isoformat(), interval="1D")
    r = _last(rate, "MID_YLD_1") or _last(rate, "B_YLD_1")
    r = (r or 4.0) / 100.0

    q = 0.004
    try:
        dv = ld.get_data(STOCK_RIC, ["TR.DivExDate", "TR.DivUnadjustedGross"],
                         {"SDate": (decided - dt.timedelta(days=365)).isoformat(),
                          "EDate": decided.isoformat()})
        amt = pd.to_numeric(dv.iloc[:, -1], errors="coerce").dropna().sum()
        if amt > 0:
            q = float(amt) / float(px.iloc[-1])
    except Exception as e:
        print(f"warning: dividends not read ({e}); q = {q}")

    earn, estimated = next_earnings(ld, decided)
    return {"px": px, "decided": decided, "r": r, "q": q,
            "earnings": earn, "earnings_estimated": estimated}


def next_earnings(ld, after: dt.date) -> tuple[dt.date | None, bool]:
    """The next report date LSEG has; else the last one plus a quarter, flagged."""
    # LSEG's expected date lags: on 17 Nov 2026 it still said 2 Nov, the
    # report just past. Use it only once it points forward.
    try:
        df = ld.get_data(STOCK_RIC, ["TR.ExpectedReportDate"])
        for v in df.iloc[:, -1].dropna():
            d = pd.Timestamp(v).date()
            if d > after:
                return d, False
    except Exception:
        pass
    try:
        df = ld.get_data(STOCK_RIC, ["TR.EPSActReportDate"],
                         {"SDate": (after - dt.timedelta(days=200)).isoformat(),
                          "EDate": after.isoformat(), "Period": "FQ0", "Frq": "FQ"})
        last = max(pd.Timestamp(v).date() for v in df.iloc[:, -1].dropna())
        est = last + dt.timedelta(days=91)
        while est <= after:
            est += dt.timedelta(days=91)
        return est, True
    except Exception:
        return None, True


def _grid(lo: float, hi: float, step: float) -> list[float]:
    lo, hi = math.floor(lo / step) * step, math.ceil(hi / step) * step
    return [round(float(k), 2) for k in np.arange(lo, hi + step / 2, step)]


def pull_chain(ld, right: str, expiry: dt.date, S: float, floor: float | None,
               decided: dt.date, today: dt.date, r: float, q: float) -> pd.DataFrame:
    """The last close's quotes on one expiry, banded as wheel/fetch.py, with IV and delta."""
    if right == "P":
        strikes = _grid(S * wf.PUT_BAND[0], S * wf.PUT_BAND[1], wf.STEP)
    else:
        top = max(S * wf.CALL_BAND[1], (floor or 0) * 1.10)
        fine = _grid(S * wf.CALL_BAND[0], S * wf.CALL_FINE_TOP, wf.STEP)
        strikes = sorted(set(fine) | set(_grid(fine[-1], top, 5.0)))
    live = expiry >= today
    rics = {}
    for k in strikes:
        ric = build_option_ric(TICKER, expiry, k, right)
        rics[ric.split("^")[0] if live else ric] = k
    got = wf._chain(ld, list(rics), ["BID", "ASK", "MID_PRICE", "TRDPRC_1", "OPINT_1"],
                    decided - dt.timedelta(days=7), decided, "1D", batch=8)
    if got.empty:
        return got
    got["date"] = pd.DatetimeIndex(got["date"]).normalize()
    # Open interest is published the morning after (OCC), so at night the
    # last session's row has none yet. Use each contract's latest reported
    # figure inside the pulled week: what was knowable at the decision.
    oi_col = got["OPINT_1"] if "OPINT_1" in got else pd.Series(np.nan, index=got.index)
    got["OPINT_1"] = pd.to_numeric(oi_col, errors="coerce").astype(float)
    last_oi = (got.dropna(subset=["OPINT_1"]).sort_values("date")
               .groupby("ric").tail(1).set_index("ric"))
    got = got[got["date"].dt.date == decided].copy()
    got["OPINT_1"] = got["ric"].map(last_oi["OPINT_1"]) if len(last_oi) else np.nan
    got["oi_date"] = got["ric"].map(last_oi["date"].dt.date) if len(last_oi) else None
    got["strike"] = got["ric"].map(rics)
    for c in ("BID", "ASK", "OPINT_1"):
        # LSEG hands back nullable dtypes; plain floats keep NaN tests simple
        col = got[c] if c in got else pd.Series(np.nan, index=got.index)
        got[c] = pd.to_numeric(col, errors="coerce").astype(float)
    two = got["BID"].notna() & got["ASK"].notna() & (got["ASK"] >= got["BID"]) & (got["BID"] > 0)
    got = got[two].copy()
    got["mid"] = (got["BID"] + got["ASK"]) / 2
    T = (expiry - decided).days / 365.0
    is_call = right == "C"
    got["iv"] = implied_vol(got["mid"], S, got["strike"], T, r, q, is_call)
    got["delta"] = bs_delta(S, got["strike"], T, r, q, got["iv"], is_call)
    got = got.dropna(subset=["delta"]).sort_values("strike").reset_index(drop=True)
    od = got["oi_date"].dropna() if "oi_date" in got else pd.Series(dtype=object)
    print(f"chain {right} {expiry}: {len(got)} two-sided quotes on {decided}, "
          f"{int(got['OPINT_1'].notna().sum())} with open interest"
          f"{f' (as of {min(od)} to {max(od)})' if len(od) else ''}")
    return got


def pick(chain: pd.DataFrame, target: float, floor: float | None = None):
    """wheel.book's choice: nearest the target delta, or, with OI_STRIKE, the
    most open interest inside OI_BAND |delta| (ties to the nearest delta)."""
    g = chain if floor is None else chain[chain["strike"] >= floor - 1e-9]
    if g.empty:
        return None
    if OI_STRIKE:
        a = g["delta"].abs()
        band = g[(a >= OI_BAND[0]) & (a <= OI_BAND[1]) & g["OPINT_1"].notna()]
        if not band.empty:
            g = band[band["OPINT_1"] == band["OPINT_1"].max()]
    return g.iloc[(g["delta"] - target).abs().to_numpy().argmin()]


# ── orders ────────────────────────────────────────────────────────────────

def _k(x: float):
    return int(x) if float(x).is_integer() else round(float(x), 2)


def sanji(for_: dt.date, action: str, qty: int, contract: str, *, expiry=None,
          strike=None, lmt=None) -> dict:
    o = {"for": for_.isoformat(), "order_type": "lmt" if lmt is not None else "mkt",
         "action": action, "qty": int(qty), "underlying": CONID, "contract": contract}
    if contract != "underlying":
        o["expiry"] = expiry.isoformat()
        o["strike"] = _k(strike)
    o["ref"] = "open"
    if lmt is not None:
        o["lmt_prc"] = lmt
    leg = ("stk" if contract == "underlying" else
           f"{contract[0]}-{expiry:%Y%m%d}-{_k(strike):g}")
    o = {"id": f"aapl-{action.lower()}-{leg}-{for_.isoformat()}", **o}
    return o


def decide(mkt: dict, book: Book, now_ny: dt.datetime, ld=None) -> dict:
    px, decided = mkt["px"], mkt["decided"]
    S = float(px.iloc[-1])
    for_ = coming_session(now_ny)
    sig = gears(px).iloc[-1]
    gear = str(sig["gear"]) if USE_GEAR else "wheel"
    out = {"decided": decided.isoformat(), "for": for_.isoformat(), "spot": round(S, 2),
           "gear": gear, "signals": {
               "close": round(S, 2), "sma": _r(sig["sma"]), "rv": _r(sig["rv"], 1),
               "rv_median": _r(sig["rv_median"], 1), "up": bool(sig["up"]),
               "calm": bool(sig["calm"]), "ma": MA, "rv_window": RV, "lookback": LOOKBACK},
           "earnings": {"next": mkt["earnings"].isoformat() if mkt["earnings"] else None,
                        "estimated": mkt["earnings_estimated"]},
           "book": {"source": book.source, "cash": round(book.cash, 2), "shares": book.shares,
                    "short": ({**book.short, "expiry": book.short["expiry"].isoformat()}
                              if book.short else None),
                    "basis": book.basis, "premium": book.premium},
           "pick": None, "orders": [], "why": []}
    why = out["why"]

    def blocked(expiry: dt.date) -> bool:
        e = mkt["earnings"]
        if not EARNINGS_BLACKOUT or e is None:
            return False
        if mkt["earnings_estimated"]:
            # a date we estimated could come up to ten days early
            return decided < e + dt.timedelta(days=3) and expiry > e - dt.timedelta(days=10)
        return decided < e < expiry

    hold = gear == "hold" and (HOLD_BUYS or book.shares > 0 or
                               (book.short is not None and book.short["right"] == "C"))
    why.append(f"gear {gear.upper()}: close {S:.2f} {'above' if sig['up'] else 'not above'} "
               f"its {MA}-day average {sig['sma']:.2f}; {RV}-day vol {sig['rv']:.1f}% "
               f"{'at or below' if sig['calm'] else 'above'} its 1-year median "
               f"{sig['rv_median']:.1f}%")

    prev = for_ - dt.timedelta(days=1)
    while not is_session(prev):
        prev -= dt.timedelta(days=1)
    if prev != decided:
        why.append(f"stale: the last close is {decided}, but {for_} follows {prev}, "
                   "which Sanji has not resolved yet. No new orders this run.")
        out["stale"] = True
        return out

    if book.short is not None:
        sh = book.short
        if book.premium is not None:
            lmt = round((1 - TAKE) * book.premium, 2)
            out["orders"].append(sanji(for_, "BTC", sh["qty"], "put" if sh["right"] == "P" else "call",
                                       expiry=sh["expiry"], strike=sh["strike"], lmt=lmt))
            why.append(f"profit-take: buy back the {sh['strike']:g} {sh['right']} at "
                       f"{lmt:.2f}, half its {book.premium:.2f} premium")
        else:
            why.append("short option open; its entry fill is not in mkt/fills.json, "
                       "so no profit-take is posted. It runs to expiry.")
        return out

    if hold:
        if book.shares == 0:
            n = int(book.cash // (CONTRACT * S)) * CONTRACT
            if n:
                out["orders"].append(sanji(for_, "BUY", n, "underlying"))
                why.append(f"hold gear, flat: buy {n} shares at the open")
        else:
            why.append(f"hold gear: own the {book.shares} shares, sell no call")
        return out

    expiry = first_monthly(decided)
    if blocked(expiry):
        why.append(f"earnings {mkt['earnings']} fall inside the {expiry} expiry: "
                   "no new short tonight")
        return out
    if ld is None:
        why.append("no LSEG session: chain not read")
        return out
    if book.shares == 0:
        chain = pull_chain(ld, "P", expiry, S, None, decided, now_ny.date(), mkt["r"], mkt["q"])
        pk = pick(chain, -PUT_DELTA) if not chain.empty else None
        if pk is None:
            why.append(f"no two-sided put quote on {expiry}: decide again tomorrow")
            return out
        K = float(pk["strike"])
        n = int(book.cash // (CONTRACT * K))
        out["pick"] = _pick_row(pk, "P", expiry, len(chain))
        if n < 1:
            why.append(f"cash {book.cash:,.0f} does not secure one {K:g} put")
            return out
        out["orders"].append(sanji(for_, "SHT", n, "put", expiry=expiry, strike=K, lmt="mid"))
        oi = pk.get("OPINT_1", np.nan)
        why.append(f"flat: sell {n} {expiry} {K:g} put (delta {pk['delta']:+.2f}"
                   f"{f', open interest {int(oi):,}, the most in the 0.20-0.40 band' if OI_STRIKE and np.isfinite(oi) else ''}"
                   f", IV {pk['iv'] * 100:.1f}%, last mid {pk['mid']:.2f}), secured by "
                   f"${n * K * CONTRACT:,.0f}")
        return out

    floor = book.basis
    chain = pull_chain(ld, "C", expiry, S, floor, decided, now_ny.date(), mkt["r"], mkt["q"])
    pk = pick(chain, CALL_DELTA, floor) if not chain.empty else None
    if pk is None:
        why.append(f"no call at or above the basis {floor} on {expiry}: hold uncovered")
        return out
    K = float(pk["strike"])
    out["pick"] = _pick_row(pk, "C", expiry, len(chain))
    n = book.shares // CONTRACT
    out["orders"].append(sanji(for_, "SHT", n, "call", expiry=expiry, strike=K, lmt="mid"))
    why.append(f"wheel, long {book.shares}: sell {n} {expiry} {K:g} call (delta "
               f"{pk['delta']:+.2f}){'' if floor is None else f', basis floor {floor:.2f}'}")
    return out


def _r(x, nd=2):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def _pick_row(pk, right, expiry, n) -> dict:
    return {"right": right, "expiry": expiry.isoformat(), "strike": _k(pk["strike"]),
            "delta": _r(pk["delta"], 3), "iv": _r(pk["iv"] * 100, 1), "bid": _r(pk["BID"]),
            "oi": None if not np.isfinite(pk.get("OPINT_1", np.nan)) else int(pk["OPINT_1"]),
            "ask": _r(pk["ASK"]), "mid": _r(pk["mid"]), "quotes": int(n)}


# ── files ─────────────────────────────────────────────────────────────────

def merged_orders(new: list[dict], for_: dt.date, today: dt.date) -> list[dict]:
    """
    Keep any order whose session has not been resolved yet (a late run must
    not pull this morning's orders out from under Sanji), replace tonight's
    session with tonight's decision, drop the rest.
    """
    old = []
    f = ROOT / "open_orders.json"
    if f.exists():
        try:
            old = json.loads(f.read_text())
        except ValueError:
            old = []
    keep = [o for o in old if isinstance(o, dict) and today.isoformat() <= str(o.get("for", ""))
            and o.get("for") != for_.isoformat()]
    return sorted(keep, key=lambda o: (o["for"], o["id"])) + new


def write(state: dict, orders: list[dict]) -> None:
    text = json.dumps(orders, indent=2) + "\n"
    MKT.mkdir(exist_ok=True)
    (MKT / "open_orders.json").write_text(text)
    (ROOT / "open_orders.json").write_text(text)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "state.json").write_text(json.dumps(state, indent=2) + "\n")
    log_f = STATE_DIR / "log.json"
    log = json.loads(log_f.read_text()) if log_f.exists() else []
    row = {"decided": state["decided"], "for": state["for"], "gear": state["gear"],
           "close": state["signals"]["close"], "sma": state["signals"]["sma"],
           "rv": state["signals"]["rv"], "rv_median": state["signals"]["rv_median"],
           "orders": [o["id"] for o in state["orders"]], "why": state["why"][-1]}
    log = [x for x in log if x.get("decided") != row["decided"]] + [row]
    log_f.write_text(json.dumps(sorted(log, key=lambda x: x["decided"]), indent=2) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="decide and print; write nothing")
    args = ap.parse_args()

    import lseg.data as ld
    from nightly.refresh import open_session

    now_ny = dt.datetime.now(ZoneInfo("America/New_York"))
    book, problem = read_book()
    session, kind = open_session(ld)
    try:
        mkt = pull_market(ld, now_ny)
        if book is None:
            state = decide(mkt, Book(0, 0, None, None, None, "unreadable"), now_ny)
            state["orders"], state["why"] = [], [state["why"][0],
                                                 f"no orders tonight: {problem}"]
        else:
            state = decide(mkt, book, now_ny, ld)
    finally:
        try:
            session.close()
        except Exception as e:
            print(f"warning: session close failed: {e}")

    state["generated_utc"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["session"] = kind
    if os.environ.get("GITHUB_RUN_ID"):
        state["run"] = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                        f"{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    orders = merged_orders(state["orders"], dt.date.fromisoformat(state["for"]), now_ny.date())
    state["open_orders"] = orders
    print("\n".join(state["why"]))
    print(json.dumps(orders, indent=2))
    if args.dry_run:
        print("dry run: nothing written")
        return
    write(state, orders)
    print(f"wrote {len(orders)} order(s) to open_orders.json and mkt/open_orders.json")


if __name__ == "__main__":
    sys.exit(main())
