"""
Build the published app into docs/ for GitHub Pages.

    python -m options_surface_lab.build

GitHub Pages serves files and nothing else, so there is no server to compute
a figure on demand. Instead every (as-of date, right) combination is rendered
ahead of time to one JSON bundle, and the page fetches the bundle it needs
when a control changes. The controls stay live — date, right, and the three
layer switches all work — because the switching happens in the browser.

Figures come from figures.py, the same functions used everywhere else. There
is no second copy of the plotting logic.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import plotly.utils

from .figures import (
    mark_vs_print_figure,
    occupancy_figure,
    quote_band_figure,
    surface_figure,
    underlying_figure,
)
from .panel import build as build_panel, day_stats, grid_stats
from .theme import (
    CARD, FONT_URL, INK, INK_MUTED, MARK, MARK_FIELD, MONO,
    PAPER, PRINT, PRINT_FIELD, RULE, SERIF, WASH,
)

# 1.1 moved down a level when 1.2 took the root. The page only ever fetches
# relative paths (meta.json, figures/*.json), so the move costs nothing.
DOCS = Path(__file__).resolve().parents[1] / "docs" / "1.1"


def _json(obj) -> str:
    return json.dumps(obj, cls=plotly.utils.PlotlyJSONEncoder, separators=(",", ":"))


def _stats(contracts: pd.DataFrame, asof: str, right: str) -> dict:
    s = day_stats(contracts, asof, right)
    g = grid_stats(contracts, asof, right)
    gap, rel = s["median_gap"], s["median_rel_gap_pct"]
    return {
        "pct_mark_no_print": f"{s['pct_mark_no_print']:.0f}%",
        "median_gap": "n/a" if gap is None else f"${gap:.3f}" + (f"  ({rel:.0f}%)" if rel else ""),
        "pct_never_traded": f"{g['pct_never_traded']:.0f}%",
        "pct_empty": f"{g['pct_empty']:.0f}%",
        "n_mark": str(s["n_mark"]),
        "n_print": str(s["n_print"]),
        "median_spread": "n/a" if s["median_spread"] is None else f"${s['median_spread']:.2f}",
    }


def build_site() -> Path:
    contracts, payload = build_panel()
    underlying = payload.get("underlying") or payload.get("ticker") or "UUUU"

    if DOCS.exists():
        shutil.rmtree(DOCS)
    (DOCS / "figures").mkdir(parents=True)

    dates = sorted(contracts["date"].dt.strftime("%Y-%m-%d").unique())
    default_date = contracts.groupby(contracts["date"].dt.strftime("%Y-%m-%d")).size().idxmax()

    available: dict[str, list[str]] = {}
    for asof in dates:
        rights = []
        for right in ("C", "P"):
            day = contracts[
                (contracts["date"] == pd.Timestamp(asof)) & (contracts["right"] == right)
            ]
            if day.empty:
                continue
            bundle = {
                "occupancy": occupancy_figure(contracts, asof, right, underlying).to_plotly_json(),
                # rendered with every layer present; the page hides them
                "surface": surface_figure(contracts, asof, right, True, underlying).to_plotly_json(),
                "compare": mark_vs_print_figure(contracts, asof, right, underlying).to_plotly_json(),
                "band": quote_band_figure(contracts, asof, right, underlying).to_plotly_json(),
                "stats": _stats(contracts, asof, right),
            }
            (DOCS / "figures" / f"{asof}_{right}.json").write_text(_json(bundle), encoding="utf-8")
            rights.append(right)
        if rights:
            available[asof] = rights

    (DOCS / "meta.json").write_text(_json({
        "underlying": underlying,
        "dates": list(available),
        "available": available,
        "default_date": default_date,
        "fetched_at": payload.get("fetched_at", "?"),
        "n_contracts": int(contracts["ric"].nunique()),
        "n_sessions": int(contracts["date"].nunique()),
        "underlying_figure": underlying_figure(payload.get("stock"), underlying).to_plotly_json(),
    }), encoding="utf-8")

    (DOCS / "index.html").write_text(page(underlying), encoding="utf-8")
    # .nojekyll lives at the site root now, written by the 1.2 build.

    size = sum(f.stat().st_size for f in DOCS.rglob("*") if f.is_file())
    n = len(list((DOCS / "figures").glob("*.json")))
    print(f"wrote {DOCS}")
    print(f"  {n} bundles · {size / 1024 / 1024:.1f} MB · default as-of {default_date}")
    return DOCS


def page(underlying: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Option Surface Lab · {underlying}</title>
<link rel="stylesheet" href="{FONT_URL}">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
  :root {{
    --paper:{PAPER}; --card:{CARD}; --rule:{RULE}; --wash:{WASH};
    --ink:{INK}; --muted:{INK_MUTED}; --mark:{MARK}; --print:{PRINT};
    --serif:{SERIF}; --mono:{MONO};
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink); font-family:var(--serif); }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:40px 24px 64px; }}
  .masthead {{ border-bottom:2px solid var(--ink); padding-bottom:20px; }}
  .kicker {{ font-family:var(--mono); font-size:11px; color:var(--muted);
             letter-spacing:.1em; text-transform:uppercase; }}
  h1 {{ font-size:44px; margin:6px 0 0; font-weight:700; letter-spacing:-.01em; }}
  .lede {{ font-size:17px; color:var(--muted); max-width:60ch; line-height:1.55; margin:10px 0 0; }}
  .prov {{ font-family:var(--mono); font-size:12px; color:var(--muted); margin:16px 0 0; }}
  .cards {{ display:flex; gap:12px; flex-wrap:wrap; margin:22px 0 0; }}
  .card {{ background:var(--card); border:1px solid var(--rule); border-radius:4px;
           padding:14px 18px; flex:1 1 190px; min-width:190px; }}
  .card .lab {{ font-family:var(--mono); font-size:11px; color:var(--muted);
                letter-spacing:.08em; text-transform:uppercase; }}
  .card .val {{ font-size:30px; font-weight:700; line-height:1.15; margin-top:5px; }}
  .card .hint {{ font-size:12px; color:var(--muted); margin-top:3px; }}
  .req {{ border-color:var(--ink); border-width:1.5px; }}
  h2 {{ font-size:24px; margin:40px 0 0; font-weight:700; }}
  .blurb {{ font-size:15px; color:var(--muted); max-width:62ch; line-height:1.55; margin:6px 0 14px; }}
  .panel {{ background:var(--card); border:1px solid var(--rule); border-radius:4px; padding:14px; }}
  .controls {{ display:flex; gap:26px; align-items:flex-end; flex-wrap:wrap;
               background:var(--card); border:1px solid var(--rule); border-radius:4px;
               padding:16px 18px; margin:16px 0 0; position:sticky; top:0; z-index:5; }}
  .ctl label {{ display:block; font-family:var(--mono); font-size:11px;
                color:var(--muted); margin-bottom:5px; }}
  select {{ font-family:var(--mono); font-size:13px; padding:6px 10px;
            border:1px solid var(--rule); border-radius:3px;
            background:var(--paper); color:var(--ink); }}
  .toggles {{ display:flex; gap:18px; flex-wrap:wrap; margin-left:auto; align-items:center; }}
  .tg {{ display:flex; align-items:center; gap:7px; font-family:var(--mono);
         font-size:12px; cursor:pointer; user-select:none; }}
  .tg input {{ accent-color:var(--mark); width:15px; height:15px; cursor:pointer; }}
  .finding {{ border-left:2px solid var(--mark); padding-left:16px; margin-bottom:22px; }}
  .finding .q {{ font-family:var(--mono); font-size:11px; color:var(--muted);
                 letter-spacing:.04em; text-transform:uppercase; }}
  .finding .a {{ font-size:16px; line-height:1.62; max-width:78ch; margin-top:7px; }}
  .note {{ background:var(--paper); border:1px solid var(--rule); border-radius:4px;
           padding:16px 18px; font-size:14px; color:var(--muted);
           line-height:1.6; max-width:78ch; }}
  footer {{ border-top:1px solid var(--rule); margin-top:44px; padding-top:16px;
            font-family:var(--mono); font-size:12px; color:var(--muted); line-height:1.7; }}
  #status {{ font-family:var(--mono); font-size:11px; color:var(--muted); }}
  nav {{ display:flex; gap:18px; align-items:baseline; font-family:var(--mono);
         font-size:11px; letter-spacing:.09em; text-transform:uppercase;
         color:var(--muted); margin-bottom:26px; flex-wrap:wrap; }}
  nav a {{ color:var(--muted); text-decoration:none;
           border-bottom:1px solid var(--rule); }}
  nav a:hover {{ color:var(--ink); border-color:var(--ink); }}
  nav .here {{ color:var(--ink); font-weight:600; border-bottom:2px solid var(--ink); }}
  @media (max-width:700px) {{ h1 {{ font-size:32px; }} .toggles {{ margin-left:0; }}
                              .controls {{ position:static; }} }}
</style>
</head>
<body>
<div class="wrap">

  <nav>
    <a href="../">1.4 · The Wheel</a>
    <a href="../1.3/">1.3 · Poor Man's Covered Call</a>
    <a href="../1.2/">1.2 · Covered Call</a>
    <span class="here">1.1 · Option Surface Lab</span>
    <a href="../data.html">Data</a>
    <a href="https://github.com/yangpuhan/Fintech535">Source</a>
  </nav>

  <div class="masthead">
    <div class="kicker">MENG FinTech · Algorithmic Trading II · Assignment 1.1</div>
    <h1>Option Surface Lab</h1>
    <p class="lede">Listed options are a sparse cloud, not a filled sheet.
       This page is arranged so the holes show up first.</p>
  </div>
  <div class="prov" id="prov">loading…</div>

  <div class="cards" id="cards"></div>

  <h2>Where the data is not</h2>
  <p class="blurb">One cell per listed (expiry, strike). Grey cells were listed and never
     quoted all day. Blue cells have a closing mid that nobody traded. Only the red cells
     are contracts a human actually transacted in.</p>
  <div class="panel"><div id="occupancy" style="height:470px"></div></div>

  <div class="controls">
    <div class="ctl"><label>as-of date</label><select id="date"></select></div>
    <div class="ctl"><label>right</label>
      <select id="right"><option value="C">C</option><option value="P">P</option></select></div>
    <div class="toggles">
      <label class="tg"><input type="checkbox" id="t-mark" checked>
        <span style="color:{MARK}">{MARK_FIELD} · mid</span></label>
      <label class="tg"><input type="checkbox" id="t-print" checked>
        <span style="color:{PRINT}">{PRINT_FIELD} · real trade</span></label>
      <label class="tg"><input type="checkbox" id="t-sheet">
        <span style="color:{INK_MUTED}">interpolated sheet</span></label>
      <span id="status"></span>
    </div>
  </div>

  <h2>The cloud in three dimensions</h2>
  <p class="blurb">Strike across, days to expiry into the page, price up. Drag to rotate.
     Turn the interpolated sheet on and watch it stretch a smooth surface over strikes
     that never had a number.</p>
  <div class="panel"><div id="surface" style="height:620px"></div></div>

  <h2>What I read off this</h2>
  <div class="panel">
    <div class="finding">
      <div class="q">1. Where is the cloud dense, and where is it empty?</div>
      <div class="a">Dense in a narrow vertical band within a couple of dollars of spot and
        in the front one or two expiries — that is the only region where a mid and a real
        trade both exist. It empties in two directions at once: away from spot, where mids
        survive but trades stop, and further out in time, where whole rows of the grid go
        grey. On the busiest session in this window, 226 call cells were listed, 150 carried
        a closing mid, and only 114 traded — 63% of the grid never changed hands. The
        surprise is at the edge: 30 of those trades have <em>no</em> mid at all, because by
        the close the bid had gone away and there was nothing left to take a midpoint of.</div>
    </div>
    <div class="finding">
      <div class="q">2. Why is interpolating across empty cells dangerous on a $0.50 grid
        for a name like {underlying}?</div>
      <div class="a">{underlying} trades in the $8–15 range, so consecutive $0.50 strikes sit
        only three to six percent apart in moneyness, and option value across strikes is
        curved rather than straight — running a straight line through the most curved part
        of the payoff is exactly the wrong shape, and it biases low near the money. On the
        wings it stops being a shape problem and becomes a meaning problem: out there a
        missing cell does not say "price unknown", it says there is no bid at all, and the
        interpolator will still hand back a confident positive number for a contract the
        market prices at zero. The sheet looks smoothest precisely where it knows least.</div>
    </div>
    <div class="finding">
      <div class="q">3. Which field is the mark next week, and which is evidence that
        someone traded?</div>
      <div class="a">{MARK_FIELD} is the mark. It is the field that survives on the contracts
        nobody trades, which is exactly where a price is needed, and being a midpoint of live
        quotes it moves with the underlying instead of going stale. {PRINT_FIELD} is evidence
        and nothing more: one trade, at one moment in the session, on a series that may not
        trade again for a week. Treating it as a mark means pricing a whole surface off a
        single stale print. But the mid is not free of sin either — on a barely-traded name
        it is the middle of a quote that may itself be stale, and the bid/ask band below shows
        how wide that middle really is.</div>
    </div>
    <div class="note">
      <b>On the mark field.</b> There is no exchange settlement price here. LSEG rejects
      <code>SETTLE</code> on this RIC space with "the universe does not support the following
      fields", and <code>TR.SettlementPrice</code> comes back empty, so {MARK_FIELD} — the
      closing NBBO midpoint — is the closest mark-of-the-close available. It is still a
      model-free number rather than a traded one.
    </div>
  </div>

  <h2>The mid is not the trade</h2>
  <p class="blurb">Two different series plotted against each other. If they were the same
     number, every point would sit on the dashed line.</p>
  <div class="panel"><div id="compare" style="height:450px"></div></div>

  <h2>So what would you actually get filled at?</h2>
  <p class="blurb">The honest answer is a range, not a number. Where the band is tall the mid
     is the middle of a guess, and where the bid drops to zero there is nobody on the other
     side at all.</p>
  <div class="panel"><div id="band" style="height:430px"></div></div>

  <h2>The underlying, for reference</h2>
  <div class="panel"><div id="underlying" style="height:320px"></div></div>

  <footer>
    Data from LSEG · mark = {MARK_FIELD} (closing NBBO mid) · print = {PRINT_FIELD} (last trade)<br>
    Figures pre-rendered from the cached pickle; controls run in the browser.<br>
    <a href="../" style="color:var(--muted)">Assignment 1.4 · The Wheel</a> ·
    <a href="../1.3/" style="color:var(--muted)">Assignment 1.3 · Poor Man's Covered Call</a> ·
    <a href="../1.2/" style="color:var(--muted)">Assignment 1.2 · Covered Call Backtest</a> ·
    <a href="https://github.com/yangpuhan/Fintech535" style="color:var(--muted)">github.com/yangpuhan/Fintech535</a>
  </footer>
</div>

<script>
const CARDS = [
  ["% mid, no trade", "pct_mark_no_print",
   "of listed series with a mid that day", "var(--print)", true],
  ["median |mid − trade|", "median_gap", "on series that have both", "var(--mark)", true],
  ["grid never traded", "pct_never_traded", "of listed cells, nobody transacted", "var(--ink)", false],
  ["nothing quoted", "pct_empty", "not even a mid — a true hole", "var(--ink)", false],
  ["series with a mid", "n_mark", "vs traded →", "var(--ink)", false],
  ["series traded", "n_print", "someone really paid this", "var(--ink)", false],
  ["median bid/ask", "median_spread", "the width you'd pay to cross", "var(--ink)", false],
];
const PLOTS = ["occupancy", "surface", "compare", "band"];
const CONFIG = {{responsive:true, displaylogo:false,
                modeBarButtonsToRemove:["lasso2d","select2d"]}};
const cache = new Map();
let meta = null;

function drawCards(stats) {{
  document.getElementById("cards").innerHTML = CARDS.map(
    ([lab, key, hint, col, req]) =>
      `<div class="card${{req ? " req" : ""}}"><div class="lab">${{lab}}</div>` +
      `<div class="val" style="color:${{col}}">${{stats[key]}}</div>` +
      `<div class="hint">${{hint}}</div></div>`).join("");
}}

function applyToggles() {{
  const el = document.getElementById("surface");
  if (!el || !el.data) return;
  const want = {{mark:  document.getElementById("t-mark").checked,
                print: document.getElementById("t-print").checked,
                sheet: document.getElementById("t-sheet").checked}};
  el.data.forEach((trace, i) => {{
    const role = trace.meta && trace.meta.role;
    if (role in want) {{
      Plotly.restyle(el, {{visible: want[role] ? true : "legendonly"}}, [i]);
    }}
  }});
}}

async function show(date, right) {{
  const key = `${{date}}_${{right}}`;
  const status = document.getElementById("status");
  status.textContent = "loading…";
  if (!cache.has(key)) {{
    const res = await fetch(`figures/${{key}}.json`);
    if (!res.ok) {{ status.textContent = "no data"; return; }}
    cache.set(key, await res.json());
  }}
  const bundle = cache.get(key);
  drawCards(bundle.stats);
  for (const id of PLOTS) Plotly.react(id, bundle[id].data, bundle[id].layout, CONFIG);
  applyToggles();
  status.textContent = "";
}}

async function refresh() {{
  const date = document.getElementById("date").value;
  const rights = meta.available[date] || [];
  const sel = document.getElementById("right");
  // a date may list only one right; fall back rather than render nothing
  if (!rights.includes(sel.value)) sel.value = rights[0];
  await show(date, sel.value);
}}

(async function init() {{
  meta = await (await fetch("meta.json")).json();
  document.getElementById("prov").textContent =
    `LSEG pull cached ${{meta.fetched_at}} · ${{meta.n_contracts}} expired contracts · ` +
    `${{meta.n_sessions}} sessions`;
  document.getElementById("date").innerHTML = meta.dates.map(d =>
    `<option value="${{d}}"${{d === meta.default_date ? " selected" : ""}}>${{d}}</option>`
  ).join("");
  Plotly.newPlot("underlying", meta.underlying_figure.data,
                 meta.underlying_figure.layout, CONFIG);
  document.getElementById("date").addEventListener("change", refresh);
  document.getElementById("right").addEventListener("change", refresh);
  for (const id of ["t-mark", "t-print", "t-sheet"]) {{
    document.getElementById(id).addEventListener("change", applyToggles);
  }}
  await refresh();
}})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build_site()
