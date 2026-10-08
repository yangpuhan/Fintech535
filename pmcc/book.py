"""
The book: rules in, blotter + ledgers out.

One walk over the daily tape decides every trade. The same trades are then
booked into four accounts, so the comparison between them is controlled:

    stock    100 AAPL, bought on the day the PMCC opens, held
    cc       the same 100 AAPL + exactly the PMCC's short calls
    leaps    exactly the PMCC's long calls, no short calls
    pmcc     long LEAPS + short calls

cc and pmcc write the identical calls on the identical days at the identical
fills. Every dollar of difference between them is the long leg: 100 shares
against one deep in-the-money LEAPS.

The rules, stated once
----------------------
TIMING     Decide on the close of session t-1, fill on the close of t. Every
           input to a decision — spot, quotes, delta, rate — is a t-1 close.
           Exchange-driven events (expiry, early assignment) happen on the
           close they happen on.

LONG       Buy 1 call on the nearest January expiry with >= 300 days to run,
           at the listed strike whose delta is closest to 0.80.
ROLL       When the long has <= 120 days left, sell it and buy the next one
           by the same rule, in one order. Never re-struck otherwise.

SHORT      Sell 1 call on the first monthly expiry with >= 21 days to run, at
           the strike whose delta is closest to 0.30 — among strikes that pass
           the gap rule.
GAP RULE   K_short - K_long >= mid_long - mid_short.
           If AAPL gaps through the short strike, the diagonal is worth at
           least its width; the rule says the width must cover what the
           diagonal costs today, so a rally can never lose money. It is the
           textbook "short strike above long strike + net debit" applied to
           today's marks instead of the original cost. It also guarantees
           K_short > K_long, which is what makes the short covered for margin.
HOLD       No profit-taking, no rolling the short. Hold to expiry.
EXPIRY     Close <= K: expires. Close > K: assigned, settled at intrinsic
           (S - K) x 100 — economically, deliver at K and buy the shares back
           on the same close. A new short is decided that evening.
EARLY      On the session before an ex-dividend date, a short call that is in
           the money with less extrinsic value than the dividend is assumed
           exercised against us, settled at intrinsic.
FILLS      Options at the closing mid (BID+ASK)/2; selling needs BID > 0.
           Stock at the closing print. No two-sided quote -> no fill, and the
           decision is re-run on the next close.
COMBO      No short call is ever written without a long call under it. If the
           first long cannot fill, neither does the short.

MARKS      Options at the closing mid; a session with no two-sided quote
           carries the last good mid forward. Stock at the close.
CASH       Cash moves on blotter events and dividends only (stock accounts,
           credited on the ex-date). Idle cash earns the 3-month T-bill rate
           only in the "same account" view; the per-unit view has no interest
           so that legs can be compared in raw dollars.
"""

from __future__ import annotations

import datetime as dt
import pickle
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from covered_call.ric import parse_option_ric

from .greeks import call_delta, implied_vol

DATA_FILE = Path(__file__).with_name("data.pkl")
CONTRACT = 100
SHARES = 100


@dataclass(frozen=True)
class Params:
    long_delta: float = 0.80
    short_delta: float = 0.30
    gap_rule: bool = True
    min_long_dte: int = 300
    roll_long_dte: int = 120
    min_short_dte: int = 21


HEADLINE = Params()

STRATEGIES = {
    "stock": {"stock": True, "long": False, "short": False},
    "cc":    {"stock": True, "long": False, "short": True},
    "leaps": {"stock": False, "long": True, "short": False},
    "pmcc":  {"stock": False, "long": True, "short": True},
}


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
    Everything the walk is allowed to look at.

    ``upto`` truncates every price series at that close. The exchange
    calendar and the expiry list are not truncated — both are published
    years ahead — and dividends are kept up to the next session's ex-date,
    which AAPL declares a week or more before it. That is what makes the
    truncation test in ``lookahead_test`` meaningful: delete the future and
    the past must not change.
    """

    def __init__(self, raw: dict, upto: dt.date | None = None):
        stock = raw["stock"].copy()
        stock.index = pd.DatetimeIndex(stock.index).normalize()
        cal = [t.date() for t in stock.index]
        self.calendar = cal
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
        # the rate is a quote with holes on bond-market holidays; carry it
        r = rate.reindex(px.index).ffill().bfill() / 100.0
        self.r = {t.date(): float(v) for t, v in r.items()}
        self.divs = divs.sort_values("ex_date").reset_index(drop=True)
        self.ex_dates = {row.ex_date: float(row.amount) for row in self.divs.itertuples()}
        self.q = {d: self._yield(d) for d in self.px}

        self.monthlies = sorted(raw["monthly_expiries"])
        self.januaries = sorted({leg["expiry"] for leg in raw["long_schedule"]})
        self.opts = self._prepare(opts)
        self._index()

    # calendar helpers ---------------------------------------------------
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

    # option table -------------------------------------------------------
    def _prepare(self, o: pd.DataFrame) -> pd.DataFrame:
        meta = {r: parse_option_ric(r) for r in o["ric"].unique()}
        o = o[o["ric"].map(lambda r: meta[r] is not None)].copy()
        o["strike"] = o["ric"].map(lambda r: meta[r]["strike"])
        o["expiry"] = o["ric"].map(lambda r: meta[r]["expiry"])
        o["d"] = o["date"].dt.date
        for c in ("BID", "ASK", "MID_PRICE", "TRDPRC_1", "DELTA", "IMP_VOLT",
                  "ACVOL_UNS", "OPINT_1"):
            o[c] = pd.to_numeric(o[c], errors="coerce").astype(float)
        # a mark needs both sides; 0.00 bid / 0.05 ask is still a market
        two = o["BID"].notna() & o["ASK"].notna() & (o["ASK"] > 0) & \
            (o["ASK"] >= o["BID"]) & (o["BID"] >= 0)
        o["mid"] = np.where(two, (o["BID"] + o["ASK"]) / 2.0, np.nan)
        o["half"] = np.where(two, (o["ASK"] - o["BID"]) / 2.0, np.nan)
        # selling into a zero bid is not a fill
        o["tradeable"] = two & (o["BID"] > 0)
        o["S"] = o["d"].map(self.px)
        o["T"] = (pd.to_datetime(o["expiry"]) - o["date"]).dt.days / 365.0
        o["r"] = o["d"].map(self.r)
        o["q"] = o["d"].map(self.q)
        live = o["mid"].notna() & o["S"].notna() & (o["T"] > 0)
        iv = np.full(len(o), np.nan)
        iv[live.to_numpy()] = implied_vol(
            o.loc[live, "mid"], o.loc[live, "S"], o.loc[live, "strike"],
            o.loc[live, "T"], o.loc[live, "r"], o.loc[live, "q"])
        o["iv"] = iv
        o["delta"] = call_delta(o["S"], o["strike"], o["T"].clip(lower=1e-6),
                                o["r"], o["q"], o["iv"])
        return o.reset_index(drop=True)

    def _index(self):
        o = self.opts
        self.quote = {(d, ric): (m, b, a, h, de, tr)
                      for d, ric, m, b, a, h, de, tr in zip(
                          o["d"], o["ric"], o["mid"], o["BID"], o["ASK"],
                          o["half"], o["delta"], o["tradeable"])}
        self.chain = {k: g for k, g in o[o["tradeable"] & o["delta"].notna()]
                      .groupby(["d", "expiry"])}
        mids = o.pivot_table(index="d", columns="ric", values="mid", aggfunc="first")
        dels = o.pivot_table(index="d", columns="ric", values="delta", aggfunc="first")
        days = [d for d in self.calendar if d <= self.end]
        self.mark_mid = mids.reindex(days).ffill()
        self.mark_delta = dels.reindex(days).ffill()
        self.meta = o.drop_duplicates("ric").set_index("ric")[["strike", "expiry"]]

    def tradeable(self, d, ric):
        q = self.quote.get((d, ric))
        return q if q is not None and q[5] else None

    def mid(self, d, ric) -> float | None:
        """Today's mid, or the last good one (a mark, not a fill)."""
        if ric not in self.mark_mid.columns or d not in self.mark_mid.index:
            return None
        v = self.mark_mid.at[d, ric]
        return float(v) if np.isfinite(v) else None


# ── the walk ─────────────────────────────────────────────────────────────

@dataclass
class Leg:
    ric: str
    strike: float
    expiry: dt.date
    opened: dt.date
    price: float
    delta: float          # at decision


@dataclass
class Run:
    params: Params
    trades: list[dict] = field(default_factory=list)
    state: list[dict] = field(default_factory=list)
    cycles: list[dict] = field(default_factory=list)
    lots: list[dict] = field(default_factory=list)
    first_fill: dt.date | None = None


def _pick(g: pd.DataFrame, target: float):
    i = (g["delta"] - target).abs().to_numpy().argmin()
    return g.iloc[i]


def select_long(m: Market, d: dt.date, p: Params):
    exp = next((e for e in m.januaries if (e - d).days >= p.min_long_dte), None)
    g = m.chain.get((d, exp))
    if g is None or g.empty:
        return None
    return _pick(g, p.long_delta)


def select_short(m: Market, d: dt.date, p: Params, k_long: float, mid_long: float):
    exp = next((e for e in m.monthlies if (e - d).days >= p.min_short_dte), None)
    g = m.chain.get((d, exp))
    if g is None or g.empty:
        return None, None
    g = g[g["strike"] > k_long]
    if g.empty:
        return None, None
    free = _pick(g, p.short_delta)
    if p.gap_rule:
        g = g[(g["strike"] - k_long) >= (mid_long - g["mid"])]
        if g.empty:
            return None, free
    return _pick(g, p.short_delta), free


def run(m: Market, p: Params = HEADLINE) -> Run:
    res = Run(params=p)
    long: Leg | None = None
    short: Leg | None = None
    cycle: dict | None = None
    lot: dict | None = None

    def book(d, leg, side, ric, strike, expiry, qty, price, half, rule, note,
             delta=None):
        res.trades.append({
            "date": d, "leg": leg, "side": side, "ric": ric, "strike": strike,
            "expiry": expiry, "qty": qty, "price": _r4(price),
            "half_spread": _r4(half) if half is not None else None,
            "cash": _r2(-qty * price * CONTRACT), "delta": _r4(delta),
            "rule": rule, "note": note})

    def decide(d) -> dict:
        """Tomorrow's order, from today's close only."""
        order = {}
        cur = long
        if long is None:
            pick = select_long(m, d, p)
            if pick is not None:
                order["long_open"] = pick
                cur = pick
        elif (long.expiry - d).days <= p.roll_long_dte:
            pick = select_long(m, d, p)
            if pick is not None:
                order["long_roll"] = pick
                cur = pick
        if short is None and cur is not None:
            k = float(cur.strike) if isinstance(cur, Leg) else float(cur["strike"])
            mid = m.mid(d, cur.ric if isinstance(cur, Leg) else cur["ric"])
            if mid is not None:
                pick, free = select_short(m, d, p, k, mid)
                if pick is not None:
                    order["short_open"] = pick
                    order["short_free"] = free
                    order["short_floor"] = k + mid
        order["decided"] = d
        return order

    sessions = m.sessions()
    order = decide(m.prev_session(sessions[0]))

    for i, d in enumerate(sessions):
        nxt = sessions[i + 1] if i + 1 < len(sessions) else m.next_session(d)
        S = m.px.get(d)

        # ---- 1. yesterday's order, at today's close ----------------------
        if "long_open" in order:
            pk = order["long_open"]
            q = m.tradeable(d, pk["ric"])
            if q is not None:
                long = Leg(pk["ric"], float(pk["strike"]), pk["expiry"], d, q[0],
                           float(pk["delta"]))
                book(d, "long", "BUY", long.ric, long.strike, long.expiry, +1,
                     q[0], q[3], "LONG",
                     f"nearest January >= {p.min_long_dte}d; delta "
                     f"{pk['delta']:.2f} at the {order['decided']} close "
                     f"(target {p.long_delta:.2f})", pk["delta"])
                lot = _open_lot(long, S, m, d)
                res.first_fill = res.first_fill or d
            else:
                order.pop("short_open", None)   # COMBO: no long, no short
        if "long_roll" in order and long is not None:
            pk = order["long_roll"]
            qn, qo = m.tradeable(d, pk["ric"]), m.tradeable(d, long.ric)
            if qn is not None and qo is not None:
                book(d, "long", "SELL", long.ric, long.strike, long.expiry, -1,
                     qo[0], qo[3], "ROLL",
                     f"{(long.expiry - order['decided']).days}d left at the "
                     f"{order['decided']} close (<= {p.roll_long_dte})")
                _close_lot(lot, d, qo[0], S, res)
                long = Leg(pk["ric"], float(pk["strike"]), pk["expiry"], d, qn[0],
                           float(pk["delta"]))
                book(d, "long", "BUY", long.ric, long.strike, long.expiry, +1,
                     qn[0], qn[3], "ROLL",
                     f"into the next January; delta {pk['delta']:.2f} "
                     f"(target {p.long_delta:.2f})", pk["delta"])
                lot = _open_lot(long, S, m, d)
            else:
                # the short was checked against the new LEAPS; without it,
                # decide again tonight against the one actually held
                order.pop("short_open", None)
        if "short_open" in order and long is not None and short is None:
            pk = order["short_open"]
            q = m.tradeable(d, pk["ric"])
            if q is not None:
                short = Leg(pk["ric"], float(pk["strike"]), pk["expiry"], d, q[0],
                            float(pk["delta"]))
                free = order.get("short_free")
                bound = free is not None and float(free["strike"]) < short.strike
                book(d, "short", "SELL", short.ric, short.strike, short.expiry, -1,
                     q[0], q[3], "SHORT",
                     f"first monthly >= {p.min_short_dte}d; delta "
                     f"{pk['delta']:.2f}" + (
                         f"; gap rule lifted it from {float(free['strike']):.2f}"
                         if bound else ""), pk["delta"])
                cycle = {
                    "opened": d, "decided": order["decided"], "ric": short.ric,
                    "strike": short.strike, "expiry": short.expiry,
                    "spot": S, "premium": q[0], "half_spread": q[3],
                    "delta": float(pk["delta"]),
                    "free_strike": float(free["strike"]) if free is not None else None,
                    "bound": bool(bound), "long_strike": long.strike,
                    "otm_pct": (short.strike / S - 1) * 100 if S else None,
                }

        # ---- 2. the exchange, at today's close ---------------------------
        if short is not None and S is not None:
            intrinsic = max(0.0, S - short.strike)
            why = None
            if short.expiry == d:
                why = "ASSIGNED" if intrinsic > 0 else "EXPIRED"
            elif nxt is not None and nxt in m.ex_dates and intrinsic > 0:
                mid = m.mid(d, short.ric)
                div = m.ex_dates[nxt]
                if mid is not None and mid - intrinsic < div:
                    why = "EARLY"
            if why is not None:
                side = {"EXPIRED": "EXPIRE", "ASSIGNED": "ASSIGN",
                        "EARLY": "ASSIGN"}[why]
                note = (f"close {S:,.2f} <= strike; worthless" if why == "EXPIRED"
                        else f"close {S:,.2f} > strike; settled at intrinsic"
                        if why == "ASSIGNED"
                        else f"ex-date {nxt}: extrinsic {m.mid(d, short.ric) - intrinsic:.2f}"
                             f" < dividend {m.ex_dates[nxt]:.2f}; exercised early")
                book(d, "short", side, short.ric, short.strike, short.expiry, +1,
                     intrinsic, 0.0, "EXPIRY" if why != "EARLY" else "EARLY", note)
                cycle.update({"closed": d, "outcome": why, "settle": S,
                              "intrinsic": intrinsic,
                              "pnl": (cycle["premium"] - intrinsic) * CONTRACT})
                res.cycles.append(cycle)
                short, cycle = None, None
        if long is not None and long.expiry == d:   # never, with the roll rule
            raise RuntimeError(f"long {long.ric} reached expiry")

        res.state.append({"date": d,
                          "long": long.ric if long else None,
                          "short": short.ric if short else None})

        # ---- 3. tonight's decision ---------------------------------------
        order = decide(d)

    if cycle is not None:
        cycle.update({"closed": None, "outcome": "OPEN",
                      "settle": None, "intrinsic": None,
                      "mark": m.mid(m.end, short.ric)})
        cycle["pnl"] = (cycle["premium"] - cycle["mark"]) * CONTRACT
        res.cycles.append(cycle)
    if lot is not None:
        lot.update({"closed": None, "exit": m.mid(m.end, long.ric),
                    "exit_spot": m.px[m.end], "open": True})
        lot["pnl"] = (lot["exit"] - lot["price"]) * CONTRACT
        res.lots.append(lot)
    return res


def _open_lot(leg: Leg, S: float, m: Market, d: dt.date) -> dict:
    T = (leg.expiry - d).days / 365.0
    r = m.r[d]
    intrinsic = max(0.0, S - leg.strike)
    return {"ric": leg.ric, "strike": leg.strike, "expiry": leg.expiry,
            "opened": d, "spot": S, "price": leg.price, "delta": leg.delta,
            "dte": (leg.expiry - d).days, "rate": r,
            "intrinsic": intrinsic, "extrinsic": leg.price - intrinsic,
            # what the option charges for financing the strike until expiry:
            # the gap between paying K at expiry and paying it today
            "carry": leg.strike * (1 - np.exp(-r * T)),
            "itm_pct": (S / leg.strike - 1) * 100}


def _close_lot(lot: dict, d: dt.date, price: float, S: float, res: Run):
    lot.update({"closed": d, "exit": price, "exit_spot": S, "open": False,
                "pnl": (price - lot["price"]) * CONTRACT})
    res.lots.append(lot)


# ── accounts ─────────────────────────────────────────────────────────────

def account(m: Market, res: Run, kind: str, opening: float = 0.0,
            interest: bool = False, scale: int = 1) -> pd.DataFrame:
    """
    The daily ledger for one strategy. Same trades, different legs.

    ``opening=0, interest=False`` is the per-unit view: NAV is cumulative
    P&L, cash goes negative by whatever the position cost. The same-account
    view funds it and lets idle cash earn the T-bill.
    """
    spec = STRATEGIES[kind]
    legs = {k for k in ("long", "short") if spec[k]}
    flows: dict[dt.date, float] = {}
    for t in res.trades:
        if t["leg"] in legs:
            flows[t["date"]] = flows.get(t["date"], 0.0) + t["cash"] * scale
    shares = 0
    rows = []
    cash = opening
    prev = None
    for st in res.state:
        d = st["date"]
        if prev is not None and interest and cash > 0:
            cash *= 1 + m.r[prev] * (d - prev).days / 360.0
        S = m.px[d]
        div = 0.0
        if spec["stock"]:
            if shares == 0 and res.first_fill is not None and d >= res.first_fill:
                shares = SHARES * scale
                cash -= S * shares
            if shares and d in m.ex_dates and d > res.first_fill:
                div = m.ex_dates[d] * shares
                cash += div
        cash += flows.get(d, 0.0)
        lm = m.mid(d, st["long"]) if spec["long"] and st["long"] else None
        sm = m.mid(d, st["short"]) if spec["short"] and st["short"] else None
        ld = m.mark_delta.at[d, st["long"]] if lm is not None else 0.0
        sd = m.mark_delta.at[d, st["short"]] if sm is not None else 0.0
        stock_mv = shares * S
        long_mv = (lm or 0.0) * CONTRACT * scale
        short_mv = -(sm or 0.0) * CONTRACT * scale
        nav = cash + stock_mv + long_mv + short_mv
        rows.append({"date": d, "spot": S, "shares": shares,
                     "long": st["long"] if spec["long"] else None,
                     "long_mark": lm, "short": st["short"] if spec["short"] else None,
                     "short_mark": sm, "cash": cash, "stock_mv": stock_mv,
                     "long_mv": long_mv, "short_mv": short_mv, "nav": nav,
                     "dividend": div,
                     "delta": shares + (float(ld) if np.isfinite(ld) else 0) * CONTRACT * scale
                              - (float(sd) if np.isfinite(sd) else 0) * CONTRACT * scale})
        prev = d
    return pd.DataFrame(rows)


def capital_required(led: pd.DataFrame) -> float:
    """
    The smallest opening balance that pays for every trade without borrowing:
    the deepest the per-unit cash column ever goes.
    """
    return float(max(0.0, -led["cash"].min()))


def spread_cost(res: Run, kind: str, m: Market) -> float:
    """
    What paying the half-spread on every option fill would have cost, plus
    liquidating whatever is still open at the far side on the last close.
    """
    legs = {k for k in ("long", "short") if STRATEGIES[kind][k]}
    cost = sum(t["half_spread"] or 0.0 for t in res.trades
               if t["leg"] in legs and t["side"] in ("BUY", "SELL")) * CONTRACT
    last = res.state[-1]
    for leg in legs:
        ric = last[leg]
        if ric:
            q = m.quote.get((m.end, ric))
            if q is not None and np.isfinite(q[3]):
                cost += q[3] * CONTRACT
    return cost


def perf(m: Market, led: pd.DataFrame, opening: float) -> dict:
    nav = led["nav"].to_numpy()
    dates = list(led["date"])
    rets = nav[1:] / nav[:-1] - 1
    rf = np.array([m.r[dates[i - 1]] * (dates[i] - dates[i - 1]).days / 360.0
                   for i in range(1, len(dates))])
    days = (dates[-1] - dates[0]).days
    dd = nav / np.maximum.accumulate(nav) - 1
    trough = int(dd.argmin())
    years = {}
    for y in sorted({d.year for d in dates}):
        idx = [i for i, d in enumerate(dates) if d.year == y]
        base = nav[idx[0] - 1] if idx[0] > 0 else opening
        years[str(y)] = _r2((nav[idx[-1]] / base - 1) * 100)
    ex = rets - rf
    return {
        "final": _r2(nav[-1]),
        "ret_pct": _r2((nav[-1] / opening - 1) * 100),
        "cagr_pct": _r2(((nav[-1] / opening) ** (365.0 / days) - 1) * 100),
        "vol_pct": _r2(rets.std(ddof=1) * np.sqrt(252) * 100),
        "sharpe": _r2(ex.mean() / ex.std(ddof=1) * np.sqrt(252)),
        "max_dd_pct": _r2(dd.min() * 100),
        "max_dd_date": str(dates[trough]),
        "years": years,
    }


def unit_stats(m: Market, res: Run, kind: str, led: pd.DataFrame) -> dict:
    pnl = led["nav"].to_numpy()
    cap = capital_required(led)
    days = (led["date"].iloc[-1] - led["date"].iloc[0]).days
    dd = pnl - np.maximum.accumulate(pnl)
    sc = spread_cost(res, kind, m)
    return {
        "pnl": _r2(pnl[-1]),
        "capital": _r2(cap),
        "roc_pct": _r2(pnl[-1] / cap * 100) if cap else None,
        "roc_ann_pct": _r2(((1 + pnl[-1] / cap) ** (365.0 / days) - 1) * 100) if cap else None,
        "max_dd": _r2(dd.min()),
        "max_dd_date": str(led["date"].iloc[int(dd.argmin())]),
        "max_dd_pct_cap": _r2(dd.min() / cap * 100) if cap else None,
        "spread_cost": _r2(sc),
        "pnl_natural": _r2(pnl[-1] - sc),
        "dividends": _r2(led["dividend"].sum()),
        "option_fills": sum(1 for t in res.trades if t["leg"] in
                            {k for k in ("long", "short") if STRATEGIES[kind][k]}
                            and t["side"] in ("BUY", "SELL")),
    }


# ── the honesty checks ───────────────────────────────────────────────────

def lookahead_test(raw: dict, full: Run, dates: list[dt.date],
                   p: Params = HEADLINE) -> list[dict]:
    """
    Truncate every price series at D, re-run, and compare the blotter up to
    D with the full run's. A rule that peeks at the future produces a
    different past when the future is deleted.
    """
    keys = ("date", "leg", "side", "ric", "qty", "price")
    out = []
    for D in dates:
        mt = Market(raw, upto=D)
        r = run(mt, p)
        a = [tuple(t[k] for k in keys) for t in full.trades if t["date"] <= D]
        b = [tuple(t[k] for k in keys) for t in r.trades if t["date"] <= D]
        out.append({"upto": str(D), "trades": len(a), "identical": a == b})
    return out


def delta_check(m: Market) -> dict:
    """Our BSM delta against LSEG's DELTA, where LSEG has one."""
    o = m.opts
    both = o[o["delta"].notna() & o["DELTA"].notna() & o["tradeable"]]
    near = both[(both["delta"] - 0.30).abs() < 0.1]
    deep = both[(both["delta"] - 0.80).abs() < 0.1]
    diff = (both["delta"] - both["DELTA"]).abs()
    lseg_missing = o[o["tradeable"] & o["DELTA"].isna()]
    return {
        "n": int(len(both)),
        "median_abs": _r4(float(diff.median())),
        "p90_abs": _r4(float(diff.quantile(0.9))),
        "near_030_median": _r4(float((near["delta"] - near["DELTA"]).abs().median())),
        "near_080_median": _r4(float((deep["delta"] - deep["DELTA"]).abs().median())),
        "lseg_missing": int(len(lseg_missing)),
        "lseg_missing_2022": int((pd.to_datetime(lseg_missing["date"]).dt.year == 2022).sum()),
        "mid_vs_mid_price": _r4(float((o["mid"] - o["MID_PRICE"]).abs().max())),
    }
