"""
Graphical identity for the lab — "Paper".

One place for the palette so the Reflex page and every Plotly figure agree.
Light, printed-page feel: warm paper ground, ink text, two accents.

The two accents carry the whole argument of this assignment:

    MARK  (THEO_VALUE) — dense, it is everywhere        -> muted Prussian blue
    PRINT (TRDPRC_1)   — sparse, someone actually traded -> vermilion

The rare thing gets the loud color. That is deliberate: the eye should land
on how *few* real prints there are.
"""

from __future__ import annotations

# ── ground ──────────────────────────────────────────────────────────────
PAPER = "#FAF8F3"     # page background, warm off-white
CARD = "#FFFFFF"      # raised panel
RULE = "#DDD7CA"      # hairline borders / grid
WASH = "#EFEBE2"      # empty heatmap cell — present but silent

# ── ink ─────────────────────────────────────────────────────────────────
INK = "#1A1A1A"       # primary text
INK_MUTED = "#6E6A63" # captions, axis labels
INK_FAINT = "#A29D93"

# ── accents ─────────────────────────────────────────────────────────────
MARK = "#2D5F7C"      # Prussian blue  — THEO_VALUE, the model mark
MARK_SOFT = "#8FB3C7"
PRINT = "#C1440E"     # vermilion      — TRDPRC_1, an actual trade
PRINT_SOFT = "#E39B7B"
SPREAD = "#7A6A55"    # bid/ask band

# ── type ────────────────────────────────────────────────────────────────
SERIF = "'Source Serif 4', 'Source Serif Pro', Georgia, serif"
MONO = "'Source Code Pro', 'SF Mono', Menlo, monospace"

FONT_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700"
    "&family=Source+Code+Pro:wght@400;600"
    "&display=swap"
)

# Field roles — imported by utils and plots so the naming never drifts.
MARK_FIELD = "THEO_VALUE"
PRINT_FIELD = "TRDPRC_1"


def plotly_layout(**overrides) -> dict:
    """Shared Plotly layout so every figure reads as one system."""
    base = dict(
        template="simple_white",
        paper_bgcolor=PAPER,
        plot_bgcolor=CARD,
        font=dict(color=INK, family=SERIF, size=13),
        title=dict(
            font=dict(size=17, color=INK, family=SERIF),
            x=0.0,
            xanchor="left",
            y=0.97,
            yanchor="top",
        ),
        margin=dict(l=64, r=24, t=76, b=52),
        legend=dict(
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor=RULE,
            borderwidth=1,
            font=dict(size=11, family=MONO),
        ),
        hoverlabel=dict(
            bgcolor=CARD,
            bordercolor=RULE,
            font=dict(family=MONO, size=12, color=INK),
        ),
    )
    base.update(overrides)
    return base


def caption(text: str, y: float = 1.02) -> dict:
    """Small grey note pinned above a figure."""
    return dict(
        text=text,
        xref="paper",
        yref="paper",
        x=0.0,
        y=y,
        xanchor="left",
        yanchor="bottom",
        showarrow=False,
        font=dict(size=11, color=INK_MUTED, family=MONO),
    )


def axis(title: str | None = None, **overrides) -> dict:
    cfg = dict(
        gridcolor=RULE,
        linecolor=RULE,
        zeroline=False,
        tickfont=dict(size=11, family=MONO, color=INK_MUTED),
        title=dict(text=title, font=dict(size=12, family=SERIF, color=INK)),
    )
    cfg.update(overrides)
    return cfg
