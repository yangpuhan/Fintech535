/* The Crossed Wheel page. Reads four files the pipeline writes and draws
   them; it never calculates a result itself.
     gear/lab.json       python -m gearwheel.lab       (by hand, once)
     gear/backtest.json  python -m gearwheel.backtest  (by hand, once)
     gear/state.json     python -m gearwheel.orders    (the Action, nightly)
     gear/log.json       the same, one row appended per decision            */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const css = getComputedStyle(document.documentElement);
  const v = (n) => css.getPropertyValue(n).trim();
  const C = {
    gear: v('--s-gear'), wheel: v('--s-wheel'), stock: v('--s-stock'), ref: v('--s-ref'),
    ink: v('--ink'), muted: v('--muted'), faint: v('--faint'),
  };
  const MONO = "'Source Code Pro','SF Mono',Menlo,monospace";
  const REPO = 'https://github.com/yangpuhan/Fintech535/blob/main/';

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const money = (x) => (x == null ? '—' : (x < 0 ? '−$' : '$') + Math.abs(Math.round(x)).toLocaleString('en-US'));
  const pct = (x, d = 1) => (x == null ? '—' : (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toFixed(d) + '%');
  const num = (x, d = 2) => (x == null ? '—' : (x < 0 ? '−' : '') + Math.abs(Number(x)).toFixed(d));
  const signed = (x, d = 2) => (x == null ? '—' : (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toFixed(d));

  async function get(path, fresh) {
    const r = await fetch(path + (fresh ? '?t=' + Date.now() : ''), { cache: fresh ? 'no-store' : 'default' });
    if (!r.ok) throw new Error(path + ': HTTP ' + r.status);
    return r.json();
  }

  function table(head, rows, opts = {}) {
    const L = (i) => i === 0 || (opts.left || []).includes(i);
    const th = head.map((h, i) => `<th class="${L(i) ? 'l' : ''}">${h}</th>`).join('');
    const tr = rows.map((r) => `<tr class="${r.cls || ''}">` + r.cells.map((c, i) =>
      `<td class="${L(i) ? 'l' : ''} ${(opts.wrap || []).includes(i) ? 'wrapcell' : ''}">${c}</td>`).join('') + '</tr>').join('');
    return `<table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
  }

  // ── tonight ──────────────────────────────────────────────────────────
  function tonight(st) {
    const s = st.signals || {};
    const n = (st.orders || []).length;
    const e = st.earnings || {};
    const pk = st.pick;
    $('tonight-lede').innerHTML =
      `Decided on the <b>${esc(st.decided)}</b> close for the <b>${esc(st.for)}</b> session: ` +
      (n ? `<b>${n} new order${n > 1 ? 's' : ''}</b>.` : '<b>no new order</b>.');
    const cards = [
      ['Orders for', esc(st.for), 'the next session not yet opened'],
      ['Contract', pk ? `${esc(pk.strike)} ${pk.right === 'P' ? 'put' : 'call'}` : '—',
        pk ? `${esc(pk.expiry)} · delta ${num(pk.delta)} · OI ${pk.oi == null ? '—' : pk.oi.toLocaleString('en-US')}` : 'no contract chosen tonight'],
      ['Next report', esc(e.next || '—'), e.estimated ? 'estimated (last + 91 days); blackout widened 10 days' : 'from LSEG'],
      ['AAPL close', num(s.close), `21-day vol ${num(s.rv, 1)}%`],
      ['Book', st.book && st.book.shares ? `${st.book.shares} sh` : money(st.book && st.book.cash),
        esc(st.book ? st.book.source : '')],
    ];
    $('tonight-cards').innerHTML = cards.map(([l, val, h]) =>
      `<div class="card"><div class="lab">${l}</div><div class="val">${val}</div><div class="hint">${h}</div></div>`).join('');
    // the gear line is published for the record; the live rule does not use it
    $('tonight-why').innerHTML = (st.why || []).filter((w) => !/^gear /.test(w))
      .map((w) => `<li>${esc(w)}</li>`).join('');

    const oo = st.open_orders || st.orders || [];
    $('tonight-orders').innerHTML = !oo.length ? '<pre class="json">[]</pre>' : table(
      ['id', 'for', 'action', 'qty', 'contract', 'expiry', 'strike', 'type', 'limit', 'ref'],
      oo.map((o) => ({ cells: [esc(o.id), esc(o.for), `<b>${esc(o.action)}</b>`, o.qty, esc(o.contract),
        esc(o.expiry || '—'), o.strike == null ? '—' : esc(o.strike), esc(o.order_type),
        o.lmt_prc == null ? '—' : esc(o.lmt_prc), esc(o.ref || 'open')] })),
      { left: [1, 2, 4, 5, 7, 8, 9] });
    const run = st.run ? ` · <a href="${esc(st.run)}">the run that wrote it</a>` : '';
    $('tonight-cap').innerHTML =
      `<a href="${REPO}mkt/open_orders.json">mkt/open_orders.json</a> · ` +
      `<a href="${REPO}open_orders.json">open_orders.json</a> (identical) · ` +
      `written ${esc(st.generated_utc || '')} from an LSEG ${esc(st.session || '')} session${run}.` +
      (pk ? ` Last bid/ask ${num(pk.bid)}/${num(pk.ask)}, IV ${num(pk.iv, 1)}%, ${pk.quotes} two-sided quotes on the expiry.` : '');
  }

  // ── the lab ──────────────────────────────────────────────────────────
  function lab(L) {
    const st = (r, w, k) => r.stats[w][k];
    $('lab-table').innerHTML = table(
      ['#', 'candidate', '1.4 window Sharpe', 'CAGR', 'new tape return', 'Sharpe', 'full CAGR', 'Sharpe', 'max DD', 'idle'],
      L.rows.map((r) => ({
        cls: r.key === L.winner ? 'hl' : '',
        cells: [r.rank_found, esc(r.label) + (r.key === L.winner ? ' · <b>winner</b>' : r.key === L.wheel ? ' · baseline' : ''),
          num(st(r, 'found', 'sharpe')), pct(st(r, 'found', 'cagr_pct'), 2),
          pct(st(r, 'new', 'ret_pct'), 1), num(st(r, 'new', 'sharpe')),
          pct(st(r, 'full', 'cagr_pct'), 2), num(st(r, 'full', 'sharpe')), pct(st(r, 'full', 'max_dd_pct')),
          r.idle_pct.toFixed(0) + '%'] })),
      { left: [1] });
    $('lab-cap').textContent =
      `$100,000, cash in T-bills, fill at mid ∓ ${L.kappa} × half-spread. 1.4's window ends ${L.split}; ` +
      `the new tape runs to ${L.end}. Idle: share of sessions in cash with no short open.`;

    const wheel = L.rows.find((r) => r.key === L.wheel);
    $('finalists').innerHTML = table(
      ['#', 'finalist', '1.4 window Sharpe', 'new tape', 'vs wheel', 'robust cells won', 'verdict'],
      L.finalists.map((f) => ({
        cls: f.key === L.winner ? 'hl' : '',
        cells: [f.rank_found, esc(f.label), num(f.found_sharpe), pct(f.new_ret),
          `${pct(wheel.stats.new.ret_pct)} → ${f.beats_new ? '<span class="pass">beats</span>' : '<span class="fail">no</span>'}`,
          `${f.robust_wins} / 9`, f.passes ? '<span class="pass">PASS</span>' : '<span class="fail">fail</span>'] })),
      { left: [1] });

    const w = L.rows.find((r) => r.key === L.winner);
    const second = L.finalists.find((f) => f.key !== L.winner && f.passes);
    const E = L.effects;
    $('verdict').innerHTML =
      `<b>The rule picks ${esc(L.winner_label)}.</b> First on 1.4's window (Sharpe ${num(w.stats.found.sharpe)}), ` +
      `${pct(w.stats.new.ret_pct)} on the new tape against the wheel's ${pct(wheel.stats.new.ret_pct)}, and ahead of the wheel ` +
      `in ${L.finalists.find((f) => f.key === L.winner).robust_wins} of 9 robustness cells.` +
      (second ? ` The runner-up, ${esc(second.label)}, is a tie on 1.4's window (${num(second.found_sharpe)}) and did better ` +
        `on the new tape (${pct(second.new_ret)}); the rule was fixed in advance and breaks ties by rank, so the page reports both.` : '') +
      ` What carries every finalist is the <b>earnings blackout</b>: it helps ${E.earnings.both.helps_found} of ` +
      `${E.earnings.both.of} pairs on 1.4's window and ${E.earnings.both.helps_new} of ${E.earnings.both.of} on the new tape. ` +
      `The <b>OI strike</b> is close to neutral on 1.4's window (${E.oi.on.helps_found} of ${E.oi.on.of}) and helps on the ` +
      `new tape (${E.oi.on.helps_new} of ${E.oi.on.of}). The gear and the IV-over-RV filter lose almost everywhere.`;

    const rows = [];
    const names = { earnings: { both: 'earnings blackout, both sides', calls: 'earnings blackout, calls only' },
      gear: { B: 'gear B (put entry)', A: 'gear A (buys when flat)' }, ivrv: { on: 'IV over RV' }, oi: { on: 'OI strike' } };
    Object.entries(E).forEach(([part, opts]) => Object.entries(opts).forEach(([o, x]) => rows.push({
      cells: [esc(names[part][o]), signed(x.found, 3), `${x.helps_found} / ${x.of}`, signed(x.new, 3), `${x.helps_new} / ${x.of}`] })));
    $('effects').innerHTML = table(['part', 'Δ Sharpe, 1.4 window', 'helps', 'Δ Sharpe, new tape', 'helps'], rows);

    const cl = { putwrite: 'put-write', buywrite: 'buy-write', puts_then_hold: 'puts, then hold', hold: 'buy & hold', tbills: 'T-bills' };
    $('controls').innerHTML = table(['control', 'full CAGR', 'Sharpe', 'max DD', 'new tape return'],
      Object.entries(L.controls).map(([k, s]) => ({ cells: [esc(cl[k] || k), pct(s.full.cagr_pct, 2),
        num(s.full.sharpe), pct(s.full.max_dd_pct), pct(s.new.ret_pct)] })));
  }

  // ── the winner ───────────────────────────────────────────────────────
  const AX = { showgrid: true, gridcolor: '#EFEBE2', zeroline: false, showline: false, ticks: '',
    tickfont: { family: MONO, size: 11, color: '#6E6A63' } };
  const CFG = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'] };

  function navChart(bt) {
    const x = bt.dates;
    const series = [
      [bt.live, bt.labels[bt.live], C.gear, 'solid', 2.4],
      ['wheel', bt.labels.wheel, C.wheel, 'dash', 2],
      ['hold', bt.labels.hold, C.stock, 'dot', 2],
      ['tbills', bt.labels.tbills, C.ref, 'dash', 1.4],
    ];
    $('nav-legend').innerHTML = series.map(([, lab, col, dash]) =>
      `<span><span class="key ${dash === 'solid' ? '' : dash}" style="border-color:${col}"></span>${esc(lab)}</span>`).join('');
    const traces = series.map(([k, lab, col, dash, w]) => ({
      x, y: bt.nav[k], name: lab, mode: 'lines', line: { color: col, width: w, dash },
      hovertemplate: '$%{y:,.0f}<extra>' + esc(lab) + '</extra>' }));
    const ends = series.map(([k, lab]) => ({ lab, y: bt.nav[k][bt.nav[k].length - 1] })).sort((a, b) => b.y - a.y);
    const span = ends[0].y - ends[ends.length - 1].y || 1;
    let prev = null, shift = 0;
    const ann = ends.map((e) => {
      shift = prev !== null && (prev.y - e.y) / span < 0.07 ? shift - 15 : 0;
      prev = e;
      return { x: x[x.length - 1], y: e.y, xanchor: 'left', xshift: 8, yshift: shift, showarrow: false,
        text: `${esc(e.lab)} ${money(e.y)}`, font: { family: MONO, size: 11, color: C.ink } };
    });
    Plotly.newPlot('chart-nav', traces, {
      template: 'none', paper_bgcolor: '#FFFFFF', plot_bgcolor: '#FFFFFF',
      font: { family: MONO, size: 12, color: C.ink }, showlegend: false, hovermode: 'x unified',
      hoverlabel: { bgcolor: '#FFFFFF', bordercolor: '#DDD7CA', font: { family: MONO, size: 12 } },
      margin: { l: 72, r: 250, t: 22, b: 36 },
      xaxis: Object.assign({}, AX, { range: [x[0], x[x.length - 1]], showspikes: true, spikemode: 'across', spikethickness: 1, spikecolor: C.faint, spikedash: 'solid' }),
      yaxis: Object.assign({}, AX, { tickprefix: '$', tickformat: ',.0f' }),
      annotations: ann.concat([{ x: bt.split, y: 1, yref: 'paper', yanchor: 'bottom', xanchor: 'left', xshift: 4,
        showarrow: false, text: 'new tape →', font: { family: MONO, size: 11, color: C.muted } }]),
      shapes: [{ type: 'line', x0: bt.split, x1: bt.split, y0: 0, y1: 1, yref: 'paper', line: { color: C.faint, width: 1, dash: 'dot' } }],
    }, CFG);
  }

  function years(bt) {
    const keys = [bt.live, 'wheel', 'putwrite', 'buywrite', 'hold'];
    const ys = Object.keys(bt.stats.wheel.full.years);
    const best = {};
    ys.forEach((y) => { best[y] = Math.max(...keys.map((k) => bt.stats[k].full.years[y])); });
    $('years').innerHTML = table(['strategy', ...ys, 'CAGR', 'Sharpe', 'max DD'],
      keys.map((k) => {
        const f = bt.stats[k].full;
        return { cls: k === bt.live ? 'hl' : '', cells: [esc(bt.labels[k]),
          ...ys.map((y) => (f.years[y] === best[y] ? `<b>${pct(f.years[y])}</b>` : pct(f.years[y]))),
          pct(f.cagr_pct, 2), num(f.sharpe), pct(f.max_dd_pct)] };
      }));
    $('years-cap').textContent =
      `Calendar-year returns, ${bt.start} to ${bt.end} (${ys[ys.length - 1]} to date); best in each year in bold. ` +
      `$100,000, cash in T-bills, options filled at mid ∓ ${bt.kappa} × half-spread (1.4's measured fill).`;
  }

  function earn(bt) {
    $('earn').innerHTML = table(['short', 'spanned a report', 'trades', 'contracts', 'assigned', 'option P&L'],
      bt.earnings_pnl.map((r) => ({ cls: r.spans && r.right === 'C' ? 'hl' : '',
        cells: [r.right === 'P' ? 'puts' : 'calls', r.spans ? 'yes' : 'no', r.n, r.contracts, r.assigned,
          `<span class="${r.pnl < 0 ? 'neg' : ''}">${money(r.pnl)}</span>`] })), { left: [1] });
  }

  function lookahead(bt) {
    $('lookahead').innerHTML = table(['cut at', 'trades before the cut', 'blotter identical'],
      bt.lookahead.map((r) => ({ cells: [esc(r.upto), r.trades,
        r.identical ? '<span class="ok">yes</span>' : '<span class="neg">NO</span>'] })));
  }

  function log(rows) {
    if (!rows || !rows.length) {
      $('logtable').innerHTML = '<pre class="json">no runs yet</pre>';
      return;
    }
    $('logtable').innerHTML = table(['decided', 'for', 'close', '21-day vol', 'orders', 'decision'],
      rows.slice().reverse().map((r) => ({ cells: [esc(r.decided), esc(r.for), num(r.close), num(r.rv, 1) + '%',
        r.orders && r.orders.length ? r.orders.map(esc).join('<br>') : '—', esc(r.why)] })),
      { left: [1, 4], wrap: [5] });
  }

  function prov(bt) {
    $('prov').innerHTML =
      `Backtest ${esc(bt.start)} – ${esc(bt.end)} on 1.4's engine and LSEG tape, new data from ${esc(bt.split)} · ` +
      `orders: AAPL (conid 265598), opening book $100,000 · built ${esc(bt.generated)}`;
  }

  get('gear/lab.json').then(lab).catch((e) => { $('lab-cap').textContent = 'Could not load the lab: ' + e.message; });
  get('gear/backtest.json').then((bt) => { prov(bt); navChart(bt); years(bt); earn(bt); lookahead(bt); })
    .catch((e) => { $('years-cap').textContent = 'Could not load the backtest: ' + e.message; });
  get('gear/state.json', true).then(tonight)
    .catch(() => { $('tonight-lede').textContent = 'No nightly run has written a decision yet.'; });
  get('gear/log.json', true).then(log).catch(() => log([]));
})();
