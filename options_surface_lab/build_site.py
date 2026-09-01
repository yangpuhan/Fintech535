"""
Static build of the lab for GitHub Pages.

Why this exists
---------------
Reflex is full-stack: the figures live in ``rx.State`` on a Python backend and
reach the browser over a websocket. GitHub Pages serves files and nothing else,
so the Reflex app itself cannot run there.

This renders the *same* Plotly figures — same functions, same theme, no second
copy of the plotting logic — to JSON, one file per (as-of date, right), and
ships a small page that fetches them on demand. Every control on the Reflex
page still works; the switching just happens in the browser instead of on a
server.

    python -m options_surface_lab.build_site
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import plotly.utils as plotly_utils

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
    WASH,
)
from .option_surface_utils import (
    grid_occupancy,
    load_payload,
    prepare,
    summarize_sparsity,
)

DOCS = Path(__file__).resolve().parents[1] / "docs"
FIGURES = DOCS / "figures"


def _dump(obj) -> str:
    return json.dumps(obj, cls=plotly_utils.PlotlyJSONEncoder, separators=(",", ":"))


def _stats_for(wide: pd.DataFrame, asof: str, cp: str) -> dict:
    day = wide[(wide["date"] == pd.Timestamp(asof)) & (wide["cp"] == cp)]
    s = summarize_sparsity(day)
    occ = grid_occupancy(wide, asof, cp)
    med = s["median_abs_diff"]
    rel = s["median_rel_diff_pct"]
    return {
        "pct_mark_no_print": f"{s['pct_mark_no_print']:.0f}%",
        "median_gap": "n/a" if med is None else f"${med:.3f}" + (f"  ({rel:.0f}%)" if rel else ""),
        "pct_never_traded": f"{occ['pct_never_traded']:.0f}%",
        "pct_empty": f"{occ['pct_empty']:.0f}%",
        "n_mark": str(s["n_mark"]),
        "n_print": str(s["n_print"]),
        "median_spread": "n/a" if s["median_spread"] is None else f"${s['median_spread']:.2f}",
    }


def build() -> Path:
    payload = load_payload()
    wide = prepare(payload)
    ticker = payload.get("ticker", "UUUU")

    if DOCS.exists():
        shutil.rmtree(DOCS)
    FIGURES.mkdir(parents=True)

    dates = sorted(wide["date"].dt.strftime("%Y-%m-%d").unique())
    default_date = wide.groupby(wide["date"].dt.strftime("%Y-%m-%d")).size().idxmax()

    written = 0
    for asof in dates:
        for cp in ("C", "P"):
            day = wide[(wide["date"] == pd.Timestamp(asof)) & (wide["cp"] == cp)]
            if day.empty:
                continue
            bundle = {
                "occupancy": occupancy_figure(wide, asof, cp, ticker).to_plotly_json(),
                # always render every trace; the page hides them client-side
                "surface": price_surface_figure(
                    wide, asof, cp=cp, show_mark=True, show_print=True,
                    show_interpolated=True, ticker=ticker,
                ).to_plotly_json(),
                "compare": mark_vs_print_figure(wide, asof, cp, ticker).to_plotly_json(),
                "spread": spread_figure(wide, asof, cp, ticker).to_plotly_json(),
                "stats": _stats_for(wide, asof, cp),
            }
            (FIGURES / f"{asof}_{cp}.json").write_text(_dump(bundle), encoding="utf-8")
            written += 1

    available = {}
    for asof in dates:
        rights = [
            cp for cp in ("C", "P")
            if (FIGURES / f"{asof}_{cp}.json").exists()
        ]
        if rights:
            available[asof] = rights

    (DOCS / "meta.json").write_text(_dump({
        "ticker": ticker,
        "dates": list(available.keys()),
        "available": available,
        "default_date": default_date,
        "fetched_at": payload.get("fetched_at", "?"),
        "synthetic": bool(payload.get("synthetic")),
        "n_contracts": int(wide["ric"].nunique()),
        "n_sessions": int(wide["date"].nunique()),
        "underlying": candlestick_figure(payload.get("stock"), ticker).to_plotly_json(),
    }), encoding="utf-8")

    (DOCS / "index.html").write_text(_page(ticker), encoding="utf-8")
    # GitHub Pages runs Jekyll by default, which skips files it does not
    # recognise. This turns that off so figures/ is served verbatim.
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")

    size = sum(f.stat().st_size for f in DOCS.rglob("*") if f.is_file())
    print(f"wrote {DOCS}")
    print(f"  {written} (date, right) bundles · {size / 1024 / 1024:.1f} MB total")
    print(f"  default as-of {default_date}")
    return DOCS


def _page(ticker: str) -> str:
    """The shell. Controls and metric cards are filled in from meta.json."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Options Surface Lab · {ticker}</title>
<link rel="stylesheet" href="{FONT_URL}">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
  :root {{
    --paper: {PAPER}; --card: {CARD}; --rule: {RULE}; --wash: {WASH};
    --ink: {INK}; --muted: {INK_MUTED}; --mark: {MARK}; --print: {PRINT};
    --serif: {SERIF}; --mono: {MONO};
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--paper); color: var(--ink);
         font-family: var(--serif); }}
  .wrap {{ max-width: 1180px; margin: 0 auto; padding: 40px 24px 64px; }}
  .masthead {{ border-bottom: 2px solid var(--ink); padding-bottom: 20px; }}
  .kicker {{ font-family: var(--mono); font-size: 11px; color: var(--muted);
             letter-spacing: .1em; text-transform: uppercase; }}
  h1 {{ font-size: 44px; margin: 6px 0 0; font-weight: 700; letter-spacing: -.01em; }}
  .lede {{ font-size: 17px; color: var(--muted); max-width: 60ch;
           line-height: 1.55; margin: 10px 0 0; }}
  .prov {{ font-family: var(--mono); font-size: 12px; color: var(--muted);
           margin: 16px 0 0; }}
  .cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 22px 0 0; }}
  .card {{ background: var(--card); border: 1px solid var(--rule); border-radius: 4px;
           padding: 14px 18px; flex: 1 1 190px; min-width: 190px; }}
  .card .lab {{ font-family: var(--mono); font-size: 11px; color: var(--muted);
                letter-spacing: .08em; text-transform: uppercase; }}
  .card .val {{ font-size: 30px; font-weight: 700; line-height: 1.15; margin-top: 5px; }}
  .card .hint {{ font-size: 12px; color: var(--muted); margin-top: 3px; }}
  h2 {{ font-size: 24px; margin: 40px 0 0; font-weight: 700; }}
  .blurb {{ font-size: 15px; color: var(--muted); max-width: 62ch;
            line-height: 1.55; margin: 6px 0 14px; }}
  .panel {{ background: var(--card); border: 1px solid var(--rule);
            border-radius: 4px; padding: 14px; }}
  .controls {{ display: flex; gap: 26px; align-items: flex-end; flex-wrap: wrap;
               background: var(--card); border: 1px solid var(--rule);
               border-radius: 4px; padding: 16px 18px; margin: 16px 0 0; }}
  .ctl label {{ display: block; font-family: var(--mono); font-size: 11px;
                color: var(--muted); margin-bottom: 5px; }}
  select {{ font-family: var(--mono); font-size: 13px; padding: 6px 10px;
            border: 1px solid var(--rule); border-radius: 3px;
            background: var(--paper); color: var(--ink); }}
  .toggles {{ display: flex; gap: 18px; flex-wrap: wrap; margin-left: auto; }}
  .tg {{ display: flex; align-items: center; gap: 7px; font-family: var(--mono);
         font-size: 12px; cursor: pointer; user-select: none; }}
  .tg input {{ accent-color: var(--mark); width: 15px; height: 15px; cursor: pointer; }}
  .finding {{ border-left: 2px solid var(--mark); padding-left: 16px; margin-bottom: 22px; }}
  .finding .q {{ font-family: var(--mono); font-size: 11px; color: var(--muted);
                 letter-spacing: .04em; text-transform: uppercase; }}
  .finding .a {{ font-size: 16px; line-height: 1.62; max-width: 78ch; margin-top: 7px; }}
  .note {{ background: var(--paper); border: 1px solid var(--rule); border-radius: 4px;
           padding: 16px 18px; font-size: 14px; color: var(--muted);
           line-height: 1.6; max-width: 78ch; }}
  footer {{ border-top: 1px solid var(--rule); margin-top: 44px; padding-top: 16px;
            font-family: var(--mono); font-size: 12px; color: var(--muted); }}
  .chart {{ width: 100%; }}
  #loading {{ font-family: var(--mono); font-size: 12px; color: var(--muted); }}
  @media (max-width: 700px) {{ h1 {{ font-size: 32px; }} .toggles {{ margin-left: 0; }} }}
</style>
</head>
<body>
<div class="wrap">

  <div class="masthead">
    <div class="kicker">MENG FinTech · Algorithmic Trading II · Assignment 1.1</div>
    <h1>Options Surface Lab</h1>
    <p class="lede">Listed options are a sparse cloud, not a filled sheet.
       This page is arranged so the holes show up first.</p>
  </div>
  <div class="prov" id="prov">loading…</div>

  <div class="cards" id="cards"></div>

  <h2>Where the data is not</h2>
  <p class="blurb">One cell per listed (expiry, strike). Grey cells were listed and
     never quoted. Blue cells carry a model mark that nobody traded. Only the red
     cells are contracts a human actually transacted.</p>
  <div class="panel"><div class="chart" id="occupancy" style="height:460px"></div></div>

  <div class="controls">
    <div class="ctl"><label>as-of date</label>
      <select id="date"></select></div>
    <div class="ctl"><label>right</label>
      <select id="cp"><option value="C">C</option><option value="P">P</option></select></div>
    <div class="toggles">
      <label class="tg"><input type="checkbox" id="t-mark" checked>
        <span style="color:{MARK}">{MARK_FIELD} · mark</span></label>
      <label class="tg"><input type="checkbox" id="t-print" checked>
        <span style="color:{PRINT}">{PRINT_FIELD} · real trade</span></label>
      <label class="tg"><input type="checkbox" id="t-sheet">
        <span style="color:{INK_MUTED}">interpolated sheet</span></label>
      <span id="loading"></span>
    </div>
  </div>

  <h2>The cloud in three dimensions</h2>
  <p class="blurb">Strike across, days to expiry into the page, price up. Turn the
     interpolated sheet on and watch it stretch a smooth surface over strikes that
     never had a number. Drag to rotate.</p>
  <div class="panel"><div class="chart" id="surface" style="height:620px"></div></div>

  <h2>What I read off this</h2>
  <div class="panel">
    <div class="finding">
      <div class="q">1. Where is the cloud dense, and where is it empty?</div>
      <div class="a">Dense in a narrow vertical band within a couple of dollars of spot,
        and in the front one or two expiries — that is where both a mark and a real
        print exist. It thins out in two directions at once: away from spot, where
        marks survive but trades stop, and further out in time, where entire rows of
        the grid go grey. On the busiest session in this window, 208 of 226 listed
        call cells carried a mark but only 114 of them ever traded — so roughly half
        the surface is a number nobody transacted at.</div>
    </div>
    <div class="finding">
      <div class="q">2. Why is interpolating across empty cells dangerous on a $0.50
        grid for {ticker}?</div>
      <div class="a">{ticker} trades in the $8–15 range, so consecutive $0.50 strikes are
        only three to six percent apart in moneyness, and option value across strikes
        is curved rather than straight — a straight line through the most curved part
        of the payoff is exactly the wrong shape. It gets worse on the wings: out there
        a missing cell does not mean “price unknown”, it means there is no bid at all,
        and the interpolator will still hand back a confident positive number for a
        contract the market is valuing at zero. The sheet looks smoothest precisely
        where it knows least.</div>
    </div>
    <div class="finding">
      <div class="q">3. Which field is the mark next week, and which is evidence
        someone traded?</div>
      <div class="a">{MARK_FIELD} is the mark. It is the only field that prints on the
        contracts nobody trades, which is exactly where a price is needed, and it moves
        with the underlying rather than going stale. {PRINT_FIELD} is evidence and
        nothing more: one trade, at one moment in the session, on a series that may not
        trade again for a week. Taking it as a mark means pricing a whole surface off a
        single stale print.</div>
    </div>
    <div class="note">
      <b>A note on fields.</b> The brief names SETTLE as the exchange mark. That field
      does not exist on this universe — LSEG answers “the universe does not support the
      following fields: [SETTLE]” for OPRA equity options, which is why the original
      cache came back holding nothing but {PRINT_FIELD}. {MARK_FIELD} is the substitute
      and it plays the role the brief describes: a model-ish number that prints on more
      series than trades do. BID and ASK came along too, so the fill question below has
      a real answer.
    </div>
  </div>

  <h2>The mark is not the trade</h2>
  <p class="blurb">Two different series, plotted against each other. If they were the
     same number every point would sit on the dashed line.</p>
  <div class="panel"><div class="chart" id="compare" style="height:440px"></div></div>

  <h2>So what would you actually get filled at?</h2>
  <p class="blurb">The honest answer is a range, not a number. Where the band is tall
     the mark is a guess, and where the bid drops to zero there is nobody on the other
     side.</p>
  <div class="panel"><div class="chart" id="spread" style="height:420px"></div></div>

  <h2>The underlying, for reference</h2>
  <div class="panel"><div class="chart" id="underlying" style="height:320px"></div></div>

  <footer>
    Built with Reflex · data from LSEG · mark = {MARK_FIELD}, print = {PRINT_FIELD} ·
    static build of the Reflex app, which needs a Python backend GitHub Pages cannot run
  </footer>
</div>

<script>
const CARDS = [
  ["marked, never traded", "pct_mark_no_print",
   "of contracts with a mark, share with no print that day", "var(--print)"],
  ["median |mark − trade|", "median_gap", "on contracts that have both", "var(--mark)"],
  ["listed grid never traded", "pct_never_traded",
   "of listed cells, nobody transacted all day", "var(--print)"],
  ["nothing quoted at all", "pct_empty", "not even a mark — a true hole", "var(--ink)"],
  ["contracts marked", "n_mark", "vs traded →", "var(--ink)"],
  ["contracts traded", "n_print", "someone really paid this", "var(--ink)"],
  ["median bid/ask", "median_spread", "the width you'd actually pay", "var(--ink)"],
];
const CONFIG = {{responsive: true, displaylogo: false,
  modeBarButtonsToRemove: ["lasso2d", "select2d"]}};
const cache = new Map();
let meta = null;

function drawCards(stats) {{
  document.getElementById("cards").innerHTML = CARDS.map(([lab, key, hint, col]) =>
    `<div class="card"><div class="lab">${{lab}}</div>` +
    `<div class="val" style="color:${{col}}">${{stats[key]}}</div>` +
    `<div class="hint">${{hint}}</div></div>`).join("");
}}

function applyToggles() {{
  const el = document.getElementById("surface");
  if (!el || !el.data) return;
  const want = {{mark: document.getElementById("t-mark").checked,
                print: document.getElementById("t-print").checked,
                sheet: document.getElementById("t-sheet").checked}};
  el.data.forEach((tr, i) => {{
    const role = tr.meta && tr.meta.role;
    if (role in want) Plotly.restyle(el, {{visible: want[role] ? true : "legendonly"}}, [i]);
  }});
}}

async function load(date, cp) {{
  const key = `${{date}}_${{cp}}`;
  document.getElementById("loading").textContent = "loading…";
  if (!cache.has(key)) {{
    const r = await fetch(`figures/${{key}}.json`);
    if (!r.ok) {{ document.getElementById("loading").textContent = "no data"; return; }}
    cache.set(key, await r.json());
  }}
  const b = cache.get(key);
  drawCards(b.stats);
  for (const id of ["occupancy", "surface", "compare", "spread"]) {{
    Plotly.react(id, b[id].data, b[id].layout, CONFIG);
  }}
  applyToggles();
  document.getElementById("loading").textContent = "";
}}

function currentCp() {{
  const d = document.getElementById("date").value;
  const cp = document.getElementById("cp").value;
  const ok = meta.available[d] || [];
  return ok.includes(cp) ? cp : ok[0];
}}

async function refresh() {{
  const d = document.getElementById("date").value;
  const cp = currentCp();
  document.getElementById("cp").value = cp;
  await load(d, cp);
}}

(async function init() {{
  meta = await (await fetch("meta.json")).json();
  document.getElementById("prov").textContent =
    (meta.synthetic ? "SYNTHETIC panel" : `LSEG pull cached ${{meta.fetched_at}}`) +
    ` · ${{meta.n_contracts}} expired contracts · ${{meta.n_sessions}} sessions`;
  const sel = document.getElementById("date");
  sel.innerHTML = meta.dates.map(d =>
    `<option value="${{d}}"${{d === meta.default_date ? " selected" : ""}}>${{d}}</option>`
  ).join("");
  Plotly.newPlot("underlying", meta.underlying.data, meta.underlying.layout, CONFIG);
  sel.addEventListener("change", refresh);
  document.getElementById("cp").addEventListener("change", refresh);
  for (const t of ["t-mark", "t-print", "t-sheet"]) {{
    document.getElementById(t).addEventListener("change", applyToggles);
  }}
  await refresh();
}})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
