/* Draws the page from window.WHEEL. Every number was computed in wheel/book.py
   and wheel/build.py; the only arithmetic here is formatting, ratios of two
   baked numbers, and looking a date up in the ledger. */
'use strict';

const W = window.WHEEL;
const M = W.meta, S = W.summary, ST = W.stats, K = W.checks, F = W.fills, V = W.vrp;
const CSS = getComputedStyle(document.documentElement);
const C = n => CSS.getPropertyValue(n).trim();

const INK = C('--ink'), MUTED = C('--muted'), FAINT = C('--faint');
const RULE = C('--rule'), CARD = C('--card'), WASH = C('--wash');
const WHEEL = C('--s-wheel'), PUT = C('--s-put'), STOCK = C('--s-stock'), SHADE = C('--shade');
const SERIF = "'Source Serif 4', Georgia, serif";
const MONO = "'Source Code Pro', Menlo, monospace";

/* ── formatting ─────────────────────────────────────────────────────── */
const fmt = (v, d) => Math.abs(v).toLocaleString('en-US',
  { minimumFractionDigits: d, maximumFractionDigits: d });
const nil = v => v === null || v === undefined || Number.isNaN(v);
const money = (v, d = 2) => nil(v) ? '—' : (v < 0 ? '−$' : '$') + fmt(v, d);
const signed = (v, d = 2) => nil(v) ? '—' : (v < 0 ? '−$' : '+$') + fmt(v, d);
const num = (v, d = 2) => nil(v) ? '—' : (v < 0 ? '−' : '') + fmt(v, d);
const pct = (v, d = 2) => nil(v) ? '—' :
  (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d) + '%';
const upct = (v, d = 1) => nil(v) ? '—' : num(v, d) + '%';
const cls = v => v < 0 ? ' class="neg"' : '';
const esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const setHTML = (id, v) => { const e = document.getElementById(id); if (e) e.innerHTML = v; };
const $ = sel => document.querySelector(sel);
const words = n => ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight',
  'nine', 'ten', 'eleven', 'twelve'][n] ?? String(n);
const contract = (right, k, e) => `${num(k, k % 1 ? 2 : 0)}${right} ${e}`;
const NAME = {};
Object.values(W.runs).forEach(r => r.trades.forEach(t => {
  if (t.right) NAME[t.ric] = contract(t.right, t.strike, t.expiry);
}));
const pretty = ric => ric ? (NAME[ric] || ric) : '—';

/* ── shared Plotly furniture ────────────────────────────────────────── */
const CONFIG = { responsive: true, displaylogo: false, displayModeBar: 'hover',
                 modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'] };
const WEEKENDS = [{ bounds: ['sat', 'mon'] }];
function axis(o = {}) {
  return Object.assign({
    gridcolor: RULE, linecolor: RULE, zeroline: false,
    tickfont: { family: MONO, size: 11, color: MUTED },
    title: { font: { family: SERIF, size: 12, color: INK } },
  }, o);
}
const ytitle = t => ({ text: t, font: { family: SERIF, size: 12, color: INK } });
function layout(o = {}) {
  return Object.assign({
    paper_bgcolor: CARD, plot_bgcolor: CARD,
    font: { family: SERIF, size: 13, color: INK },
    margin: { l: 70, r: 24, t: 34, b: 42 },
    hovermode: 'x unified',
    hoverlabel: { bgcolor: CARD, bordercolor: RULE, font: { family: MONO, size: 12, color: INK } },
    legend: { orientation: 'h', y: 1.1, x: 0, font: { family: MONO, size: 11, color: INK },
              bgcolor: 'rgba(0,0,0,0)' },
    xaxis: axis(), yaxis: axis(),
  }, o);
}

const BOOKS = [
  { k: 'wheel', name: 'Wheel', color: WHEEL, dash: 'solid', width: 2.6 },
  { k: 'expiry', name: 'Wheel, held to expiry', color: WHEEL, dash: 'dot', width: 1.4 },
  { k: 'putwrite', name: 'Put-write', color: PUT, dash: 'dash', width: 1.8 },
  { k: 'buywrite', name: 'Buy-write', color: STOCK, dash: 'solid', width: 1.8 },
  { k: 'hold', name: 'Buy & hold', color: STOCK, dash: 'dot', width: 1.8 },
  { k: 'tbill', name: 'T-bills', color: FAINT, dash: 'solid', width: 1.2 },
];
const keyFor = b => `<span class="key${b.dash === 'dot' ? ' dot' : b.dash === 'dash' ? ' dash' : ''}"
  style="border-color:${b.color}"></span>`;

/* the run the records and the portfolio view show */
let RUN = 'wheel';
const R = () => W.runs[RUN];
const L = () => W.runs[RUN].ledger;
const DATES = W.curves.date;
const IDX = Object.fromEntries(DATES.map((d, i) => [d, i]));

/* ══ masthead ═══════════════════════════════════════════════════════ */
setHTML('prov',
  `${M.ticker} · ${M.stock_ric} · daily closes · ${M.sessions} sessions, ${M.first_fill} → ${M.end} ·
   opening cash ${money(M.opening, 0)}<br>
   LSEG pull ${M.fetched_at} · ${M.n_contracts.toLocaleString()} monthly puts and calls ·
   ${M.n_option_rows.toLocaleString()} daily quotes · ${M.n_hourly.toLocaleString()} hourly bars
   on ${M.n_hourly_contracts} more for the fill test · rate ${M.rate_ric}`);

setHTML('r-k1', num(M.kappa)); setHTML('r-k2', num(M.kappa));
setHTML('r-k3', `k = ${num(M.kappa)}`);
setHTML('r-rates', `${num(M.rate_lo)}% to ${num(M.rate_hi)}%`);
setHTML('r-delta', `${num(K.delta.P.median_abs, 4)} on puts and ${num(K.delta.C.median_abs, 4)} on calls`);
{
  const e = ST.wheel.outcomes.EARLY;
  const ep = W.runs.wheel.shorts.filter(s => s.outcome === 'EARLY');
  setHTML('r-early', e === 0 ? 'never in the headline run' :
    `${words(e)} time${e > 1 ? 's' : ''} in the headline run (${ep.map(s =>
      `${s.right === 'P' ? 'a put' : 'a call'}, ${s.closed}`).join('; ')})`);
}

/* ══ 01 · VRP ═══════════════════════════════════════════════════════ */
(function vrp() {
  const rows = V.rows;
  const x = rows.map(r => r.date);
  Plotly.newPlot('plot-vrp', [
    { x, y: rows.map(r => r.put_iv * 100), type: 'scatter', mode: 'lines+markers', name: 'implied vol of the 0.30Δ put',
      line: { color: PUT, width: 2 }, marker: { size: 5, color: PUT },
      customdata: rows.map(r => [contract('P', r.put_k, r.expiry), money(r.put_mid)]),
      hovertemplate: '%{y:.1f}%  %{customdata[0]} at %{customdata[1]}<extra>implied</extra>' },
    { x, y: rows.map(r => r.rv * 100), type: 'scatter', mode: 'lines+markers', name: 'vol AAPL then realised to expiry',
      line: { color: INK, width: 1.5, dash: 'dot' }, marker: { size: 5, color: INK, symbol: 'circle-open' },
      hovertemplate: '%{y:.1f}%<extra>realised</extra>' },
  ], layout({
    xaxis: axis({ type: 'date' }),
    yaxis: axis({ title: ytitle('annualised volatility (%)'), ticksuffix: '%', rangemode: 'tozero' }),
  }), CONFIG);
})();

/* ══ 03 · fills ═════════════════════════════════════════════════════ */
(function fills() {
  const H = F.hourly, D = F.daily;
  Plotly.newPlot('plot-z', [{
    x: H.hist.centres, y: H.hist.counts, type: 'bar', name: 'hourly prints',
    marker: { color: STOCK, line: { color: CARD, width: 1 } },
    hovertemplate: '%{x:+.2f} half-spreads<br>%{y:,} prints<extra></extra>',
  }], layout({
    hovermode: 'closest', bargap: 0.08,
    margin: { l: 60, r: 18, t: 40, b: 50 },
    shapes: [-1, 0, 1].map(v => ({ type: 'line', x0: v, x1: v, y0: 0, y1: 1, yref: 'paper',
      line: { color: v === 0 ? INK : FAINT, width: 1, dash: v === 0 ? 'solid' : 'dot' } })),
    annotations: [[-1, 'bid'], [0, 'mid'], [1, 'ask']].map(([v, t]) => ({
      x: v, y: 1, yref: 'paper', yanchor: 'bottom', text: t, showarrow: false,
      font: { family: MONO, size: 10.5, color: MUTED } })),
    xaxis: axis({ title: ytitle('(print − mid) ÷ half-spread'), range: [-1.55, 1.55], dtick: 0.5 }),
    yaxis: axis({ title: ytitle('hourly bars with a trade') }),
  }), CONFIG);

  $('#t-zyear tbody').innerHTML = D.by_year.map(y => `<tr>
    <td class="l">${y.year}</td><td>${y.n.toLocaleString()}</td><td><b>${num(y.k)}</b></td>
    <td>${upct(y.pct_inside)}</td><td>${upct(y.pct_near_mid)}</td><td>${upct(y.spread_pct)}</td></tr>`
  ).join('') + `<tr class="sum"><td class="l">hourly, ${H.first.slice(0, 7)} → ${H.last.slice(0, 7)}</td>
    <td>${H.n.toLocaleString()}</td><td>${num(H.k)}</td><td>${upct(H.pct_inside)}</td>
    <td>${upct(H.pct_near_mid)}</td><td>${upct(H.spread_pct)}</td></tr>`;

  $('#t-sweep tbody').innerHTML = F.sweep.map(s => `<tr${s.label === 'measured' ? ' class="hl"' : ''}>
    <td class="l">${s.label === 'measured' ? 'measured (headline)' : s.label}</td><td>${num(s.kappa)}</td>
    <td>${money(s.final, 0)}</td><td>${num(s.cagr_pct)}%</td><td>${num(s.sharpe)}</td>
    <td>${money(s.half_spread_paid, 0)}</td></tr>`).join('');
})();

/* ══ 04 · results ═══════════════════════════════════════════════════ */
const navPlot = document.getElementById('plot-nav');
(function nav() {
  const Cv = W.curves;
  const last = DATES.length - 1;
  const traces = BOOKS.map(b => ({
    x: DATES, y: Cv[b.k], type: 'scatter', mode: 'lines', name: b.name,
    line: { color: b.color, width: b.width, dash: b.dash },
    hovertemplate: '%{y:$,.0f}<extra>' + b.name + '</extra>',
  }));
  /* end labels, nudged apart so none overlap */
  const ends = BOOKS.map(b => ({ b, y: Cv[b.k][last] })).sort((a, z) => a.y - z.y);
  const span = Math.max(...ends.map(e => e.y)) - Math.min(...Cv.tbill);
  const gap = span * 0.045;
  for (let i = 1; i < ends.length; i++) ends[i].ly = Math.max(ends[i].y, (ends[i - 1].ly ?? ends[i - 1].y) + gap);
  ends[0].ly = ends[0].y;
  Plotly.newPlot(navPlot, traces, layout({
    margin: { l: 74, r: 150, t: 40, b: 42 },
    annotations: ends.map(e => ({
      x: DATES[last], y: e.ly, text: e.b.name, xanchor: 'left', xshift: 6, showarrow: false,
      font: { family: MONO, size: 10.5, color: INK } })),
    shapes: [{ type: 'line', x0: DATES[0], x1: DATES[last], y0: M.opening, y1: M.opening,
               line: { color: FAINT, width: 1 } }],
    xaxis: axis({ rangebreaks: WEEKENDS, range: [DATES[0], DATES[last]] }),
    yaxis: axis({ title: ytitle(`account value, opened with ${money(M.opening, 0)}`), tickformat: '$,.0f' }),
  }), CONFIG);
  navPlot.on('plotly_click', ev => { if (ev.points[0]) showDate(String(ev.points[0].x).slice(0, 10), true); });
})();

(function perfTable() {
  $('#t-perf tbody').innerHTML = BOOKS.map(b => {
    const a = ST[b.k];
    return `<tr${b.k === 'wheel' ? ' class="hl"' : ''}>
      <td class="l">${keyFor(b)}${b.name}</td>
      <td>${money(a.final, 0)}</td><td>${pct(a.ret_pct, 1)}</td><td>${num(a.cagr_pct)}%</td>
      <td>${num(a.vol_pct, 1)}%</td><td><b>${num(a.sharpe)}</b></td><td>${num(a.sortino)}</td>
      <td${cls(a.max_dd_pct)}>${a.max_dd_pct ? `${pct(a.max_dd_pct, 1)}
        <span style="color:${FAINT}">${a.max_dd_date.slice(0, 7)}</span>` : '—'}</td>
      <td>${nil(a.beta) ? '—' : num(a.beta)}</td>
      <td>${nil(a.up_capture_pct) ? '—' : `${num(a.up_capture_pct, 0)} / ${num(a.down_capture_pct, 0)}`}</td></tr>`;
  }).join('');

  const years = Object.keys(ST.wheel.years);
  $('#t-years thead').innerHTML = `<tr><th class="l">book</th>${years.map((y, i) =>
    `<th>${y}${i === years.length - 1 ? ' to ' + M.end.slice(5) : ''}</th>`).join('')}</tr>`;
  $('#t-years tbody').innerHTML = BOOKS.map(b => `<tr${b.k === 'wheel' ? ' class="hl"' : ''}>
    <td class="l">${keyFor(b)}${b.name}</td>
    ${years.map(y => `<td${cls(ST[b.k].years[y])}>${pct(ST[b.k].years[y], 1)}</td>`).join('')}</tr>`).join('');

  const RC = K.recon, H = ST.hold;
  const row = (lab, f, c = '') => `<tr${c}><td class="l">${lab}</td>${['wheel', 'putwrite', 'buywrite', 'hold']
    .map(k => { const v = f(k); return `<td${cls(v)}>${nil(v) || v === 0 ? '—' : signed(v, 0)}</td>`; }).join('')}</tr>`;
  const get = (k, f) => k === 'hold' ? H[f] : RC[k][f];
  const opt = f => k => k === 'hold' ? null : f(ST[k]);
  $('#t-attr tbody').innerHTML = [
    row('premium received', opt(s => s.premium)),
    row('&nbsp;&nbsp;bought back (rolls, closes)', opt(s => -s.buyback)),
    row('&nbsp;&nbsp;intrinsic on assigned puts', opt(s => -s.put_intrinsic)),
    row('&nbsp;&nbsp;intrinsic on called calls', opt(s => -s.call_intrinsic)),
    row('&nbsp;&nbsp;open option, at its mark', opt(s => -s.open_mark)),
    row('options, net', k => k === 'hold' ? null : RC[k].option_pnl, ' class="sum"'),
    row('shares', k => get(k, k === 'hold' ? 'share_pnl' : 'stock_pnl')),
    row('dividends', k => get(k, 'dividends')),
    row('T-bill interest on cash', k => get(k, 'interest')),
    row('NAV − opening', k => ST[k].final - M.opening, ' class="sum"'),
  ].join('');
  setHTML('recon', money(RC.wheel.pnl_gap));
})();

/* ══ 05 · the portfolio on any date ═════════════════════════════════ */
let CUR = DATES.length - 1;
const range = $('#insp-range'), pick = $('#insp-pick');
range.max = DATES.length - 1;
pick.min = DATES[0]; pick.max = DATES[DATES.length - 1];

const PHASE = {
  put: ['short put on cash', PUT], call: ['shares + covered call', STOCK],
  shares: ['shares, uncovered', STOCK], cash: ['cash', MUTED],
};
const tradeDates = () => [...new Set(R().trades.filter(t => t.action !== 'DIVIDEND').map(t => t.date))];

function showDate(d, scroll) {
  let i = IDX[d];
  if (i === undefined) {                       /* a weekend or holiday: the session before */
    i = DATES.findIndex(x => x > d) - 1;
    if (i < -1) i = DATES.length - 1;
    if (i < 0) i = 0;
  }
  CUR = i;
  renderInspector();
  if (scroll) document.getElementById('portfolio').scrollIntoView({ behavior: 'smooth' });
}

function renderInspector() {
  const Lg = L(), i = CUR, d = DATES[i];
  range.value = i; pick.value = d;
  setHTML('insp-date', d);
  const ph = PHASE[Lg.phase[i]];
  const pe = document.getElementById('insp-phase');
  pe.textContent = ph[0]; pe.style.color = ph[1];

  const nav = Lg.nav[i], cash = Lg.cash[i], sec = Lg.collateral[i], sh = Lg.shares[i];
  const qty = Lg.qty[i], ric = Lg.short[i];
  const dte = ric ? Math.round((new Date(Lg.expiry[i]) - new Date(d)) / 864e5) : null;
  const cells = [
    ['NAV', money(nav, 0), `${pct((nav / M.opening - 1) * 100, 1)} since the open<br>
      buy &amp; hold ${money(W.curves.hold[i], 0)}`],
    ['cash', money(cash, 0), sec ? `${money(sec, 0)} secures the put<br>${money(cash - sec, 0)} free` :
      `all free · earning ${M.rate_ric}`],
    ['shares', sh ? sh.toLocaleString() : '0', sh ? `${money(Lg.stock_mv[i], 0)} at ${money(Lg.spot[i])}<br>
      basis ${money(Lg.basis[i])} · ${signed((Lg.spot[i] - Lg.basis[i]) * sh, 0)} vs basis` :
      `AAPL ${money(Lg.spot[i])}`],
    ['open option', ric ? `${qty} × ${Lg.right[i] === 'P' ? 'put' : 'call'}` : 'none',
      ric ? `${pretty(ric)} · ${dte} days left<br>sold ${money(Lg.entry[i])} · now ${money(Lg.mark[i])}` :
      (Lg.phase[i] === 'shares' ? 'no strike above the basis had a bid' : 'between trades')],
  ];
  setHTML('insp-grid', cells.map(([lab, val, sub]) =>
    `<div class="insp-cell"><div class="lab">${lab}</div><div class="val">${val}</div>
     <div class="sub">${sub}</div></div>`).join(''));

  const rows = [`<tr><td class="l">cash</td><td class="l">USD, in T-bills</td><td>—</td><td>—</td><td>—</td>
    <td>${money(cash)}</td><td>0</td><td class="l" style="color:${MUTED}">${sec ? `${money(sec, 0)} secured` : ''}
    ${Lg.interest[i] ? `· ${money(Lg.interest[i])} interest today` : ''}</td></tr>`];
  if (sh) rows.push(`<tr><td class="l">long</td><td class="l">AAPL.O</td><td>${sh}</td>
    <td>${money(Lg.basis[i])}</td><td>${money(Lg.spot[i])}</td><td>${money(Lg.stock_mv[i])}</td>
    <td>${num(sh, 0)}</td><td class="l" style="color:${MUTED}">entry is the cost basis
    ${Lg.dividend[i] ? `· ${money(Lg.dividend[i])} dividend today` : ''}</td></tr>`);
  if (ric) rows.push(`<tr><td class="l">short</td><td class="l">${esc(ric)}</td><td>−${qty}</td>
    <td>${money(Lg.entry[i], 3)}</td><td>${money(Lg.mark[i], 3)}</td>
    <td class="neg">${money(Lg.short_mv[i])}</td>
    <td>${num(-(Lg.short_delta[i] ?? 0) * 100 * qty, 1)}</td>
    <td class="l" style="color:${MUTED}">${pretty(ric)} · delta ${num(Lg.short_delta[i], 3)} ·
    ${signed((Lg.entry[i] - Lg.mark[i]) * 100 * qty, 0)} open P&amp;L</td></tr>`);
  rows.push(`<tr class="sum"><td class="l">total</td><td class="l"></td><td></td><td></td><td></td>
    <td>${money(nav)}</td><td>${num(Lg.delta[i], 1)}</td><td class="l" style="color:${MUTED}">
    ${money(Lg.premium_cum[i], 0)} premium collected to date · ${signed(Lg.option_cum[i], 0)} realised on options</td></tr>`);
  $('#t-insp tbody').innerHTML = rows.join('');

  const today = R().trades.filter(t => t.date === d);
  setHTML('insp-trades', today.length
    ? `<b>Booked on ${d}:</b><br>` + today.map(t => `${t.action} ${t.qty > 0 ? '+' : ''}${t.qty}
        ${t.right ? pretty(t.ric) : t.ric} at ${money(t.price, 3)} · ${signed(t.cash)} — ${esc(t.note)}`).join('<br>')
    : 'No trades on this date.');

  [navPlot, posPlot].forEach(p => {
    if (!p || !p.layout) return;
    const shapes = (p.layout.shapes || []).filter(s => s.name !== 'cursor');
    shapes.push({ name: 'cursor', type: 'line', x0: d, x1: d, y0: 0, y1: 1, yref: 'paper',
                  line: { color: INK, width: 1, dash: 'dot' } });
    Plotly.relayout(p, { shapes });
  });
}
range.addEventListener('input', () => { CUR = +range.value; renderInspector(); });
pick.addEventListener('change', () => pick.value && showDate(pick.value));
$('#insp-back').addEventListener('click', () => { CUR = Math.max(0, CUR - 1); renderInspector(); });
$('#insp-fwd').addEventListener('click', () => { CUR = Math.min(DATES.length - 1, CUR + 1); renderInspector(); });
$('#insp-prev').addEventListener('click', () => {
  const t = tradeDates().filter(x => x < DATES[CUR]); if (t.length) showDate(t[t.length - 1]);
});
$('#insp-next').addEventListener('click', () => {
  const t = tradeDates().find(x => x > DATES[CUR]); if (t) showDate(t);
});

/* ══ 06 · position ══════════════════════════════════════════════════ */
const posPlot = document.getElementById('plot-pos');
function spans(Lg) {
  const out = []; let a = null;
  Lg.shares.forEach((s, i) => {
    if (s && a === null) a = i;
    if (!s && a !== null) { out.push([DATES[a], DATES[i - 1]]); a = null; }
  });
  if (a !== null) out.push([DATES[a], DATES[DATES.length - 1]]);
  return out;
}
(function position() {
  const run = W.runs.wheel, Lg = run.ledger;
  const traces = [{
    x: DATES, y: W.curves.spot, type: 'scatter', mode: 'lines', name: 'AAPL close',
    line: { color: INK, width: 1.4 }, hovertemplate: '%{y:$,.2f}<extra>AAPL</extra>',
  }, {
    x: DATES, y: Lg.basis, type: 'scatter', mode: 'lines', name: 'cost basis of the shares',
    line: { color: MUTED, width: 1.6, dash: 'dash' }, connectgaps: false,
    hovertemplate: 'basis %{y:$,.2f}<extra></extra>',
  }];
  const seen = {};
  run.shorts.forEach(s => {
    const g = s.right;
    traces.push({
      x: [s.opened, s.closed || M.end], y: [s.strike, s.strike], type: 'scatter', mode: 'lines',
      name: g === 'P' ? 'put sold (strike)' : 'call sold (strike)', legendgroup: g, showlegend: !seen[g],
      line: { color: g === 'P' ? PUT : STOCK, width: 3 },
      hovertemplate: `${s.qty} × ${contract(s.right, s.strike, s.expiry)}, delta ${num(s.delta)}<br>` +
        `sold ${money(s.premium)} · ${s.outcome.toLowerCase()}${s.closed ? ' ' + s.closed : ''}` +
        ` · ${signed(s.pnl, 0)}<extra></extra>`,
    });
    seen[g] = true;
  });
  const ev = (want, name, symbol) => {
    const t = run.trades.filter(want);
    return { x: t.map(x => x.date), y: t.map(x => x.price), type: 'scatter', mode: 'markers', name,
      marker: { symbol, size: 10, color: CARD, line: { color: INK, width: 2 } },
      hovertemplate: t.map(x => `${x.date}: ${esc(x.note)}<extra>${name}</extra>`) };
  };
  traces.push(ev(t => t.rule === 'ASSIGNMENT', 'put assigned: shares bought', 'triangle-up'));
  traces.push(ev(t => t.rule === 'CALLED AWAY', 'called away: shares sold', 'triangle-down'));
  Plotly.newPlot(posPlot, traces, layout({
    hovermode: 'closest',
    legend: { orientation: 'h', y: 1.12, x: 0, font: { family: MONO, size: 11, color: INK } },
    margin: { l: 70, r: 24, t: 54, b: 42 },
    shapes: spans(Lg).map(([a, b]) => ({ type: 'rect', x0: a, x1: b, y0: 0, y1: 1, yref: 'paper',
      fillcolor: SHADE, line: { width: 0 }, layer: 'below' })),
    xaxis: axis({ rangebreaks: WEEKENDS }),
    yaxis: axis({ title: ytitle('price / strike ($)'), tickprefix: '$' }),
  }), CONFIG);
  posPlot.on('plotly_click', e => { if (e.points[0]) showDate(String(e.points[0].x).slice(0, 10), true); });
})();

function renderLots() {
  const lots = R().lots;
  $('#t-lots tbody').innerHTML = lots.map(l => `<tr class="clickable" data-date="${l.opened}">
    <td class="l">${l.opened}</td><td>${num(l.strike)}</td><td>${l.shares}</td>
    <td>${money(l.put_premium)}</td><td>${l.calls}</td><td>${money(l.calls_net)}</td>
    <td><b>${money(l.basis)}</b></td>
    <td class="l">${l.closed || `<span style="color:${FAINT}">still held</span>`}</td>
    <td>${l.closed ? num(l.exit) : `<span style="color:${FAINT}">${num(l.exit)}</span>`}</td>
    <td>${l.days}</td><td>${money(l.dividends, 0)}</td>
    <td${cls(l.pnl)}><b>${signed(l.pnl, 0)}</b></td></tr>`).join('');
}

(function shortsPlot() {
  const sh = W.runs.wheel.shorts;
  Plotly.newPlot('plot-shorts', ['P', 'C'].map(g => {
    const rows = sh.filter(s => s.right === g);
    return {
      x: rows.map(s => s.opened), y: rows.map(s => s.pnl), type: 'bar',
      name: g === 'P' ? 'puts' : 'calls', marker: { color: g === 'P' ? PUT : STOCK },
      width: 1000 * 60 * 60 * 24 * 9,
      customdata: rows.map(s => [`${s.qty} × ${contract(s.right, s.strike, s.expiry)}`,
        money(s.premium), s.outcome.toLowerCase()]),
      hovertemplate: '%{customdata[0]}<br>sold %{customdata[1]} · %{customdata[2]}<br>%{y:$,.0f}<extra></extra>',
    };
  }), layout({
    hovermode: 'closest', barmode: 'overlay',
    xaxis: axis({ type: 'date' }),
    yaxis: axis({ title: ytitle('P&L per option sold ($)'), tickformat: '$,.0f',
                  zeroline: true, zerolinecolor: INK, zerolinewidth: 1 }),
  }), CONFIG);
})();

/* ══ 07 · grid ══════════════════════════════════════════════════════ */
$('#t-grid tbody').innerHTML = W.grid.map(g => `<tr${g.headline ? ' class="hl"' : ''}>
  <td class="l">${num(g.put_delta)}</td><td class="l">${num(g.call_delta)}</td>
  <td class="l">${g.take ? 'on' : '<b>off</b>'}</td><td class="l">${g.basis_rule ? 'on' : '<b>off</b>'}</td>
  <td>${money(g.final, 0)}</td><td>${num(g.cagr_pct)}%</td><td>${num(g.vol_pct, 1)}%</td>
  <td><b>${num(g.sharpe)}</b></td><td class="neg">${pct(g.max_dd_pct, 1)}</td><td>${num(g.beta)}</td>
  <td${cls(g.option_pnl)}>${signed(g.option_pnl, 0)}</td><td>${g.n_shorts}</td>
  <td>${g.assigned_puts}</td><td>${g.called}</td>
  <td>${num(g.phase_pct.call + g.phase_pct.shares, 0)}%</td></tr>`).join('');

/* ══ 08 · checks ════════════════════════════════════════════════════ */
$('#t-look tbody').innerHTML = K.lookahead.map(x => `<tr>
  <td class="l">${x.upto}</td><td>${x.trades}</td>
  <td class="l ${x.identical ? 'ok' : 'neg'}">${x.identical ? '✓ identical' : '× DIFFERENT'}</td></tr>`).join('');

/* ══ 09 · records ═══════════════════════════════════════════════════ */
function renderShorts() {
  $('#t-shorts tbody').innerHTML = R().shorts.map(s => `<tr class="clickable" data-date="${s.opened}">
    <td class="l">${s.opened}</td><td class="l"><span class="pill ${s.right}">${s.right === 'P' ? 'PUT' : 'CALL'}</span></td>
    <td class="l">${s.expiry}</td><td>${s.qty}</td><td>${num(s.spot)}</td><td><b>${num(s.strike)}</b></td>
    <td>${pct(s.otm_pct, 1)}</td><td>${num(s.delta)}</td><td>${upct(s.iv * 100)}</td>
    <td>${money(s.premium)}</td><td style="color:${MUTED}">${s.bound ? num(s.free) : ''}</td>
    <td class="l">${s.closed || '—'}</td><td class="l"><span class="pill muted">${s.outcome}</span></td>
    <td>${money(s.exit)}</td><td>${nil(s.rv) ? '—' : upct(s.rv * 100)}</td>
    <td${cls(s.pnl)}><b>${signed(s.pnl, 0)}</b></td></tr>`).join('');
}

const FILTERS = {
  all: () => true,
  P: t => t.right === 'P', C: t => t.right === 'C',
  ROLL: t => t.rule === 'ROLL' || t.rule === 'CLOSE',
  ASSIGN: t => t.action === 'ASSIGNED' || t.rule === 'ASSIGNMENT' || t.rule === 'CALLED AWAY',
  STOCK: t => t.ric === 'AAPL.O' && t.action !== 'DIVIDEND',
  DIVIDEND: t => t.action === 'DIVIDEND',
};
let FLT = 'all';
function renderBlotter() {
  const all = R().trades, rows = all.filter(FILTERS[FLT]);
  $('#t-blotter tbody').innerHTML = rows.map(t => `<tr class="clickable" data-date="${t.date}">
    <td class="l">${t.date}</td><td class="l"><b>${t.action}</b></td>
    <td class="l">${t.right ? `${pretty(t.ric)} <span style="color:${FAINT}">${esc(t.ric)}</span>` : esc(t.ric)}</td>
    <td>${t.qty > 0 ? '+' : t.qty < 0 ? '−' : ''}${Math.abs(t.qty).toLocaleString()}</td>
    <td>${money(t.price, 3)}</td><td style="color:${MUTED}">${nil(t.mid) ? '—' : money(t.mid, 3)}</td>
    <td style="color:${MUTED}">${nil(t.half) ? '—' : money(t.half, 3)}</td>
    <td${cls(t.cash)}>${signed(t.cash)}</td><td class="l" style="color:${MUTED}">${t.rule}</td>
    <td class="note">${esc(t.note)}</td></tr>`).join('');
  setHTML('blotter-count', `${rows.length} of ${all.length} rows`);
}

let LEDV = 'month';
function ledgerIdx() {
  const Lg = L(), n = Lg.date.length;
  if (LEDV === 'all') return [...Array(n).keys()];
  if (LEDV === 'trade') { const t = new Set(tradeDates()); return [...Array(n).keys()].filter(i => t.has(Lg.date[i])); }
  const last = new Map();
  Lg.date.forEach((d, i) => last.set(d.slice(0, 7), i));
  return [...last.values()];
}
function renderLedger() {
  const Lg = L(), idx = ledgerIdx();
  $('#t-ledger tbody').innerHTML = idx.map(i => `<tr class="clickable" data-date="${Lg.date[i]}">
    <td class="l">${Lg.date[i]}</td><td>${num(Lg.spot[i])}</td>
    <td class="l" style="color:${PHASE[Lg.phase[i]][1]}">${Lg.phase[i]}</td>
    <td>${money(Lg.cash[i])}</td><td style="color:${MUTED}">${Lg.collateral[i] ? money(Lg.collateral[i], 0) : ''}</td>
    <td>${Lg.shares[i] || ''}</td><td>${nil(Lg.basis[i]) ? '' : num(Lg.basis[i])}</td>
    <td>${Lg.shares[i] ? money(Lg.stock_mv[i]) : ''}</td>
    <td class="l">${Lg.short[i] ? pretty(Lg.short[i]) : ''}</td><td>${Lg.qty[i] ? '−' + Lg.qty[i] : ''}</td>
    <td>${nil(Lg.mark[i]) ? '' : num(Lg.mark[i], 3)}</td>
    <td${cls(Lg.short_mv[i])}>${Lg.short_mv[i] ? money(Lg.short_mv[i]) : ''}</td>
    <td><b>${money(Lg.nav[i])}</b></td><td>${num(Lg.delta[i], 1)}</td>
    <td style="color:${MUTED}">${money(Lg.premium_cum[i], 0)}</td></tr>`).join('');
  setHTML('ledger-count', `${idx.length} of ${Lg.date.length} sessions`);
}

/* CSV, built from the same baked rows the tables draw */
function csv(name, head, rows) {
  const q = v => v === null || v === undefined ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v;
  const text = [head.join(','), ...rows.map(r => r.map(q).join(','))].join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
  a.download = name; document.body.appendChild(a); a.click(); a.remove();
}
$('#dl-blotter').addEventListener('click', () => {
  const H = ['date', 'action', 'ric', 'right', 'strike', 'expiry', 'qty', 'price', 'mid', 'half', 'cash', 'rule', 'note'];
  csv(`wheel-blotter-${RUN}.csv`, H, R().trades.map(t => H.map(h => t[h])));
});
$('#dl-ledger').addEventListener('click', () => {
  const Lg = L(), H = Object.keys(Lg);
  csv(`wheel-ledger-${RUN}.csv`, H, Lg.date.map((_, i) => H.map(h => Lg[h][i])));
});

document.querySelectorAll('[data-flt]').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('[data-flt]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  FLT = b.dataset.flt; renderBlotter();
}));
document.querySelectorAll('[data-led]').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('[data-led]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  LEDV = b.dataset.led; renderLedger();
}));
document.querySelectorAll('[data-run]').forEach(b => b.addEventListener('click', () => {
  RUN = b.dataset.run;
  document.querySelectorAll('[data-run]').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.run === RUN)));
  renderAll();
}));
['#t-shorts', '#t-blotter', '#t-ledger', '#t-lots'].forEach(sel =>
  $(sel).addEventListener('click', e => {
    const tr = e.target.closest('tr[data-date]'); if (tr) showDate(tr.dataset.date, true);
  }));

function renderAll() { renderShorts(); renderBlotter(); renderLedger(); renderLots(); renderInspector(); }
renderAll();

/* ══ the words: every claim below is conditioned on the baked numbers ═══ */
(function narrative() {
  const w = ST.wheel, h = ST.hold, pw = ST.putwrite, bw = ST.buywrite, ex = ST.expiry, tb = ST.tbill;
  const VS = V.summary, RC = K.recon, H = F.hourly, AF = F.at_summary;
  const better = (a, b) => a > b, lower = (a, b) => Math.abs(a) < Math.abs(b);
  const verdict = ok => ok === null ? '<span class="verdict part">PARTLY</span>'
    : ok ? '<span class="verdict yes">✓ YES</span>' : '<span class="verdict no">× NO</span>';
  const pts = v => `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(1)} pts`;
  const interestShare = RC.wheel.interest / (w.final - M.opening) * 100;

  setHTML('thesis', `<b>Thesis.</b> The wheel is always short one option against fully paid
    collateral. If AAPL options are priced above the volatility the stock goes on to realise — the
    volatility risk premium — the seller keeps the difference, and the collateral earns T-bills on
    top. So the wheel should <b>earn a steady premium with well under the stock's risk: lower
    volatility, a smaller drawdown and a higher Sharpe ratio than buying and holding AAPL</b>. It
    should <b>trail buy-and-hold on raw return</b> when the stock rallies, because every call caps the
    upside and every call-away sells the shares and waits for a put to buy them back lower.`);

  const sharpeWin = better(w.sharpe, h.sharpe);
  const RR = F.rerun, DV = F.diverge;
  const rrS = RR.map(r => r.sharpe), rrF = RR.map(r => r.final);
  const rrBelow = RR.filter(r => r.sharpe <= h.sharpe).length;
  const fragile = sharpeWin && rrBelow > 0;
  const kk = k => num(k, k % 1 ? 2 : 0);
  const cents = DV ? `${num((DV.basis - DV.mid.strike) * 100, 1)} cents` : '';
  setHTML('answer', [
    `<b>The premium was ${VS.put_gap > 0 ? '' : 'not '}there${VS.put_gap > 0 && VS.call_gap < 0
      ? ' — on the put side only' : ''}${VS.put_gap > 0 && VS.put_pnl < 0
      ? ', and on its own it did not pay' : ''}.</b> On ${VS.put_above} of ${VS.n} monthly expiries the
     0.30-delta put was priced at a higher implied volatility than AAPL then realised, by
     ${pts(VS.put_gap)} on average; the 0.30-delta call was priced ${pts(VS.call_gap)} against the
     same realised vol. Selling the put every month and holding it to expiry
     ${VS.put_pnl < 0 ? 'still lost' : 'made'} ${money(Math.abs(VS.put_pnl), 0)} per contract over the
     window${VS.put_pnl < 0 && VS.put_gap > 0 ? ` — the usual month's small edge was outweighed by the
     few months AAPL fell through the strike` : ''}; the call ${signed(VS.call_pnl, 0)}.
     ${VS.put_gap > 0 && VS.call_gap < 0 ? `That is AAPL's skew: downside insurance is sold rich,
     upside calls cheap — and the wheel spends ${num(w.phase_pct.call + w.phase_pct.shares, 0)}% of its
     time on the call side.` : ''}`,
    `<b>Where the wheel's money came from.</b> ${w.n_shorts} options sold (${w.n_puts} puts,
     ${w.n_calls} calls) for ${money(w.premium, 0)}; ${money(w.buyback, 0)} went on buying them back to
     roll, ${money(w.put_intrinsic, 0)} was the strike-over-close on the days puts were assigned and
     ${money(w.call_intrinsic, 0)} the close-over-strike on the days shares were called away — net
     ${signed(RC.wheel.option_pnl, 0)} on the options. The shares, held ${num(w.phase_pct.call +
     w.phase_pct.shares, 0)}% of the time, made ${signed(RC.wheel.stock_pnl, 0)} (much of it the
     assigned shares recovering from below their strike); dividends ${signed(RC.wheel.dividends, 0)};
     T-bill interest on the cash ${signed(RC.wheel.interest, 0)}.`,
    `<b>Return: ${w.final < h.final ? 'it trailed' : 'it beat'} buy-and-hold</b>, as the thesis
     ${w.final < h.final ? 'predicted' : 'did not predict'}. ${money(M.opening, 0)} became
     ${money(w.final, 0)} (${num(w.cagr_pct)}% a year) against ${money(h.final, 0)}
     (${num(h.cagr_pct)}%) for the shares, while AAPL rose ${num(S.stock_move_pct, 0)}%.`,
    `<b>Risk: ${lower(w.vol_pct, h.vol_pct) && lower(w.max_dd_pct, h.max_dd_pct) ? 'lower' : 'not lower on both counts'}.</b>
     Volatility ${num(w.vol_pct, 1)}% against ${num(h.vol_pct, 1)}%, worst drawdown
     ${pct(w.max_dd_pct, 1)} against ${pct(h.max_dd_pct, 1)}, beta ${num(w.beta)}.`,
    `<b>Sharpe: ${num(w.sharpe)} against ${num(h.sharpe)} — the central prediction
     ${sharpeWin ? (fragile ? 'held on the headline run' : 'held') : 'failed'}.</b> ${sharpeWin
      ? 'Per unit of risk the wheel did better than the stock.'
      : 'Per unit of risk the wheel did no better than simply owning the stock.'}`,
    `<b>The two halves on their own:</b> put-write ${num(pw.cagr_pct)}% a year, Sharpe
     ${num(pw.sharpe)}; buy-write ${num(bw.cagr_pct)}%, Sharpe ${num(bw.sharpe)}.
     ${w.sharpe > Math.max(pw.sharpe, bw.sharpe) ? `The wheel beat both, so its edge is not the
     premium — each half sells the same options on its own. It is timing: the wheel takes shares only after a
     fall (that is when puts are assigned), and because its calls may not be struck below the cost
     basis, it keeps most of the position through the rebound.` : ''} Holding every option to
     expiry instead of rolling at 50%: ${num(ex.cagr_pct)}%, Sharpe ${num(ex.sharpe)}.`,
    `<b>${fragile ? 'And the edge is fragile.' : 'The path is sensitive to cents.'}</b> Re-run with
     every fill a few cents different and the trades themselves change: across k = 0 to 1 the final
     NAV runs ${money(Math.min(...rrF), 0)} to ${money(Math.max(...rrF), 0)} and the Sharpe ratio
     ${num(Math.min(...rrS))} to ${num(Math.max(...rrS))}${rrBelow ? `, ${words(rrBelow)} of
     ${words(RR.length)} runs at or below buy-and-hold's ${num(h.sharpe)}` : `, every run still above
     buy-and-hold's ${num(h.sharpe)}`}. ${DV ? `The runs part
     on ${DV.headline.date}: the shares' basis was ${money(DV.basis, 4)}, ${cents} above the
     ${kk(DV.mid.strike)} strike, so the headline had to sell the ${kk(DV.headline.strike)} call
     instead — and the paths never rejoin.` : ''}`,
  ].map(t => `<li>${t}</li>`).join(''));

  $('#t-pred tbody').innerHTML = [
    ['AAPL options are priced above the volatility they then cover',
     `put IV − realised ${pts(VS.put_gap)}, higher in ${VS.put_above}/${VS.n} months; call ${pts(VS.call_gap)}`,
     VS.put_gap > 0 && VS.put_above > VS.n / 2],
    ['so selling puts on cash beats leaving the cash in T-bills (the put-write control)',
     `${money(pw.final, 0)} vs ${money(tb.final, 0)} · Sharpe ${num(pw.sharpe)}`, pw.final > tb.final],
    ['lower volatility and drawdown than the stock',
     `vol ${num(w.vol_pct, 1)}% vs ${num(h.vol_pct, 1)}% · drawdown ${pct(w.max_dd_pct, 1)} vs ${pct(h.max_dd_pct, 1)}`,
     lower(w.vol_pct, h.vol_pct) && lower(w.max_dd_pct, h.max_dd_pct)],
    ['a higher Sharpe ratio than buy-and-hold',
     `${num(w.sharpe)} vs ${num(h.sharpe)}${fragile ? ` · but ${num(Math.min(...rrS))} in the worst
      re-run at other fills (section 07)` : ''}`, fragile ? null : sharpeWin],
    ['but a lower total return than buy-and-hold in a rising market',
     `${money(w.final, 0)} vs ${money(h.final, 0)}`, w.final < h.final],
    ['and still better than leaving the cash in T-bills',
     `${money(w.final, 0)} vs ${money(tb.final, 0)} · Sharpe ${num(w.sharpe)} vs 0`, w.final > tb.final],
    ['rolling at 50% beats holding to expiry (the usual management advice)',
     `Sharpe ${num(w.sharpe)} vs ${num(ex.sharpe)} · CAGR ${num(w.cagr_pct)}% vs ${num(ex.cagr_pct)}%`,
     better(w.sharpe, ex.sharpe)],
  ].map(([a, b, ok]) => `<tr><td class="l" style="white-space:normal;max-width:380px">${a}</td>
     <td class="l" style="white-space:normal">${b}</td><td class="l">${verdict(ok)}</td></tr>`).join('');

  const CARDS = [
    ['final NAV', money(w.final, 0), `buy &amp; hold ${money(h.final, 0)} · T-bills ${money(tb.final, 0)}`],
    ['CAGR', `${num(w.cagr_pct)}%`, `buy &amp; hold ${num(h.cagr_pct)}%`],
    ['Sharpe', num(w.sharpe), `buy &amp; hold ${num(h.sharpe)}`],
    ['max drawdown', pct(w.max_dd_pct, 1), `buy &amp; hold ${pct(h.max_dd_pct, 1)}`],
    ['premium collected', money(w.premium, 0), `${w.n_shorts} options · net of exits ${signed(RC.wheel.option_pnl, 0)}`],
    ['assignments', `${w.assigned_puts} / ${w.called}`, `puts assigned / calls called away`],
  ];
  setHTML('cards', CARDS.map(([lab, val, hint]) =>
    `<div class="card"><div class="lab">${lab}</div><div class="val">${val}</div>` +
    `<div class="hint">${hint}</div></div>`).join(''));

  setHTML('thesis-rules', [
    ['Premium', `Options are insurance, and insurance is usually sold above its expected payout.
      If the 0.30-delta put's implied volatility exceeds what AAPL then realises, the seller earns the
      gap on average. <em>Tested directly below.</em>`],
    ['Collateral', `The cash behind a put is not idle: it earns the T-bill rate, ${num(M.rate_lo)}% at
      the start of 2022 and ${num(M.rate_hi)}% at the peak. A cash-secured put is "T-bills plus a short
      put"; the interest is a large, riskless part of the return.`],
    ['Less exposure', `A 0.30-delta put on cash carries about 30 shares of exposure per 100 secured;
      only after assignment does the wheel hold the full 100, and then a call trims it. Less exposure
      for most of the time means less volatility and shallower drawdowns.`],
    ['The cost', `Capped upside. In a strong rally the calls are assigned and the shares go at the
      strike; the next put is struck below the market. A rising stock should leave the wheel behind
      on raw return — the claim is about return per unit of risk.`],
  ].map(([t, b]) => `<div class="rule"><div class="tag">${t}</div><div class="body">${b}</div></div>`).join(''));

  setHTML('vrp-cap', `${VS.n} monthly expiries, ${V.rows[0].expiry} to ${V.rows[V.rows.length - 1].expiry}.
    Average implied ${num(VS.put_iv * 100, 1)}% (put) and ${num(VS.call_iv * 100, 1)}% (call) against
    ${num(VS.rv * 100, 1)}% realised. The put won in ${VS.put_wins} of ${VS.n} months and the call in
    ${VS.call_wins}; the worst put month, ${VS.put_worst.expiry}, lost ${money(Math.abs(VS.put_worst.put_pnl) * 100, 0)}
    a contract, and the worst call month, ${VS.call_worst.expiry}, ${money(Math.abs(VS.call_worst.call_pnl) * 100, 0)}.
    Implied vol here is Black–Scholes from the closing mid; realised is close-to-close.`);

  setHTML('fill-facts', [
    `<b>${H.n.toLocaleString()} hourly prints</b> on ${H.contracts} out-of-the-money AAPL monthlies,
     14–45 days out — the kind of contract the wheel sells — from ${H.first} to ${H.last}, the one
     year LSEG keeps hourly. It comes after the backtest window; the table below checks the
     backtest years on the daily tape.`,
    `${upct(H.pct_inside)} printed inside the quote of their own hour, ${upct(H.pct_near_mid)} within
     a quarter of the half-spread of the mid. ${upct(H.pct_at_bid)} printed at or near the bid,
     ${upct(H.pct_at_ask)} at or near the ask — the tape is roughly symmetric around the mid
     (mean ${num(H.mean_z, 2)} half-spreads).`,
    `<b>k = ${num(H.k)}</b>: the average print sits ${num(H.k * 100, 0)}% of the way from the mid
     to the far side (puts ${num(H.by_right.P.k)}, calls ${num(H.by_right.C.k)}). The book gives that
     up on every option it trades — sells at mid − ${num(M.kappa)} × half-spread, buys at mid +
     ${num(M.kappa)} ×.`,
    `<b>The book's own fills.</b> All ${AF.n} option trades were in contracts that traded that day — a
     median ${AF.median_volume.toLocaleString()} contracts, the thinnest ${AF.min_volume.toLocaleString()};
     the book's order was a median ${num(AF.median_share_pct)}% of the day's volume (largest
     ${num(AF.max_share_pct, 1)}%). On ${AF.n_reached} of ${AF.n_range} days the contract's own traded
     range reached the book's fill price. Median quoted spread at the fill: ${upct(AF.median_spread_pct)}
     of the mid.`,
  ].map(t => `<li>${t}</li>`).join(''));

  setHTML('z-cap', `Each bar's last trade against that bar's closing bid and ask. A print outside its own
    quote is a clock mismatch — the trade came minutes before the quote moved — so |z| is capped at 1
    (the far side) when k is computed; the same mismatch pushes inside prints away from the mid, so if
    anything k is too high.`);
  const D = F.daily, ks = D.by_year.map(y => y.k);
  setHTML('zyear-cap', `The same statistic on each day's last trade against the closing quote, for
    contracts at 0.15–0.45 delta, 14–45 days out. Noisier — the last trade can be well before the close —
    and k comes out ${num(Math.min(...ks))}–${num(Math.max(...ks))} by year — the same range as the hourly
    year's ${num(H.k)}. Nothing says the backtest years traded differently, so the hourly k is applied
    to all of them.`);
  const sw = F.sweep, mid = sw[0], nat = sw[sw.length - 1];
  setHTML('sweep-cap', `From the mid to the natural side the final NAV moves by
    ${money(mid.final - nat.final, 0)} and the Sharpe ratio from ${num(mid.sharpe)} to ${num(nat.sharpe)}.
    ${nil(h.sharpe) ? '' : (mid.sharpe > h.sharpe) === (nat.sharpe > h.sharpe)
      ? `The comparison with buy-and-hold (Sharpe ${num(h.sharpe)}) comes out the same way at every fill.`
      : `Whether the wheel beats buy-and-hold's Sharpe of ${num(h.sharpe)} depends on the fill.`}`);

  setHTML('perf-cap', `Every book opens with ${money(M.opening, 0)} on ${M.first_fill} and holds idle cash
    in T-bills. Sharpe and Sortino are daily excess returns over the T-bill, annualised. Beta and
    capture are against AAPL's daily price change. Buy &amp; hold buys ${h.shares} shares at the
    ${M.first_fill} close.`);

  setHTML('attr-facts', [
    `T-bill interest is ${num(interestShare, 0)}% of the wheel's gain. Without it the wheel made
     ${signed(w.final - M.opening - RC.wheel.interest, 0)} in ${num(S.years, 1)} years.`,
    `The wheel spent ${num(w.phase_pct.put, 0)}% of sessions short a put on cash,
     ${num(w.phase_pct.call, 0)}% holding shares with a call written, ${num(w.phase_pct.shares, 0)}% holding
     shares with no call it was allowed to sell, and ${num(w.phase_pct.cash, 0)}% in cash between trades.
     Average exposure ${num(w.mean_delta, 0)} share-equivalents, against ${h.shares} for buy &amp; hold.`,
    `${words(S.turns)[0].toUpperCase() + words(S.turns).slice(1)} full turns: put assigned, calls sold, shares called away — a
     median ${S.lot_days} days each, ${signed(S.lot_pnl, 0)} between them including the assigned
     put's premium and the dividends.`,
    `The basis rule lifted ${S.bound} of ${w.n_calls} calls above their 0.30-delta strike, and left the
     shares with no call at all on ${S.uncovered_days} sessions.`,
  ].map(t => `<li>${t}</li>`).join(''));

  setHTML('pos-cap', `${w.n_puts} puts and ${w.n_calls} calls. ${w.assigned_puts} puts were assigned
    (${w.outcomes.EARLY} exercises early), ${w.called} calls called away. The dashed line is the cost
    basis while shares were held: calls are never struck below it, so after a fall the calls sit far
    above the price and earn little until AAPL comes back.`);
  setHTML('lots-cap', `Turn P&amp;L = (call strike − basis) × shares + dividends, where the basis already
    nets the assigned put's premium and every call sold on the shares. The last turn, if still held, is
    marked at the ${M.end} close and excludes the open call. Click a row to open the portfolio that day.`);

  const G = W.grid, base = G.find(g => g.headline);
  const on = G.filter(g => g.take && g.basis_rule);
  const beatH = on.filter(g => g.sharpe > h.sharpe).length;
  const off = G.find(g => g.take && !g.basis_rule), noroll = G.find(g => !g.take && g.basis_rule);
  setHTML('grid-cap', `The headline row is the textbook default, fixed before the run. Across the nine
    delta pairs the Sharpe ratio runs ${num(Math.min(...on.map(g => g.sharpe)))} to
    ${num(Math.max(...on.map(g => g.sharpe)))}; ${beatH === 0 ? 'none' : beatH === 9 ? 'all nine' : words(beatH)}
    beat${beatH === 1 ? 's' : ''} buy-and-hold's ${num(h.sharpe)}. Dropping the basis rule moves the
    headline from ${num(base.sharpe)} to ${num(off.sharpe)}; dropping the 50% roll, to
    ${num(noroll.sharpe)}. None of these rows were used to choose the headline.`);

  $('#t-rerun tbody').innerHTML = RR.map(r => `<tr${r.headline ? ' class="hl"' : ''}>
    <td class="l">${num(r.kappa)}${r.headline ? ' (headline)' : ''}</td><td>${money(r.final, 0)}</td>
    <td>${num(r.cagr_pct)}%</td><td><b>${num(r.sharpe)}</b></td><td class="neg">${pct(r.max_dd_pct, 1)}</td>
    <td>${r.n_shorts}</td><td>${r.assigned_puts} / ${r.called}</td></tr>`).join('');
  const sw0 = F.sweep;
  setHTML('rerun-facts', [
    `Section 03 re-priced the headline's own trades at other fills: the final NAV moved by only
     ${money(sw0[0].final - sw0[sw0.length - 1].final, 0)} from mid to natural. Here the rule is
     re-run from scratch instead, so a different fill can change a decision.`,
    `It does, because two rules compare prices with thresholds: the 50% profit-take is measured
     against the premium actually received, and the call floor is the cost basis built from fills.
     ${DV ? `On ${DV.headline.date} the headline's basis was ${money(DV.basis, 4)}, ${cents} over the
     ${kk(DV.mid.strike)} strike; at mid fills the premiums were a few cents larger, the basis sat just
     under it, so that run sold the ${kk(DV.mid.strike)} call and the headline the
     ${kk(DV.headline.strike)}. Everything after differs.` : ''}`,
    `So read the headline as one draw from a spread of nearly identical strategies:
     Sharpe ${num(Math.min(...rrS))}–${num(Math.max(...rrS))}, final NAV
     ${money(Math.min(...rrF), 0)}–${money(Math.max(...rrF), 0)}, against buy-and-hold's
     ${num(h.sharpe)} and ${money(h.final, 0)}.`,
  ].map(x => `<li>${x}</li>`).join(''));

  const D2 = K.delta, req = M.chain.reduce((s, c) => s + c.requested, 0),
        res = M.chain.reduce((s, c) => s + c.resolved, 0);
  setHTML('checks-list', [
    `<b>Accounting.</b> Two independent routes to the same NAV. Cash: opening + every blotter cash
     flow + interest equals the ledger's cash (gap ${money(RC.wheel.cash_gap)}). P&amp;L: options +
     shares + dividends + interest equals NAV − opening (gap ${money(RC.wheel.pnl_gap)}). The same
     holds for every control (largest gap ${money(Math.max(...Object.values(RC).map(r =>
       Math.max(Math.abs(r.cash_gap), Math.abs(r.pnl_gap)))))}).`,
    `<b>Never borrowed.</b> The lowest cash balance, after securing every put, was
     ${money(w.min_cash, 0)}.`,
    `<b>Delta.</b> Our Black–Scholes delta against LSEG's DELTA field: median gap
     ${num(D2.P.median_abs, 4)} on ${D2.P.n.toLocaleString()} put quotes and ${num(D2.C.median_abs, 4)} on
     ${D2.C.n.toLocaleString()} call quotes; ${num(D2.P.near_030, 4)} / ${num(D2.C.near_030, 4)} near
     0.30. LSEG's field is blank on ${D2.lseg_missing.toLocaleString()} tradeable quotes.`,
    `<b>Mid.</b> (BID + ASK) / 2 equals LSEG's MID_PRICE on every row (largest gap
     ${num(D2.mid_vs_mid_price, 4)}).`,
    `<b>Stale marks.</b> ${K.carried.stale} of ${K.carried.held.toLocaleString()} held-option sessions had
     no two-sided close and carried the previous mid. Fills never use a stale quote.`,
    `<b>Pull.</b> ${res.toLocaleString()} of ${req.toLocaleString()} constructed RICs resolved; the rest
     are strikes that never listed. ${K.bands.put_at_bottom.length + K.bands.call_at_top.length === 0
      ? 'No chosen strike sits on the edge of what was pulled, so the band never limited the rule.'
      : 'Picks on the band edge: ' + esc(K.bands.put_at_bottom.concat(K.bands.call_at_top).join(', '))}`,
  ].map(t => `<li>${t}</li>`).join(''));

  setHTML('not-modelled', `<b>Not modelled.</b> Commissions — at $0.65 a contract the wheel's
    ${w.contracts.toLocaleString()} contracts traded would cost about ${money(w.contracts * 0.65, 0)}, and
    assignment fees vary by broker. Taxes, which treat short-option gains and assignments very
    differently from a long-held stock. Early exercise for reasons other than the two rules above, and
    pin risk at expiry. Intraday fills: every trade is at a daily close, so a stock that gaps between
    the decision close and the fill close moves the price paid (the decide-then-fill lag is the honest
    cost of daily data). And the choice of AAPL — a deep options market, but one stock that rose
    ${num(S.stock_move_pct, 0)}% in the window; the comparison between books on the same tape is the
    fair test, not the level.`);

  setHTML('next-list', [
    `<b>Other underlyings and a flat market.</b> One stock in one window is one observation. The wheel
     is built for sideways markets; this window was a bear year followed by a long rally.`,
    `<b>Drop the basis rule.</b> "Never sell below cost" is anchoring on a sunk price; section 07 shows
     what it costs here. A wheel that sells the 0.30-delta call whatever the basis is a buy-write with a
     put entry.`,
    `<b>Stand down over earnings.</b> Every monthly option spans at most one report; skipping the cycle
     that contains one is the obvious event filter to test.`,
    `<b>Intraday fills.</b> The year of hourly data used for k could also run the book itself at a
     fixed hour, as 1.2 did, removing the close-to-close lag on the trades that year.`,
  ].map(t => `<li>${t}</li>`).join(''));

  const timing = w.sharpe > Math.max(pw.sharpe, bw.sharpe);
  setHTML('rec', `<b>Verdict.</b> ${sharpeWin
    ? `On this tape the thesis held${fragile ? ', narrowly' : ''}: the wheel took
       ${num(w.vol_pct / h.vol_pct * 100, 0)}% of the stock's volatility and a smaller drawdown, and
       earned more per unit of risk (Sharpe ${num(w.sharpe)} vs ${num(h.sharpe)})${w.final < h.final
         ? `, giving up ${money(h.final - w.final, 0)} of return to the rally.`
         : `, and on this window it also returned more (${money(w.final, 0)} vs ${money(h.final, 0)}).`}
       ${timing ? `But not for the reason the thesis gave. Selling puts on cash alone
       (${num(pw.cagr_pct)}% a year) and calls on shares alone (${num(bw.cagr_pct)}%) ${
       pw.cagr_pct < tb.cagr_pct && bw.cagr_pct < tb.cagr_pct ? `both trailed T-bills (${num(tb.cagr_pct)}%)`
       : 'did far worse'}; the wheel's edge came from when it held stock — bought by assignment
       after falls, kept through the rebounds by the cost-basis rule. That is a timing effect on one
       stock's path, and section 07 shows it is sensitive to the rule's details.` : ''}
       ${fragile ? `But the margin rests on one stock's path and a rule with knife edges: the same
       wheel with fills a few cents different lands between Sharpe ${num(Math.min(...rrS))} and
       ${num(Math.max(...rrS))}. The robust findings are the risk reduction, the role of the T-bill
       interest, and that AAPL's premium is in the puts, not the calls; "beats buy-and-hold on a
       risk-adjusted basis" is supported here, not proven.` : ''}`
    : `On this tape the thesis failed where it mattered: the wheel took less risk than the stock but did
       not earn more per unit of it (Sharpe ${num(w.sharpe)} vs ${num(h.sharpe)}), and gave up
       ${money(Math.max(0, h.final - w.final), 0)} of return.`}
    `);

  setHTML('foot', `${M.ticker} wheel · ${w.n_shorts} options sold · ${w.n_trades} trades ·
    ${M.sessions} sessions · k = ${num(M.kappa)} · look-ahead test
    ${K.lookahead.every(x => x.identical) ? 'passed' : 'FAILED'} at ${K.lookahead.length} cut dates`);
})();
