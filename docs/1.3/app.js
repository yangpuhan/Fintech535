/* Draws the page from window.PMCC. Every number was computed in pmcc/book.py
   and pmcc/build.py; the only arithmetic here is formatting, ratios of two
   baked numbers, and scaling the PMCC row by the contract count for the
   levered line of the performance table. */
'use strict';

const P = window.PMCC;
const S = P.summary, U = P.unit, A = P.same, M = P.meta, K = P.checks;
const CSS = getComputedStyle(document.documentElement);
const C = n => CSS.getPropertyValue(n).trim();

const INK = C('--ink'), MUTED = C('--muted'), FAINT = C('--faint');
const RULE = C('--rule'), CARD = C('--card');
const STOCK = C('--s-stock'), LEAPS = C('--s-leaps'), HIT = C('--s-hit'), KEPT = C('--s-kept');
const SERIF = "'Source Serif 4', Georgia, serif";
const MONO = "'Source Code Pro', Menlo, monospace";

/* ── formatting ─────────────────────────────────────────────────────── */
const fmt = (v, d) => Math.abs(v).toLocaleString('en-US',
  { minimumFractionDigits: d, maximumFractionDigits: d });
const money = (v, d = 2) => v === null || v === undefined ? '—' : (v < 0 ? '−$' : '$') + fmt(v, d);
const signed = (v, d = 2) => v === null || v === undefined ? '—' : (v < 0 ? '−$' : '+$') + fmt(v, d);
const num = (v, d = 2) => v === null || v === undefined ? '—' : (v < 0 ? '−' : '') + fmt(v, d);
const pct = (v, d = 2) => v === null || v === undefined ? '—' :
  (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d) + '%';
const cls = v => v < 0 ? ' class="neg"' : '';
const esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const setHTML = (id, v) => { const e = document.getElementById(id); if (e) e.innerHTML = v; };
const contract = (k, e) => `${num(k, k % 1 ? 2 : 0)}C ${e}`;
/* RIC -> "140C 2023-01-20", from the blotter, for the ledger's position columns */
const NAMES = Object.fromEntries(P.trades.map(t => [t.ric, contract(t.strike, t.expiry)]));
const short = ric => ric ? NAMES[ric] || ric : '—';

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
  { k: 'stock', name: 'Stock', color: STOCK, dash: 'dot' },
  { k: 'cc', name: 'Covered call', color: STOCK, dash: 'solid' },
  { k: 'leaps', name: 'LEAPS only', color: LEAPS, dash: 'dot' },
  { k: 'pmcc', name: 'PMCC', color: LEAPS, dash: 'solid' },
  { k: 'pmcc_lev', name: `PMCC ×${M.n_lev}`, color: LEAPS, dash: 'dashdot', width: 1.3 },
];

/* ══ masthead ═══════════════════════════════════════════════════════ */
setHTML('prov',
  `${M.ticker} · ${M.stock_ric} · daily closes · ${M.sessions} sessions, ${M.first_fill} → ${M.end}<br>` +
  `LSEG pull ${M.fetched_at} · ${M.n_contracts.toLocaleString()} option contracts · ` +
  `${M.n_option_rows.toLocaleString()} daily quotes · rate ${M.rate_ric}`);

const spreadShare = U.pmcc.spread_cost / U.pmcc.pnl * 100;
setHTML('answer', [
  `<b>It does use less capital.</b> ${money(U.pmcc.capital, 0)} per unit against
   ${money(U.cc.capital, 0)} for a covered call writing the identical calls —
   ${num(S.capital_ratio_pct, 0)}%.`,
  `<b>Its return on that capital is higher, because it is leverage.</b>
   ${num(U.pmcc.roc_ann_pct)}% a year on capital deployed against ${num(U.cc.roc_ann_pct)}%
   for the covered call. Its worst peak-to-trough loss, into the April 2025 low, was
   ${num(Math.abs(U.pmcc.max_dd_pct_cap), 0)}% of that capital; the covered call's was
   ${num(Math.abs(U.cc.max_dd_pct_cap), 0)}%.`,
  `<b>On the same money it is a smaller covered call, not a cheaper one.</b> In the same
   ${money(M.account, 0)} account, spare cash in T-bills, one PMCC returned
   ${num(A.pmcc.cagr_pct)}% a year against ${num(A.cc.cagr_pct)}%, with less volatility
   (${num(A.pmcc.vol_pct, 1)}% vs ${num(A.cc.vol_pct, 1)}%) and a shallower drawdown
   (${pct(A.pmcc.max_dd_pct, 1)} vs ${pct(A.cc.max_dd_pct, 1)}) — it held the equivalent of
   ${num(S.mean_pmcc_delta, 0)} shares on average, against ${num(S.mean_cc_delta, 0)}.
   ${['None', 'One', 'Two', 'Three', 'Four'][M.n_lev] || M.n_lev} PMCCs, as many as the account can fund, returned ${num(A.pmcc_lev.cagr_pct)}% with
   ${num(A.pmcc_lev.vol_pct, 1)}% volatility and a ${pct(A.pmcc_lev.max_dd_pct, 1)} drawdown.
   Risk-adjusted it trailed either way: Sharpe ${num(A.pmcc.sharpe)} and ${num(A.pmcc_lev.sharpe)}
   against ${num(A.cc.sharpe)}.`,
  `<b>The capital it saves is not free.</b> A LEAPS price includes interest on its strike
   until expiry. Over the five completed LEAPS, the part of that charge used up while
   held came to ${money(S.carry_held, 0)}; T-bill interest on the cash the PMCC freed came
   to ${money(S.tbill_freed, 0)}. One pays for the other.`,
  `<b>Writing calls lost money in this window, in both books.</b> AAPL rose
   ${num(S.stock_move_pct, 0)}%. The ${S.n_cycles} short calls collected ${money(S.premium, 0)}
   and paid back ${money(S.intrinsic, 0)} in intrinsic value, net ${signed(S.overlay_pnl, 0)}.
   Both call-writing books trailed simply holding their long leg.`,
].map(t => `<li>${t}</li>`).join(''));

setHTML('rec',
  `<b>Recommendation.</b> Use the PMCC when capital is the binding constraint and a covered
   call with about ${num(S.mean_pmcc_delta / S.mean_cc_delta * 100, 0)}% of the share exposure
   is what you want. Don't use it to earn more per unit of risk: here it did not, and
   with T-bills at 4–5% the LEAPS charges back what the freed cash earns. Budget for costs:
   two option legs and a wide LEAPS quote cost ${money(U.pmcc.spread_cost, 0)} in half-spreads,
   ${num(spreadShare, 0)}% of its P&amp;L, against ${money(U.cc.spread_cost, 0)} for the covered call.`);

const CARDS = [
  ['capital per unit', money(U.pmcc.capital, 0), `covered call ${money(U.cc.capital, 0)}`],
  ['P&amp;L per unit', signed(U.pmcc.pnl, 0), `covered call ${signed(U.cc.pnl, 0)} · at mid`],
  ['return on capital', `${num(U.pmcc.roc_ann_pct)}%/yr`, `covered call ${num(U.cc.roc_ann_pct)}%/yr`],
  ['same-account CAGR', `${num(A.pmcc.cagr_pct)}%`,
    `covered call ${num(A.cc.cagr_pct)}% · stock ${num(A.stock.cagr_pct)}%`],
  ['max drawdown, same account', pct(A.pmcc.max_dd_pct), `covered call ${pct(A.cc.max_dd_pct)}`],
  ['short calls, net', signed(S.overlay_pnl, 0), `${S.n_cycles} calls, identical in both books`],
];
setHTML('cards', CARDS.map(([lab, val, hint]) =>
  `<div class="card"><div class="lab">${lab}</div><div class="val">${val}</div>` +
  `<div class="hint">${hint}</div></div>`).join(''));

setHTML('r-delta', num(K.delta.median_abs, 4));
setHTML('r-acct', money(M.account, 0));

/* ══ 01 · payoff ════════════════════════════════════════════════════ */
(function payoff() {
  const Y = P.payoff;
  const line = (y, name, color) => ({
    x: Y.S, y, type: 'scatter', mode: 'lines', name,
    line: { color, width: 2 }, hovertemplate: '%{y:$,.0f}<extra>' + name + '</extra>',
  });
  const vline = (x, text, side) => ({
    shape: { type: 'line', x0: x, x1: x, y0: 0, y1: 1, yref: 'paper',
             line: { color: FAINT, width: 1, dash: 'dot' } },
    ann: { x, y: 1, yref: 'paper', yanchor: 'bottom', xanchor: side, text, showarrow: false,
           xshift: side === 'left' ? 3 : -3, font: { family: MONO, size: 10, color: MUTED } },
  });
  /* the two prices sit $15 apart: anchor the labels away from each other */
  const v = [vline(Y.spot, `entry ${money(Y.spot)}`, 'left'),
             vline(Y.settle, `expiry ${money(Y.settle)}`, 'right')];
  const n = Y.S.length - 1;
  Plotly.newPlot('plot-payoff', [
    line(Y.cc, 'Covered call', STOCK),
    line(Y.pmcc, 'PMCC', LEAPS),
  ], layout({
    margin: { l: 70, r: 92, t: 40, b: 46 },
    /* bottom-right is the one empty corner of a capped payoff */
    legend: { x: 0.98, y: 0.04, xanchor: 'right', yanchor: 'bottom', bgcolor: CARD,
              font: { family: MONO, size: 11, color: INK } },
    shapes: v.map(o => o.shape).concat([{ type: 'line', x0: Y.S[0], x1: Y.S[n], y0: 0, y1: 0,
      line: { color: INK, width: 1 } }]),
    annotations: v.map(o => o.ann).concat([
      { x: Y.S[n], y: Y.cc[n], text: 'covered call', xanchor: 'left', xshift: 6, showarrow: false,
        font: { family: MONO, size: 10.5, color: INK } },
      { x: Y.S[n], y: Y.pmcc[n], text: 'PMCC', xanchor: 'left', xshift: 6, showarrow: false,
        font: { family: MONO, size: 10.5, color: INK } }]),
    xaxis: axis({ title: ytitle(`AAPL at the ${Y.expiry} expiry`), tickprefix: '$',
                  range: [Y.S[0], Y.S[n]] }),
    yaxis: axis({ title: ytitle('P&L per unit ($)'), tickformat: '$,.0f' }),
  }), CONFIG);

  const lossP = Y.pmcc[0] / Y.debit * 100, lossC = Y.cc[0] / Y.cc_cost * 100;
  setHTML('payoff-facts', [
    `<b>Cost.</b> The PMCC paid ${money(Y.debit, 0)}: the ${num(Y.long_strike, 0)} call
     expiring ${Y.long_expiry} at ${money(Y.long_price)}, less ${money(Y.short_price)} for the
     ${num(Y.short_strike, 0)} call. The covered call paid ${money(Y.cc_cost, 0)} for the shares,
     less the same premium.`,
    `<b>Upside.</b> Both are capped at the ${num(Y.short_strike, 0)} strike. Above it the PMCC is
     worth about the width of the spread, ${money(Y.short_strike - Y.long_strike, 0)} a share,
     plus whatever time value the LEAPS still has.`,
    `<b>Downside.</b> The PMCC can lose at most its debit; the covered call can lose
     ${money(Y.cc_cost, 0)}. Per dollar invested the PMCC falls faster: at the left edge of the
     chart (AAPL ${pct((Y.S[0] / Y.spot - 1) * 100, 0)}) it has lost ${num(Math.abs(lossP), 0)}% of
     what it paid, the covered call ${num(Math.abs(lossC), 0)}%.`,
    `<b>The PMCC's own risk is a rally.</b> If the spread's width were less than its cost,
     a gap through the short strike would lose money. The gap rule in 02 forbids that trade.`,
  ].map(t => `<li>${t}</li>`).join(''));
  setHTML('payoff-cap',
    `The LEAPS is revalued at the short call's expiry with Black–Scholes at the implied
     volatility it was bought at (${num(Y.iv * 100, 1)}%), holding the rate and dividend yield
     fixed — the one model-made curve on the page. Everything else is booked off quotes.`);
})();

/* ══ 03 · NAV ═══════════════════════════════════════════════════════ */
(function nav() {
  const Cv = P.curves;
  const traces = BOOKS.map(b => ({
    x: Cv.date, y: Cv[b.k], type: 'scatter', mode: 'lines', name: b.name,
    line: { color: b.color, width: b.width || 2, dash: b.dash },
    hovertemplate: '%{y:$,.0f}<extra>' + b.name + '</extra>',
  }));
  const last = Cv.date.length - 1;
  const ann = BOOKS.filter(b => b.k !== 'pmcc_lev').map(b => ({
    x: Cv.date[last], y: Cv[b.k][last], text: b.name, xanchor: 'left', xshift: 6,
    showarrow: false, font: { family: MONO, size: 10.5, color: INK },
  }));
  Plotly.newPlot('plot-nav', traces, layout({
    margin: { l: 70, r: 104, t: 40, b: 42 },
    annotations: ann,
    shapes: [{ type: 'line', x0: Cv.date[0], x1: Cv.date[last], y0: M.account, y1: M.account,
               line: { color: FAINT, width: 1 } }],
    xaxis: axis({ rangebreaks: WEEKENDS, range: [Cv.date[0], Cv.date[last]] }),
    yaxis: axis({ title: ytitle(`account value, opened with ${money(M.account, 0)}`),
                  tickformat: '$,.0f' }),
  }), CONFIG);
})();

(function perfTable() {
  const n = M.n_lev;
  const rows = BOOKS.map(b => {
    const u = b.k === 'pmcc_lev'
      ? { capital: U.pmcc.capital * n, pnl: U.pmcc.pnl * n, pnl_natural: U.pmcc.pnl_natural * n,
          roc_ann_pct: U.pmcc.roc_ann_pct }
      : U[b.k];
    const a = A[b.k];
    return `<tr${b.k === 'pmcc' ? ' class="hl"' : ''}>
      <td class="l"><span class="key${b.dash === 'dot' ? ' dot' : ''}" style="border-color:${b.color}"></span>${b.name}</td>
      <td>${money(u.capital, 0)}</td><td>${signed(u.pnl, 0)}</td><td>${signed(u.pnl_natural, 0)}</td>
      <td>${num(u.roc_ann_pct)}%</td>
      <td>${money(a.final, 0)}</td><td>${num(a.cagr_pct)}%</td><td>${num(a.vol_pct, 1)}%</td>
      <td>${num(a.sharpe)}</td><td${cls(a.max_dd_pct)}>${pct(a.max_dd_pct, 1)}
        <span style="color:${FAINT}">${a.max_dd_date.slice(0, 7)}</span></td></tr>`;
  });
  document.querySelector('#t-perf tbody').innerHTML = rows.join('');
  setHTML('perf-cap',
    `Per unit = 100 shares or one contract of each leg, no interest. Capital required is the
     deepest the per-unit cash ever went: the covered call needs more than the shares alone
     because buying back assigned calls is paid in cash. Return on capital is per-unit P&amp;L
     over that capital, annualised over ${num(S.years, 1)} years. The same-account columns open
     every book with ${money(M.account, 0)} and pay the T-bill rate on idle cash; Sharpe is the
     daily excess over T-bills, annualised. "PMCC ×${n}" is ${n} contracts of everything, the most
     the account can fund.`);

  const years = Object.keys(A.pmcc.years);
  document.querySelector('#t-years thead').innerHTML =
    `<tr><th class="l">book</th>${years.map((y, i) =>
      `<th>${y}${i === years.length - 1 ? ' to ' + M.end.slice(5) : ''}</th>`).join('')}</tr>`;
  document.querySelector('#t-years tbody').innerHTML = BOOKS.map(b =>
    `<tr${b.k === 'pmcc' ? ' class="hl"' : ''}><td class="l">
      <span class="key${b.dash === 'dot' ? ' dot' : ''}" style="border-color:${b.color}"></span>${b.name}</td>
      ${years.map(y => `<td${cls(A[b.k].years[y])}>${pct(A[b.k].years[y], 1)}</td>`).join('')}</tr>`
  ).join('');
})();

/* ══ 04 · position ══════════════════════════════════════════════════ */
(function position() {
  const Cv = P.curves;
  const traces = [{
    x: Cv.date, y: Cv.spot, type: 'scatter', mode: 'lines', name: 'AAPL close',
    line: { color: INK, width: 1.5 }, hovertemplate: '%{y:$,.2f}<extra>AAPL</extra>',
  }];
  P.lots.forEach((l, i) => traces.push({
    x: [l.opened, l.closed || M.end], y: [l.strike, l.strike], type: 'scatter', mode: 'lines',
    name: 'LEAPS strike', legendgroup: 'leaps', showlegend: i === 0,
    line: { color: MUTED, width: 2, dash: 'dash' },
    hovertemplate: `long ${contract(l.strike, l.expiry)}<br>bought ${money(l.price)}, ` +
      `delta ${num(l.delta)}<extra></extra>`,
  }));
  const seen = {};
  P.cycles.forEach(c => {
    const hit = c.outcome === 'ASSIGNED' || c.outcome === 'EARLY';
    const g = c.outcome === 'OPEN' ? 'open' : hit ? 'hit' : 'kept';
    const name = { hit: 'short call · assigned', kept: 'short call · expired', open: 'short call · open' }[g];
    traces.push({
      x: [c.opened, c.closed || M.end], y: [c.strike, c.strike], type: 'scatter', mode: 'lines',
      name, legendgroup: g, showlegend: !seen[g],
      line: { color: g === 'hit' ? HIT : g === 'kept' ? KEPT : FAINT, width: 2.5,
              dash: g === 'hit' ? 'solid' : 'dot' },
      hovertemplate: `short ${contract(c.strike, c.expiry)}, delta ${num(c.delta)}<br>` +
        `premium ${money(c.premium)} · ${c.outcome.toLowerCase()}` +
        (c.settle ? ` at ${money(c.settle)}` : '') + `<extra></extra>`,
    });
    seen[g] = true;
  });
  Plotly.newPlot('plot-pos', traces, layout({
    hovermode: 'closest',
    xaxis: axis({ rangebreaks: WEEKENDS }),
    yaxis: axis({ title: ytitle('price / strike ($)'), tickprefix: '$' }),
  }), CONFIG);
  setHTML('pos-cap',
    `${S.n_cycles} short calls, ${S.n_assigned + S.n_early} of them finished in the money. The gap
     rule lifted ${S.n_bound} of them above their 0.30-delta strike, so the average delta actually
     sold was ${num(S.mean_delta)}, a median ${num(S.median_otm, 1)}% out of the money. The LEAPS
     strike resets once a year at the roll. In mid-2022 AAPL fell under it, and the gap rule
     pushed the short strikes far out, because a call struck below the long's breakeven would
     lock in a loss if AAPL recovered through it.`);

  Plotly.newPlot('plot-mv', [
    { x: Cv.date, y: Cv.cc_mv, type: 'scatter', mode: 'lines', name: 'Covered call: shares − short call',
      line: { color: STOCK, width: 2 }, hovertemplate: '%{y:$,.0f}<extra>covered call</extra>' },
    { x: Cv.date, y: Cv.pmcc_mv, type: 'scatter', mode: 'lines', name: 'PMCC: LEAPS − short call',
      line: { color: LEAPS, width: 2 }, hovertemplate: '%{y:$,.0f}<extra>PMCC</extra>' },
  ], layout({
    xaxis: axis({ rangebreaks: WEEKENDS }),
    yaxis: axis({ title: ytitle('position value ($)'), tickformat: '$,.0f', rangemode: 'tozero' }),
  }), CONFIG);
  setHTML('mv-cap',
    `Market value of each position, per unit. The PMCC keeps between a quarter and a third as
     much at work — which is why its drawdowns are smaller in dollars and larger as a share of
     what it put up.`);
})();

/* ══ 05 · attribution ═══════════════════════════════════════════════ */
(function attribution() {
  const row = (lab, a, b, c = '') => `<tr${c}><td class="l">${lab}</td>
    <td${cls(a)}>${a === null ? '—' : signed(a, 0)}</td><td${cls(b)}>${b === null ? '—' : signed(b, 0)}</td></tr>`;
  document.querySelector('#t-attr tbody').innerHTML = [
    row('long leg: shares / LEAPS', U.stock.pnl - U.stock.dividends, U.leaps.pnl),
    row('dividends', U.stock.dividends, null),
    row('short calls', S.overlay_pnl, S.overlay_pnl),
    row('P&amp;L at mid', U.cc.pnl, U.pmcc.pnl, ' class="sum"'),
    row('half-spread on every option fill', -U.cc.spread_cost, -U.pmcc.spread_cost),
    row('P&amp;L paying the half-spread', U.cc.pnl_natural, U.pmcc.pnl_natural, ' class="sum"'),
    row('T-bill on idle cash (same account)', A.cc.interest, A.pmcc.interest),
  ].join('');

  const w = S.worst_cycle;
  setHTML('short-facts', [
    `${S.n_cycles} calls: ${S.n_expired} expired worthless, ${S.n_assigned} were in the money at
     expiry, ${S.n_early} was exercised early ahead of an ex-dividend date, and one is still open.`,
    `${money(S.premium, 0)} of premium in, ${money(S.intrinsic, 0)} of intrinsic value out.
     The usual call wins a little; the occasional one loses a lot. The worst, the
     ${num(w.strike, 0)} call sold on ${w.opened}, lost ${money(Math.abs(w.short_pnl), 0)} when AAPL
     closed at ${money(w.settle)} on expiry — in a month the LEAPS made ${signed(w.long_pnl, 0)}.`,
    `${S.earn_n} calls had an earnings report inside them. Together they lost
     ${money(Math.abs(S.earn_short), 0)} (${money(Math.abs(S.earn_short / S.earn_n), 0)} a call), against
     ${money(Math.abs(S.noearn_short), 0)} for the other ${S.n_cycles - S.earn_n}
     (${money(Math.abs(S.noearn_short / (S.n_cycles - S.earn_n)), 0)} a call). No worse — so standing down
     over earnings, the fix 1.2 proposed after one bad week, would not have helped here.`,
    `Quoted spreads at the fill: a median ${num(M.spread_pct.short, 1)}% of the mid on the short calls,
     ${num(M.spread_pct.long, 1)}% on the LEAPS. But a LEAPS costs ~25 times as much, so the
     LEAPS leg carried ${money(U.leaps.spread_cost, 0)} of the PMCC's ${money(U.pmcc.spread_cost, 0)}
     in half-spreads, against ${money(U.cc.spread_cost, 0)} for all ${S.n_cycles} short calls.`,
  ].map(t => `<li>${t}</li>`).join(''));

  const Cy = P.cycles;
  const grp = c => c.outcome === 'OPEN' ? 'open' : (c.outcome === 'EXPIRED' ? 'kept' : 'hit');
  const names = { kept: 'expired worthless', hit: 'in the money', open: 'still open' };
  const cols = { kept: KEPT, hit: HIT, open: FAINT };
  Plotly.newPlot('plot-cycles', ['kept', 'hit', 'open'].map(g => {
    const rows = Cy.filter(c => grp(c) === g);
    return {
      x: rows.map(c => c.opened), y: rows.map(c => c.short_pnl), type: 'bar', name: names[g],
      marker: { color: cols[g] }, width: 1000 * 60 * 60 * 24 * 18,
      customdata: rows.map(c => [contract(c.strike, c.expiry), money(c.premium), c.settle ? money(c.settle) : '—']),
      hovertemplate: '%{customdata[0]}<br>premium %{customdata[1]} · settle %{customdata[2]}' +
        '<br>%{y:$,.0f}<extra></extra>',
    };
  }), layout({
    hovermode: 'closest', barmode: 'overlay',
    xaxis: axis({ type: 'date' }),
    yaxis: axis({ title: ytitle('short call P&L ($)'), tickformat: '$,.0f',
                  zeroline: true, zerolinecolor: INK, zerolinewidth: 1 }),
  }), CONFIG);

  document.querySelector('#t-lots tbody').innerHTML = P.lots.map(l => `<tr>
    <td class="l"><b>${contract(l.strike, l.expiry)}</b></td>
    <td class="l">${l.opened}</td><td class="l">${l.closed || '<span style="color:' + FAINT + '">open</span>'}</td>
    <td>${num(l.spot)}</td>
    <td>${money(l.price)}</td><td>${money(l.intrinsic)}</td><td>${money(l.extrinsic)}</td>
    <td>${money(l.carry)}</td><td>${num(l.rate_pct)}%</td>
    <td>${money(l.exit)}</td><td${cls(l.pnl)}><b>${signed(l.pnl, 0)}</b></td>
    <td>${money(l.freed, 0)}</td><td>${money(l.carry_held, 0)}</td>
    <td>${money(l.tbill_on_freed, 0)}</td></tr>`).join('');
  setHTML('carry-note',
    `<b>Read the two interest columns together.</b> A deep in-the-money call is partly a loan:
     the holder pays the strike at expiry instead of today, and the option's price includes the
     interest on that, K(1 − e<sup>−rT</sup>). In 2022, with T-bills near zero, the charge was
     nothing ($0.09 a share on the first LEAPS); from late 2023, at 4–5%, it was around half of
     the time value paid. "Financing used while held" is the part of that charge consumed
     between purchase and sale, at the entry rate; "T-bill earned on freed cash" is what the
     money not spent on shares earned over the same days. Over the five
     completed LEAPS: <b>${money(S.carry_held, 0)}</b> against <b>${money(S.tbill_freed, 0)}</b>.
     The PMCC's capital saving is real, but it is not a saving in cost — the cash it doesn't tie
     up earns about what the LEAPS charges for not tying it up. By put–call parity the rest of
     the time value is a put, less the dividends the call never receives: downside protection
     below the LEAPS strike that the covered call does not have. It is what bends the PMCC's
     curve on the left of the chart in 01.`);
})();

/* ══ 06 · grid ══════════════════════════════════════════════════════ */
(function grid() {
  const G = P.grid;
  document.querySelector('#t-grid tbody').innerHTML = G.map(g => `<tr${g.headline ? ' class="hl"' : ''}>
    <td class="l">${num(g.long_delta)}</td><td class="l">${num(g.short_delta)}</td>
    <td class="l">${g.gap_rule ? 'on' : '<b>off</b>'}</td>
    <td>${signed(g.pmcc_pnl, 0)}</td><td>${signed(g.pmcc_natural, 0)}</td>
    <td>${money(g.pmcc_capital, 0)}</td><td>${num(g.pmcc_roc, 0)}%</td>
    <td class="neg">${signed(g.pmcc_max_dd, 0)}</td><td>${signed(g.cc_pnl, 0)}</td>
    <td${cls(g.pmcc_pnl - g.cc_pnl)}>${signed(g.pmcc_pnl - g.cc_pnl, 0)}</td>
    <td${cls(g.overlay_pnl)}>${signed(g.overlay_pnl, 0)}</td>
    <td>${g.assigned} / ${g.cycles}</td><td>${g.bound}</td></tr>`).join('');
  const gaps = G.map(g => g.pmcc_pnl - g.cc_pnl);
  const on = G.filter(g => g.gap_rule), head = G.find(g => g.headline), off = G.find(g => !g.gap_rule);
  const worst = Math.min(...on.map(g => g.pmcc_pnl));
  setHTML('grid-cap',
    `The headline row is the textbook default, fixed before the run${head.pmcc_pnl === worst
      ? ' — and it turns out to be the weakest PMCC of the nine' : ''}. In every row the PMCC
     trails the covered call writing the same calls (by ${money(Math.abs(Math.max(...gaps)), 0)} to
     ${money(Math.abs(Math.min(...gaps)), 0)}), and the short calls lose money. That gap depends
     only on the long delta: the short calls are the same in both books, so they cancel. Deeper
     LEAPS (0.90)
     earn more because they are closer to the stock and need the gap rule less, but cost more
     capital. Switching the gap rule off barely moves the P&amp;L (${signed(off.pmcc_pnl, 0)} vs
     ${signed(head.pmcc_pnl, 0)}) and raises assignments from ${head.assigned} to ${off.assigned}. None
     of these rows were used to choose the headline.`);
})();

/* ══ 07 · checks ════════════════════════════════════════════════════ */
document.querySelector('#t-look tbody').innerHTML = K.lookahead.map(x => `<tr>
  <td class="l">${x.upto}</td><td>${x.trades}</td>
  <td class="l ${x.identical ? 'ok' : 'neg'}">${x.identical ? '✓ identical' : '× DIFFERENT'}</td></tr>`).join('');

(function checks() {
  const D = K.delta, req = M.chain.reduce((s, c) => s + c.requested, 0),
        res = M.chain.reduce((s, c) => s + c.resolved, 0);
  setHTML('checks', [
    `<b>Delta.</b> Our Black–Scholes delta against LSEG's DELTA field: median gap
     ${num(D.median_abs, 4)} on ${D.n.toLocaleString()} quotes (90th percentile ${num(D.p90_abs, 3)});
     ${num(D.near_030_median, 4)} near 0.30 and ${num(D.near_080_median, 4)} near 0.80. LSEG's field
     is blank on ${D.lseg_missing} tradeable quotes, ${D.lseg_missing_2022} of them in 2022.`,
    `<b>Mid.</b> (BID + ASK) / 2 equals LSEG's MID_PRICE on every row (largest gap
     ${num(D.mid_vs_mid_price, 4)}).`,
    `<b>Stale marks.</b> ${K.carried_marks.stale} of ${K.carried_marks.held.toLocaleString()}
     held-contract sessions had no two-sided close and carried the previous mid
     (${num(K.carried_marks.stale / K.carried_marks.held * 100, 1)}%). Fills never use a stale quote.`,
    `<b>Pull.</b> ${res.toLocaleString()} of ${req.toLocaleString()} constructed RICs resolved; the
     rest are strikes that never listed. (${res - M.n_contracts} turn up in both legs' pulls,
     because each January monthly is also that year's LEAPS, hence
     ${M.n_contracts.toLocaleString()} distinct contracts.) ${K.bands.short_at_top.length + K.bands.long_at_bottom.length === 0
      ? 'No chosen strike sits on the edge of what was pulled, so the band never limited the rule.'
      : 'Some picks sit on the band edge: ' + esc(K.bands.short_at_top.concat(K.bands.long_at_bottom).join(', '))}`,
    `<b>Accounting.</b> Short-call P&amp;L is identical in the two books (gap
     ${money(K.overlay_identical)}), and the per-call rows below sum to total P&amp;L (gap
     ${money(K.attribution_gap)}).`,
  ].map(t => `<li>${t}</li>`).join(''));
  setHTML('nm-fills', U.pmcc.option_fills);
  setHTML('nm-comm', money(U.pmcc.option_fills * 0.65, 0));
  setHTML('nm-move', `${num(S.stock_move_pct, 0)}%`);
  setHTML('recon', money(K.attribution_gap));
})();

/* ══ 08 · records ═══════════════════════════════════════════════════ */
document.querySelector('#t-cycles tbody').innerHTML = P.cycles.map(c => `<tr>
  <td class="l">${c.opened}</td><td class="l">${c.expiry}</td><td>${num(c.spot)}</td>
  <td style="color:${MUTED}">${num(c.long_strike, 0)}</td><td><b>${num(c.strike)}</b></td>
  <td>${num(c.otm_pct, 1)}%</td><td>${num(c.delta)}</td><td>${money(c.premium)}</td>
  <td style="color:${MUTED}">${c.bound ? num(c.free_strike) : ''}</td>
  <td class="l"><span class="pill pill-${c.outcome}">${c.outcome}</span></td>
  <td>${c.settle ? num(c.settle) : '—'}</td>
  <td${cls(c.short_pnl)}>${signed(c.short_pnl, 0)}</td><td${cls(c.long_pnl)}>${signed(c.long_pnl, 0)}</td>
  <td${cls(c.pmcc_pnl)}><b>${signed(c.pmcc_pnl, 0)}</b></td><td${cls(c.cc_pnl)}>${signed(c.cc_pnl, 0)}</td>
  <td class="l" style="color:${MUTED}">${c.earnings || ''}</td></tr>`).join('');

function renderBlotter(f) {
  const rows = P.trades.filter(t => f === 'all' ? true : f === 'ASSIGN' ? t.side === 'ASSIGN' : t.leg === f);
  document.querySelector('#t-blotter tbody').innerHTML = rows.map(t => `<tr>
    <td class="l">${t.date}</td><td class="l">${t.leg === 'long' ? 'LEAPS' : 'short call'}</td>
    <td class="l"><b>${t.side}</b></td><td class="l">${esc(t.ric)}</td>
    <td>${t.qty > 0 ? '+' : '−'}${Math.abs(t.qty)}</td><td>${money(t.price, 3)}</td>
    <td style="color:${MUTED}">${t.half_spread ? money(t.half_spread, 3) : '—'}</td>
    <td${cls(t.cash)}>${signed(t.cash)}</td><td class="l" style="color:${MUTED}">${t.rule}</td>
    <td class="note">${esc(t.note)}</td></tr>`).join('');
  setHTML('blotter-count', `${rows.length} of ${P.trades.length} booked trades`);
}
document.querySelectorAll('[data-flt]').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('[data-flt]').forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
  renderBlotter(btn.dataset.flt);
}));
renderBlotter('all');

const LED = { book: 'pmcc', view: 'month' };
function renderLedger() {
  let rows = P.ledger[LED.book];
  if (LED.view === 'month') {
    const last = new Map();
    rows.forEach(r => last.set(r.date.slice(0, 7), r));
    rows = [...last.values()];
  }
  document.querySelector('#t-ledger tbody').innerHTML = rows.map(r => `<tr>
    <td class="l">${r.date}</td><td>${num(r.spot)}</td><td>${r.shares}</td>
    <td class="l">${short(r.long)}</td><td>${r.long_mark === null ? '—' : num(r.long_mark, 3)}</td>
    <td class="l">${short(r.short)}</td><td>${r.short_mark === null ? '—' : num(r.short_mark, 3)}</td>
    <td${cls(r.cash)}>${money(r.cash)}</td><td>${money(r.stock_mv)}</td><td>${money(r.long_mv)}</td>
    <td${cls(r.short_mv)}>${money(r.short_mv)}</td><td${cls(r.nav)}><b>${signed(r.nav)}</b></td>
    <td>${num(r.delta, 1)}</td></tr>`).join('');
  setHTML('ledger-count', `${rows.length} of ${P.ledger[LED.book].length} sessions`);
}
['book', 'led'].forEach(attr => document.querySelectorAll(`[data-${attr}]`).forEach(btn =>
  btn.addEventListener('click', () => {
    document.querySelectorAll(`[data-${attr}]`).forEach(b => b.setAttribute('aria-pressed', String(b === btn)));
    if (attr === 'book') LED.book = btn.dataset.book; else LED.view = btn.dataset.led;
    renderLedger();
  })));
renderLedger();

setHTML('foot', `${M.ticker} PMCC · ${S.n_cycles} short calls · ${P.lots.length} LEAPS · ` +
  `${P.trades.length} booked trades · ${M.sessions} sessions · look-ahead test ` +
  `${K.lookahead.every(x => x.identical) ? 'passed' : 'FAILED'} at ${K.lookahead.length} cut dates`);
