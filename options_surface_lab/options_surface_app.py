"""
Options Surface Lab — Assignment 1.1
MENG FinTech · Algorithmic Trading II

The point of the page: listed options are a sparse cloud, not a filled sheet.
Everything on it is arranged to make the holes visible before anything else.
"""

from __future__ import annotations

import warnings

import pandas as pd
import plotly.graph_objects as go
import reflex as rx

from .option_surface_plots import (
    candlestick_figure,
    mark_vs_print_figure,
    occupancy_figure,
    price_surface_figure,
    spread_figure,
)
from .option_surface_theme import (
    CARD,
    FONT_URL,
    INK,
    INK_MUTED,
    MARK,
    MARK_FIELD,
    MONO,
    PAPER,
    PRINT,
    PRINT_FIELD,
    RULE,
    SERIF,
)
from .option_surface_utils import (
    grid_occupancy,
    load_payload,
    prepare,
    summarize_sparsity,
)

warnings.filterwarnings("ignore")

# The panel is a static file, so read it once per process instead of once per
# page mount — a fresh prepare() on every visit costs seconds for no reason.
_CACHE: dict = {}


def get_panel() -> tuple[pd.DataFrame, dict]:
    if "wide" not in _CACHE:
        payload = load_payload()
        _CACHE["payload"] = payload
        _CACHE["wide"] = prepare(payload)
    return _CACHE["wide"], _CACHE["payload"]


def reload_panel() -> tuple[pd.DataFrame, dict]:
    _CACHE.clear()
    return get_panel()


class State(rx.State):
    # provenance
    ticker: str = "UUUU"
    data_note: str = ""
    status: str = "loading"

    # controls
    asof: str = ""
    asof_options: list[str] = []
    cp: str = "C"
    show_mark: bool = True
    show_print: bool = True
    show_sheet: bool = False

    # the two numbers the assignment asks for, plus context
    pct_mark_no_print: str = "—"
    median_gap: str = "—"
    pct_never_traded: str = "—"
    pct_grid_empty: str = "—"
    n_listed_cells: str = "—"
    n_series: str = "—"
    n_traded: str = "—"
    median_spread: str = "—"

    fig_occupancy: go.Figure = go.Figure()
    fig_surface: go.Figure = go.Figure()
    fig_compare: go.Figure = go.Figure()
    fig_spread: go.Figure = go.Figure()
    fig_stock: go.Figure = go.Figure()

    def on_load(self):
        wide, payload = get_panel()
        self._install(wide, payload)

    def reload(self):
        wide, payload = reload_panel()
        self._install(wide, payload)

    def _install(self, wide: pd.DataFrame, payload: dict):
        self.ticker = payload.get("ticker", "UUUU")
        if payload.get("synthetic"):
            self.data_note = (
                "SYNTHETIC panel — no pickle found, so the numbers below are simulated"
            )
        else:
            self.data_note = (
                f"LSEG pull cached {payload.get('fetched_at', '?')} · "
                f"{wide['ric'].nunique()} expired contracts · "
                f"{wide['date'].nunique()} sessions"
            )
        dates = sorted(wide["date"].dt.strftime("%Y-%m-%d").unique()) if len(wide) else []
        self.asof_options = dates
        if self.asof not in dates:
            # land on the date with the most listed contracts — the best demo
            self.asof = (
                wide.groupby(wide["date"].dt.strftime("%Y-%m-%d")).size().idxmax()
                if dates
                else ""
            )
        self.fig_stock = candlestick_figure(payload.get("stock"), self.ticker)
        self._rebuild()
        self.status = "ready"

    def set_asof(self, value: str):
        self.asof = value
        self._rebuild()

    def set_cp(self, value: str):
        self.cp = value
        self._rebuild()

    def toggle_mark(self, value: bool):
        self.show_mark = value
        self._rebuild()

    def toggle_print(self, value: bool):
        self.show_print = value
        self._rebuild()

    def toggle_sheet(self, value: bool):
        self.show_sheet = value
        self._rebuild()

    def _rebuild(self):
        wide, _ = get_panel()
        if wide is None or wide.empty or not self.asof:
            return

        day = wide[wide["date"] == pd.Timestamp(self.asof)]
        stats = summarize_sparsity(day[day["cp"] == self.cp])
        occ = grid_occupancy(wide, self.asof, self.cp)

        self.pct_mark_no_print = f"{stats['pct_mark_no_print']:.0f}%"
        if stats["median_abs_diff"] is None:
            self.median_gap = "n/a"
        else:
            rel = stats["median_rel_diff_pct"]
            self.median_gap = f"${stats['median_abs_diff']:.3f}" + (
                f"  ({rel:.0f}%)" if rel is not None else ""
            )
        self.pct_never_traded = f"{occ['pct_never_traded']:.0f}%"
        self.pct_grid_empty = f"{occ['pct_empty']:.0f}%"
        self.n_listed_cells = f"{occ['cells']}"
        self.n_series = f"{stats['n_mark']}"
        self.n_traded = f"{stats['n_print']}"
        self.median_spread = (
            f"${stats['median_spread']:.2f}" if stats["median_spread"] is not None else "n/a"
        )

        self.fig_occupancy = occupancy_figure(wide, self.asof, self.cp, self.ticker)
        self.fig_surface = price_surface_figure(
            wide, self.asof, cp=self.cp,
            show_print=self.show_print,
            show_mark=self.show_mark,
            show_interpolated=self.show_sheet,
            ticker=self.ticker,
        )
        self.fig_compare = mark_vs_print_figure(wide, self.asof, self.cp, self.ticker)
        self.fig_spread = spread_figure(wide, self.asof, self.cp, self.ticker)


# ── page furniture ──────────────────────────────────────────────────────
def panel(*children, **kw) -> rx.Component:
    return rx.box(
        *children,
        bg=CARD,
        border=f"1px solid {RULE}",
        border_radius="4px",
        padding="1.25rem",
        width="100%",
        **kw,
    )


def metric(label: str, value, hint: str = "", accent: str = INK) -> rx.Component:
    return rx.box(
        rx.text(label, font_family=MONO, font_size="0.7rem", color=INK_MUTED,
                style={"letterSpacing": "0.08em", "textTransform": "uppercase"}),
        rx.text(value, font_family=SERIF, font_size="1.9rem", color=accent,
                weight="bold", style={"lineHeight": "1.15", "marginTop": "0.3rem"}),
        rx.text(hint, font_family=SERIF, font_size="0.78rem", color=INK_MUTED,
                style={"marginTop": "0.2rem"}),
        bg=CARD,
        border=f"1px solid {RULE}",
        border_radius="4px",
        padding="0.9rem 1.1rem",
        flex="1 1 190px",
        min_width="190px",
    )


def section(title: str, blurb: str = "") -> rx.Component:
    return rx.box(
        rx.heading(title, size="5", font_family=SERIF, color=INK, weight="bold"),
        rx.cond(
            blurb != "",
            rx.text(blurb, font_family=SERIF, font_size="0.9rem", color=INK_MUTED,
                    style={"marginTop": "0.25rem", "maxWidth": "62ch"}),
        ),
        width="100%",
        style={"marginTop": "0.5rem"},
    )


def finding(n: str, question: str, answer: str) -> rx.Component:
    return rx.box(
        rx.text(f"{n}. {question}", font_family=MONO, font_size="0.74rem", color=INK_MUTED,
                style={"letterSpacing": "0.04em", "textTransform": "uppercase"}),
        rx.text(answer, font_family=SERIF, font_size="1rem", color=INK,
                style={"marginTop": "0.4rem", "lineHeight": "1.62", "maxWidth": "78ch"}),
        border_left=f"2px solid {MARK}",
        padding_left="1rem",
        style={"marginBottom": "1.4rem"},
    )


def controls() -> rx.Component:
    def sw(checked, handler, label, color) -> rx.Component:
        return rx.hstack(
            rx.switch(checked=checked, on_change=handler, size="1"),
            rx.text(label, font_family=MONO, font_size="0.8rem", color=color),
            spacing="2", align="center",
        )

    return panel(
        rx.hstack(
            rx.vstack(
                rx.text("as-of date", font_family=MONO, font_size="0.7rem", color=INK_MUTED),
                rx.select(State.asof_options, value=State.asof,
                          on_change=State.set_asof, size="2"),
                spacing="1", align="start",
            ),
            rx.vstack(
                rx.text("right", font_family=MONO, font_size="0.7rem", color=INK_MUTED),
                rx.select(["C", "P"], value=State.cp, on_change=State.set_cp, size="2"),
                spacing="1", align="start",
            ),
            rx.spacer(),
            sw(State.show_mark, State.toggle_mark, f"{MARK_FIELD}  ·  mark", MARK),
            sw(State.show_print, State.toggle_print, f"{PRINT_FIELD}  ·  real trade", PRINT),
            sw(State.show_sheet, State.toggle_sheet, "interpolated sheet", INK_MUTED),
            rx.button("reload", on_click=State.reload, size="2", variant="outline",
                      color_scheme="gray", font_family=MONO),
            spacing="5", align="end", wrap="wrap", width="100%",
        ),
    )


def index() -> rx.Component:
    return rx.box(
        rx.vstack(
            # ── masthead ────────────────────────────────────────────────
            rx.box(
                rx.hstack(
                    rx.vstack(
                        rx.text("MENG FinTech · Algorithmic Trading II · Assignment 1.1",
                                font_family=MONO, font_size="0.72rem", color=INK_MUTED,
                                style={"letterSpacing": "0.1em"}),
                        rx.heading("Options Surface Lab", size="8", font_family=SERIF,
                                   color=INK, weight="bold",
                                   style={"marginTop": "0.2rem"}),
                        rx.text(
                            "Listed options are a sparse cloud, not a filled sheet. "
                            "This page is arranged so the holes show up first.",
                            font_family=SERIF, font_size="1.02rem", color=INK_MUTED,
                            style={"marginTop": "0.45rem", "maxWidth": "60ch"},
                        ),
                        spacing="0", align="start",
                    ),
                    rx.spacer(),
                    rx.badge(State.status, variant="outline", color_scheme="gray",
                             font_family=MONO),
                    width="100%", align="start",
                ),
                border_bottom=f"2px solid {INK}",
                padding_bottom="1.25rem",
                width="100%",
            ),
            rx.text(State.data_note, font_family=MONO, font_size="0.74rem", color=INK_MUTED),

            # ── the two required numbers, up front ──────────────────────
            rx.hstack(
                metric("marked, never traded", State.pct_mark_no_print,
                       "of contracts with a mark, share with no print that day", PRINT),
                metric("median |mark − trade|", State.median_gap,
                       "on contracts that have both", MARK),
                metric("listed grid never traded", State.pct_never_traded,
                       "of listed cells, nobody transacted all day", PRINT),
                metric("nothing quoted at all", State.pct_grid_empty,
                       "not even a mark — a true hole"),
                metric("contracts marked", State.n_series, "vs traded →"),
                metric("contracts traded", State.n_traded, "someone really paid this"),
                metric("median bid/ask", State.median_spread,
                       "the width you'd actually pay"),
                spacing="3", width="100%", wrap="wrap", align="stretch",
            ),

            # ── lead figure: the holes ──────────────────────────────────
            section(
                "Where the data is not",
                "One cell per listed (expiry, strike). Grey cells were listed and never "
                "quoted. Blue cells carry a model mark that nobody traded. Only the red "
                "cells are contracts a human actually transacted.",
            ),
            panel(rx.plotly(data=State.fig_occupancy,
                            style={"width": "100%", "height": "460px"})),

            controls(),

            # ── 3D ──────────────────────────────────────────────────────
            section(
                "The cloud in three dimensions",
                "Strike across, days to expiry into the page, price up. Turn the "
                "interpolated sheet on and watch it stretch a smooth surface over "
                "strikes that never had a number.",
            ),
            panel(rx.plotly(data=State.fig_surface,
                            style={"width": "100%", "height": "620px"})),

            # ── the three sentences ─────────────────────────────────────
            section("What I read off this"),
            panel(
                finding(
                    "1",
                    "Where is the cloud dense, and where is it empty?",
                    "Dense in a narrow vertical band within a couple of dollars of spot, "
                    "and in the front one or two expiries — that is where both a mark and "
                    "a real print exist. It thins out in two directions at once: away from "
                    "spot, where marks survive but trades stop, and further out in time, "
                    "where entire rows of the grid go grey. On the busiest session in this "
                    "window, 208 of 226 listed call cells carried a mark but only 114 of "
                    "them ever traded — so roughly half the surface is a number nobody "
                    "transacted at.",
                ),
                finding(
                    "2",
                    f"Why is interpolating across empty cells dangerous on a $0.50 grid for {State.ticker}?",
                    "UUUU trades in the $8–15 range, so consecutive $0.50 strikes are only "
                    "three to six percent apart in moneyness, and option value across strikes "
                    "is curved rather than straight — a straight line through the most curved "
                    "part of the payoff is exactly the wrong shape. It gets worse on the wings: "
                    "out there a missing cell does not mean 'price unknown', it means there is "
                    "no bid at all, and the interpolator will still hand back a confident "
                    "positive number for a contract the market is valuing at zero. The sheet "
                    "looks smoothest precisely where it knows least.",
                ),
                finding(
                    "3",
                    "Which field is the mark next week, and which is evidence someone traded?",
                    f"{MARK_FIELD} is the mark. It is the only field that prints on the "
                    f"contracts nobody trades, which is exactly where a price is needed, and "
                    f"it moves with the underlying rather than going stale. {PRINT_FIELD} is "
                    "evidence and nothing more: one trade, at one moment in the session, on a "
                    "series that may not trade again for a week. Taking it as a mark means "
                    "pricing a whole surface off a single stale print.",
                ),
                rx.box(
                    rx.text(
                        "A note on fields: the brief names SETTLE as the exchange mark. That "
                        "field does not exist on this universe — LSEG answers "
                        "\"the universe does not support the following fields: [SETTLE]\" for "
                        "OPRA equity options, which is why the original cache came back holding "
                        "nothing but TRDPRC_1. THEO_VALUE is the substitute and it plays the "
                        "role the brief describes: a model-ish number that prints on more series "
                        "than trades do. BID and ASK came along too, so the fill question below "
                        "has a real answer.",
                        font_family=SERIF, font_size="0.9rem", color=INK_MUTED,
                        style={"lineHeight": "1.6", "maxWidth": "78ch"},
                    ),
                    bg=PAPER,
                    border=f"1px solid {RULE}",
                    border_radius="4px",
                    padding="1rem 1.1rem",
                ),
            ),

            # ── mark vs print ───────────────────────────────────────────
            section(
                "The mark is not the trade",
                "Two different series, plotted against each other. If they were the same "
                "number every point would sit on the dashed line.",
            ),
            panel(rx.plotly(data=State.fig_compare,
                            style={"width": "100%", "height": "440px"})),

            # ── fills ───────────────────────────────────────────────────
            section(
                "So what would you actually get filled at?",
                "The honest answer is a range, not a number. Where the band is tall the mark "
                "is a guess, and where the bid drops to zero there is nobody on the other side.",
            ),
            panel(rx.plotly(data=State.fig_spread,
                            style={"width": "100%", "height": "420px"})),

            # ── underlying ──────────────────────────────────────────────
            section("The underlying, for reference"),
            panel(rx.plotly(data=State.fig_stock,
                            style={"width": "100%", "height": "320px"})),

            rx.box(
                rx.text(
                    f"Built with Reflex · data from LSEG · mark = {MARK_FIELD}, "
                    f"print = {PRINT_FIELD}",
                    font_family=MONO, font_size="0.72rem", color=INK_MUTED,
                ),
                border_top=f"1px solid {RULE}",
                padding_top="1rem",
                width="100%",
                style={"marginTop": "1.5rem"},
            ),

            spacing="5",
            width="100%",
            max_width="1180px",
            style={"marginLeft": "auto", "marginRight": "auto"},
        ),
        on_mount=State.on_load,
        bg=PAPER,
        min_height="100vh",
        padding="2.5rem 2rem 4rem",
        width="100%",
    )


app = rx.App(
    stylesheets=[FONT_URL],
    style={"backgroundColor": PAPER, "fontFamily": SERIF},
)
app.add_page(index, title="Options Surface Lab · UUUU")
