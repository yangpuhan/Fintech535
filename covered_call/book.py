"""
The book: rules in, blotter + ledger + Reg T out.

Nothing in here looks at a chart. It walks the hourly tape once, forward, and
records what it did. Every number the site prints comes from this walk.

The rules, stated once
----------------------
ENTRY      First trading session of the expiry week, at ORDER_HOUR_UTC.
           7 Sep 2026 is Labor Day, so that week enters on Tuesday the 8th.
           "Monday" is a name for the first session, not a date arithmetic.

STOCK      If flat, BUY 100 shares at the stock print on that bar. If the
           previous week's call expired worthless the shares are still here,
           so nothing is bought and the basis carries.

STRIKE     SELL 1 call expiring that Friday, struck at the lowest listed
           strike >= spot. Nearest OTM; ATM only if spot sits exactly on a
           strike. AAPL weeklies list on a $2.50 grid at this price, so the
           call is never more than 0.8% out of the money.

FILL       Limit at mid = (BID+ASK)/2 on the order bar. Stock at the print.
           No bid or no ask -> no fill, skip the week.

COMBO      The two legs go on together or not at all. If the call cannot be
           priced while the book is flat, the stock is not bought either —
           buying 100 shares with no call against them is a different
           strategy, and a backtest that quietly does it is lying about what
           it tested. Already long and the call cannot be priced: hold the
           shares uncovered and write nothing.

EXPIRY     Wait through it. No rolls, no buy-to-close. Settlement is the last
           stock print of the expiry session.
             settle <= K : EXPIRE. Short call goes to zero. Keep shares, keep
                           premium, cash unchanged. Next week just writes
                           again.
             settle >  K : ASSIGNED. Deliver the 100 shares at K, cash up by
                           100 x K, flat. Next week starts the combo over.

Ties go to the writer: settle exactly == K expires worthless, which is what
the contract says. In practice a pin gets exercised or not on the holder's
whim, and that is a real risk this backtest does not model.

MARKS      Stock at TRDPRC_1 of the bar. Short call at its mid. A bar with
           only one side quoted is not a mid, so the last good mid is carried
           forward; if there has never been one, intrinsic. Marks move NAV.
           Marks never move cash — only blotter events do.

REG T      Reg T, not portfolio margin.
             LMV       = shares x stock mark
             Initial   = 50% of stock LMV; a covered short call adds $0
             Maint     = 25% of stock LMV (FINRA house minimum floor)
             NAV       = cash + stock MV + option MV   (short call negative)
             Available = NAV - initial
             Excess    = NAV - maintenance
           The call is covered by the shares for its whole life, so it never
           contributes margin. That is the entire reason this structure is
           computable without a broker's risk engine.
"""

from __future__ import annotations

import datetime as dt
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .ric import parse_option_ric

DATA_FILE = Path(__file__).with_name("data.pkl")

CONTRACT = 100           # shares per option contract
QTY_SHARES = 100         # long 100 shares
QTY_CALLS = 1            # short 1 call

# Reg T / FINRA. Not portfolio margin: a book that lives in Reg T lives in
# PM, not the reverse.
INITIAL_RATE = 0.50
MAINT_RATE = 0.25

# The smallest round opening balance that keeps Reg T available funds
# non-negative on every bar of this run. Checked, not guessed — see
# `min_opening_cash` on the result.
OPENING_CASH = 20_000.00


def _r2(x: float) -> float:
    return float(np.round(x, 2))


def _r3(x: float) -> float:
    """Option marks need three places: a mid off a penny spread is a half-cent."""
    return float(np.round(x, 3))


# Illustrative only. The book carries a Reg T debit whenever it is long stock,
# and this backtest does not charge interest on it. Quoting a rate makes the
# omission a number the reader can check instead of a silence.
DEBIT_RATE = 0.065


@dataclass
class Fill:
    """One line of the blotter. Working orders never get here."""
    ts: pd.Timestamp
    instrument: str
    side: str            # BUY | SELL | EXPIRE | ASSIGN
    qty: int
    limit: float | None  # the price the order was worked at; None if not an order
    fill: float
    cash_delta: float
    cash_after: float
    rule: str
    note: str


@dataclass
class Short:
    ric: str
    strike: float
    expiry: dt.date
    premium: float
    opened: pd.Timestamp


@dataclass
class Result:
    blotter: list[Fill] = field(default_factory=list)
    ledger: list[dict] = field(default_factory=list)
    weeks: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


# ── reading the tape ─────────────────────────────────────────────────────

def load(path: Path = DATA_FILE) -> dict:
    with path.open("rb") as f:
        return pickle.load(f)


def option_frame(raw: dict) -> pd.DataFrame:
    """
    Long table: one row per (timestamp, contract), with a mid where there is
    a two-sided quote.

    A mid needs *both* sides. A bar quoted 0.00 bid / 0.05 ask is a real
    two-sided market and keeps its mid of 0.025; a bar with a bid and no ask
    does not get one.
    """
    o = raw["options"]
    rows = []
    for ric in o.columns.get_level_values(0).unique():
        m = parse_option_ric(ric)
        if m is None:
            continue
        sub = o[ric].copy()
        sub.index = pd.DatetimeIndex(sub.index)
        sub = sub.dropna(how="all")
        if sub.empty:
            continue
        sub = sub.assign(ric=ric, strike=m["strike"], expiry=m["expiry"],
                         right=m["right"])
        rows.append(sub.reset_index().rename(columns={"index": "ts",
                                                      "Timestamp": "ts"}))
    df = pd.concat(rows, ignore_index=True)
    for c in ("BID", "ASK", "TRDPRC_1", "ACVOL_UNS", "NUM_MOVES"):
        if c not in df:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")
    both = df["BID"].notna() & df["ASK"].notna()
    df["mid"] = np.where(both, (df["BID"] + df["ASK"]) / 2.0, np.nan)
    df["spread"] = np.where(both, df["ASK"] - df["BID"], np.nan)
    return df


def stock_series(raw: dict) -> pd.DataFrame:
    s = raw["stock"].copy()
    s.index = pd.DatetimeIndex(s.index)
    return s.sort_index()


# ── the walk ─────────────────────────────────────────────────────────────

def run(raw: dict, opening_cash: float = OPENING_CASH) -> Result:
    stock = stock_series(raw)
    opts = option_frame(raw)
    order_hour = raw["order_hour_utc"]

    # (ts, ric) -> quote, so the walk is a lookup rather than a scan
    quote = opts.set_index(["ts", "ric"]).sort_index()
    by_expiry: dict[dt.date, pd.DataFrame] = {
        e: g for e, g in opts[opts["right"] == "C"].groupby("expiry")
    }

    res = Result()
    cash = opening_cash
    shares = 0
    short: Short | None = None
    basis: float | None = None       # average cost of the shares on hand
    carry_mark: float | None = None  # stock value the week opened at
    mark_cache: dict[str, float] = {}  # last good mid per ric

    bars = list(stock.index)
    stock_dates = np.array([t.date() for t in bars])

    # what happens on which bar
    entries = {pd.Timestamp(w["entry"]) + pd.Timedelta(hours=order_hour): w
               for w in raw["weeks"] if w["entry"] is not None}
    expiry_bar = {}
    for w in raw["weeks"]:
        same = [t for t in bars if t.date() == w["expiry"]]
        if same:
            expiry_bar[same[-1]] = w

    for ts in bars:
        px = stock.loc[ts, "TRDPRC_1"]
        px = float(px) if pd.notna(px) else np.nan

        # ---- entry -------------------------------------------------------
        if ts in entries and pd.notna(px):
            w = entries[ts]
            chain = by_expiry.get(w["expiry"])
            pick = None
            if chain is not None:
                live = chain[(chain["ts"] == ts) & (chain["strike"] >= px)]
                live = live[live["mid"].notna()].sort_values("strike")
                if not live.empty:
                    pick = live.iloc[0]

            if pick is None:
                res.skipped.append({
                    "expiry": str(w["expiry"]), "entry": str(w["entry"]),
                    "spot": _r2(px),
                    "why": "no two-sided quote on any OTM strike at the order bar",
                })
            else:
                k = float(pick["strike"])
                mid = float(pick["mid"])
                bought = shares == 0
                if bought:
                    cost = px * QTY_SHARES
                    cash -= cost
                    shares = QTY_SHARES
                    basis = px
                    carry_mark = px
                    res.blotter.append(Fill(
                        ts=ts, instrument=raw["stock_ric"], side="BUY",
                        qty=QTY_SHARES, limit=None, fill=_r2(px),
                        cash_delta=_r2(-cost), cash_after=_r2(cash),
                        rule="ENTRY / STOCK",
                        note="flat at the order bar, so the long leg goes on "
                             "at the print"))
                credit = mid * CONTRACT * QTY_CALLS
                cash += credit
                short = Short(ric=str(pick["ric"]), strike=k,
                              expiry=w["expiry"], premium=mid, opened=ts)
                res.blotter.append(Fill(
                    ts=ts, instrument=short.ric, side="SELL", qty=QTY_CALLS,
                    limit=_r2(mid), fill=_r2(mid),
                    cash_delta=_r2(credit), cash_after=_r2(cash),
                    rule="ENTRY / STRIKE + FILL",
                    note=f"lowest listed strike >= spot {px:,.2f}; "
                         f"limit at mid of {pick['BID']:.2f}/{pick['ASK']:.2f}"))
                res.weeks.append({
                    "expiry": str(w["expiry"]), "entry": str(w["entry"]),
                    "entry_ts": ts.isoformat(sep=" "),
                    "spot": _r2(px), "strike": k, "ric": short.ric,
                    "otm_pct": _r2((k / px - 1) * 100),
                    "bid": float(pick["BID"]), "ask": float(pick["ASK"]),
                    "mid": _r2(mid), "premium": _r2(credit),
                    "bought": bought,
                    "basis": _r2(basis),
                    # the stock value this week opened at: the purchase price
                    # if bought, otherwise last week's settle, so a position
                    # carried through an OTM expiry is not counted twice
                    "open_mark": _r2(carry_mark),
                    # unrounded, because rounding to cents before differencing
                    # leaks a few dimes into the reconciliation
                    "_open_raw": float(carry_mark),
                    "_mid_raw": float(mid),
                })

        # ---- mark --------------------------------------------------------
        call_mark = 0.0
        if short is not None:
            call_mark = _mark(quote, ts, short, px, mark_cache)

        # ---- expiry ------------------------------------------------------
        if ts in expiry_bar and short is not None and \
                expiry_bar[ts]["expiry"] == short.expiry:
            settle = px
            wk = next(x for x in res.weeks if x["expiry"] == str(short.expiry))
            wk["settle"] = _r2(settle)
            # Attribution, per week, marked open-to-settle rather than from
            # the purchase basis — a week that inherits shares from an OTM
            # expiry must not be charged again for a move the previous week
            # already reported. Stock marks to settle; the call keeps its
            # premium and pays out its intrinsic. The two add to the same
            # total either way, but this split is the one that shows the
            # call losing money in the week it actually lost it.
            intrinsic = max(0.0, settle - short.strike)
            wk["stock_pnl"] = _r2((settle - wk["_open_raw"]) * CONTRACT)
            wk["call_pnl"] = _r2((short.premium - intrinsic) * CONTRACT)
            wk["intrinsic"] = _r2(intrinsic * CONTRACT)
            wk["week_pnl"] = _r2(wk["stock_pnl"] + wk["call_pnl"])
            if settle > short.strike:
                proceeds = short.strike * CONTRACT * QTY_CALLS
                cash += proceeds
                res.blotter.append(Fill(
                    ts=ts, instrument=short.ric, side="ASSIGN",
                    qty=QTY_CALLS, limit=None, fill=_r2(short.strike),
                    cash_delta=_r2(proceeds), cash_after=_r2(cash),
                    rule="EXPIRY / ITM",
                    note=f"settle {settle:,.2f} > strike {short.strike:,.2f}; "
                         f"100 shares delivered at the strike"))
                wk["outcome"] = "ASSIGNED"
                wk["round_trip"] = _r2((short.strike - basis) * CONTRACT)
                shares, basis, short, carry_mark = 0, None, None, None
                call_mark = 0.0
            else:
                res.blotter.append(Fill(
                    ts=ts, instrument=short.ric, side="EXPIRE",
                    qty=QTY_CALLS, limit=None, fill=0.0,
                    cash_delta=0.0, cash_after=_r2(cash),
                    rule="EXPIRY / OTM",
                    note=f"settle {settle:,.2f} <= strike {short.strike:,.2f}; "
                         f"worthless, shares and premium stay"))
                wk["outcome"] = "EXPIRED"
                wk["round_trip"] = None   # still open; nothing realised yet
                carry_mark = settle       # next week opens from here
                short = None
                call_mark = 0.0

        # ---- ledger ------------------------------------------------------
        stock_mv = shares * px if pd.notna(px) else 0.0
        option_mv = -call_mark * CONTRACT * QTY_CALLS if short is not None else 0.0
        nav = cash + stock_mv + option_mv
        lmv = stock_mv
        initial = INITIAL_RATE * lmv
        maint = MAINT_RATE * lmv
        res.ledger.append({
            "ts": ts.isoformat(sep=" "),
            "shares": shares,
            "stock_mark": _r2(px) if pd.notna(px) else None,
            "call": short.ric if short else None,
            "strike": short.strike if short else None,
            "expiry": str(short.expiry) if short else None,
            "call_mark": _r3(call_mark) if short else None,
            "cash": _r2(cash),
            "stock_mv": _r2(stock_mv),
            "option_mv": _r2(option_mv),
            "nav": _r2(nav),
            "lmv": _r2(lmv),
            "initial": _r2(initial),
            "maint": _r2(maint),
            "available": _r2(nav - initial),
            "excess": _r2(nav - maint),
        })

    res.stats = _stats(res, raw, stock, opening_cash)
    return res


def _mark(quote: pd.DataFrame, ts: pd.Timestamp, short: Short,
          spot: float, cache: dict[str, float]) -> float:
    """
    Mid if the bar is two-sided; otherwise last good mid; otherwise intrinsic.

    Carrying a stale mid forward is the honest failure mode here — the
    alternative, re-deriving a price from a model, would put a number on the
    ledger that no quote ever supported.
    """
    try:
        row = quote.loc[(ts, short.ric)]
    except KeyError:
        row = None
    if row is not None:
        mid = row["mid"]
        if isinstance(mid, pd.Series):
            mid = mid.iloc[0]
        if pd.notna(mid):
            cache[short.ric] = float(mid)
            return float(mid)
    if short.ric in cache:
        return cache[short.ric]
    return max(0.0, (spot - short.strike)) if pd.notna(spot) else 0.0


def _stats(res: Result, raw: dict, stock: pd.DataFrame,
           opening_cash: float) -> dict:
    led = pd.DataFrame(res.ledger)
    nav = led["nav"]
    avail = led["available"]

    # Buy-and-hold has to start where the book started — same bar, same
    # money. Benchmarking against the first bar of the pull instead would
    # hand the baseline a 2.90 head start the book never had.
    first_buy = next(f for f in res.blotter if f.side == "BUY")
    first_px = float(first_buy.fill)
    last_px = float(stock["TRDPRC_1"].dropna().iloc[-1])
    bh_pnl = (last_px - first_px) * QTY_SHARES

    weeks = [w for w in res.weeks if "outcome" in w]
    assigned = [w for w in weeks if w["outcome"] == "ASSIGNED"]
    expired = [w for w in weeks if w["outcome"] == "EXPIRED"]
    prem = sum(w["premium"] for w in res.weeks)

    # the binding Reg T constraint: how little could this book have opened with
    worst = float(avail.min())
    min_cash = opening_cash - worst

    # the week table has to add up to the NAV change, or the attribution is
    # decoration rather than accounting
    attributed = sum(w["week_pnl"] for w in weeks)
    realised = float(nav.iloc[-1]) - opening_cash

    # The Reg T debit this book runs, and what it would have cost. Not
    # deducted anywhere — quoted so the omission is auditable.
    debit = led["cash"].clip(upper=0.0).abs()
    days = (pd.Timestamp(led["ts"].iloc[-1]) - pd.Timestamp(led["ts"].iloc[0])).days

    return {
        "attribution_gap": _r2(attributed - realised),
        # deepest debit the account ever ran, including the moment between
        # the stock buy printing and the premium landing on the same bar
        "cash_min": _r2(min([float(led["cash"].min())]
                           + [f.cash_after for f in res.blotter])),
        "debit_mean": _r2(float(debit.mean())),
        "debit_days": int(days),
        "debit_rate_pct": _r2(DEBIT_RATE * 100),
        "debit_interest": _r2(float(debit.mean()) * DEBIT_RATE * days / 365.0),
        "opening_cash": _r2(opening_cash),
        "final_nav": _r2(float(nav.iloc[-1])),
        "pnl": _r2(float(nav.iloc[-1]) - opening_cash),
        "ret_pct": _r2((float(nav.iloc[-1]) / opening_cash - 1) * 100),
        "nav_max": _r2(float(nav.max())),
        "nav_min": _r2(float(nav.min())),
        "max_drawdown": _r2(float((nav / nav.cummax() - 1).min() * 100)),
        "weeks_total": len(raw["weeks"]),
        "weeks_traded": len(res.weeks),
        "weeks_skipped": len(res.skipped),
        "n_assigned": len(assigned),
        "n_expired": len(expired),
        "premium_total": _r2(prem),
        "premium_mean": _r2(prem / len(res.weeks)) if res.weeks else 0.0,
        "stock_pnl": _r2(sum(w["stock_pnl"] for w in weeks)),
        "call_pnl": _r2(sum(w["call_pnl"] for w in weeks)),
        "intrinsic_paid": _r2(sum(w["intrinsic"] for w in weeks)),
        "bh_first": _r2(first_px),
        "bh_last": _r2(last_px),
        "bh_pnl": _r2(bh_pnl),
        "bh_ret_pct": _r2(bh_pnl / opening_cash * 100),
        "vs_bh": _r2(float(nav.iloc[-1]) - opening_cash - bh_pnl),
        "min_available": _r2(worst),
        "min_available_ts": str(led.loc[avail.idxmin(), "ts"]),
        "min_opening_cash": _r2(min_cash),
        "ever_negative": bool(worst < 0),
        "max_initial": _r2(float(led["initial"].max())),
        "n_bars": len(led),
        "n_blotter": len(res.blotter),
        "mean_otm_pct": _r2(float(np.mean([w["otm_pct"] for w in res.weeks]))),
        "max_otm_pct": _r2(float(np.max([w["otm_pct"] for w in res.weeks]))),
    }
