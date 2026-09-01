"""
Workhorse functions for the options surface lab.

Parses LSEG expired-option history into a tidy long table, pivots it so the
mark and the print sit side by side, and reports how much of the listed grid
is actually empty.

A note on fields
---------------
The assignment names ``SETTLE`` as the exchange mark. That field does not
exist on this universe — LSEG answers ``The universe does not support the
following fields: [SETTLE]`` for OPRA equity options, which is why the
original cache contained nothing but TRDPRC_1.

``THEO_VALUE`` is the stand-in and it plays the same role the README
describes: a model-ish number that prints on more series than trades do. The
argument the assignment is after — *mark is not print* — is unchanged.
"""

from __future__ import annotations

import datetime as dt
import pickle
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import griddata

from .option_surface_theme import MARK_FIELD, PRINT_FIELD


# OPRA month codes: A-L are calls Jan-Dec, M-X are puts Jan-Dec.
CALL_MONTHS = {chr(ord("A") + i): i + 1 for i in range(12)}
PUT_MONTHS = {chr(ord("M") + i): i + 1 for i in range(12)}
MONTH_CODE_TO_CP = {**{k: "C" for k in CALL_MONTHS}, **{k: "P" for k in PUT_MONTHS}}
MONTH_CODE_TO_MONTH = {**CALL_MONTHS, **PUT_MONTHS}

# UUUUA1502600650.U   or   UUUUA1502600650.U^A26
RIC_RE = re.compile(
    r"^(?P<root>[A-Z]+)(?P<code>[A-X])(?P<day>\d{2})(?P<year>\d{2})"
    r"(?P<strike>\d{5})(?:\.U)?(?:\^[A-X]\d{2})?$",
    re.IGNORECASE,
)

# Every numeric field we keep off the pull.
VALUE_FIELDS = [
    PRINT_FIELD,
    MARK_FIELD,
    "MID_PRICE",
    "BID",
    "ASK",
    "ACVOL_UNS",
    "OPINT_1",
    "IMP_VOLT",
]


def parse_option_ric(ric: str) -> dict | None:
    """Extract root, put/call, expiry, strike from an expired OPRA-style RIC."""
    text = str(ric).strip()
    m = RIC_RE.match(text)
    if not m:
        return None
    code = m.group("code").upper()
    month = MONTH_CODE_TO_MONTH.get(code)
    cp = MONTH_CODE_TO_CP.get(code)
    if month is None or cp is None:
        return None
    try:
        expiry = dt.date(2000 + int(m.group("year")), month, int(m.group("day")))
    except ValueError:
        return None
    return {
        "ric": text,
        "root": m.group("root").upper(),
        "cp": cp,
        "expiry": expiry,
        "strike": int(m.group("strike")) / 100.0,
        "month_code": code,
    }


def _field_and_ric_levels(cols: pd.MultiIndex) -> tuple[int, int]:
    """LSEG is inconsistent about whether RIC or field is the outer level."""
    known = {f.upper() for f in VALUE_FIELDS} | {"SETTLE", "CLOSE"}
    for i in range(cols.nlevels):
        vals = {str(v).upper() for v in cols.get_level_values(i)}
        if vals & known:
            return i, (1 if i == 0 else 0)
    return 1, 0


def flatten_lseg_options(df_options: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse an LSEG get_history frame into one row per (date, ric, field).

    Wide (dates x contracts) is unusable for analysis: the contract's
    attributes are buried in the column label and most cells are empty. Long
    format puts strike / dte / field in columns where they can be grouped.
    """
    empty = pd.DataFrame(
        columns=["date", "ric", "field", "value", "root", "cp", "expiry", "strike", "dte"]
    )
    if df_options is None or df_options.empty:
        return empty

    frame = df_options.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index)

    if isinstance(frame.columns, pd.MultiIndex):
        field_level, ric_level = _field_and_ric_levels(frame.columns)
        pairs = [
            (str(c[ric_level]), str(c[field_level]).upper(), c) for c in frame.columns
        ]
    else:
        # A single-field pull comes back flat, with the field name parked on
        # columns.name — that is exactly how the original cache lost SETTLE.
        field = str(frame.columns.name or PRINT_FIELD).upper()
        pairs = [(str(c), field, c) for c in frame.columns]

    parsed_cache: dict[str, dict | None] = {}
    rows = []
    for ric, field, col in pairs:
        if ric not in parsed_cache:
            parsed_cache[ric] = parse_option_ric(ric)
        parsed = parsed_cache[ric]
        if parsed is None:
            continue
        series = pd.to_numeric(frame[col], errors="coerce").dropna()
        if series.empty:
            continue
        for ts, val in series.items():
            rows.append(
                {
                    "date": pd.Timestamp(ts).normalize(),
                    "field": field,
                    "value": float(val),
                    **parsed,
                }
            )

    tidy = pd.DataFrame(rows)
    if tidy.empty:
        return empty
    tidy["date"] = pd.to_datetime(tidy["date"])
    tidy["expiry"] = pd.to_datetime(tidy["expiry"])
    tidy["dte"] = (tidy["expiry"] - tidy["date"]).dt.days
    return tidy[tidy["dte"] >= 0].copy()


def attach_underlying(tidy: pd.DataFrame, df_stock: pd.DataFrame) -> pd.DataFrame:
    """Join each option row to that day's underlying close, and add K/S."""
    tidy = tidy.copy()
    if tidy.empty or df_stock is None or df_stock.empty:
        tidy["spot"] = np.nan
        tidy["moneyness"] = np.nan
        return tidy

    stock = df_stock.copy()
    if not isinstance(stock.index, pd.DatetimeIndex):
        stock.index = pd.to_datetime(stock.index)
    close_col = "TRDPRC_1" if "TRDPRC_1" in stock.columns else stock.columns[-1]
    spot = pd.to_numeric(stock[close_col], errors="coerce").dropna()
    spot.index = pd.DatetimeIndex(spot.index).normalize()
    spot = spot.sort_index()

    # reindex + ffill: an option can quote on a day the tape has no stock bar
    aligned = spot.reindex(
        spot.index.union(pd.DatetimeIndex(tidy["date"].unique()))
    ).ffill()
    tidy["spot"] = tidy["date"].map(aligned)
    tidy["moneyness"] = tidy["strike"] / tidy["spot"]
    return tidy


def pivot_mark_print(tidy: pd.DataFrame) -> pd.DataFrame:
    """One row per (date, contract) with every field as its own column."""
    if tidy.empty:
        return tidy

    idx_cols = [
        c
        for c in ["date", "ric", "root", "cp", "expiry", "strike", "dte", "spot", "moneyness"]
        if c in tidy.columns
    ]
    wide = (
        tidy.pivot_table(index=idx_cols, columns="field", values="value", aggfunc="last")
        .reset_index()
    )
    wide.columns.name = None

    for f in VALUE_FIELDS:
        if f not in wide.columns:
            wide[f] = np.nan

    wide["has_mark"] = wide[MARK_FIELD].notna()
    wide["has_print"] = wide[PRINT_FIELD].notna()
    wide["abs_diff"] = (wide[MARK_FIELD] - wide[PRINT_FIELD]).abs()
    wide["rel_diff"] = wide["abs_diff"] / wide[MARK_FIELD].replace(0, np.nan)
    wide["spread"] = wide["ASK"] - wide["BID"]
    # A missing BID on a deep-OTM strike is not missing data — it means no
    # one bids at all. Treating it as 0 is what makes the fill question real.
    wide["bid_filled"] = wide["BID"].fillna(0.0).where(wide["ASK"].notna())
    wide["spread_filled"] = wide["ASK"] - wide["bid_filled"]

    # 0 = nothing quoted, 1 = mark only, 2 = mark and a real print
    wide["occupancy"] = np.where(
        wide["has_mark"] & wide["has_print"], 2, np.where(wide["has_mark"] | wide["has_print"], 1, 0)
    )
    return wide


# Kept so older imports of the starter name keep working.
pivot_trade_settle = pivot_mark_print


def surface_grid(points: pd.DataFrame, value_col: str, n_strike: int = 44, n_dte: int = 32):
    """
    Interpolate the sparse cloud onto a regular grid for a Plotly Surface.

    This sheet is an assumption, not a market. Holes stay NaN so Plotly does
    not paint a surface over wings that never quoted.
    """
    cloud = points.dropna(subset=["strike", "dte", value_col])
    if len(cloud) < 8:
        return None
    x = cloud["strike"].to_numpy(float)
    y = cloud["dte"].to_numpy(float)
    z = cloud[value_col].to_numpy(float)
    if len(np.unique(x)) < 2 or len(np.unique(y)) < 2:
        return None
    xi = np.linspace(x.min(), x.max(), n_strike)
    yi = np.linspace(max(0, y.min()), y.max(), n_dte)
    XX, YY = np.meshgrid(xi, yi)
    return {"x": xi, "y": yi, "z": griddata((x, y), z, (XX, YY), method="linear")}


def summarize_sparsity(wide: pd.DataFrame) -> dict:
    """The two numbers the assignment asks to be printed on the page, plus context."""
    blank = {
        "n_series": 0,
        "n_mark": 0,
        "n_print": 0,
        "n_mark_only": 0,
        "n_print_only": 0,
        "n_both": 0,
        "pct_mark_no_print": 0.0,
        "median_abs_diff": None,
        "median_rel_diff_pct": None,
        "median_spread": None,
        "n_dates": 0,
    }
    if wide is None or wide.empty:
        return blank

    n = len(wide)
    both = wide["has_mark"] & wide["has_print"]
    mark_only = wide["has_mark"] & ~wide["has_print"]
    print_only = wide["has_print"] & ~wide["has_mark"]
    diffs = wide.loc[both, "abs_diff"].dropna()
    rel = wide.loc[both, "rel_diff"].dropna()
    spread = wide["spread_filled"].dropna()

    # Denominator is series carrying a mark — "of the contracts the exchange
    # priced, how many did nobody trade?"
    n_mark = int(wide["has_mark"].sum())
    return {
        "n_series": int(n),
        "n_mark": n_mark,
        "n_print": int(wide["has_print"].sum()),
        "n_mark_only": int(mark_only.sum()),
        "n_print_only": int(print_only.sum()),
        "n_both": int(both.sum()),
        "pct_mark_no_print": float(100.0 * mark_only.sum() / n_mark) if n_mark else 0.0,
        "median_abs_diff": float(diffs.median()) if len(diffs) else None,
        "median_rel_diff_pct": float(100.0 * rel.median()) if len(rel) else None,
        "median_spread": float(spread.median()) if len(spread) else None,
        "n_dates": int(wide["date"].nunique()),
    }


def listed_ladder(wide: pd.DataFrame, cp: str = "C") -> dict:
    """
    Every strike ever seen for each expiry — the listed ladder.

    A contract that never quoted on any day never appears in ``wide`` at all,
    so counting empty cells from the day's own rows understates the holes
    badly. The ladder is the honest denominator: the strikes the exchange
    listed, whether or not a number ever showed up in them.
    """
    sl = wide[wide["cp"] == cp]
    return {
        expiry: np.sort(g["strike"].unique())
        for expiry, g in sl.groupby("expiry")
    }


def occupancy_matrix(wide: pd.DataFrame, asof, cp: str = "C"):
    """
    Occupancy over the full listed grid for one as-of date.

    Returns (expiries, strikes, Z) where Z is
        0 — nothing quoted, the cell is a hole
        1 — a mark, but nobody traded
        2 — a mark and a real print
    """
    asof_ts = pd.Timestamp(asof).normalize()
    ladder = listed_ladder(wide, cp)
    expiries = sorted(e for e in ladder if e >= asof_ts)
    if not expiries:
        return [], np.array([]), np.zeros((0, 0))

    strikes = np.unique(np.concatenate([ladder[e] for e in expiries]))
    sl = wide[(wide["date"] == asof_ts) & (wide["cp"] == cp)]
    seen = {
        (row.expiry, row.strike): int(row.occupancy)
        for row in sl.itertuples()
    }

    Z = np.full((len(expiries), len(strikes)), np.nan)
    strike_pos = {k: j for j, k in enumerate(strikes)}
    for i, expiry in enumerate(expiries):
        for k in ladder[expiry]:
            # nan stays nan for strikes this expiry never listed at all
            Z[i, strike_pos[k]] = seen.get((expiry, k), 0)
    return expiries, strikes, Z


def grid_occupancy(wide: pd.DataFrame, asof, cp: str = "C") -> dict:
    """
    How much of the listed (strike x expiry) grid has nothing in it on one date.

    Two different numbers, and the weaker one is the tempting one:

    ``pct_empty``        cells with no number at all — understates the problem,
                         because a cell holding only a model mark still looks
                         populated when you plot it.
    ``pct_never_traded`` cells nobody transacted in. This is the honest figure:
                         it counts marks as what they are, an absence of trade.
    """
    _, _, Z = occupancy_matrix(wide, asof, cp)
    listed = np.isfinite(Z)
    cells = int(listed.sum())
    if not cells:
        return {"cells": 0, "filled": 0, "traded": 0, "pct_empty": 0.0,
                "pct_never_traded": 0.0}
    filled = int((Z[listed] > 0).sum())
    traded = int((Z[listed] == 2).sum())
    return {
        "cells": cells,
        "filled": filled,
        "traded": traded,
        "pct_empty": float(100.0 * (1 - filled / cells)),
        "pct_never_traded": float(100.0 * (1 - traded / cells)),
    }


def synthesize_demo_payload(
    ticker_root: str = "UUUU",
    ticker_stock: str = "UUUU.K",
    weeks_back: int = 14,
    seed: int = 7,
) -> dict:
    """
    Fallback panel so the page renders with no pickle and no LSEG session.

    Shaped to the same teaching points as the real data: the mark prints on
    most listed strikes near the money, a real trade prints on far fewer, and
    when both exist they are close but not equal.
    """
    rng = np.random.default_rng(seed)
    end = dt.date.today()
    start = end - dt.timedelta(weeks=weeks_back)
    bdays = pd.bdate_range(start, end)

    rets = rng.normal(0.0005, 0.035, size=len(bdays))
    close = np.clip(8.0 * np.exp(np.cumsum(rets)), 3.5, 16.0)
    df_stock = pd.DataFrame(
        {
            "OPEN_PRC": close * (1 + rng.normal(0, 0.01, len(bdays))),
            "HIGH_1": close * (1 + rng.uniform(0.005, 0.04, len(bdays))),
            "LOW_1": close * (1 - rng.uniform(0.005, 0.04, len(bdays))),
            "TRDPRC_1": close,
        },
        index=bdays,
    )

    expiries = [
        d.date()
        for d in pd.date_range(start, end, freq="W-FRI")
        if start <= d.date() < end
    ]
    step = 0.50
    records: dict[tuple[str, str], pd.Series] = {}

    def ric_for(expiry: dt.date, strike: float, cp: str) -> str:
        code = chr(ord("A") + expiry.month - 1) if cp == "C" else chr(ord("M") + expiry.month - 1)
        return f"{ticker_root}{code}{expiry:%d}{expiry:%y}{int(round(strike * 100)):05d}.U^{code}{expiry:%y}"

    for expiry in expiries:
        alive = df_stock[df_stock.index.date <= expiry]
        if alive.empty:
            continue
        lo = np.floor((float(alive["LOW_1"].min()) - 2) / step) * step
        hi = np.ceil((float(alive["HIGH_1"].max()) + 2) / step) * step
        for strike in np.arange(max(1.0, lo), hi + step, step):
            for cp in ("C", "P"):
                ric = ric_for(expiry, float(strike), cp)
                for f in (PRINT_FIELD, MARK_FIELD, "BID", "ASK"):
                    records[(ric, f)] = pd.Series(index=bdays, dtype=float)
                for ts, spot in df_stock["TRDPRC_1"].items():
                    dte = (expiry - ts.date()).days
                    if dte < 0:
                        continue
                    intrinsic = max(spot - strike, 0.0) if cp == "C" else max(strike - spot, 0.0)
                    mny = abs(np.log(max(strike, 1e-6) / spot))
                    t_years = max(dte, 1) / 365.0
                    time_val = spot * 0.55 * np.sqrt(t_years) * np.exp(-3.2 * mny)
                    mark = max(intrinsic + time_val, 0.01)

                    if not (mny < 0.55 or dte < 21):
                        continue
                    records[(ric, MARK_FIELD)].loc[ts] = round(mark, 4)
                    half = max(0.01, mark * 0.12)
                    records[(ric, "ASK")].loc[ts] = round(mark + half, 2)
                    if mny < 0.35:
                        records[(ric, "BID")].loc[ts] = round(max(mark - half, 0.0), 2)

                    near = mny < 0.25
                    p = 0.8 if (near and dte <= 5) else 0.55 if (near and dte <= 21) else 0.18 if near else 0.04
                    if rng.random() < p:
                        records[(ric, PRINT_FIELD)].loc[ts] = round(
                            max(mark * rng.normal(1.0, 0.06) + rng.normal(0, 0.02), 0.01), 2
                        )

    live = {k: s.dropna() for k, s in records.items() if s.notna().any()}
    if live:
        df_options = pd.concat(live, axis=1)
        df_options.columns = pd.MultiIndex.from_tuples(df_options.columns, names=["RIC", "Field"])
    else:
        df_options = pd.DataFrame()

    return {
        "stock": df_stock,
        "options": df_options,
        "ticker": ticker_root,
        "fields": VALUE_FIELDS,
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "synthetic": True,
    }


DATA_FILE = Path(__file__).with_name("option_surface_data.pkl")


def load_payload(cache_file: str | Path | None = None) -> dict:
    """Cache first. Only synthesize when the pickle is genuinely absent."""
    path = Path(cache_file) if cache_file else DATA_FILE
    if path.exists():
        with path.open("rb") as f:
            payload = pickle.load(f)
        payload.setdefault("synthetic", False)
        return payload
    warnings.warn(
        f"{path.name} not found — synthesizing a sparse UUUU-like panel instead.",
        RuntimeWarning,
    )
    return synthesize_demo_payload()


def prepare(payload: dict) -> pd.DataFrame:
    """pickle -> tidy -> underlying joined -> one row per (date, contract)."""
    tidy = flatten_lseg_options(payload.get("options"))
    tidy = attach_underlying(tidy, payload.get("stock"))
    return pivot_mark_print(tidy)
