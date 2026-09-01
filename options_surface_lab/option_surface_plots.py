"""
Every figure in the lab.

House style lives in option_surface_theme; nothing here hard-codes a colour.
The lead figure is the occupancy grid, because the thing this week is meant
to show is where the data *is not*.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .option_surface_theme import (
    CARD,
    INK,
    INK_MUTED,
    MARK,
    MARK_FIELD,
    MARK_SOFT,
    MONO,
    PAPER,
    PRINT,
    PRINT_FIELD,
    RULE,
    SERIF,
    SPREAD,
    WASH,
    axis,
    caption,
    plotly_layout,
)
from .option_surface_utils import occupancy_matrix, surface_grid


def _empty(msg: str, height: int = 380) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(**plotly_layout(height=height, title=dict(text=msg, x=0.0, xanchor="left")))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def _slice(wide: pd.DataFrame, asof, cp: str) -> pd.DataFrame:
    sl = wide
    if asof is not None and len(sl):
        sl = sl[sl["date"] == pd.Timestamp(asof).normalize()]
    if cp in {"C", "P"}:
        sl = sl[sl["cp"] == cp]
    return sl


# ── lead figure ─────────────────────────────────────────────────────────
def occupancy_figure(wide: pd.DataFrame, asof, cp: str = "C", ticker: str = "UUUU") -> go.Figure:
    """
    The listed grid, one cell per (expiry, strike).

    Blank  — the exchange never listed that strike for that expiry
    Grey   — listed, and nothing quoted all day. A hole.
    Blue   — a model mark, but nobody traded it
    Red    — somebody actually traded
    """
    expiries, strikes, Z = occupancy_matrix(wide, asof, cp)
    if not len(expiries):
        return _empty("No listed contracts on this date", height=460)

    listed = np.isfinite(Z)
    n_cells = int(listed.sum())
    n_hole = int((Z[listed] == 0).sum())
    n_mark = int((Z[listed] == 1).sum())
    n_trade = int((Z[listed] == 2).sum())

    # discrete three-step scale over zmin=0..zmax=2
    scale = [
        [0.0, WASH], [1 / 3, WASH],
        [1 / 3, MARK_SOFT], [2 / 3, MARK_SOFT],
        [2 / 3, PRINT], [1.0, PRINT],
    ]
    label = np.where(Z == 2, "traded", np.where(Z == 1, "mark only", "hole — nothing quoted"))

    fig = go.Figure(
        go.Heatmap(
            z=Z,
            x=[f"{k:.2f}" for k in strikes],
            y=[pd.Timestamp(e).strftime("%b %d") for e in expiries],
            colorscale=scale,
            zmin=0,
            zmax=2,
            showscale=False,
            xgap=1.5,
            ygap=1.5,
            hoverongaps=False,
            customdata=label,
            hovertemplate="K=$%{x} · exp %{y}<br>%{customdata}<extra></extra>",
        )
    )

    cp_word = "calls" if cp == "C" else "puts"
    pct_never = 100.0 * (1 - n_trade / n_cells) if n_cells else 0.0
    fig.update_layout(
        **plotly_layout(
            height=460,
            title=dict(
                text=f"{ticker} {cp_word} · {pd.Timestamp(asof).date()} · "
                     f"{pct_never:.0f}% of the listed grid never traded",
                x=0.0,
                xanchor="left",
            ),
            xaxis=axis("Strike ($)", tickangle=-90, showgrid=False),
            yaxis=axis("Expiry", showgrid=False),
            margin=dict(l=76, r=24, t=86, b=68),
            annotations=[
                caption(
                    f"{n_cells} listed cells &nbsp;·&nbsp; "
                    f"<span style='color:{WASH}'>■</span> {n_hole} hole &nbsp;"
                    f"<span style='color:{MARK_SOFT}'>■</span> {n_mark} mark only &nbsp;"
                    f"<span style='color:{PRINT}'>■</span> {n_trade} traded"
                )
            ],
        )
    )
    return fig


# ── 3D cloud ────────────────────────────────────────────────────────────
def price_surface_figure(
    wide: pd.DataFrame,
    asof,
    cp: str = "C",
    show_print: bool = True,
    show_mark: bool = True,
    show_interpolated: bool = False,
    ticker: str = "UUUU",
) -> go.Figure:
    """Strike x days-to-expiry x price, as a point cloud rather than a sheet."""
    sl = _slice(wide, asof, cp)
    if sl.empty:
        return _empty("No quotes on this date / filter", height=620)

    fig = go.Figure()
    spot = sl["spot"].dropna()
    spot_val = float(spot.median()) if len(spot) else None

    if show_mark and sl[MARK_FIELD].notna().any():
        m = sl.dropna(subset=[MARK_FIELD])
        fig.add_trace(
            go.Scatter3d(
                x=m["strike"], y=m["dte"], z=m[MARK_FIELD],
                mode="markers",
                name=f"{MARK_FIELD} (mark)",
                marker=dict(size=3.5, color=MARK, opacity=0.75, symbol="circle", line=dict(width=0)),
                customdata=np.stack([m["ric"].astype(str)], axis=1),
                hovertemplate=(
                    f"<b>{MARK_FIELD}</b> $%{{z:.3f}}<br>K=$%{{x:.2f}} · DTE=%{{y}}"
                    "<br>%{customdata[0]}<extra></extra>"
                ),
            )
        )
        if show_interpolated:
            grid = surface_grid(m, MARK_FIELD)
            if grid is not None:
                fig.add_trace(
                    go.Surface(
                        x=grid["x"], y=grid["y"], z=grid["z"],
                        name="interpolated sheet",
                        colorscale=[[0, "#EAF0F4"], [1, MARK_SOFT]],
                        opacity=0.35,
                        showscale=False,
                        hoverinfo="skip",
                        contours=dict(x=dict(show=False), y=dict(show=False), z=dict(show=False)),
                    )
                )

    if show_print and sl[PRINT_FIELD].notna().any():
        t = sl.dropna(subset=[PRINT_FIELD])
        fig.add_trace(
            go.Scatter3d(
                x=t["strike"], y=t["dte"], z=t[PRINT_FIELD],
                mode="markers",
                name=f"{PRINT_FIELD} (a real trade)",
                marker=dict(size=5.5, color=PRINT, opacity=0.95, symbol="diamond",
                            line=dict(width=0.5, color="#8A2F08")),
                customdata=np.stack([t["ric"].astype(str), t["ACVOL_UNS"].fillna(0)], axis=1),
                hovertemplate=(
                    f"<b>{PRINT_FIELD}</b> $%{{z:.3f}}<br>K=$%{{x:.2f}} · DTE=%{{y}}"
                    "<br>volume %{customdata[1]:.0f}<br>%{customdata[0]}<extra></extra>"
                ),
            )
        )

    def _ax(title: str, **kw) -> dict:
        return dict(
            title=dict(text=title, font=dict(size=12, family=SERIF, color=INK)),
            backgroundcolor=CARD,
            gridcolor=RULE,
            linecolor=RULE,
            showbackground=True,
            zeroline=False,
            tickfont=dict(size=10, family=MONO, color=INK_MUTED),
            **kw,
        )

    cp_word = "Calls" if cp == "C" else "Puts"
    spot_txt = f" · spot ${spot_val:.2f}" if spot_val is not None else ""
    fig.update_layout(
        **plotly_layout(
            height=620,
            title=dict(
                text=f"{ticker} {cp_word} · {pd.Timestamp(asof).date()}{spot_txt}",
                x=0.0, xanchor="left",
            ),
            scene=dict(
                xaxis=_ax("Strike ($)"),
                # near-dated toward the viewer
                yaxis=_ax("Days to expiry", autorange="reversed"),
                zaxis=_ax("Option price ($)"),
                bgcolor=PAPER,
                aspectmode="manual",
                aspectratio=dict(x=1.2, y=1.0, z=0.65),
                camera=dict(eye=dict(x=1.6, y=-1.5, z=0.8), center=dict(x=0, y=0, z=-0.08)),
            ),
            legend=dict(orientation="h", yanchor="bottom", y=1.0, x=1.0, xanchor="right",
                        bgcolor="rgba(255,255,255,0.85)", bordercolor=RULE, borderwidth=1,
                        font=dict(size=11, family=MONO), itemsizing="constant"),
            margin=dict(l=8, r=8, t=64, b=8),
            annotations=[
                caption(
                    "Blue dots are the model mark · red diamonds are trades that really happened"
                    + (" · the pale sheet is interpolation, not a market" if show_interpolated else "")
                )
            ],
        )
    )
    return fig


# ── mark vs print ───────────────────────────────────────────────────────
def mark_vs_print_figure(wide: pd.DataFrame, asof=None, cp: str = "C", ticker: str = "UUUU") -> go.Figure:
    """Left: paired quotes against y=x. Right: who had what, as counts."""
    sl = _slice(wide, asof, cp)
    if sl.empty:
        return _empty("No data on this date", height=440)

    both = sl.dropna(subset=[PRINT_FIELD, MARK_FIELD])
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=(f"{MARK_FIELD} vs {PRINT_FIELD}", "What existed that day"),
        horizontal_spacing=0.13,
        column_widths=[0.58, 0.42],
    )

    if len(both):
        fig.add_trace(
            go.Scatter(
                x=both[PRINT_FIELD], y=both[MARK_FIELD],
                mode="markers",
                marker=dict(size=7, color=PRINT, opacity=0.7,
                            line=dict(width=0.6, color=CARD)),
                customdata=np.stack(
                    [both["ric"].astype(str), both["strike"], both["dte"]], axis=1
                ),
                hovertemplate=(
                    "traded $%{x:.3f} · marked $%{y:.3f}"
                    "<br>K=$%{customdata[1]:.2f} · DTE=%{customdata[2]}"
                    "<br>%{customdata[0]}<extra></extra>"
                ),
                name="both exist",
                showlegend=False,
            ),
            row=1, col=1,
        )
        lo = float(min(both[PRINT_FIELD].min(), both[MARK_FIELD].min()))
        hi = float(max(both[PRINT_FIELD].max(), both[MARK_FIELD].max()))
        pad = (hi - lo) * 0.07 if hi > lo else 0.05
        fig.add_trace(
            go.Scatter(
                x=[lo - pad, hi + pad], y=[lo - pad, hi + pad],
                mode="lines",
                line=dict(color=INK_MUTED, dash="dash", width=1),
                name="mark = print",
                hoverinfo="skip",
            ),
            row=1, col=1,
        )
        fig.update_xaxes(range=[lo - pad, hi + pad], row=1, col=1)
        fig.update_yaxes(range=[lo - pad, hi + pad], row=1, col=1)

    n_mark_only = int((sl["has_mark"] & ~sl["has_print"]).sum())
    n_both = int((sl["has_mark"] & sl["has_print"]).sum())
    n_print_only = int((sl["has_print"] & ~sl["has_mark"]).sum())
    counts = [n_mark_only, n_both, n_print_only]
    fig.add_trace(
        go.Bar(
            x=["marked,<br>never traded", "both", "traded,<br>no mark"],
            y=counts,
            marker_color=[MARK_SOFT, MARK, PRINT],
            text=counts,
            textposition="outside",
            textfont=dict(family=MONO, size=12, color=INK),
            cliponaxis=False,
            showlegend=False,
            hovertemplate="%{x}: %{y} series<extra></extra>",
        ),
        row=1, col=2,
    )
    fig.update_yaxes(range=[0, max(counts + [1]) * 1.22], row=1, col=2)

    fig.update_xaxes(**axis(f"{PRINT_FIELD} — what someone paid ($)"), row=1, col=1)
    fig.update_yaxes(**axis(f"{MARK_FIELD} — the model mark ($)"), row=1, col=1)
    fig.update_xaxes(**axis(None, showgrid=False), row=1, col=2)
    fig.update_yaxes(**axis("Series count"), row=1, col=2)

    cp_word = "calls" if cp == "C" else "puts"
    fig.update_layout(
        **plotly_layout(
            height=440,
            title=dict(text=f"{ticker} {cp_word} · the mark is not the trade", x=0.0, xanchor="left"),
            margin=dict(l=64, r=24, t=92, b=64),
            legend=dict(orientation="h", yanchor="top", y=-0.16, x=0.0, xanchor="left",
                        bgcolor="rgba(0,0,0,0)", bordercolor=RULE, borderwidth=0,
                        font=dict(size=11, family=MONO)),
            annotations=[caption("Points off the dashed line are contracts where the mark and the "
                                 "one trade that happened disagree", y=1.04)],
        )
    )
    fig.update_annotations(font=dict(size=13, family=SERIF, color=INK), selector=dict(yref="paper"))
    return fig


# ── what could you actually get filled at ───────────────────────────────
def spread_figure(wide: pd.DataFrame, asof, cp: str = "C", ticker: str = "UUUU") -> go.Figure:
    """
    Bid/ask against the mark, per strike.

    A missing bid is not a gap in the data — it means nobody is bidding, so
    the honest floor is zero. That is why the band runs down to $0 on the
    deep out-of-the-money wing.
    """
    sl = _slice(wide, asof, cp).sort_values("strike")
    sl = sl[sl["ASK"].notna() | sl["has_mark"]]
    if sl.empty:
        return _empty("No quotes on this date", height=420)

    # one expiry at a time keeps the band readable
    near = sl.dropna(subset=["dte"])
    if len(near):
        target = near["dte"].min()
        sl = sl[sl["dte"] == target]
    dte_txt = f" · {int(target)} days to expiry" if len(near) else ""

    fig = go.Figure()
    ask = sl.dropna(subset=["ASK"])
    if len(ask):
        fig.add_trace(go.Scatter(
            x=ask["strike"], y=ask["ASK"], mode="lines",
            line=dict(width=0), showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=ask["strike"], y=ask["bid_filled"], mode="lines",
            line=dict(width=0), fill="tonexty",
            fillcolor="rgba(122,106,85,0.16)",
            name="bid → ask (what you could trade)",
            hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=ask["strike"], y=ask["ASK"], mode="lines+markers",
            line=dict(color=SPREAD, width=1.2), marker=dict(size=4, color=SPREAD),
            name="ask", hovertemplate="ask $%{y:.2f} @ K=$%{x:.2f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=ask["strike"], y=ask["bid_filled"], mode="lines+markers",
            line=dict(color=SPREAD, width=1.2, dash="dot"), marker=dict(size=4, color=SPREAD),
            name="bid (0 = no bid at all)",
            hovertemplate="bid $%{y:.2f} @ K=$%{x:.2f}<extra></extra>",
        ))

    mk = sl.dropna(subset=[MARK_FIELD])
    if len(mk):
        fig.add_trace(go.Scatter(
            x=mk["strike"], y=mk[MARK_FIELD], mode="lines+markers",
            line=dict(color=MARK, width=2), marker=dict(size=5, color=MARK),
            name=f"{MARK_FIELD} (mark)",
            hovertemplate="mark $%{y:.3f} @ K=$%{x:.2f}<extra></extra>",
        ))
    pr = sl.dropna(subset=[PRINT_FIELD])
    if len(pr):
        fig.add_trace(go.Scatter(
            x=pr["strike"], y=pr[PRINT_FIELD], mode="markers",
            marker=dict(size=8, color=PRINT, symbol="diamond", line=dict(width=0.6, color=CARD)),
            name=f"{PRINT_FIELD} (a real trade)",
            hovertemplate="traded $%{y:.3f} @ K=$%{x:.2f}<extra></extra>",
        ))

    spot = sl["spot"].dropna()
    if len(spot):
        s = float(spot.median())
        fig.add_vline(x=s, line=dict(color=INK_MUTED, width=1, dash="dash"))
        fig.add_annotation(x=s, y=1.0, yref="paper", text=f"spot ${s:.2f}",
                           showarrow=False, yanchor="bottom",
                           font=dict(size=11, family=MONO, color=INK_MUTED))

    cp_word = "calls" if cp == "C" else "puts"
    fig.update_layout(
        **plotly_layout(
            height=420,
            title=dict(text=f"{ticker} {cp_word} · what you could actually get filled at{dte_txt}",
                       x=0.0, xanchor="left"),
            xaxis=axis("Strike ($)"),
            yaxis=axis("Price ($)"),
            legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.0, xanchor="left",
                        bgcolor="rgba(0,0,0,0)", borderwidth=0, font=dict(size=11, family=MONO)),
            margin=dict(l=64, r=24, t=76, b=88),
            annotations=[caption("The shaded band is the whole range you could transact in. "
                                 "Where it is tall, the mark is a guess.")],
        )
    )
    return fig


# ── underlying ──────────────────────────────────────────────────────────
def candlestick_figure(df_stock: pd.DataFrame, ticker: str = "UUUU") -> go.Figure:
    if df_stock is None or df_stock.empty:
        return _empty("No underlying history", height=320)
    fig = go.Figure(
        go.Candlestick(
            x=df_stock.index,
            open=df_stock["OPEN_PRC"], high=df_stock["HIGH_1"],
            low=df_stock["LOW_1"], close=df_stock["TRDPRC_1"],
            increasing=dict(line=dict(color=MARK, width=1), fillcolor=CARD),
            decreasing=dict(line=dict(color=PRINT, width=1), fillcolor=PRINT),
            name=ticker,
        )
    )
    fig.update_layout(
        **plotly_layout(
            height=320,
            title=dict(text=f"{ticker} · the underlying", x=0.0, xanchor="left"),
            xaxis=axis(None, rangeslider=dict(visible=False)),
            yaxis=axis("Price ($)"),
            showlegend=False,
            margin=dict(l=64, r=24, t=68, b=40),
            annotations=[caption("Close here is TRDPRC_1 — the stock trades every day, "
                                 "which is exactly what its options do not")],
        )
    )
    return fig
