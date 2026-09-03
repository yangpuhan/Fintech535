"""
Every figure in the lab.

Nothing here hard-codes a colour — the identity lives in theme.py. The lead
figure is the occupancy grid, because what this week is meant to show is
where the data is *not*.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .panel import interpolated_sheet, occupancy
from .theme import (
    CARD, INK, INK_MUTED, MARK, MARK_FIELD, MARK_SOFT, MONO, PAPER,
    PRINT, PRINT_FIELD, QUOTE, RULE, SERIF, WASH, axis, caption, layout,
)


def _blank(message: str, height: int = 400) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(**layout(height=height, title=dict(text=message, x=0.0, xanchor="left")))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def _day(contracts: pd.DataFrame, asof, right: str) -> pd.DataFrame:
    return contracts[
        (contracts["date"] == pd.Timestamp(asof).normalize())
        & (contracts["right"] == right)
    ]


def _right_word(right: str) -> str:
    return "calls" if right == "C" else "puts"


# ── lead figure ─────────────────────────────────────────────────────────
def occupancy_figure(contracts: pd.DataFrame, asof, right: str = "C",
                     underlying: str = "UUUU") -> go.Figure:
    """
    The listed grid, one cell per (expiry, strike).

    blank  the exchange never listed that strike for that expiry
    grey   listed, and nothing quoted all day — a hole
    blue   a closing mid, but nobody traded it
    red    somebody actually traded
    """
    expiries, strikes, Z = occupancy(contracts, asof, right)
    if not len(expiries):
        return _blank("No listed contracts on this date", height=470)

    listed = np.isfinite(Z)
    n_cells = int(listed.sum())
    n_hole = int((Z[listed] == 0).sum())
    n_mid = int((Z[listed] == 1).sum())
    n_trade = int((Z[listed] == 2).sum())
    pct_never = 100.0 * (1 - n_trade / n_cells) if n_cells else 0.0

    label = np.where(Z == 2, "traded",
                     np.where(Z == 1, "mid only — nobody traded", "hole — nothing quoted"))

    fig = go.Figure(go.Heatmap(
        z=Z,
        x=[f"{k:.2f}" for k in strikes],
        y=[pd.Timestamp(e).strftime("%b %d") for e in expiries],
        # three flat steps, not a gradient — these are categories
        colorscale=[[0.0, WASH], [1 / 3, WASH],
                    [1 / 3, MARK_SOFT], [2 / 3, MARK_SOFT],
                    [2 / 3, PRINT], [1.0, PRINT]],
        zmin=0, zmax=2,
        showscale=False,
        xgap=1.5, ygap=1.5,
        hoverongaps=False,
        customdata=label,
        hovertemplate="K=$%{x} · exp %{y}<br>%{customdata}<extra></extra>",
    ))
    fig.update_layout(**layout(
        height=470,
        title=dict(text=f"{underlying} {_right_word(right)} · {pd.Timestamp(asof).date()} · "
                        f"{pct_never:.0f}% of the listed grid never traded",
                   x=0.0, xanchor="left"),
        xaxis=axis("Strike ($)", tickangle=-90, showgrid=False),
        yaxis=axis("Expiry", showgrid=False),
        margin=dict(l=76, r=24, t=88, b=70),
        annotations=[caption(
            f"{n_cells} listed cells &nbsp;·&nbsp; {n_hole} hole &nbsp;·&nbsp; "
            f"{n_mid} mid only &nbsp;·&nbsp; {n_trade} traded"
        )],
    ))
    return fig


# ── 3D ──────────────────────────────────────────────────────────────────
def surface_figure(contracts: pd.DataFrame, asof, right: str = "C",
                   show_sheet: bool = True, underlying: str = "UUUU") -> go.Figure:
    """Strike across, days to expiry into the page, price up — as a cloud."""
    day = _day(contracts, asof, right)
    if day.empty:
        return _blank("No quotes on this date", height=620)

    fig = go.Figure()
    spot = day["spot"].dropna()
    spot_value = float(spot.median()) if len(spot) else None

    marks = day.dropna(subset=[MARK_FIELD])
    if len(marks):
        fig.add_trace(go.Scatter3d(
            x=marks["strike"], y=marks["dte"], z=marks[MARK_FIELD],
            mode="markers",
            name=f"{MARK_FIELD} — closing mid",
            # meta.role lets the published page toggle traces by role rather
            # than by an index that shifts when one is absent
            meta=dict(role="mark"),
            marker=dict(size=3.5, color=MARK, opacity=0.75, line=dict(width=0)),
            customdata=marks["ric"].astype(str),
            hovertemplate=(f"<b>{MARK_FIELD}</b> $%{{z:.3f}}<br>K=$%{{x:.2f}} · DTE=%{{y}}"
                           "<br>%{customdata}<extra></extra>"),
        ))
        if show_sheet:
            sheet = interpolated_sheet(marks, MARK_FIELD)
            if sheet is not None:
                fig.add_trace(go.Surface(
                    x=sheet["x"], y=sheet["y"], z=sheet["z"],
                    name="interpolated sheet",
                    meta=dict(role="sheet"),
                    colorscale=[[0, "#EAF0F4"], [1, MARK_SOFT]],
                    opacity=0.35, showscale=False, hoverinfo="skip",
                    contours=dict(x=dict(show=False), y=dict(show=False), z=dict(show=False)),
                ))

    prints = day.dropna(subset=[PRINT_FIELD])
    if len(prints):
        fig.add_trace(go.Scatter3d(
            x=prints["strike"], y=prints["dte"], z=prints[PRINT_FIELD],
            mode="markers",
            name=f"{PRINT_FIELD} — a real trade",
            meta=dict(role="print"),
            marker=dict(size=5.5, color=PRINT, opacity=0.95, symbol="diamond",
                        line=dict(width=0.5, color="#8A2F08")),
            customdata=np.stack([prints["ric"].astype(str),
                                 prints["ACVOL_UNS"].fillna(0)], axis=1),
            hovertemplate=(f"<b>{PRINT_FIELD}</b> $%{{z:.3f}}<br>K=$%{{x:.2f}} · DTE=%{{y}}"
                           "<br>volume %{customdata[1]:.0f}<br>%{customdata[0]}<extra></extra>"),
        ))

    def scene_axis(title: str, **kw) -> dict:
        return dict(
            title=dict(text=title, font=dict(size=12, family=SERIF, color=INK)),
            backgroundcolor=CARD, gridcolor=RULE, linecolor=RULE,
            showbackground=True, zeroline=False,
            tickfont=dict(size=10, family=MONO, color=INK_MUTED),
            **kw,
        )

    spot_text = f" · spot ${spot_value:.2f}" if spot_value is not None else ""
    fig.update_layout(**layout(
        height=620,
        title=dict(text=f"{underlying} {_right_word(right).title()} · "
                        f"{pd.Timestamp(asof).date()}{spot_text}",
                   x=0.0, xanchor="left"),
        scene=dict(
            xaxis=scene_axis("Strike ($)"),
            yaxis=scene_axis("Days to expiry", autorange="reversed"),  # near-dated in front
            zaxis=scene_axis("Option price ($)"),
            bgcolor=PAPER,
            aspectmode="manual",
            aspectratio=dict(x=1.2, y=1.0, z=0.65),
            camera=dict(eye=dict(x=1.6, y=-1.5, z=0.8), center=dict(x=0, y=0, z=-0.08)),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=1.0, xanchor="right",
                    bgcolor="rgba(255,255,255,0.85)", bordercolor=RULE, borderwidth=1,
                    font=dict(size=11, family=MONO), itemsizing="constant"),
        margin=dict(l=8, r=8, t=64, b=8),
        annotations=[caption(
            "Blue dots are the closing mid · red diamonds are trades that really happened"
            + (" · the pale sheet is interpolation, not a market" if show_sheet else "")
        )],
    ))
    return fig


# ── mark vs print ───────────────────────────────────────────────────────
def mark_vs_print_figure(contracts: pd.DataFrame, asof, right: str = "C",
                         underlying: str = "UUUU") -> go.Figure:
    """Left: paired series against y=x. Right: what existed, as counts."""
    day = _day(contracts, asof, right)
    if day.empty:
        return _blank("No data on this date", height=450)

    both = day.dropna(subset=[MARK_FIELD, PRINT_FIELD])
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=(f"{MARK_FIELD} vs {PRINT_FIELD}", "What existed that day"),
        horizontal_spacing=0.13,
        column_widths=[0.58, 0.42],
    )

    if len(both):
        fig.add_trace(go.Scatter(
            x=both[PRINT_FIELD], y=both[MARK_FIELD],
            mode="markers",
            marker=dict(size=7, color=PRINT, opacity=0.7, line=dict(width=0.6, color=CARD)),
            customdata=np.stack([both["ric"].astype(str), both["strike"], both["dte"]], axis=1),
            hovertemplate=("traded $%{x:.3f} · mid $%{y:.3f}"
                           "<br>K=$%{customdata[1]:.2f} · DTE=%{customdata[2]}"
                           "<br>%{customdata[0]}<extra></extra>"),
            showlegend=False,
        ), row=1, col=1)

        lo = float(min(both[PRINT_FIELD].min(), both[MARK_FIELD].min()))
        hi = float(max(both[PRINT_FIELD].max(), both[MARK_FIELD].max()))
        pad = (hi - lo) * 0.07 if hi > lo else 0.05
        fig.add_trace(go.Scatter(
            x=[lo - pad, hi + pad], y=[lo - pad, hi + pad],
            mode="lines", line=dict(color=INK_MUTED, dash="dash", width=1),
            name="mid = trade", hoverinfo="skip",
        ), row=1, col=1)
        fig.update_xaxes(range=[lo - pad, hi + pad], row=1, col=1)
        fig.update_yaxes(range=[lo - pad, hi + pad], row=1, col=1)

    counts = [
        int((day["has_mark"] & ~day["has_print"]).sum()),
        int((day["has_mark"] & day["has_print"]).sum()),
        int((day["has_print"] & ~day["has_mark"]).sum()),
    ]
    fig.add_trace(go.Bar(
        x=["mid,<br>never traded", "both", "traded,<br>no mid"],
        y=counts,
        marker_color=[MARK_SOFT, MARK, PRINT],
        text=counts, textposition="outside",
        textfont=dict(family=MONO, size=12, color=INK),
        cliponaxis=False, showlegend=False,
        hovertemplate="%{x}: %{y} series<extra></extra>",
    ), row=1, col=2)
    fig.update_yaxes(range=[0, max(counts + [1]) * 1.22], row=1, col=2)

    fig.update_xaxes(**axis(f"{PRINT_FIELD} — what someone paid ($)"), row=1, col=1)
    fig.update_yaxes(**axis(f"{MARK_FIELD} — the closing mid ($)"), row=1, col=1)
    fig.update_xaxes(**axis(None, showgrid=False), row=1, col=2)
    fig.update_yaxes(**axis("Series count"), row=1, col=2)

    fig.update_layout(**layout(
        height=450,
        title=dict(text=f"{underlying} {_right_word(right)} · the mid is not the trade",
                   x=0.0, xanchor="left"),
        margin=dict(l=64, r=24, t=94, b=66),
        legend=dict(orientation="h", yanchor="top", y=-0.16, x=0.0, xanchor="left",
                    bgcolor="rgba(0,0,0,0)", borderwidth=0, font=dict(size=11, family=MONO)),
        annotations=[caption("Points off the dashed line are contracts where the mid and the "
                             "one trade that happened disagree", y=1.04)],
    ))
    fig.update_annotations(font=dict(size=13, family=SERIF, color=INK), selector=dict(yref="paper"))
    return fig


# ── what could you actually get filled at ───────────────────────────────
def quote_band_figure(contracts: pd.DataFrame, asof, right: str = "C",
                      underlying: str = "UUUU") -> go.Figure:
    """
    Bid/ask against the mid, one expiry, per strike.

    Where the band is tall, the mid is the midpoint of a guess. Where the bid
    falls to zero there is nobody on the other side at all — and MID_PRICE
    itself goes missing there, which is the part worth noticing.
    """
    day = _day(contracts, asof, right).sort_values("strike")
    day = day[day["ASK"].notna() | day["has_mark"]]
    if day.empty:
        return _blank("No quotes on this date", height=430)

    front = day["dte"].min()
    day = day[day["dte"] == front]
    fig = go.Figure()

    quoted = day.dropna(subset=["ASK"])
    if len(quoted):
        fig.add_trace(go.Scatter(x=quoted["strike"], y=quoted["ASK"], mode="lines",
                                 line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=quoted["strike"], y=quoted["bid_floor"], mode="lines",
            line=dict(width=0), fill="tonexty", fillcolor="rgba(122,106,85,0.16)",
            name="bid → ask · everything you could transact in", hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=quoted["strike"], y=quoted["ASK"], mode="lines+markers",
            line=dict(color=QUOTE, width=1.2), marker=dict(size=4, color=QUOTE),
            name="ask", hovertemplate="ask $%{y:.2f} @ K=$%{x:.2f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=quoted["strike"], y=quoted["bid_floor"], mode="lines+markers",
            line=dict(color=QUOTE, width=1.2, dash="dot"), marker=dict(size=4, color=QUOTE),
            name="bid · 0 means no bid at all",
            hovertemplate="bid $%{y:.2f} @ K=$%{x:.2f}<extra></extra>",
        ))

    marks = day.dropna(subset=[MARK_FIELD])
    if len(marks):
        fig.add_trace(go.Scatter(
            x=marks["strike"], y=marks[MARK_FIELD], mode="lines+markers",
            line=dict(color=MARK, width=2), marker=dict(size=5, color=MARK),
            name=f"{MARK_FIELD} — closing mid",
            hovertemplate="mid $%{y:.3f} @ K=$%{x:.2f}<extra></extra>",
        ))
    prints = day.dropna(subset=[PRINT_FIELD])
    if len(prints):
        fig.add_trace(go.Scatter(
            x=prints["strike"], y=prints[PRINT_FIELD], mode="markers",
            marker=dict(size=8, color=PRINT, symbol="diamond", line=dict(width=0.6, color=CARD)),
            name=f"{PRINT_FIELD} — a real trade",
            hovertemplate="traded $%{y:.3f} @ K=$%{x:.2f}<extra></extra>",
        ))

    spot = day["spot"].dropna()
    if len(spot):
        s = float(spot.median())
        fig.add_vline(x=s, line=dict(color=INK_MUTED, width=1, dash="dash"))
        fig.add_annotation(x=s, y=1.0, yref="paper", text=f"spot ${s:.2f}",
                           showarrow=False, yanchor="bottom",
                           font=dict(size=11, family=MONO, color=INK_MUTED))

    fig.update_layout(**layout(
        height=430,
        title=dict(text=f"{underlying} {_right_word(right)} · what you could actually get "
                        f"filled at · {int(front)} days to expiry",
                   x=0.0, xanchor="left"),
        xaxis=axis("Strike ($)"),
        yaxis=axis("Price ($)"),
        legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.0, xanchor="left",
                    bgcolor="rgba(0,0,0,0)", borderwidth=0, font=dict(size=11, family=MONO)),
        margin=dict(l=64, r=24, t=78, b=92),
        annotations=[caption("Where the band is tall the mid is the middle of a guess. "
                             "Where the bid is 0 there is nobody on the other side.")],
    ))
    return fig


# ── underlying ──────────────────────────────────────────────────────────
def underlying_figure(df_stock: pd.DataFrame, underlying: str = "UUUU") -> go.Figure:
    if df_stock is None or df_stock.empty:
        return _blank("No underlying history", height=320)
    fig = go.Figure(go.Candlestick(
        x=df_stock.index,
        open=df_stock["OPEN_PRC"], high=df_stock["HIGH_1"],
        low=df_stock["LOW_1"], close=df_stock[PRINT_FIELD],
        increasing=dict(line=dict(color=MARK, width=1), fillcolor=CARD),
        decreasing=dict(line=dict(color=PRINT, width=1), fillcolor=PRINT),
        name=underlying,
    ))
    fig.update_layout(**layout(
        height=320,
        title=dict(text=f"{underlying} · the underlying", x=0.0, xanchor="left"),
        xaxis=axis(None, rangeslider=dict(visible=False)),
        yaxis=axis("Price ($)"),
        showlegend=False,
        margin=dict(l=64, r=24, t=70, b=40),
        annotations=[caption("The stock trades every session — which is exactly what "
                             "its options do not")],
    ))
    return fig
