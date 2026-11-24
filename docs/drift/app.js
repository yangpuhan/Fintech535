/* Earnings Surprise Drift. Draws drift/tracker.json, which the nightly Action
   writes (python -m drift.tracker); the page computes nothing itself. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const css = getComputedStyle(document.documentElement);
  const v = (n) => css.getPropertyValue(n).trim();
  const C = { sig: v('--s-sig'), ref: v('--s-ref'), spy: v('--s-spy'), bad: v('--s-bad'),
    ink: v('--ink'), muted: v('--muted'), faint: v('--faint'), rule: v('--rule') };
  const MONO = "'Source Code Pro','SF Mono',Menlo,monospace";
  const BASE = new URL('.', document.currentScript.src).href;
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const pct = (x, d = 1) => (x == null ? '—' : (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toFixed(d) + '%');
  const cls = (x) => (x == null ? '' : x > 0 ? 'pos' : x < 0 ? 'neg' : '');
  const date = (s) => (s ? new Date(s + 'T00:00:00').toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' }) : '—');

  function table(id, head, rows, left = [0]) {
    const th = head.map((h, i) => `<th class="${left.includes(i) ? 'l' : ''}">${h}</th>`).join('');
    const tr = rows.map((r) => `<tr class="${r.hl ? 'hl' : ''}">` + r.cells.map((c, i) =>
      `<td class="${left.includes(i) ? 'l' : ''} ${c.cls || ''}">${c.html != null ? c.html : esc(c)}</td>`).join('') + '</tr>').join('');
    $(id).innerHTML = `<thead><tr>${th}</tr></thead><tbody>${tr}</tbody>`;
  }

  function header(j) {
    const s = j.status, paused = s.short.tripped, wrong = s.long.tripped || s.surprise.tripped;
    $('prov').innerHTML = `Tracker through ${esc(date(j.through))} · rebuilt ${esc(j.generated_utc)} · ` +
      `${j.counts.reports} reports by top-20 companies since Jan 2022, ${j.counts.signals} signals ` +
      `(${j.counts.surprise_rate}% of reports moved more than the options priced)`;
    const state = wrong ? ['Thesis wrong', 'a long-window condition has tripped', C.bad]
      : paused ? ['Paused', 'last 20 closed trades average ' + pct(s.short.value, 2) + ': no new trades', C.bad]
      : ['Active', 'every condition holds', C.sig];
    const cards = [
      ['Status tonight', `<span style="color:${state[2]}">${state[0]}</span>`, state[1]],
      ['Signals being followed', j.open.length, j.open.map((t) => `${t.name} ${t.dir} ${pct(t.ret, 1)}`).join(' · ') || 'none'],
      ['Average trade', pct(j.trade.mean, 2), `20 sessions, net of SPY and costs · control ${pct(j.trade.control_mean, 2)}`],
      ['Signals a year', j.counts.per_year, 'in the four earnings seasons'],
    ];
    $('cards').innerHTML = cards.map((c) => `<div class="card"><div class="lab">${c[0]}</div>` +
      `<div class="val">${c[1]}</div><div class="hint">${esc(c[2])}</div></div>`).join('');
    const y = Object.keys(j.universe).sort().pop();
    $('u-now').textContent = `${y}: ${j.universe[y].join(', ')}.`;
  }

  function chart(j) {
    const s = j.tracker.signals, c = j.tracker.control, r = j.tracker.rolling;
    const traces = [
      { x: c.dates, y: c.cum, name: 'control', mode: 'lines', line: { color: C.ref, width: 2, dash: 'dash' },
        hovertemplate: '%{x|%d %b %Y}<br>control, running sum %{y:.1f}%<extra></extra>' },
      { x: s.dates, y: s.cum, name: 'signals', mode: 'lines', line: { color: C.sig, width: 2.6 },
        text: s.name, hovertemplate: '%{x|%d %b %Y} · %{text}<br>signals, running sum %{y:.1f}%<extra></extra>' },
      { x: r.dates, y: r.avg, name: 'last 20', mode: 'lines', xaxis: 'x', yaxis: 'y2',
        line: { color: C.spy, width: 2, dash: 'dot' }, hovertemplate: '%{x|%d %b %Y}<br>last 20 trades %{y:.2f}%<extra></extra>' },
    ];
    const ends = [[s, C.sig, 'signals'], [c, C.ref, 'control']].map(([d, col, lab]) => ({
      x: d.dates[d.dates.length - 1], y: d.cum[d.cum.length - 1], xref: 'x', yref: 'y', text: `${lab} ${pct(d.cum[d.cum.length - 1], 0)}`,
      showarrow: false, xanchor: 'left', xshift: 6, font: { family: MONO, size: 11, color: col } }));
    const lay = {
      margin: { l: 56, r: 92, t: 10, b: 36 }, paper_bgcolor: '#fff', plot_bgcolor: '#fff', showlegend: false,
      font: { family: MONO, size: 11, color: C.muted }, hovermode: 'closest',
      grid: { rows: 2, columns: 1, subplots: [['xy'], ['xy2']], roworder: 'top to bottom' },
      xaxis: { type: 'date', gridcolor: '#F1EDE4', linecolor: C.rule, matches: 'x' },
      yaxis: { domain: [0.36, 1], title: { text: 'running sum of trades, %' }, gridcolor: '#F1EDE4', zerolinecolor: C.faint, ticksuffix: '%' },
      yaxis2: { domain: [0, 0.26], title: { text: 'last 20, %' }, gridcolor: '#F1EDE4', zerolinecolor: C.ink, zerolinewidth: 1.2, ticksuffix: '%' },
      annotations: ends,
      shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y2', y0: 0, y1: 0, line: { color: C.bad, width: 1, dash: 'dash' } }],
    };
    Plotly.newPlot('chart', traces, lay, { displayModeBar: false, responsive: true });
    $('chart-cap').textContent = `Each point is one trade, added on its entry date: the stock's return less SPY's over the 20 sessions, ` +
      `in the direction of the earnings move, after 20 bp of costs; open trades count at their return so far. ` +
      `The red dashed line in the lower panel is zero: below it, the rule opens no new trades.`;
  }

  function tables(j) {
    table('t-reports', ['Company', 'Reaction day', 'Options priced', 'Moved', 'Signal'],
      j.latest_reports.map((r) => ({ hl: r.signal, cells: [r.name, date(r.reaction), '±' + r.implied.toFixed(1) + '%',
        { html: pct(r.move, 1), cls: cls(r.move) }, { html: r.signal ? '<span class="pill ok">yes</span>' : '<span class="pill mut">no</span>' }] })));
    table('t-trades', ['Company', 'Side', 'Entered', 'Out', 'Return'],
      j.recent.map((t) => ({ hl: !t.closed, cells: [t.name, t.dir, date(t.entry), t.closed ? date(t.exit) : 'open',
        { html: pct(t.ret, 1), cls: cls(t.ret) }] })));
  }

  function conds(j) {
    const s = j.status;
    const row = (tag, text, now, tripped, label) => `<div class="cond"><div class="tag">${tag}</div><div>${text}</div>` +
      `<div class="now">${now} <span class="pill ${tripped ? 'bad' : 'ok'}">${tripped ? label : 'holds'}</span></div></div>`;
    $('conds').innerHTML =
      row('1 · pause', `The average of the last 20 closed trades falls below zero. No new trades until it is back above.`,
        `${pct(s.short.value, 2)}`, s.short.tripped, 'paused') +
      row('2 · wrong', `The average of every trade closed in the last two years falls below zero (about 55 trades).`,
        `${pct(s.long.value, 2)} · ${s.long.n} trades`, s.long.tripped, 'wrong') +
      row('3 · wrong', `Fewer than 20% of reports move more than the options priced, two seasons running: the options have caught up and there is nothing left to trade (the long-run share is about 36%).`,
        s.surprise.seasons.map((q, i) => `${q} ${s.surprise.value[i]}%`).join(' · '), s.surprise.tripped, 'wrong');
  }

  function backtest(j) {
    const b = j.backtest, yrs = Object.keys(b.strategy.years);
    const line = (lab, x, hl) => ({ hl, cells: [lab, pct(x.cagr), x.vol.toFixed(1) + '%', x.sharpe == null ? '—' : x.sharpe.toFixed(2),
      { html: pct(x.max_dd), cls: 'neg' }].concat(yrs.map((y) => ({ html: pct(x.years[y], 0), cls: cls(x.years[y]) }))) });
    table('t-bt', ['', 'A year', 'Volatility', 'Sharpe', 'Worst drawdown'].concat(yrs),
      [line('The rule, idle cash in T-bills', b.strategy, true), line('SPY, bought and held', b.spy), line('T-bills', b.tbills)]);
    $('bt-cap').textContent = `Daily, 3 Jan 2022 to ${date(j.through)}; ${yrs[yrs.length - 1]} is to date. Every signal is taken: ` +
      `the pause in condition 1 governs new trades from here on and is not applied to the history. Sharpe is the return over the ` +
      `3-month T-bill rate divided by its volatility, annualised.`;
    const t = j.trade;
    $('alpha-lede').innerHTML = `<b>About ${pct(t.mean, 1)} a trade</b> over 20 sessions, net of SPY and after costs ` +
      `(median ${pct(t.median, 2)}, ${t.win}% of trades positive), against ${pct(t.control_mean, 1)} for the same trade after reports ` +
      `that stayed within the options' estimate. At ${Math.round(j.counts.per_year)} trades a year and 25% of equity each, ` +
      `the book earned about ${pct(b.strategy.cagr - b.tbills.cagr, 0)} a year over cash, with a worst drawdown of ` +
      `${pct(b.strategy.max_dd, 0)}.`;
  }

  fetch(new URL('tracker.json', BASE).href + '?t=' + Date.now(), { cache: 'no-store' })
    .then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then((j) => { header(j); chart(j); tables(j); conds(j); backtest(j); })
    .catch((e) => { $('prov').textContent = 'Could not load the tracker: ' + e.message; });
})();
