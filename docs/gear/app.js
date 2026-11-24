/* The Nightly Wheel page. Draws three files the pipeline writes; it never
   calculates a result itself.
     gear/backtest.json  python -m gearwheel.backtest  (by hand)
     gear/state.json     python -m gearwheel.orders    (the Action, nightly)
     gear/log.json       the same, one row appended per decision            */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const css = getComputedStyle(document.documentElement);
  const v = (n) => css.getPropertyValue(n).trim();
  const C = { gear: v('--s-gear'), wheel: v('--s-wheel'), stock: v('--s-stock'), ref: v('--s-ref'),
    ink: v('--ink'), muted: v('--muted'), faint: v('--faint') };
  const MONO = "'Source Code Pro','SF Mono',Menlo,monospace";
  const REPO = 'https://github.com/yangpuhan/Fintech535/blob/main/';

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const money = (x) => (x == null ? '—' : (x < 0 ? '−$' : '$') + Math.abs(Math.round(x)).toLocaleString('en-US'));
  const pct = (x, d = 1) => (x == null ? '—' : (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toFixed(d) + '%');
  const num = (x, d = 2) => (x == null ? '—' : (x < 0 ? '−' : '') + Math.abs(Number(x)).toFixed(d));

  // The data sits beside this script (docs/gear/); the page that loads it lives elsewhere (docs/final/).
  const BASE = new URL('..', document.currentScript.src).href;
  async function get(path, fresh) {
    const r = await fetch(new URL(path, BASE).href + (fresh ? '?t=' + Date.now() : ''), { cache: fresh ? 'no-store' : 'default' });
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
    const cr = st.credit || {};
    const pk = st.pick;
    $('tonight-lede').innerHTML =
      `Decided on the <b>${esc(st.decided)}</b> close for the <b>${esc(st.for)}</b> session: ` +
      (n ? `<b>${n} new order${n > 1 ? 's' : ''}</b>.` : '<b>no new order</b>.');
    const cards = [
      ['Orders for', esc(st.for), 'the next session not yet opened'],
      ['Contract', pk ? `${esc(pk.strike)} ${pk.right === 'P' ? 'put' : 'call'}` : '—',
        pk ? `expires ${esc(pk.expiry)} · delta ${num(pk.delta)}` : 'no contract chosen tonight'],
      ['Next report', esc(e.next || '—'), e.estimated ? 'estimated; blackout starts 10 days early' : 'from LSEG'],
      ['Credit', cr.stress === false ? 'calm' : cr.stress ? 'pause' : '—',
        cr.baa != null ? `spread ${num(cr.baa)} vs 200-day ${num(cr.baa_ma)}` : esc(cr.error || 'not read')],
      ['Book', st.book && st.book.shares ? `${st.book.shares} sh` : money(st.book && st.book.cash),
        st.book && /opening book/.test(st.book.source) ? 'opening book (Sanji has not written one yet)' : esc(st.book ? st.book.source : '')],
    ];
    $('tonight-cards').innerHTML = cards.map(([l, val, h]) =>
      `<div class="card"><div class="lab">${l}</div><div class="val">${val}</div><div class="hint">${h}</div></div>`).join('');
    $('tonight-why').innerHTML = (st.why || []).filter((w) => !/^gear /.test(w))
      .map((w) => `<li>${esc(w)}</li>`).join('');

    const oo = st.open_orders || st.orders || [];
    $('tonight-orders').innerHTML = !oo.length ? '<pre class="json">[]</pre>' : table(
      ['id', 'for', 'action', 'qty', 'contract', 'expiry', 'strike', 'type', 'limit'],
      oo.map((o) => ({ cells: [esc(o.id), esc(o.for), `<b>${esc(o.action)}</b>`, o.qty, esc(o.contract),
        esc(o.expiry || '—'), o.strike == null ? '—' : esc(o.strike), esc(o.order_type),
        o.lmt_prc == null ? '—' : esc(o.lmt_prc)] })),
      { left: [1, 2, 4, 5, 7, 8] });
    const run = st.run ? ` · <a href="${esc(st.run)}">the run that wrote it</a>` : '';
    $('tonight-cap').innerHTML =
      `<a href="${REPO}mkt/open_orders.json">mkt/open_orders.json</a> · ` +
      `<a href="${REPO}open_orders.json">open_orders.json</a> (identical) · written ${esc(st.generated_utc || '')}${run}.`;
    $('order-json').textContent = oo.length ? JSON.stringify(oo[oo.length - 1], null, 2) : '[]';
  }

  // ── why ──────────────────────────────────────────────────────────────
  function compare(bt) {
    const keys = [bt.live, 'wheel', 'hold'];
    const ys = Object.keys(bt.stats.wheel.full.years);
    $('compare').innerHTML = table(
      ['$100,000 from ' + bt.start, 'ends at', 'a year', 'volatility', 'Sharpe', 'worst drawdown', ...ys],
      keys.map((k) => {
        const f = bt.stats[k].full;
        return { cls: k === bt.live ? 'hl' : '', cells: [esc(bt.labels[k]), money(f.final), pct(f.cagr_pct),
          pct(f.vol_pct).replace('+', ''), num(f.sharpe), pct(f.max_dd_pct), ...ys.map((y) => pct(f.years[y]))] };
      }));
    $('compare-cap').textContent =
      `${bt.start} to ${bt.end} (${ys[ys.length - 1]} to date). Same engine and data as 1.4, carried forward; ` +
      `options filled at mid ∓ ${bt.kappa} × half-spread, the fill 1.4 measured.`;
    const W = bt.stats[bt.live], H = bt.stats.hold;
    $('honest').innerHTML =
      `<b>Read it as a lower-risk way to own AAPL, not as a way to beat it.</b> Most of the lead over holding comes ` +
      `from 2022, when the stock fell 28%. Counted from January 2023, holding made ${pct(H.since2023.ret_pct, 0)} ` +
      `to the strategy's ${pct(W.since2023.ret_pct, 0)}, with about the same Sharpe (${num(H.since2023.sharpe)} vs ` +
      `${num(W.since2023.sharpe)}): short calls give up the top of a rally. Since October 2025 — data pulled after the ` +
      `rules were written — it made ${pct(W.new.ret_pct)} against ${pct(H.new.ret_pct)}, with a worst drawdown of ` +
      `${pct(W.new.max_dd_pct)} against ${pct(H.new.max_dd_pct)}.`;
  }

  const AX = { showgrid: true, gridcolor: '#EFEBE2', zeroline: false, showline: false, ticks: '',
    tickfont: { family: MONO, size: 11, color: '#6E6A63' } };

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
      margin: { l: 72, r: 200, t: 16, b: 36 },
      xaxis: Object.assign({}, AX, { range: [x[0], x[x.length - 1]], showspikes: true, spikemode: 'across',
        spikethickness: 1, spikecolor: C.faint, spikedash: 'solid' }),
      yaxis: Object.assign({}, AX, { tickprefix: '$', tickformat: ',.0f' }),
      annotations: ann,
    }, { displaylogo: false, responsive: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'] });
  }

  function log(rows) {
    if (!rows || !rows.length) {
      $('logtable').innerHTML = '<pre class="json">no runs yet</pre>';
      return;
    }
    $('logtable').innerHTML = table(['decided', 'for', 'AAPL close', 'orders', 'decision'],
      rows.slice().reverse().map((r) => ({ cells: [esc(r.decided), esc(r.for), num(r.close),
        r.orders && r.orders.length ? r.orders.map(esc).join('<br>') : '—', esc(r.why)] })),
      { left: [1, 3], wrap: [4] });
  }

  function prov(bt) {
    $('prov').innerHTML = `AAPL (conid 265598) · opening book $100,000 · backtest ${esc(bt.start)} – ${esc(bt.end)} ` +
      `on 1.4's engine and LSEG data · <a href="${REPO}gearwheel/orders.py">gearwheel/orders.py</a>`;
  }

  get('gear/backtest.json').then((bt) => { prov(bt); compare(bt); navChart(bt); })
    .catch((e) => { $('compare-cap').textContent = 'Could not load the backtest: ' + e.message; });
  get('gear/state.json', true).then(tonight)
    .catch(() => { $('tonight-lede').textContent = 'No nightly run has written a decision yet.'; });
  get('gear/log.json', true).then(log).catch(() => log([]));
})();
