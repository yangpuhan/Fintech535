/* Draws the page from window.BOOK. No calculation lives here — every number
   on screen was computed in covered_call/book.py and baked into book.js.
   The one exception is the y = a + bx line in section 06, which is evaluated
   from the slope and intercept the fit already reported. */
'use strict';

const B = window.BOOK;
const CSS = getComputedStyle(document.documentElement);
const C = n => CSS.getPropertyValue(n).trim();

const INK = C('--ink'), MUTED = C('--muted'), FAINT = C('--faint');
const RULE = C('--rule'), CARD = C('--card'), PAPER = C('--paper');
const NAVC = C('--s-nav'), REQ = C('--s-req'), AVAIL = C('--s-avail'), QUOTE = C('--s-quote');
const SERIF = "'Source Serif 4', Georgia, serif";
const MONO = "'Source Code Pro', Menlo, monospace";

/* ── formatting ─────────────────────────────────────────────────────── */
const money = (v, d = 2) => v === null || v === undefined ? '—' :
  (v < 0 ? '−$' : '$') + Math.abs(v).toLocaleString('en-US',
    { minimumFractionDigits: d, maximumFractionDigits: d });
const signed = (v, d = 2) => v === null || v === undefined ? '—' :
  (v < 0 ? '−$' : '+$') + Math.abs(v).toLocaleString('en-US',
    { minimumFractionDigits: d, maximumFractionDigits: d });
const num = (v, d = 2) => v === null || v === undefined ? '—' :
  v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v, d = 2) => v === null || v === undefined ? '—' :
  (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d) + '%';
const cls = v => v < 0 ? ' class="neg"' : v > 0 ? ' class="pos"' : '';
const hhmm = t => t.slice(0, 16);
const dmy = t => t.slice(0, 10);
const esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

/* ── shared Plotly furniture ────────────────────────────────────────── */
const CONFIG = { responsive: true, displaylogo: false, displayModeBar: 'hover',
                 modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'] };

/* Hide the hours and weekends the market is shut, so an hourly series reads
   as one continuous line instead of 49 islands. */
const TRADING_HOURS = [
  { pattern: 'hour', bounds: [20, 13] },
  { pattern: 'day of week', bounds: ['sat', 'mon'] },
];

function layout(o = {}) {
  return Object.assign({
    paper_bgcolor: CARD, plot_bgcolor: CARD,
    font: { family: SERIF, size: 13, color: INK },
    margin: { l: 66, r: 22, t: 34, b: 42 },
    hovermode: 'x unified',
    hoverlabel: { bgcolor: CARD, bordercolor: RULE, font: { family: MONO, size: 12, color: INK } },
    legend: { orientation: 'h', y: 1.1, x: 0, font: { family: MONO, size: 11 },
              bgcolor: 'rgba(0,0,0,0)' },
    xaxis: axis(), yaxis: axis(),
  }, o);
}
function axis(o = {}) {
  return Object.assign({
    gridcolor: RULE, linecolor: RULE, zeroline: false,
    tickfont: { family: MONO, size: 11, color: MUTED },
    title: { font: { family: SERIF, size: 12, color: INK } },
  }, o);
}

/* ══ masthead, cards, write-up numbers ═══════════════════════════════ */
const S = B.stats, M = B.meta;

document.getElementById('prov').innerHTML =
  `${M.ticker} · ${M.stock_ric} · ${M.interval} bars · ${M.n_bars} bars over ` +
  `${M.n_sessions} sessions, ${dmy(M.first_bar)} → ${dmy(M.last_bar)}<br>` +
  `LSEG pull cached ${M.fetched_at} · ${M.n_contracts} expired call contracts · ` +
  `${M.n_option_bars.toLocaleString()} option bars · orders stamped at ` +
  `${String(M.order_hour_utc).padStart(2, '0')}:00 UTC`;

const CARDS = [
  ['final NAV', money(S.final_nav), `from ${money(S.opening_cash, 0)} opening cash`, INK, true],
  ['strategy P&amp;L', signed(S.pnl), `${pct(S.ret_pct)} over ${S.weeks_traded} weeks`,
    S.pnl < 0 ? REQ : AVAIL, true],
  ['vs. buy &amp; hold', signed(S.vs_bh), `same bar, same money: ${pct(S.bh_ret_pct)}`,
    S.vs_bh < 0 ? REQ : AVAIL, true],
  ['assigned', `${S.n_assigned} / ${S.weeks_traded}`, `${S.n_expired} expired worthless`, REQ, false],
  ['premium collected', money(S.premium_total, 0), `${money(S.premium_mean, 0)} a week`, QUOTE, false],
  ['handed back', money(S.intrinsic_paid, 0), 'intrinsic value on assignment', REQ, false],
  ['max drawdown', pct(S.max_drawdown), 'peak-to-trough on NAV', INK, false],
  ['min available funds', money(S.min_available), `${dmy(S.min_available_ts)} · never negative`,
    AVAIL, false],
];
document.getElementById('cards').innerHTML = CARDS.map(([lab, val, hint, col, hero]) =>
  `<div class="card${hero ? ' hero' : ''}"><div class="lab">${lab}</div>` +
  `<div class="val" style="color:${col}">${val}</div><div class="hint">${hint}</div></div>`
).join('');

document.getElementById('skipnote').innerHTML = B.skipped.length === 0
  ? `<b>No week was skipped.</b> All ${S.weeks_total} expiry weeks in the window had a
     two-sided quote on an out-of-the-money strike at the order bar, so the
     no-bid/no-ask branch never fired. On a thinner name it would be the rule that
     decides most of the outcome — in Assignment 1.1, 63% of the listed UUUU grid never
     traded at all.`
  : `<b>${B.skipped.length} week(s) skipped.</b> ` + B.skipped.map(s =>
      `${s.entry}: ${s.why} (spot ${num(s.spot)})`).join(' · ');

const setText = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
setText('cap-otm', `${num(S.mean_otm_pct)}%`);
setText('cap-otm-max', `${num(S.max_otm_pct)}%`);
setText('cap-lmv', money(S.max_initial * 2, 0));
setText('cap-outside', `${(100 - B.fit.pct_inside).toFixed(1)}%`);
setText('a-otm', `${num(S.mean_otm_pct)}%`);
setText('a-prem', money(S.premium_total, 0));
setText('a-intr', money(S.intrinsic_paid, 0));
setText('a-callpnl', money(Math.abs(S.call_pnl), 0));
setText('a-stockpnl', money(S.stock_pnl, 0));
setText('a-ret', pct(S.ret_pct));
setText('a-lmv', money(S.max_initial * 2, 0));
setText('a-open', money(S.opening_cash, 0));
setText('a-lev', `${(S.max_initial * 2 / S.opening_cash).toFixed(2)}×`);
setText('a-vsbh', money(Math.abs(S.vs_bh)));
setText('a-debit', money(S.debit_mean, 0));
setText('a-days', `${S.debit_days} days`);
setText('a-rate', `${num(S.debit_rate_pct, 1)}%`);
setText('a-int', money(S.debit_interest, 0));
setText('a-intpct', `${(S.debit_interest / S.pnl * 100).toFixed(0)}%`);
setText('foot', `${M.ticker} covered call · ${S.weeks_traded} weekly expiries · ` +
  `${S.n_blotter} booked trades · ${S.n_bars} ledger bars · ` +
  `week attribution reconciles to NAV within ${money(Math.abs(S.attribution_gap))}`);

document.getElementById('a-headline').innerHTML =
  `The book ended at <b>${money(S.final_nav)}</b> on <b>${money(S.opening_cash, 0)}</b>
   of opening cash — <b>${signed(S.pnl)}</b>, ${pct(S.ret_pct)} over ten weeks, with a
   ${pct(S.max_drawdown)} drawdown along the way. Buying the same 100 shares on the same
   bar and doing nothing else returned <b>${signed(S.bh_pnl)}</b>. Writing a call against
   them every week, collecting ${money(S.premium_total, 0)} of premium for the trouble,
   <b>cost ${money(Math.abs(S.vs_bh))}</b>. That is not a bug in the implementation; it is
   what the structure does to a stock that rises ${pct((S.bh_last / S.bh_first - 1) * 100, 1)}
   in ten weeks.`;

/* ══ 02 · stock and strikes ══════════════════════════════════════════ */
(function strikes() {
  const traces = [{
    x: B.stock.ts, y: B.stock.px, type: 'scatter', mode: 'lines',
    name: `${M.ticker} print`, line: { color: INK, width: 1.6 },
    hovertemplate: '%{y:$,.2f}<extra>AAPL</extra>',
  }];
  let seenA = false, seenE = false;
  B.weeks.forEach(w => {
    const end = B.stock.ts.filter(t => t.slice(0, 10) === w.expiry).pop() || w.entry_ts;
    const on = w.outcome === 'ASSIGNED';
    const col = on ? REQ : AVAIL;
    const first = on ? !seenA : !seenE;
    if (on) seenA = true; else seenE = true;
    traces.push({
      x: [w.entry_ts, end], y: [w.strike, w.strike],
      type: 'scatter', mode: 'lines',
      name: on ? 'strike · assigned' : 'strike · expired',
      legendgroup: w.outcome, showlegend: first,
      line: { color: col, width: 2.5, dash: on ? 'solid' : 'dot' },
      hovertemplate: `short ${num(w.strike)} call<br>` +
        `premium ${money(w.premium, 2)}<br>settle ${money(w.settle)}` +
        `<extra>${w.outcome.toLowerCase()}</extra>`,
    });
  });
  traces.push({
    x: B.weeks.map(w => w.entry_ts), y: B.weeks.map(w => w.spot),
    type: 'scatter', mode: 'markers', name: 'order bar',
    marker: { color: NAVC, size: 9, symbol: 'circle',
              line: { color: CARD, width: 2 } },
    hovertemplate: 'entry · spot %{y:$,.2f}<extra></extra>',
  });
  /* The one week the rule sold into an event it could not see. */
  const ev = M.earnings, evx = '2026-07-30 19:00:00';
  Plotly.newPlot('plot-strikes', traces, layout({
    hovermode: 'closest',
    shapes: ev ? [{ type: 'line', x0: evx, x1: evx, y0: 0, y1: 1, yref: 'paper',
                    line: { color: MUTED, width: 1.2, dash: 'dot' } }] : [],
    annotations: ev ? [{ x: evx, y: 1, yref: 'paper', yanchor: 'bottom',
                         text: 'earnings, after the close', showarrow: false,
                         xanchor: 'right', xshift: -4,
                         font: { family: MONO, size: 10, color: MUTED } }] : [],
    xaxis: axis({ rangebreaks: TRADING_HOURS }),
    yaxis: axis({ title: { text: 'price ($)', font: { family: SERIF, size: 12, color: INK } },
                  tickprefix: '$' }),
  }), CONFIG);
})();

/* ══ 03 · NAV and Reg T ═════════════════════════════════════════════ */
(function nav() {
  const L = B.ledger, x = L.map(r => r.ts);
  const line = (key, name, color, dash, width) => ({
    x, y: L.map(r => r[key]), type: 'scatter', mode: 'lines', name,
    line: { color, width: width || 2, dash, shape: 'hv' },
    hovertemplate: '%{y:$,.0f}<extra>' + name + '</extra>',
  });
  const traces = [
    line('nav', 'NAV', NAVC, 'solid', 2.2),
    line('initial', 'initial requirement (50%)', REQ, 'dash'),
    line('maint', 'maintenance (25%)', REQ, 'dot'),
    line('available', 'available funds', AVAIL, 'solid'),
  ];
  // event ticks along the bottom, so the chart and the blotter line up
  traces.push({
    x: B.blotter.map(b => b.ts),
    y: B.blotter.map(() => 0),
    type: 'scatter', mode: 'markers', name: 'blotter event',
    marker: { symbol: 'line-ns-open', size: 11, color: MUTED,
              line: { width: 1.4, color: MUTED } },
    hoverinfo: 'skip', showlegend: true,
  });

  /* Direct-label each line at the last bar the book was still long. On the
     very last bar the position is flat, so initial and maintenance are both
     zero and available equals NAV — four labels stacked on two points. */
  let li = L.length - 1;
  while (li > 0 && L[li].shares === 0) li--;
  const ann = [['nav', 'NAV', NAVC], ['initial', 'initial', REQ],
               ['maint', 'maint', REQ], ['available', 'available', AVAIL]]
    .map(([k, text, color]) => ({
      x: x[li], y: L[li][k], xref: 'x', yref: 'y', text,
      font: { family: MONO, size: 10.5, color },
      xanchor: 'left', xshift: 8, showarrow: false,
    }));

  Plotly.newPlot('plot-nav', traces, layout({
    margin: { l: 70, r: 82, t: 34, b: 42 },
    annotations: ann,
    xaxis: axis({ rangebreaks: TRADING_HOURS, showspikes: true,
                  spikecolor: FAINT, spikethickness: 1, spikedash: 'dot',
                  spikemode: 'across' }),
    yaxis: axis({ title: { text: 'dollars', font: { family: SERIF, size: 12, color: INK } },
                  tickprefix: '$', rangemode: 'tozero' }),
  }), CONFIG);
})();

/* worked bar — the bar where Reg T bound hardest */
(function worked() {
  const r = B.ledger.find(x => x.available === S.min_available) || B.ledger[B.ledger.length - 1];
  const row = (k, v, strong) => `<span style="color:${MUTED}">${k}</span> ` +
    `<span style="float:right${strong ? ';font-weight:700' : ''}">${v}</span><br>`;
  document.getElementById('worked').innerHTML =
    `<div style="color:${MUTED};font-size:11px;letter-spacing:.06em;margin-bottom:8px">` +
    `${hhmm(r.ts)} UTC · TIGHTEST BAR OF THE RUN</div>` +
    row('shares', `${r.shares} @ ${money(r.stock_mark)}`) +
    row('short call', r.call ? `${num(r.strike)} · ${money(r.call_mark, 3)}` : 'none') +
    row('cash', money(r.cash)) +
    row('stock MV', money(r.stock_mv)) +
    row('option MV', money(r.option_mv)) +
    `<hr style="border:none;border-top:1px solid ${RULE};margin:7px 0">` +
    row('NAV', money(r.nav), true) +
    row('initial (50%)', money(r.initial)) +
    row('maintenance (25%)', money(r.maint)) +
    `<hr style="border:none;border-top:1px solid ${RULE};margin:7px 0">` +
    `<span style="color:${MUTED}">available funds</span>` +
    `<span style="float:right;font-weight:700;color:${AVAIL}">${money(r.available)}</span><br>` +
    `<span style="color:${MUTED}">excess liquidity</span>` +
    `<span style="float:right">${money(r.excess)}</span>`;

  document.getElementById('marginnote').innerHTML =
    `<b>Available funds never went negative.</b> The tightest bar left
     ${money(S.min_available)} of room, so every trade in the blotter was one this
     account could actually have put on. Running the same book backwards, the smallest
     opening balance that clears Reg T on every bar is
     <b>${money(S.min_opening_cash)}</b> — ${money(S.opening_cash, 0)} is the nearest
     round number above it, which is how the opening cash was chosen rather than picked
     to flatter the return. The account carries a debit the whole time it is long,
     peaking at ${money(Math.abs(S.cash_min), 0)}; Reg T permits that (50% of
     ${money(S.max_initial * 2, 0)} of stock), and this book does not charge itself
     interest on it. See section 07.`;
})();

/* ══ 04 · blotter and weeks ═════════════════════════════════════════ */
function renderBlotter(filter) {
  const rows = B.blotter.filter(b =>
    filter === 'all' ? true :
    filter === 'AAPL.O' ? b.instrument === M.stock_ric :
    filter === 'opt' ? b.instrument !== M.stock_ric :
    b.side === filter);
  document.querySelector('#t-blotter tbody').innerHTML = rows.map(b => `<tr>
    <td class="l">${hhmm(b.ts)}</td>
    <td class="l">${esc(b.instrument)}</td>
    <td class="l side side-${b.side}">${b.side}</td>
    <td>${b.qty}</td>
    <td>${b.limit === null ? '—' : money(b.limit)}</td>
    <td>${money(b.fill)}</td>
    <td${cls(b.cash_delta)}>${b.cash_delta === 0 ? money(0) : signed(b.cash_delta)}</td>
    <td>${money(b.cash_after)}</td>
    <td class="l" style="color:${MUTED}">${esc(b.rule)}</td>
    <td class="note">${esc(b.note)}</td></tr>`).join('');
  document.getElementById('blotter-count').textContent =
    `${rows.length} of ${B.blotter.length} booked trades`;
}
document.querySelectorAll('[data-flt]').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('[data-flt]').forEach(b =>
    b.setAttribute('aria-pressed', String(b === btn)));
  renderBlotter(btn.dataset.flt);
}));
renderBlotter('all');

document.querySelector('#t-weeks tbody').innerHTML = B.weeks.map(w => `<tr>
  <td class="l">${w.entry}${w.bought ? '' :
    ` <span style="color:${FAINT}">carry</span>`}</td>
  <td class="l">${w.expiry}</td>
  <td>${num(w.spot)}</td>
  <td><b>${num(w.strike)}</b></td>
  <td style="color:${MUTED}">${num(w.otm_pct)}%</td>
  <td>${num(w.bid)}</td><td>${num(w.ask)}</td><td><b>${num(w.mid)}</b></td>
  <td class="pos">${signed(w.premium)}</td>
  <td>${num(w.open_mark)}</td>
  <td>${num(w.settle)}</td>
  <td class="l"><span class="pill pill-${w.outcome}">${w.outcome}</span></td>
  <td${cls(w.stock_pnl)}>${signed(w.stock_pnl)}</td>
  <td style="color:${MUTED}">${w.intrinsic ? money(w.intrinsic) : '—'}</td>
  <td${cls(w.call_pnl)}>${signed(w.call_pnl)}</td>
  <td${cls(w.week_pnl)}><b>${signed(w.week_pnl)}</b></td></tr>`).join('');

document.getElementById('weekcap').innerHTML =
  `<b>“carry”</b> marks a week that opened already long, because the previous Friday's
   call expired worthless — no stock was bought and the basis carried, so that week is
   marked from the previous settle rather than from a purchase. That is what keeps the
   week column from charging the same move twice: the ten weeks sum to
   ${signed(B.weeks.reduce((a, w) => a + w.week_pnl, 0))}, against an actual NAV change
   of ${signed(S.pnl)}.`;

/* ══ 05 · ledger ════════════════════════════════════════════════════ */
function renderLedger(view) {
  let rows = B.ledger;
  if (view === 'day') {
    const last = new Map();
    B.ledger.forEach(r => last.set(r.ts.slice(0, 10), r));
    rows = [...last.values()];
  } else if (view === 'open') {
    rows = B.ledger.filter(r => r.call !== null);
  }
  document.querySelector('#t-ledger tbody').innerHTML = rows.map(r => `<tr>
    <td class="l">${hhmm(r.ts)}</td>
    <td>${r.shares}</td>
    <td>${num(r.stock_mark)}</td>
    <td class="l" style="color:${r.call ? INK : FAINT}">${r.call
      ? `${num(r.strike)}C ${r.expiry.slice(5)}` : '—'}</td>
    <td>${r.call_mark === null ? '—' : num(r.call_mark, 3)}</td>
    <td${cls(r.cash)}>${money(r.cash)}</td>
    <td>${money(r.stock_mv)}</td>
    <td${cls(r.option_mv)}>${money(r.option_mv)}</td>
    <td><b>${money(r.nav)}</b></td>
    <td>${money(r.lmv)}</td>
    <td>${money(r.initial)}</td>
    <td>${money(r.maint)}</td>
    <td${cls(r.available)}>${money(r.available)}</td>
    <td>${money(r.excess)}</td></tr>`).join('');
  document.getElementById('ledger-count').textContent =
    `${rows.length} of ${B.ledger.length} hourly bars`;
}
document.querySelectorAll('[data-led]').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('[data-led]').forEach(b =>
    b.setAttribute('aria-pressed', String(b === btn)));
  renderLedger(btn.dataset.led);
}));
renderLedger('day');

/* ══ 06 · mid vs print ══════════════════════════════════════════════ */
(function scatter() {
  const F = B.fit, P = F.points;
  const lo = 0.01, hi = Math.max(...P.map(p => p[0])) * 1.15;
  const xs = [];
  for (let i = 0; i <= 120; i++) xs.push(lo * Math.pow(hi / lo, i / 120));

  const traces = [
    { x: [lo, hi], y: [lo, hi], type: 'scatter', mode: 'lines', name: 'print = mid',
      line: { color: FAINT, width: 1.4, dash: 'dash' }, hoverinfo: 'skip' },
    /* plain SVG scatter, not scattergl: 2.5k markers render fine without
       WebGL, and a chart that shows "WebGL is not supported" to anyone with
       it disabled is not a chart. */
    { x: P.map(p => p[0]), y: P.map(p => p[1]), type: 'scatter', mode: 'markers',
      name: 'hourly bar', showlegend: false,
      marker: {
        size: 5, opacity: 0.5, color: P.map(p => p[2]),
        colorscale: [[0, NAVC], [0.5, '#CFC8BA'], [1, REQ]],
        cmin: -8, cmax: 8,
        colorbar: { title: { text: 'moneyness %', font: { family: SERIF, size: 11 } },
                    thickness: 9, len: 0.55, y: 0.28, outlinewidth: 0,
                    tickfont: { family: MONO, size: 10, color: MUTED } },
      },
      hovertemplate: 'mid %{x:$,.2f}<br>print %{y:$,.2f}<extra></extra>' },
    { x: xs, y: xs.map(v => F.overall.intercept + F.overall.slope * v),
      type: 'scatter', mode: 'lines', name: 'OLS fit',
      line: { color: INK, width: 2 }, hoverinfo: 'skip' },
  ];
  Plotly.newPlot('plot-scatter', traces, layout({
    hovermode: 'closest',
    title: { text: `TRDPRC_1 against mid · R² = ${F.overall.r2}`, x: 0, xanchor: 'left',
             font: { family: SERIF, size: 15, color: INK } },
    margin: { l: 66, r: 22, t: 46, b: 48 },
    /* inside the plot, top-left: on a y ≈ x scatter that corner is the only
       reliably empty one, and it keeps the legend off the title */
    legend: { x: 0.02, y: 0.98, xanchor: 'left', yanchor: 'top',
              bgcolor: 'rgba(255,255,255,0.88)', bordercolor: RULE, borderwidth: 1,
              font: { family: MONO, size: 11 } },
    xaxis: axis({ type: 'log', title: { text: 'mid = (BID+ASK)/2 ($)',
                  font: { family: SERIF, size: 12, color: INK } }, tickprefix: '$' }),
    yaxis: axis({ type: 'log', title: { text: 'TRDPRC_1 ($)',
                  font: { family: SERIF, size: 12, color: INK } }, tickprefix: '$' }),
  }), CONFIG);

  document.getElementById('fitcap').innerHTML =
    `<b>TRDPRC_1 = ${F.overall.intercept >= 0 ? '' : '−'}${Math.abs(F.overall.intercept).toFixed(4)}
     + ${F.overall.slope.toFixed(4)} × mid</b>, R² = <b>${F.overall.r2}</b> on
     ${F.n_pairs.toLocaleString()} hourly bars across ${F.n_contracts} contracts where
     both a two-sided quote and a print exist. Near the money (within 2%, the band this
     book writes in) R² = ${F.cuts.near.r2} on ${F.cuts.near.n.toLocaleString()} bars,
     slope ${F.cuts.near.slope}.<br>
     Axes are logarithmic so the penny wings are visible next to the $${F.overall.x_hi}
     in-the-money calls; the fitted line is the linear fit drawn on log axes, which is
     why it bends. Colour is moneyness — <span style="color:${REQ}">red in the
     money</span>, <span style="color:${NAVC}">blue out</span>. The dashed
     <em>print = mid</em> reference is under the fitted line and invisible at this
     scale: that is the result, not a missing trace.`;
})();

(function resid() {
  const H = B.fit.resid_hist;
  Plotly.newPlot('plot-resid', [{
    x: H.centres, y: H.counts, type: 'bar', name: 'hourly bars',
    marker: { color: QUOTE, line: { color: CARD, width: 1 } },
    hovertemplate: '%{y:,} bars<br>%{x} half-spreads<extra></extra>',
  }], layout({
    hovermode: 'closest', bargap: 0.08, showlegend: false,
    title: { text: 'Where the print landed inside its quote', x: 0, xanchor: 'left',
             font: { family: SERIF, size: 15, color: INK } },
    margin: { l: 66, r: 22, t: 54, b: 48 },
    shapes: [-1, 0, 1].map(v => ({
      type: 'line', x0: v, x1: v, y0: 0, y1: 1, yref: 'paper',
      line: { color: v === 0 ? INK : FAINT, width: v === 0 ? 1.6 : 1, dash: 'dot' },
    })),
    annotations: [[-1, 'bid'], [0, 'mid'], [1, 'ask']].map(([v, t]) => ({
      x: v, y: 1.0, yref: 'paper', text: t, showarrow: false,
      font: { family: MONO, size: 10.5, color: v === 0 ? INK : MUTED },
      yanchor: 'bottom',
    })),
    xaxis: axis({ title: { text: '(print − mid) ÷ half-spread',
                  font: { family: SERIF, size: 12, color: INK } },
                  range: [-1.6, 1.6] }),
    yaxis: axis({ title: { text: 'hourly bars', font: { family: SERIF, size: 12, color: INK } } }),
  }), CONFIG);
})();

document.querySelector('#t-orders tbody').innerHTML = B.order_bars.map(o => `<tr>
  <td class="l">${o.entry}</td>
  <td><b>${num(o.strike)}</b></td>
  <td>${num(o.bid)}</td><td>${num(o.ask)}</td>
  <td><b>${num(o.mid)}</b></td>
  <td>${o.trade === null ? '<span class="neg">no print</span>' : num(o.trade)}</td>
  <td${cls(o.vs_mid)}>${o.vs_mid === null ? '—' :
    (o.vs_mid > 0 ? '+' : o.vs_mid < 0 ? '−' : '') + Math.abs(o.vs_mid).toFixed(3)}</td>
  <td>${o.volume === null ? '—' : o.volume.toLocaleString()}</td>
  <td style="color:${MUTED}">${o.moves === null ? '—' : o.moves.toLocaleString()}</td></tr>`).join('');

(function ordercap() {
  const F = B.fit, O = F.order_bar;
  document.getElementById('ordercap').innerHTML =
    `<b>${O.n_traded} of ${O.n} traded on their own order bar</b>, on volume between
     ${O.min_volume.toLocaleString()} and ${O.max_volume.toLocaleString()} contracts and
     hundreds of separate moves. Across the whole chain,
     <b>${F.pct_inside}%</b> of prints land inside their own quote, the median spread is
     ${money(F.median_spread)} (${F.median_spread_pct}% of the mid), and the median print
     sits ${F.median_z} half-spreads from the mid — unbiased. The mean leans
     ${F.mean_z} toward the offer, which for a seller is a small optimism; on this
     book's own ten orders the tape actually printed an average of
     ${money(O.mean_vs_mid, 3)} <em>above</em> the assumed fill, worth
     ${money(O.total_dollars)} in total. <b>The fill assumption is not where this
     backtest is wrong.</b>`;
})();

/* ══ 07 · attribution ═══════════════════════════════════════════════ */
(function attrib() {
  const W = B.weeks, lab = W.map(w => w.expiry.slice(5));
  const bar = (key, name, color) => ({
    x: lab, y: W.map(w => w[key]), type: 'bar', name,
    marker: { color, line: { color: CARD, width: 2 } },
    hovertemplate: '%{y:$,.0f}<extra>' + name + '</extra>',
  });
  Plotly.newPlot('plot-attrib', [
    bar('stock_pnl', 'stock leg (open → settle)', NAVC),
    bar('call_pnl', 'call leg (premium − intrinsic)', REQ),
    { x: lab, y: W.map(w => w.week_pnl), type: 'scatter', mode: 'markers',
      name: 'week total', marker: { symbol: 'diamond', size: 10, color: INK,
      line: { color: CARD, width: 1.5 } },
      hovertemplate: '%{y:$,.0f}<extra>week total</extra>' },
  ], layout({
    barmode: 'group', bargap: 0.28, bargroupgap: 0.06,
    xaxis: axis({ title: { text: 'expiry', font: { family: SERIF, size: 12, color: INK } },
                  type: 'category' }),
    yaxis: axis({ title: { text: 'P&L ($)', font: { family: SERIF, size: 12, color: INK } },
                  tickprefix: '$', zeroline: true, zerolinecolor: INK, zerolinewidth: 1 }),
  }), CONFIG);
})();
