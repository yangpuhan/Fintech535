#!/usr/bin/env python3
"""Nightly LSEG refresh: AAPL against the market (SPY), price and volatility.

Run by .github/workflows/nightly.yml, or by hand from the repo root:

    python -m nightly.refresh

Two get_history requests (AAPL.O and SPY, daily closes, ~15 months), so two
requests a day against LSEG's 10,000-a-day cap. Writes:

    docs/nightly/aapl-vol.html   the Plotly figure, iframed by docs/nightly/index.html
    docs/nightly/meta.json       as-of session, latest values, and which run wrote them

Why SPY and not the VIX: this account is not permissioned for CBOE indices
(.VIX returns TSCC.QS.UserNotPermission), while exchange-listed equities and
ETFs are. SPY stands in for "the market".

Session. A GitHub runner has no Workspace app, so in Actions the script opens
a *platform* session from three repository secrets: LSEG_APP_KEY,
LSEG_USERNAME and LSEG_PASSWORD. Run by hand with those unset, it opens the
default session in lseg-data.config.json instead (desktop.workspace, which
needs the Workspace app running and signed in).

Nothing is written unless both series come back, so a failed run leaves the
last good chart on the site.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "nightly"
CONFIG = ROOT / "lseg-data.config.json"

STOCK = "AAPL.O"
MARKET = "SPY"
WINDOW = 21        # sessions in the realised-vol window: one trading month
SHOW_DAYS = 365    # calendar days the chart shows
PAD_DAYS = 60      # extra history so the first plotted vol point has a full window
CLOSE_NY = dt.time(16, 15)   # before this, today's daily bar is still forming

# The site's "paper" tokens (docs/index.html). Blue is AAPL, as on every
# page of the site; vermilion, dotted, is the market.
INK, MUTED, FAINT, RULE, WASH, CARD = (
    "#1A1A1A", "#6E6A63", "#A29D93", "#DDD7CA", "#EFEBE2", "#FFFFFF")
BLUE, VERMILION = "#1D6091", "#C1440E"
MONO = "'Source Code Pro', 'SF Mono', Menlo, monospace"
FONTS = ("https://fonts.googleapis.com/css2?family=Source+Code+Pro:wght@400;600"
         "&display=swap")


def open_session(ld):
    """Platform session from env secrets in CI; Workspace desktop session locally."""
    key, user, pw = (os.environ.get(k, "") for k in
                     ("LSEG_APP_KEY", "LSEG_USERNAME", "LSEG_PASSWORD"))
    if key and user and pw:
        session = ld.session.platform.Definition(
            app_key=key,
            grant=ld.session.platform.GrantPassword(username=user, password=pw),
            # True would take exclusive sign-on and log this account's other
            # sessions out, including the Workspace app on the desktop.
            signon_control=False,
        ).get_session()
        session.open()
        ld.session.set_default(session)
        kind = "platform"
    elif os.environ.get("GITHUB_ACTIONS") == "true":
        sys.exit("LSEG_APP_KEY, LSEG_USERNAME and LSEG_PASSWORD are not all set. "
                 "Add them under Settings -> Secrets and variables -> Actions.")
    else:
        session = (ld.open_session(config_name=str(CONFIG)) if CONFIG.exists()
                   else ld.open_session())
        kind = "desktop"
    if session.open_state != ld.OpenState.Opened:
        hint = ("check the three secrets, and that this LSEG account may sign in "
                "to the Data Platform" if kind == "platform"
                else "is LSEG Workspace running and signed in?")
        raise RuntimeError(f"LSEG {kind} session did not open ({hint})")
    print(f"LSEG {kind} session opened")
    return session, kind


def closes(ld, ric: str, start: dt.date, end: dt.date, today_ny: dt.date,
           before_close: bool) -> pd.Series:
    """Daily TRDPRC_1 for one RIC, completed sessions only."""
    df = ld.get_history(universe=ric, fields=["TRDPRC_1"], interval="1D",
                        start=start.isoformat(), end=end.isoformat())
    if df is None or df.empty or "TRDPRC_1" not in df.columns:
        raise RuntimeError(f"{ric}: no TRDPRC_1 history came back")
    s = pd.to_numeric(df["TRDPRC_1"], errors="coerce").dropna()
    s.index = pd.to_datetime(s.index).normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    if before_close:
        s = s[s.index.date < today_ny]
    if len(s) < WINDOW + 20:
        raise RuntimeError(f"{ric}: only {len(s)} sessions came back")
    print(f"{ric}: {len(s)} sessions, {s.index[0].date()} -> {s.index[-1].date()}")
    return s


def realised_vol(px: pd.Series) -> pd.Series:
    """Annualised close-to-close volatility, in percent."""
    r = np.log(px).diff()
    return (r.rolling(WINDOW).std(ddof=1) * np.sqrt(252) * 100).dropna()


def end_label(fig, s: pd.Series, text: str, color: str, row: int, yshift: int = 0) -> None:
    # x in paper units (the plot's right edge), so the label sits in the right
    # margin and never widens the date axis; plotly autoranges data-x labels.
    fig.add_annotation(xref="paper", x=1, yref="y" if row == 1 else f"y{row}",
                       y=float(s.iloc[-1]), text=text, xanchor="left", xshift=8,
                       yshift=yshift, showarrow=False,
                       font=dict(family=MONO, size=11, color=INK))
    fig.add_trace(go.Scatter(x=[s.index[-1]], y=[float(s.iloc[-1])], mode="markers",
                             marker=dict(size=8, color=color,
                                         line=dict(width=2, color=CARD)),
                             cliponaxis=False, hoverinfo="skip", showlegend=False),
                  row=row, col=1)


def figure(px: pd.Series, mkt: pd.Series, rv: pd.Series, mrv: pd.Series) -> go.Figure:
    lo = max(px.index[-1], mkt.index[-1]) - dt.timedelta(days=SHOW_DAYS)
    px, mkt, rv, mrv = (s.loc[lo:] for s in (px, mkt, rv, mrv))
    # One axis for two prices: both rebased to 100 on the first shown session.
    ix, mix = px / px.iloc[0] * 100, mkt / mkt.iloc[0] * 100
    since = px.index[0].strftime("%-d %b %Y")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                        row_heights=[0.5, 0.5])
    fig.add_trace(go.Scatter(
        x=ix.index, y=ix, name="AAPL", legendgroup="aapl",
        line=dict(color=BLUE, width=2), customdata=px,
        hovertemplate="%{y:.1f}  ($%{customdata:.2f})<extra>AAPL</extra>"),
        row=1, col=1)
    fig.add_trace(go.Scatter(
        x=mix.index, y=mix, name="SPY (S&P 500)", legendgroup="spy",
        line=dict(color=VERMILION, width=2, dash="dot"), customdata=mkt,
        hovertemplate="%{y:.1f}  ($%{customdata:.2f})<extra>SPY</extra>"),
        row=1, col=1)
    fig.add_trace(go.Scatter(
        x=rv.index, y=rv, name="AAPL", legendgroup="aapl", showlegend=False,
        line=dict(color=BLUE, width=2),
        hovertemplate="%{y:.1f}%<extra>AAPL</extra>"), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=mrv.index, y=mrv, name="SPY", legendgroup="spy", showlegend=False,
        line=dict(color=VERMILION, width=2, dash="dot"),
        hovertemplate="%{y:.1f}%<extra>SPY</extra>"), row=2, col=1)

    # Direct end labels. When a pair of line ends crowd, push the upper
    # label up and the lower one down (pixels; the other label gets -n).
    def nudge(a: float, b: float, gap: float) -> int:
        return 0 if abs(a - b) >= gap else (8 if a >= b else -8)
    n1 = nudge(ix.iloc[-1], mix.iloc[-1], 6)
    n2 = nudge(rv.iloc[-1], mrv.iloc[-1], 3)
    end_label(fig, ix, f"AAPL ${px.iloc[-1]:.2f}", BLUE, 1, n1)
    end_label(fig, mix, f"SPY ${mkt.iloc[-1]:.2f}", VERMILION, 1, -n1)
    end_label(fig, rv, f"AAPL {rv.iloc[-1]:.1f}%", BLUE, 2, n2)
    end_label(fig, mrv, f"SPY {mrv.iloc[-1]:.1f}%", VERMILION, 2, -n2)

    axis = dict(showgrid=True, gridcolor=WASH, gridwidth=1, zeroline=False,
                showline=False, ticks="", tickfont=dict(family=MONO, size=11, color=MUTED))
    fig.update_xaxes(**axis, showspikes=True, spikemode="across", spikesnap="cursor",
                     spikethickness=1, spikecolor=FAINT, spikedash="solid")
    fig.update_yaxes(**axis)
    title = dict(font=dict(size=11, color=MUTED))
    fig.update_yaxes(title=dict(text=f"Price, {since} = 100", **title), row=1, col=1)
    fig.update_yaxes(title=dict(text=f"{WINDOW}-day realised vol, % ann.", **title),
                     ticksuffix="%", rangemode="tozero", row=2, col=1)
    fig.update_layout(
        template="none", paper_bgcolor=CARD, plot_bgcolor=CARD,
        font=dict(family=MONO, size=12, color=INK),
        margin=dict(l=64, r=112, t=40, b=36), autosize=True,
        hovermode="x unified",
        hoverlabel=dict(bgcolor=CARD, bordercolor=RULE,
                        font=dict(family=MONO, size=12, color=INK)),
        legend=dict(orientation="h", x=0, xanchor="left", y=1.0, yanchor="bottom",
                    font=dict(family=MONO, size=11, color=INK)),
    )
    return fig


def write_figure(fig: go.Figure, path: Path) -> None:
    html = fig.to_html(include_plotlyjs="cdn", full_html=True,
                       default_width="100%", default_height="100%",
                       config={"displaylogo": False, "responsive": True,
                               "modeBarButtonsToRemove": ["lasso2d", "select2d"]})
    head = (f'<link rel="stylesheet" href="{FONTS}">'
            "<style>html,body{margin:0;height:100%;background:#FFFFFF}</style>")
    path.write_text(html.replace("<head>", "<head>" + head, 1), encoding="utf-8")


def main() -> None:
    import lseg.data as ld

    now_ny = dt.datetime.now(ZoneInfo("America/New_York"))
    before_close = now_ny.time() < CLOSE_NY
    end = now_ny.date()
    start = end - dt.timedelta(days=SHOW_DAYS + PAD_DAYS)

    session, kind = open_session(ld)
    try:
        px = closes(ld, STOCK, start, end, now_ny.date(), before_close)
        mkt = closes(ld, MARKET, start, end, now_ny.date(), before_close)
    finally:
        try:
            session.close()
            print("LSEG session closed")
        except Exception as e:  # closing must not mask the real result
            print(f"warning: session close failed: {e}")

    through = min(px.index[-1], mkt.index[-1])
    px, mkt = px.loc[:through], mkt.loc[:through]
    rv, mrv = realised_vol(px), realised_vol(mkt)

    OUT.mkdir(parents=True, exist_ok=True)
    write_figure(figure(px, mkt, rv, mrv), OUT / "aapl-vol.html")

    run = None
    if os.environ.get("GITHUB_RUN_ID"):
        run = {"number": int(os.environ.get("GITHUB_RUN_NUMBER", "0")),
               "url": (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                       f"{os.environ['GITHUB_REPOSITORY']}/actions/runs/"
                       f"{os.environ['GITHUB_RUN_ID']}"),
               "event": os.environ.get("GITHUB_EVENT_NAME", "")}
    meta = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": kind,
        "through": through.date().isoformat(),
        "aapl_close": round(float(px.iloc[-1]), 2),
        "spy_close": round(float(mkt.iloc[-1]), 2),
        "aapl_rv": round(float(rv.iloc[-1]), 1),
        "spy_rv": round(float(mrv.iloc[-1]), 1),
        "window": WINDOW,
        "run": run,
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'aapl-vol.html'} and meta.json (through {meta['through']})")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
