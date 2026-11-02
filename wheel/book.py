"""
The book: rules in, blotter + ledger out.

The wheel alternates between two positions. With no shares it sells
cash-secured puts; when a put is assigned it owns the shares and sells
covered calls on them; when the shares are called away it is back to cash
and puts. One engine runs that loop, and the same engine runs the two halves
on their own, as controls:

    wheel      puts while flat, calls while long, shares change hands at the
               strike on assignment
    putwrite   the put half forever: an in-the-money put is settled at
               intrinsic in cash and the next put is sold (CBOE PUT-style)
    buywrite   the call half forever: shares bought on day one; when a call
               is assigned the shares are bought straight back on the same
               close (CBOE BXM-style, and 1.3's covered call)

The rules, stated once
----------------------
TIMING     Decide on the close of session t-1, fill on the close of t. Every
           input to a decision is a t-1 close. Exchange events (expiry,
           assignment, early exercise) happen on the close they happen on.
PUT        With no shares and no short option: sell puts on the first monthly
           expiry with >= 21 days to run, at the strike whose delta is
           closest to -0.30. As many contracts as the cash secures:
           n = floor(cash / (100 x K)), sized on the t-1 cash.
CALL       With shares and no short option: sell one call per 100 shares on
           the first monthly with >= 21 days, at the strike whose delta is
           closest to 0.30 among strikes >= the cost basis of the shares
           (the textbook "never sell below your basis"). If no strike at or
           above the basis has a bid, hold the shares uncovered and try again
           the next session.
BASIS      Per share: the assigned put's strike, less that put's premium,
           less every call premium sold on these shares, plus any paid to buy
           one back. Earlier puts that expired or were closed are not in it:
           they were income on cash, before the shares existed.
ROLL       Profit-take: once a short option can be bought back for half the
           premium it was sold for (closing mid <= 50%), buy it back and sell
           the next one by the same rule in the same order, on a later expiry
           than the one closed (a roll out — otherwise the rule can buy and
           sell the same contract and pay the spread for nothing). If the new
           leg cannot fill, the close stands alone. Otherwise hold to expiry.
EXPIRY     Put: close < K -> assigned, buy 100 shares a contract at K.
           Call: close > K -> called away, deliver the shares at K.
           Otherwise expires worthless. The next leg is decided that evening.
EARLY      Call: on the session before an ex-dividend date, in the money with
           less time value than the dividend -> assigned that close.
           Put: in the money with less time value than the interest on the
           strike to expiry, K(1 - e^-rT), unless the next session is an
           ex-date (the holder waits for the drop) -> assigned that close.
           Both are the holder's rational exercise.
FILLS      Options: sell at mid - k x half-spread, buy at mid + k x half,
           where k is the measured effective spread (fills.py). Selling needs
           BID > 0. No two-sided quote -> no fill, decide again. Stock moves
           only on assignment, at the strike; benchmarks buy at the close.
CASH       Earns the 3-month T-bill rate, actual/360, every night — including
           the cash securing the puts, which is how a cash-secured put is
           held in practice (sweep or T-bills). Dividends are credited on the
           ex-date to shares held into it.
MARKS      Short options at the closing mid; a session with no two-sided
           quote carries the last good mid. Shares at the close.
"""

from __future__ import annotations

import datetime as dt
import pickle
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd

from covered_call.ric import parse_option_ric

from .greeks import delta as bs_delta
from .greeks import implied_vol

DATA_FILE = Path(__file__).with_name("data.pkl")
CONTRACT = 100
OPENING = 100_000.0


@dataclass(frozen=True)
class Params:
    put_delta: float = 0.30
    call_delta: float = 0.30
    min_dte: int = 21
    take: float | None = 0.50        # buy back once this share of premium is earned
    basis_rule: bool = True
    kappa: float = 0.0               # fill = mid -/+ kappa x half-spread
    mode: str = "wheel"              # wheel | putwrite | buywrite


HEADLINE = Params()


def _r2(x):
    return None if x is None or not np.isfinite(x) else float(np.round(x, 2))


def _r4(x):
    return None if x is None or not np.isfinite(x) else float(np.round(x, 4))


def load(path: Path = DATA_FILE) -> dict:
    with path.open("rb") as f:
        return pickle.load(f)


# ── the market, as of a date ─────────────────────────────────────────────

class Market:
    """
    Everything the walk is allowed to look at. ``upto`` truncates every price
    series at that close, for the look-ahead test; the calendar and expiry
    list are published years ahead and are kept, and dividends are kept up to
    the next session's ex-date (AAPL declares them a week or more before).
    """

    def __init__(self, raw: dict, upto: dt.date | None = None):
        stock = raw["stock"].copy()
        stock.index = pd.DatetimeIndex(stock.index).normalize()
        self.calendar = [t.date() for t in stock.index]
        self.start = raw["start"]
        px = stock["TRDPRC_1"].astype(float)
        rate = raw["rate"]["MID_YLD_1"].astype(float).fillna(
            raw["rate"]["B_YLD_1"].astype(float))
        rate.index = pd.DatetimeIndex(rate.index).normalize()
        opts = raw["options"].copy()
        opts["date"] = pd.DatetimeIndex(opts["date"]).normalize()
        divs = raw["dividends"].copy()
        divs["ex_date"] = pd.to_datetime(divs["ex_date"]).dt.date
        divs["pay_date"] = pd.to_datetime(divs["pay_date"]).dt.date

        if upto is not None:
            nxt = self.next_session(upto)
            px = px[px.index.date <= upto]
            rate = rate[rate.index.date <= upto]
            opts = opts[opts["date"].dt.date <= upto]
            divs = divs[divs["ex_date"] <= (nxt or upto)]
        self.end = px.index[-1].date()

        self.px = {t.date(): float(v) for t, v in px.items() if np.isfinite(v)}
        r = rate.reindex(px.index).ffill().bfill() / 100.0
        self.r = {t.date(): float(v) for t, v in r.items()}
        self.divs = divs.sort_values("ex_date").reset_index(drop=True)
        self.ex_dates = {row.ex_date: float(row.amount) for row in self.divs.itertuples()}
        self.q = {d: self._yield(d) for d in self.px}
        self.monthlies = sorted(raw["monthly_expiries"])
        self.opts = self._prepare(opts)
        self._index()

    def next_session(self, d: dt.date) -> dt.date | None:
        later = [s for s in self.calendar if s > d]
        return later[0] if later else None

    def prev_session(self, d: dt.date) -> dt.date:
        return max(s for s in self.calendar if s < d)

    def sessions(self) -> list[dt.date]:
        return [s for s in self.calendar if self.start <= s <= self.end]

    def _yield(self, d: dt.date) -> float:
        lo = d - dt.timedelta(days=365)
        paid = self.divs[(self.divs["ex_date"] > lo) & (self.divs["ex_date"] <= d)]
        return float(paid["amount"].sum()) / self.px[d] if d in self.px else 0.0

    def _prepare(self, o: pd.DataFrame) -> pd.DataFrame:
        meta = {r: parse_option_ric(r) for r in o["ric"].unique()}
        o = o[o["ric"].map(lambda r: meta[r] is not None)].copy()
        o["strike"] = o["ric"].map(lambda r: meta[r]["strike"])
        o["expiry"] = o["ric"].map(lambda r: meta[r]["expiry"])
        o["right"] = o["ric"].map(lambda r: meta[r]["right"])
        o["d"] = o["date"].dt.date
        for c in ("BID", "ASK", "MID_PRICE", "TRDPRC_1", "HIGH_1", "LOW_1",
                  "ACVOL_UNS", "OPINT_1", "IMP_VOLT", "DELTA"):
            o[c] = pd.to_numeric(o[c], errors="coerce").astype(float)
        two = o["BID"].notna() & o["ASK"].notna() & (o["ASK"] > 0) & \
            (o["ASK"] >= o["BID"]) & (o["BID"] >= 0)
        o["mid"] = np.where(two, (o["BID"] + o["ASK"]) / 2.0, np.nan)
        o["half"] = np.where(two, (o["ASK"] - o["BID"]) / 2.0, np.nan)
        o["sellable"] = two & (o["BID"] > 0)     # selling into a zero bid is not a fill
        o["S"] = o["d"].map(self.px)
        o["T"] = (pd.to_datetime(o["expiry"]) - o["date"]).dt.days / 365.0
        o["r"] = o["d"].map(self.r)
        o["q"] = o["d"].map(self.q)
        is_call = (o["right"] == "C").to_numpy()
        live = (o["mid"].notna() & o["S"].notna() & (o["T"] > 0)).to_numpy()
        iv = np.full(len(o), np.nan)
        iv[live] = implied_vol(o.loc[live, "mid"], o.loc[live, "S"], o.loc[live, "strike"],
                               o.loc[live, "T"], o.loc[live, "r"], o.loc[live, "q"],
                               is_call[live])
        o["iv"] = iv
        o["delta"] = bs_delta(o["S"], o["strike"], o["T"].clip(lower=1e-6),
                              o["r"], o["q"], o["iv"], is_call)
        return o.reset_index(drop=True)

    def _index(self):
        o = self.opts
        self.quote = {(d, ric): (m, b, a, h, de, s, v)
                      for d, ric, m, b, a, h, de, s, v in zip(
                          o["d"], o["ric"], o["mid"], o["BID"], o["ASK"],
                          o["half"], o["delta"], o["sellable"], o["iv"])}
        self.chain = {k: g for k, g in o[o["sellable"] & o["delta"].notna()]
                      .groupby(["d", "expiry", "right"])}
        days = [d for d in self.calendar if d <= self.end]
        mids = o.pivot_table(index="d", columns="ric", values="mid", aggfunc="first")
        dels = o.pivot_table(index="d", columns="ric", values="delta", aggfunc="first")
        self.mark_mid = mids.reindex(days).ffill()
        self.mark_delta = dels.reindex(days).ffill()

    def mid(self, d, ric) -> float | None:
        """Today's mid, or the last good one (a mark, not a fill)."""
        if ric not in self.mark_mid.columns or d not in self.mark_mid.index:
            return None
        v = self.mark_mid.at[d, ric]
        return float(v) if np.isfinite(v) else None

    def mark_d(self, d, ric) -> float | None:
        if ric not in self.mark_delta.columns or d not in self.mark_delta.index:
            return None
        v = self.mark_delta.at[d, ric]
        return float(v) if np.isfinite(v) else None

    def fill(self, d, ric, side: str, kappa: float):
        """
        (price, mid, half) for a fill on d's close, or None. A sale needs a
        bid; a purchase needs an ask. kappa never pushes past the quote.
        """
        q = self.quote.get((d, ric))
        if q is None or not np.isfinite(q[0]):
            return None
        mid, bid, ask, half = q[0], q[1], q[2], q[3]
        if side == "SELL":
            if not q[5]:
                return None
            return max(bid, mid - kappa * half), mid, half
        return min(ask, mid + kappa * half), mid, half


# ── the walk ─────────────────────────────────────────────────────────────

@dataclass
class Short:
    ric: str
    right: str
    strike: float
    expiry: dt.date
    qty: int              # contracts, positive number, held short
    premium: float        # per share, the fill
    opened: dt.date
    delta: float          # at decision
    iv: float             # at fill
    spot: float           # at fill
    id: int = 0
    bound: bool = False   # the basis rule moved the strike
    free: float | None = None   # the strike it would have been without it


@dataclass
class Run:
    params: Params
    trades: list[dict] = field(default_factory=list)
    ledger: list[dict] = field(default_factory=list)
    shorts: list[dict] = field(default_factory=list)
    lots: list[dict] = field(default_factory=list)
    first_fill: dt.date | None = None


def first_expiry(m: Market, d: dt.date, p: Params,
                 after: dt.date | None = None) -> dt.date | None:
    """First monthly with >= min_dte days; on a roll, also later than the old one."""
    return next((e for e in m.monthlies if (e - d).days >= p.min_dte
                 and (after is None or e > after)), None)


def _pick(g: pd.DataFrame, target: float):
    i = (g["delta"] - target).abs().to_numpy().argmin()
    return g.iloc[i]


def select_put(m: Market, d: dt.date, p: Params, after: dt.date | None = None):
    exp = first_expiry(m, d, p, after)
    g = m.chain.get((d, exp, "P"))
    if g is None or g.empty:
        return None
    return _pick(g, -p.put_delta)


def select_call(m: Market, d: dt.date, p: Params, floor: float | None,
                after: dt.date | None = None):
    """(pick, free): the rule's call, and the one it would be without the basis floor."""
    exp = first_expiry(m, d, p, after)
    g = m.chain.get((d, exp, "C"))
    if g is None or g.empty:
        return None, None
    free = _pick(g, p.call_delta)
    if floor is not None:
        g = g[g["strike"] >= floor - 1e-9]
        if g.empty:
            return None, free
    return _pick(g, p.call_delta), free


def run(m: Market, p: Params = HEADLINE, opening: float = OPENING) -> Run:
    res = Run(params=p)
    cash = opening
    shares = 0
    basis: float | None = None     # per share, wheel lots only
    short: Short | None = None
    lot: dict | None = None
    next_id = [1]
    stock_mode = p.mode == "buywrite"

    def book(d, action, ric, right, strike, expiry, qty, price, mid, half, rule,
             note, cash_flow):
        res.trades.append({
            "date": d, "action": action, "ric": ric, "right": right,
            "strike": strike, "expiry": expiry, "qty": qty,
            "price": _r4(price), "mid": _r4(mid), "half": _r4(half),
            "cash": _r2(cash_flow), "rule": rule, "note": note,
            "short_id": short.id if short is not None and ric == short.ric else None})

    def close_short(d, outcome, exit_px, S):
        rec = {"id": short.id, "ric": short.ric, "right": short.right,
               "strike": short.strike, "expiry": short.expiry, "qty": short.qty,
               "opened": short.opened, "premium": short.premium,
               "delta": short.delta, "iv": short.iv, "spot": short.spot,
               "otm_pct": (short.strike / short.spot - 1) * 100,
               "closed": d, "outcome": outcome, "exit": exit_px, "settle": S,
               "pnl": (short.premium - exit_px) * CONTRACT * short.qty,
               "bound": short.bound, "free": short.free}
        res.shorts.append(rec)

    def decide(d) -> dict:
        """Tomorrow's order, from today's close only."""
        order = {"decided": d}
        if stock_mode and shares == 0 and short is None:
            S = m.px[d]
            n = int(cash // (CONTRACT * S))
            pick, _ = select_call(m, d, p, None)
            if n > 0 and pick is not None:
                order["buy_stock"] = n * CONTRACT
                order["open"] = ("C", pick, None, n)
            return order
        flat_after = short is None
        if short is not None and p.take is not None:
            mk = m.mid(d, short.ric)
            q = m.quote.get((d, short.ric))
            if mk is not None and q is not None and np.isfinite(q[0]) and \
                    mk <= (1 - p.take) * short.premium:
                order["close"] = short.ric
                flat_after = True
        if not flat_after:
            return order
        after = short.expiry if "close" in order else None
        if shares == 0:
            pick = select_put(m, d, p, after)
            if pick is not None:
                spend = 0.0
                if "close" in order:
                    spend = m.mid(d, short.ric) * CONTRACT * short.qty
                n = int((cash - spend) // (CONTRACT * float(pick["strike"])))
                if n > 0:
                    order["open"] = ("P", pick, None, n)
        else:
            floor = basis if (p.basis_rule and p.mode == "wheel") else None
            pick, free = select_call(m, d, p, floor, after)
            if pick is not None:
                order["open"] = ("C", pick, free, shares // CONTRACT)
            else:
                order["uncovered"] = True
        return order

    sessions = m.sessions()
    prev = m.prev_session(sessions[0])
    order = decide(prev)

    for i, d in enumerate(sessions):
        nxt = sessions[i + 1] if i + 1 < len(sessions) else m.next_session(d)
        S = m.px[d]
        interest = cash * m.r[prev] * (d - prev).days / 360.0 if cash > 0 and i else 0.0
        cash += interest
        div = 0.0
        if shares and d in m.ex_dates:
            div = m.ex_dates[d] * shares
            cash += div
            if lot is not None:
                lot["dividends"] += div
            book(d, "DIVIDEND", "AAPL.O", None, None, None, shares, m.ex_dates[d],
                 None, None, "DIVIDEND", f"ex-date; ${m.ex_dates[d]:.2f} on {shares} shares",
                 div)
        dec = order["decided"]

        # ---- 1. yesterday's order, at today's close ----------------------
        if "buy_stock" in order:
            n_sh = order["buy_stock"]
            while n_sh and n_sh * S > cash:
                n_sh -= CONTRACT
            if n_sh:
                shares = n_sh
                cash -= n_sh * S
                book(d, "BUY", "AAPL.O", None, None, None, n_sh, S, None, None,
                     "STOCK", "buy-write: round lots the cash buys, at the close", -n_sh * S)
                res.first_fill = res.first_fill or d
                order["open"] = order["open"][:3] + (n_sh // CONTRACT,)
            else:
                order.pop("open", None)
        rolled = False
        if "close" in order and short is not None:
            f = m.fill(d, short.ric, "BUY", p.kappa)
            if f is not None:
                px_, mid_, half_ = f
                cost = px_ * CONTRACT * short.qty
                cash -= cost
                rolling = "open" in order
                book(d, "BUY TO CLOSE", short.ric, short.right, short.strike, short.expiry,
                     +short.qty, px_, mid_, half_, "ROLL" if rolling else "CLOSE",
                     f"mid {m.mid(dec, short.ric):.2f} at the {dec} close <= "
                     f"{(1 - p.take) * 100:.0f}% of the {short.premium:.2f} premium",
                     -cost)
                if lot is not None and short.right == "C":
                    lot["calls_net"] -= px_
                    basis += px_
                close_short(d, "ROLLED" if rolling else "CLOSED", px_, S)
                short = None
                rolled = rolling
            else:
                order.pop("open", None)
        if "open" in order and short is None:
            right, pk, free, n = order["open"]
            K = float(pk["strike"])
            if right == "P":
                while n and n * CONTRACT * K > cash:
                    n -= 1
            else:
                n = min(n, shares // CONTRACT)
            f = m.fill(d, pk["ric"], "SELL", p.kappa) if n else None
            if f is not None:
                px_, mid_, half_ = f
                q = m.quote[(d, pk["ric"])]
                bound = free is not None and float(free["strike"]) < K
                short = Short(pk["ric"], right, K, pk["expiry"], n, px_, d,
                              float(pk["delta"]), float(q[6]) if np.isfinite(q[6]) else np.nan,
                              S, next_id[0], bound, float(free["strike"]) if bound else None)
                next_id[0] += 1
                cash += px_ * CONTRACT * n
                what = "put" if right == "P" else "call"
                note = (f"first monthly >= {p.min_dte}d; delta {pk['delta']:+.2f} at the "
                        f"{dec} close (target {'-' if right == 'P' else '+'}"
                        f"{p.put_delta if right == 'P' else p.call_delta:.2f})")
                if right == "P":
                    note += f"; {n} x ${K:,.2f} x 100 = ${n * K * CONTRACT:,.0f} secured"
                if bound:
                    note += f"; basis rule lifted it from {float(free['strike']):.2f}"
                book(d, "SELL TO OPEN", short.ric, right, K, short.expiry, -n, px_, mid_,
                     half_, "ROLL" if rolled else "OPEN", note, px_ * CONTRACT * n)
                if lot is not None and right == "C":
                    lot["calls_net"] += px_
                    lot["calls"] += 1
                    basis -= px_
                res.first_fill = res.first_fill or d

        # ---- 2. the exchange, at today's close ---------------------------
        if short is not None:
            K = short.strike
            intrinsic = max(0.0, (K - S) if short.right == "P" else (S - K))
            why = None
            if short.expiry == d:
                why = "ASSIGNED" if intrinsic > 0 else "EXPIRED"
            elif intrinsic > 0:
                mk = m.mid(d, short.ric)
                if mk is not None:
                    tv = mk - intrinsic
                    if short.right == "C" and nxt in m.ex_dates and tv < m.ex_dates[nxt]:
                        why = "EARLY"
                    elif short.right == "P":
                        T = (short.expiry - d).days / 365.0
                        carry = K * (1 - np.exp(-m.r[d] * T))
                        if tv < carry and nxt not in m.ex_dates:
                            why = "EARLY"
            if why == "EXPIRED":
                book(d, "EXPIRE", short.ric, short.right, K, short.expiry, +short.qty, 0.0,
                     None, None, "EXPIRY",
                     f"close {S:,.2f} {'>=' if short.right == 'P' else '<='} strike; worthless", 0.0)
                close_short(d, "EXPIRED", 0.0, S)
                short = None
            elif why is not None:
                n, sh = short.qty, short.qty * CONTRACT
                tv_note = ""
                if why == "EARLY":
                    tv = m.mid(d, short.ric) - intrinsic
                    tv_note = (f"time value {tv:.2f} < dividend {m.ex_dates[nxt]:.2f} "
                               f"going ex {nxt}" if short.right == "C" else
                               f"time value {tv:.2f} < interest on the strike to expiry; ")
                physical = (p.mode == "wheel")
                if physical and short.right == "P":
                    book(d, "ASSIGNED", short.ric, "P", K, short.expiry, +n, 0.0, None, None,
                         "EARLY" if why == "EARLY" else "EXPIRY",
                         f"{tv_note}close {S:,.2f} < strike; put assigned", 0.0)
                    cash -= K * sh
                    shares += sh
                    basis = K - short.premium
                    lot = {"opened": d, "strike": K, "shares": sh, "put_premium": short.premium,
                           "spot": S, "calls": 0, "calls_net": 0.0, "dividends": 0.0,
                           "put_id": short.id}
                    book(d, "BUY", "AAPL.O", None, None, None, sh, K, None, None, "ASSIGNMENT",
                         f"{sh} shares delivered at the {K:,.2f} strike; basis "
                         f"{K:,.2f} - {short.premium:.2f} premium = {basis:,.2f}", -K * sh)
                    close_short(d, "ASSIGNED" if why != "EARLY" else "EARLY", intrinsic, S)
                elif physical and short.right == "C":
                    book(d, "ASSIGNED", short.ric, "C", K, short.expiry, +n, 0.0, None, None,
                         "EARLY" if why == "EARLY" else "EXPIRY",
                         f"{tv_note}{'; ' if tv_note else ''}close {S:,.2f} > strike; "
                         "call assigned", 0.0)
                    cash += K * sh
                    shares -= sh
                    book(d, "SELL", "AAPL.O", None, None, None, -sh, K, None, None, "CALLED AWAY",
                         f"{sh} shares delivered at the {K:,.2f} strike", K * sh)
                    close_short(d, "CALLED" if why != "EARLY" else "EARLY", intrinsic, S)
                    if lot is not None:
                        lot.update({"closed": d, "exit": K, "exit_spot": S,
                                    "basis": basis,
                                    "pnl": (K - basis) * lot["shares"] + lot["dividends"]})
                        res.lots.append(lot)
                    if shares == 0:
                        lot, basis = None, None
                elif short.right == "C":
                    # buy-write: called away, and the shares bought straight back on
                    # the same close — as many round lots as the cash buys, so the
                    # control stays a cash account like the wheel
                    book(d, "ASSIGNED", short.ric, "C", K, short.expiry, +n, 0.0, None, None,
                         "EARLY" if why == "EARLY" else "EXPIRY",
                         f"{tv_note}{'; ' if tv_note else ''}close {S:,.2f} > strike; "
                         "call assigned", 0.0)
                    cash += K * sh
                    shares -= sh
                    book(d, "SELL", "AAPL.O", None, None, None, -sh, K, None, None, "CALLED AWAY",
                         f"{sh} shares delivered at the {K:,.2f} strike", K * sh)
                    back = int(cash // (CONTRACT * S)) * CONTRACT
                    cash -= back * S
                    shares += back
                    book(d, "BUY", "AAPL.O", None, None, None, back, S, None, None, "STOCK",
                         "buy-write: bought back on the same close, round lots the cash buys",
                         -back * S)
                    close_short(d, "CALLED" if why != "EARLY" else "EARLY", intrinsic, S)
                else:
                    # put-write: settle the in-the-money put at intrinsic, take no shares
                    cost = intrinsic * sh
                    cash -= cost
                    book(d, "CASH SETTLE", short.ric, short.right, K, short.expiry, +n,
                         intrinsic, None, None, "EARLY" if why == "EARLY" else "EXPIRY",
                         f"{tv_note}close {S:,.2f}; settled at intrinsic {intrinsic:.2f}, "
                         "no shares taken", -cost)
                    close_short(d, "SETTLED" if why != "EARLY" else "EARLY", intrinsic, S)
                short = None

        # ---- 3. the books, at today's close ------------------------------
        mk = m.mid(d, short.ric) if short is not None else None
        dl = m.mark_d(d, short.ric) if short is not None else None
        n = short.qty if short is not None else 0
        short_mv = -(mk or 0.0) * CONTRACT * n
        res.ledger.append({
            "date": d, "spot": S, "cash": cash, "shares": shares,
            "basis": basis if shares else None,
            "stock_mv": shares * S, "short": short.ric if short else None,
            "short_id": short.id if short else None,
            "right": short.right if short else None,
            "strike": short.strike if short else None,
            "expiry": short.expiry if short else None,
            "qty": n, "entry": short.premium if short else None,
            "mark": mk, "short_delta": dl, "short_mv": short_mv,
            "collateral": short.strike * CONTRACT * n if short and short.right == "P" else 0.0,
            "nav": cash + shares * S + short_mv,
            "delta": shares - (dl or 0.0) * CONTRACT * n,
            "interest": interest, "dividend": div,
            "phase": ("put" if short and short.right == "P" else
                      "call" if short else "shares" if shares else "cash"),
            "uncovered": bool(shares and short is None),
        })

        # ---- 4. tonight's decision ---------------------------------------
        order = decide(d)
        prev = d

    if short is not None:
        mk = m.mid(m.end, short.ric)
        res.shorts.append({
            "id": short.id, "ric": short.ric, "right": short.right, "strike": short.strike,
            "expiry": short.expiry, "qty": short.qty, "opened": short.opened,
            "premium": short.premium, "delta": short.delta, "iv": short.iv,
            "spot": short.spot, "otm_pct": (short.strike / short.spot - 1) * 100,
            "closed": None, "outcome": "OPEN", "exit": mk, "settle": None,
            "pnl": (short.premium - mk) * CONTRACT * short.qty,
            "bound": short.bound, "free": short.free})
    if lot is not None:
        S = m.px[m.end]
        lot.update({"closed": None, "exit": S, "exit_spot": S, "basis": basis,
                    "pnl": (S - basis) * lot["shares"] + lot["dividends"]})
        res.lots.append(lot)
    return res


# ── benchmarks that need no engine ───────────────────────────────────────

def buy_and_hold(m: Market, first: dt.date, opening: float = OPENING) -> pd.DataFrame:
    """As many whole shares as the account buys on the wheel's first fill, held."""
    cash, shares, rows, prev = opening, 0, [], None
    for d in m.sessions():
        if prev is not None and cash > 0:
            cash *= 1 + m.r[prev] * (d - prev).days / 360.0
        S = m.px[d]
        div = 0.0
        if shares and d in m.ex_dates:
            div = m.ex_dates[d] * shares
            cash += div
        if d == first:
            shares = int(cash // S)
            cash -= shares * S
        rows.append({"date": d, "spot": S, "cash": cash, "shares": shares,
                     "nav": cash + shares * S, "dividend": div})
        prev = d
    return pd.DataFrame(rows)


def tbills(m: Market, opening: float = OPENING) -> pd.DataFrame:
    cash, rows, prev = opening, [], None
    for d in m.sessions():
        if prev is not None:
            cash *= 1 + m.r[prev] * (d - prev).days / 360.0
        rows.append({"date": d, "nav": cash})
        prev = d
    return pd.DataFrame(rows)


# ── statistics ───────────────────────────────────────────────────────────

def perf(m: Market, led: pd.DataFrame, opening: float = OPENING,
         spot: pd.Series | None = None) -> dict:
    nav = led["nav"].to_numpy(float)
    dates = list(led["date"])
    rets = nav[1:] / nav[:-1] - 1
    rf = np.array([m.r[dates[i - 1]] * (dates[i] - dates[i - 1]).days / 360.0
                   for i in range(1, len(dates))])
    days = (dates[-1] - dates[0]).days
    dd = nav / np.maximum.accumulate(nav) - 1
    trough = int(dd.argmin())
    peak = int(np.argmax(nav[:trough + 1])) if trough else 0
    ex = rets - rf
    down = np.minimum(ex, 0.0)
    years = {}
    for y in sorted({d.year for d in dates}):
        idx = [i for i, d in enumerate(dates) if d.year == y]
        base = nav[idx[0] - 1] if idx[0] > 0 else opening
        years[str(y)] = _r2((nav[idx[-1]] / base - 1) * 100)
    out = {
        "final": _r2(nav[-1]),
        "ret_pct": _r2((nav[-1] / opening - 1) * 100),
        "cagr_pct": _r2(((nav[-1] / opening) ** (365.0 / days) - 1) * 100),
        "vol_pct": _r2(rets.std(ddof=1) * np.sqrt(252) * 100),
        # T-bills against T-bills is 0/0; report no ratio rather than rounding noise
        "sharpe": _r2(ex.mean() / ex.std(ddof=1) * np.sqrt(252)) if ex.std() > 1e-9 else None,
        "sortino": _r2(ex.mean() / np.sqrt((down ** 2).mean()) * np.sqrt(252))
                   if (down ** 2).mean() > 1e-18 else None,
        "max_dd_pct": _r2(dd.min() * 100),
        "max_dd_date": str(dates[trough]),
        "max_dd_peak": str(dates[peak]),
        "years": years,
    }
    if spot is not None:
        s = spot.to_numpy(float)
        sr = s[1:] / s[:-1] - 1
        cov = np.cov(rets, sr, ddof=1)
        out["beta"] = _r2(cov[0, 1] / cov[1, 1])
        out["corr"] = _r2(np.corrcoef(rets, sr)[0, 1])
        up, dn = sr > 0, sr < 0
        out["up_capture_pct"] = _r2(rets[up].mean() / sr[up].mean() * 100)
        out["down_capture_pct"] = _r2(rets[dn].mean() / sr[dn].mean() * 100)
    return out


def realized_vol(m: Market, a: dt.date, b: dt.date) -> float | None:
    """Close-to-close realized vol from a to b, annualised on 252 sessions."""
    px = [m.px[d] for d in m.calendar if a <= d <= b and d in m.px]
    if len(px) < 3:
        return None
    lr = np.diff(np.log(px))
    return float(np.sqrt((lr ** 2).mean() * 252))


# ── the honesty checks ───────────────────────────────────────────────────

def lookahead_test(raw: dict, full: Run, dates: list[dt.date], p: Params) -> list[dict]:
    """
    Truncate every price series at D, re-run from scratch, and compare the
    blotter up to D. A rule that peeks at the future produces a different
    past when the future is deleted.
    """
    keys = ("date", "action", "ric", "qty", "price")
    out = []
    for D in dates:
        r = run(Market(raw, upto=D), p)
        a = [tuple(t[k] for k in keys) for t in full.trades if t["date"] <= D]
        b = [tuple(t[k] for k in keys) for t in r.trades if t["date"] <= D]
        out.append({"upto": str(D), "trades": len(a), "identical": a == b})
    return out


def reconcile(m: Market, res: Run, opening: float = OPENING) -> dict:
    """
    Two independent ways to the same NAV. Cash: opening + every blotter cash
    flow + interest must equal the ledger's cash. P&L: option P&L (premium
    less what was paid or forgone at the exit) + share P&L (shares held
    overnight x the day's move) + dividends + interest must equal NAV - opening.
    """
    led = pd.DataFrame(res.ledger)
    flows = sum(t["cash"] or 0.0 for t in res.trades)
    cash_gap = opening + flows + led["interest"].sum() - led["cash"].iloc[-1]
    opt = sum(s["pnl"] for s in res.shorts)
    sh = led["shares"].to_numpy()
    sp = led["spot"].to_numpy()
    stock = float((sh[:-1] * np.diff(sp)).sum())
    # shares that arrive by assignment enter at the close, at the close's price;
    # the strike-vs-close gap is in the option's intrinsic, so nothing is missed
    total = opt + stock + led["dividend"].sum() + led["interest"].sum()
    return {"cash_gap": _r2(cash_gap),
            "pnl_gap": _r2(total - (led["nav"].iloc[-1] - opening)),
            "option_pnl": _r2(opt), "stock_pnl": _r2(stock),
            "dividends": _r2(led["dividend"].sum()),
            "interest": _r2(led["interest"].sum())}
