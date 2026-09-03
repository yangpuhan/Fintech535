"""
Pickle -> tidy long table -> one row per (date, contract) -> statistics.

The reshape is the point. LSEG hands back a wide frame — dates down, RIC
strings across — where a contract's attributes are buried in its column
label and most cells are empty. Nothing can be grouped in that shape. Long
format puts strike, days-to-expiry and field in columns where they can be.
"""

from __future__ import annotations

import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import griddata

from .ric import parse_option_ric
from .theme import MARK_FIELD, PRINT_FIELD

DATA_FILE = Path(__file__).with_name("data.pkl")

# Everything kept off the pull. The first two are the assignment.
FIELDS = [PRINT_FIELD, MARK_FIELD, "BID", "ASK", "ACVOL_UNS", "OPINT_1", "IMP_VOLT"]


# ── load ────────────────────────────────────────────────────────────────
def load_payload(path: str | Path | None = None) -> dict:
    """Read the cached pull. No network, ever — fetch.py is the only puller."""
    path = Path(path) if path else DATA_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build it with:  python -m options_surface_lab.fetch"
        )
    with path.open("rb") as f:
        return pickle.load(f)


# ── wide -> long ────────────────────────────────────────────────────────
def _split_levels(cols: pd.MultiIndex) -> tuple[int, int]:
    """LSEG is inconsistent about whether RIC or field is the outer level."""
    known = {f.upper() for f in FIELDS} | {"MID_PRICE", "SETTLE", "CLOSE"}
    for i in range(cols.nlevels):
        if {str(v).upper() for v in cols.get_level_values(i)} & known:
            return i, (1 if i == 0 else 0)
    return 1, 0


def to_long(df_options: pd.DataFrame) -> pd.DataFrame:
    """One row per (date, contract, field). Contracts that never quoted vanish."""
    columns = ["date", "ric", "underlying", "right", "expiry", "strike", "dte", "field", "value"]
    if df_options is None or df_options.empty:
        return pd.DataFrame(columns=columns)

    frame = df_options.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index)

    if isinstance(frame.columns, pd.MultiIndex):
        field_level, ric_level = _split_levels(frame.columns)
        triples = [(str(c[ric_level]), str(c[field_level]).upper(), c) for c in frame.columns]
    else:
        # A single-field pull comes back flat with the field name on
        # columns.name. Losing that is how a pull silently becomes one field.
        field = str(frame.columns.name or PRINT_FIELD).upper()
        triples = [(str(c), field, c) for c in frame.columns]

    parsed_cache: dict[str, dict | None] = {}
    rows = []
    for ric, field, col in triples:
        if ric not in parsed_cache:
            parsed_cache[ric] = parse_option_ric(ric)
        parsed = parsed_cache[ric]
        if parsed is None:
            continue
        series = pd.to_numeric(frame[col], errors="coerce").dropna()
        for ts, value in series.items():
            rows.append({
                "date": pd.Timestamp(ts).normalize(),
                "field": field,
                "value": float(value),
                **parsed,
            })

    long = pd.DataFrame(rows, columns=columns)
    if long.empty:
        return long
    long["expiry"] = pd.to_datetime(long["expiry"])
    long["dte"] = (long["expiry"] - long["date"]).dt.days
    return long[long["dte"] >= 0].reset_index(drop=True)


def attach_spot(long: pd.DataFrame, df_stock: pd.DataFrame) -> pd.DataFrame:
    """Join each row to that day's underlying close and add moneyness K/S."""
    long = long.copy()
    if long.empty or df_stock is None or df_stock.empty:
        long["spot"] = np.nan
        long["moneyness"] = np.nan
        return long

    stock = df_stock.copy()
    if not isinstance(stock.index, pd.DatetimeIndex):
        stock.index = pd.to_datetime(stock.index)
    close_col = PRINT_FIELD if PRINT_FIELD in stock.columns else stock.columns[-1]
    spot = pd.to_numeric(stock[close_col], errors="coerce").dropna()
    spot.index = pd.DatetimeIndex(spot.index).normalize()

    # An option can quote on a day the stock tape has no bar; carry forward.
    aligned = spot.sort_index().reindex(
        spot.index.union(pd.DatetimeIndex(long["date"].unique()))
    ).ffill()
    long["spot"] = long["date"].map(aligned)
    long["moneyness"] = long["strike"] / long["spot"]
    return long


def to_contracts(long: pd.DataFrame) -> pd.DataFrame:
    """One row per (date, contract), every field its own column."""
    if long.empty:
        return long

    keys = ["date", "ric", "underlying", "right", "expiry", "strike", "dte", "spot", "moneyness"]
    keys = [k for k in keys if k in long.columns]
    wide = (
        long.pivot_table(index=keys, columns="field", values="value", aggfunc="last")
        .reset_index()
    )
    wide.columns.name = None
    for f in FIELDS:
        if f not in wide.columns:
            wide[f] = np.nan

    wide["has_mark"] = wide[MARK_FIELD].notna()
    wide["has_print"] = wide[PRINT_FIELD].notna()
    wide["abs_gap"] = (wide[MARK_FIELD] - wide[PRINT_FIELD]).abs()
    wide["rel_gap"] = wide["abs_gap"] / wide[MARK_FIELD].replace(0, np.nan)

    # A missing BID out on the wing is not missing data — it means nobody is
    # bidding. Zero is the honest floor, and it is what makes the fill
    # question answerable at all.
    wide["bid_floor"] = wide["BID"].fillna(0.0).where(wide["ASK"].notna())
    wide["spread"] = wide["ASK"] - wide["bid_floor"]

    # 0 nothing quoted · 1 a mid but no trade · 2 a mid and a real trade
    wide["state"] = np.where(
        wide["has_mark"] & wide["has_print"], 2,
        np.where(wide["has_mark"] | wide["has_print"], 1, 0),
    )
    return wide


def build(path: str | Path | None = None) -> tuple[pd.DataFrame, dict]:
    """pickle -> the table everything else reads."""
    payload = load_payload(path)
    long = to_long(payload.get("options"))
    long = attach_spot(long, payload.get("stock"))
    return to_contracts(long), payload


# ── the listed grid ─────────────────────────────────────────────────────
def listed_ladder(contracts: pd.DataFrame, right: str) -> dict:
    """
    Every strike ever seen for each expiry — the honest denominator.

    A contract that never quoted on any day is absent from the table
    entirely, so counting holes from one day's rows understates them badly.
    The ladder is what the exchange listed, quoted or not.
    """
    sl = contracts[contracts["right"] == right]
    return {expiry: np.sort(g["strike"].unique()) for expiry, g in sl.groupby("expiry")}


def occupancy(contracts: pd.DataFrame, asof, right: str = "C"):
    """
    (expiries, strikes, Z) over the full listed grid for one date.

    Z is 0 hole / 1 mid only / 2 mid and a trade, and NaN where that expiry
    never listed that strike at all.
    """
    asof_ts = pd.Timestamp(asof).normalize()
    ladder = listed_ladder(contracts, right)
    expiries = sorted(e for e in ladder if e >= asof_ts)
    if not expiries:
        return [], np.array([]), np.zeros((0, 0))

    strikes = np.unique(np.concatenate([ladder[e] for e in expiries]))
    position = {k: j for j, k in enumerate(strikes)}
    day = contracts[(contracts["date"] == asof_ts) & (contracts["right"] == right)]
    seen = {(r.expiry, r.strike): int(r.state) for r in day.itertuples()}

    Z = np.full((len(expiries), len(strikes)), np.nan)
    for i, expiry in enumerate(expiries):
        for strike in ladder[expiry]:
            Z[i, position[strike]] = seen.get((expiry, strike), 0)
    return expiries, strikes, Z


def grid_stats(contracts: pd.DataFrame, asof, right: str = "C") -> dict:
    """How much of the listed grid is empty, and how much never traded."""
    _, _, Z = occupancy(contracts, asof, right)
    listed = np.isfinite(Z)
    cells = int(listed.sum())
    if not cells:
        return {"cells": 0, "quoted": 0, "traded": 0, "pct_empty": 0.0, "pct_never_traded": 0.0}
    quoted = int((Z[listed] > 0).sum())
    traded = int((Z[listed] == 2).sum())
    return {
        "cells": cells,
        "quoted": quoted,
        "traded": traded,
        "pct_empty": float(100.0 * (1 - quoted / cells)),
        "pct_never_traded": float(100.0 * (1 - traded / cells)),
    }


# ── the two required numbers ────────────────────────────────────────────
def day_stats(contracts: pd.DataFrame, asof, right: str = "C") -> dict:
    """
    The statistics the brief asks to be printed on the page.

    ``pct_mark_no_print`` — of listed series with a mid that day, the share
                            with no trade.
    ``median_gap``        — median |MID_PRICE - TRDPRC_1| where both exist.
    """
    day = contracts[
        (contracts["date"] == pd.Timestamp(asof).normalize())
        & (contracts["right"] == right)
    ]
    blank = {
        "n_series": 0, "n_mark": 0, "n_print": 0, "n_both": 0,
        "n_mark_only": 0, "n_print_only": 0,
        "pct_mark_no_print": 0.0,
        "median_gap": None, "median_rel_gap_pct": None, "median_spread": None,
    }
    if day.empty:
        return blank

    both = day["has_mark"] & day["has_print"]
    mark_only = day["has_mark"] & ~day["has_print"]
    print_only = day["has_print"] & ~day["has_mark"]
    n_mark = int(day["has_mark"].sum())
    gaps = day.loc[both, "abs_gap"].dropna()
    rel = day.loc[both, "rel_gap"].dropna()
    spread = day["spread"].dropna()

    return {
        "n_series": int(len(day)),
        "n_mark": n_mark,
        "n_print": int(day["has_print"].sum()),
        "n_both": int(both.sum()),
        "n_mark_only": int(mark_only.sum()),
        "n_print_only": int(print_only.sum()),
        "pct_mark_no_print": float(100.0 * mark_only.sum() / n_mark) if n_mark else 0.0,
        "median_gap": float(gaps.median()) if len(gaps) else None,
        "median_rel_gap_pct": float(100.0 * rel.median()) if len(rel) else None,
        "median_spread": float(spread.median()) if len(spread) else None,
    }


# ── the sheet you are not supposed to trust ─────────────────────────────
def interpolated_sheet(points: pd.DataFrame, value_col: str,
                       n_strike: int = 44, n_dte: int = 32):
    """
    Linear interpolation of the cloud onto a regular grid.

    This is an assumption imposed on the holes, not a market. Cells outside
    the convex hull stay NaN so Plotly does not paint a surface over wings
    that never quoted — the interpolator invents enough as it is.
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
    yi = np.linspace(max(0.0, y.min()), y.max(), n_dte)
    XX, YY = np.meshgrid(xi, yi)
    return {"x": xi, "y": yi, "z": griddata((x, y), z, (XX, YY), method="linear")}
