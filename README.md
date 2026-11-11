# Fintech 535

MENG FinTech · Algorithmic Trading II

One site, built up over the semester. Each assignment adds a module and a
page rather than a new project.

**Published: https://yangpuhan.github.io/Fintech535/**

## Assignments

| # | Module | Page | What it does |
|---|---|---|---|
| 1.4 | [`wheel/`](wheel/) | **[/](https://yangpuhan.github.io/Fintech535/)** | A mechanical wheel on AAPL — cash-secured puts, assignment, covered calls, called away — Jan 2022 – Sep 2025, a $100,000 cash account, fills measured on the hourly tape. |
| 1.3 | [`pmcc/`](pmcc/) | [/1.3/](https://yangpuhan.github.io/Fintech535/1.3/) | A mechanical Poor Man's Covered Call on AAPL, Jan 2022 – Oct 2026, daily LSEG closes, against a covered call writing the identical calls. |
| 1.2 | [`covered_call/`](covered_call/) | [/1.2/](https://yangpuhan.github.io/Fintech535/1.2/) | Ten weeks of a mechanical AAPL covered call on hourly LSEG bars: blotter, ledger, Reg T, and the evidence for filling at the mid. |
| 1.1 | [`options_surface_lab/`](options_surface_lab/) | [/1.1/](https://yangpuhan.github.io/Fintech535/1.1/) | Expired UUUU option contracts. Listed options are a sparse cloud, not a filled sheet — and the closing mid is not a price anyone paid. |
|  | — | [/data.html](https://yangpuhan.github.io/Fintech535/data.html) | Provenance, chain resolution, and the live/no-live connection state. |
|  | [`nightly/`](nightly/) | [/nightly/](https://yangpuhan.github.io/Fintech535/nightly/) | In-class activity: AAPL against SPY, price and 21-day realised volatility, re-queried from LSEG and redrawn by a GitHub Action every weeknight. |

---

## 1.4 — The Wheel

Sell cash-secured puts; if assigned, sell covered calls on the shares; if
called away, start again. AAPL, every session from 3 Jan 2022 to 30 Sep 2025,
in a $100,000 cash account. The same engine also runs the wheel's two halves
on their own — **put-write** (puts forever, settled in cash) and
**buy-write** (shares plus calls forever) — so the comparison says what the
switching itself does.

```
wheel/
  fetch.py    the LSEG pull  ->  data.pkl                   (run once, by hand)
  data.pkl    2,560 monthly AAPL puts + calls, daily; the hourly year LSEG
              keeps (Nov 2025 - Oct 2026) for the fill test; stock, T-bill,
              dividends, earnings dates
  greeks.py   Black-Scholes IV and delta for both rights (puts by parity on 1.3's calls)
  fills.py    the fill assumption, measured: where real prints land in the spread
  book.py     the rules -> blotter, daily ledger, controls, stats, look-ahead test
  build.py    -> docs/wheel.js                              (what Pages serves)
```

### The rule

| | |
|---|---|
| **Timing** | decide on the t-1 close, fill on the t close (daily bars, as 1.3) |
| **Put** | no shares: first monthly with >= 21 days, delta closest to -0.30, as many contracts as the cash secures |
| **Assigned** | buy 100 shares a contract at the strike; basis = strike - that put's premium - calls sold since |
| **Call** | shares: one call per 100, first monthly >= 21 days, delta closest to 0.30 among strikes >= basis |
| **Called away** | deliver at the strike, back to cash and puts |
| **Roll** | buy back at 50% of the premium and sell the next one, on a later expiry, in the same order; otherwise hold to expiry |
| **Early** | call before an ex-date if time value < dividend; put if time value < interest on the strike |
| **Fills** | sell at mid - k x half-spread, buy at mid + k x half-spread; k measured on the hourly tape |
| **Cash** | earns the 3-month T-bill, including the cash securing a put |

### The fill, measured

35,274 hourly prints on 257 out-of-the-money AAPL monthlies: 85.6% inside
their own quote, symmetric around the mid (21.6% at the bid, 21.8% at the
ask, 28.7% within a quarter-spread of the mid). The average print gives up
**k = 0.57** of the half-spread, so the book sells at mid - 0.57 x half and
buys at mid + 0.57 x half. The same statistic on the daily tape is 0.55-0.63
in every backtest year. Every one of the book's 107 option fills was in a
contract that traded that day (median 4,444 contracts; the order a median
0.14% of it), and on every day the contract's own range reached the fill.

### What it found

| $100,000, 3 Jan 2022 - 30 Sep 2025 | wheel | buy & hold | put-write | buy-write | T-bills |
|---|---|---|---|---|---|
| final | **$162,273** | $142,052 | $109,795 | $113,849 | $117,028 |
| CAGR | **13.81%** | 9.83% | 2.53% | 3.53% | 4.29% |
| volatility | 19.6% | 28.8% | 12.9% | 17.3% | 0.2% |
| Sharpe | **0.55** | 0.32 | -0.07 | 0.04 | - |
| max drawdown | -23.4% | -32.9% | -23.1% | -23.7% | 0 |

The thesis (short volatility against paid-up collateral: lower risk, higher
Sharpe, lower return) held on risk and Sharpe and failed on return — the
wheel also out-earned the stock. But not for the reason given. The 0.30-delta
put was priced above realised vol in 32 of 43 months (+1.3 pts) and the call
below it (-2.3 pts); selling either every month and holding to expiry lost
money, and both halves of the wheel run alone trailed T-bills. The edge is
timing: shares arrive by assignment after falls and the never-below-basis
rule keeps them through the rebounds. It is path-sensitive — re-running the
rule with fills a few cents different moves the Sharpe between 0.37 and 0.55
(the paths part on 3 Oct 2022, when the basis sat 2.6 cents above a strike) —
though every re-run still beats buy-and-hold's 0.32. Holding every option to
expiry instead of rolling at 50% returned 9.43% (Sharpe 0.33); dropping the
basis rule, Sharpe 0.25.

---

## 1.3 — Poor Man's Covered Call

Long one deep in-the-money January LEAPS call instead of 100 shares, short
one monthly call against it, every session from 3 Jan 2022 to 7 Oct 2026.
The covered-call benchmark writes **exactly the same calls** on the same days
at the same fills, so every dollar between the two books is the long leg.

```
pmcc/
  fetch.py    the LSEG pull  ->  data.pkl                   (run once, by hand)
  data.pkl    1,817 AAPL calls (monthlies + Jan LEAPS), daily; stock, T-bill,
              dividends, earnings dates
  greeks.py   Black-Scholes implied vol and delta from the closing mid
  book.py     the rules -> blotter, four ledgers, stats, look-ahead test
  build.py    -> docs/pmcc.js                               (what Pages serves)
```

Daily, not hourly: LSEG's hourly option history only reaches back a year, and
a strategy with a one-year long leg needs several. The cost is that every
quote is a close, so the book **decides on the t-1 close and fills on the t
close**. `book.lookahead_test` proves it: truncate every price series at a
date, re-run from scratch, and the blotter up to that date is identical.

### The rule

| | |
|---|---|
| **Long** | nearest January expiry with >= 300 days left, strike with delta closest to 0.80; roll at <= 120 days |
| **Short** | first monthly with >= 21 days left, delta closest to 0.30, subject to the gap rule; hold to expiry |
| **Gap rule** | K_short - K_long >= mid_long - mid_short, so a gap through the short strike can never lose money |
| **Expiry** | in the money -> settled at intrinsic; early exercise assumed on the eve of an ex-date when time value < dividend |
| **Fills** | closing mid; results also shown paying the half-spread on every option fill |
| **Delta** | computed, not LSEG's DELTA field, which is blank on 426 tradeable quotes in 2022 |

### What it found

| per unit / same $23,000 account | PMCC | covered call | stock |
|---|---|---|---|
| capital required | **$8,001** | $22,810 | $18,201 |
| P&L at mid | +$5,089 | +$10,915 | +$15,934 |
| return on capital, per year | 10.89% | 8.56% | 14.12% |
| same account CAGR (idle cash in T-bills) | **7.07%** | **9.17%** | 12.34% |
| max drawdown, same account | -19.5% | -27.5% | -27.1% |
| Sharpe | 0.26 | 0.34 | 0.45 |

The PMCC uses 35% of the capital and is, on the same money, a smaller covered
call rather than a cheaper one. The capital it frees is not free: over the
five completed LEAPS the financing charge inside the option price used up
while held was $2,758, and the T-bill interest on the freed cash $2,781.
Two PMCCs in the same account (as many as it funds) returned 9.68% a year with
31% volatility and a -40% drawdown. The 57 short calls lost $5,019 net in both
books while AAPL rose 85%. The headline settings are the textbook defaults and
turn out to be the weakest PMCC of a 3x3 delta grid; the PMCC trails the
covered call in every cell.

---

## 1.2 — Covered Call Backtest

Long 100 AAPL, short 1 weekly call, held to expiry, ten consecutive weeks
(6 Jul – 11 Sep 2026), no discretion anywhere in the loop.

```
covered_call/
  ric.py            build and parse OPRA RICs for expired contracts
  fetch.py          the LSEG pull  →  data.pkl        (run once, by hand)
  data.pkl          the cache: 208 call contracts, 10 weekly expiries, hourly
  book.py           the rules → blotter, ledger, Reg T          (all the maths)
  fit.py            mid vs TRDPRC_1: regression, and the fill-assumption tests
  build.py          → docs/book.js                     (what Pages serves)
  local_server.py   serve docs/ plus /api/status        (a tool, not the site)
```

The page is **hand-written** `docs/index.html` + `docs/app.js`. Python computes
the whole run once and bakes it into `docs/book.js` as one JSON blob; the
browser draws and never calculates. No Node, no build step.

### The rule

| | |
|---|---|
| **Entry** | first trading session of the expiry week, at the 14:00 UTC bar (10:00 ET) |
| **Stock** | if flat, buy 100 shares at the print; if already long, the basis carries |
| **Strike** | sell 1 call expiring that Friday, at the lowest listed strike ≥ spot |
| **Fill** | option at mid = (BID+ASK)/2, stock at the print; no bid/ask → skip the week |
| **Combo** | both legs or neither — never long stock with no call against it |
| **Expiry** | wait through it. settle ≤ K → expire, keep shares and premium. settle > K → assigned at K, flat |
| **Reg T** | initial 50% of stock LMV, maintenance 25%, covered call adds $0 |

### What it found

| | |
|---|---|
| final NAV on $20,000 | **$21,201.70** (+6.01% over ten weeks) |
| buy and hold, same bar, same money | **+$1,970.00** (+9.85%) |
| **cost of writing the calls** | **−$768.30** |
| premium collected | $3,472.00 |
| intrinsic handed back on assignment | $5,144.00 → the option leg **lost $1,672** |
| assigned / expired | 8 / 2 |
| mid vs TRDPRC_1 | R² = **0.9988** on 6,692 hourly bars, slope 0.9979 |
| prints inside their own quote | 87.0% |
| min Reg T available funds | $3,266.95 — never negative |

Eight of ten weeks were assigned because the *strike grid*, not the rule, set
the risk: AAPL weeklies list every $2.50 and AAPL traded near $310, so
"nearest OTM" is arithmetically pinned 0.1–0.8% above spot, well inside an
average AAPL week.

The single most instructive week is 31 July. The rule wrote the 340 call for
$6.02 — double its usual premium — and had no idea why. Apple reported at
16:31 on Thursday 30 July, one session before that call expired. The market
had priced the event; the rule collected the premium blind, kept all of it,
and the shares underneath lost $2,916.

---

## Two more things the briefs get wrong about the data

Assignment 1.1 found that the expired-contract `^` suffix uses the **call**
month code even for puts. Two more, from 1.2:

**The day is zero-padded.** The 1.2 brief says "DAY not zero-padded" and gives
single-digit examples. They do not resolve:

```
AAPLH72633000.U^H26    bare day    →  universe is not found
AAPLH072633000.U^H26   padded day  →  resolves
```

The brief's one sample that *does* resolve has a two-digit day, so it cannot
distinguish the conventions. Two Fridays in this window have single-digit
days — 7 Aug and 4 Sep — so following the appendix literally silently drops
two of the ten weeks.

**`LOW_1` on the hourly stock tape is not the low.** The 19:00 UTC bar on
10 Jul reports a low of 280.11 on a day AAPL never traded below 312. Stray
prints in the consolidated low, not the stock. Nothing in the book touches
`LOW_1`, but the first fetcher banded its strike requests off it and asked for
three times as many contracts as it needed.

---

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m wheel.build                 # data.pkl  → docs/wheel.js
python -m pmcc.build                  # data.pkl  → docs/1.3/pmcc.js
python -m covered_call.build          # data.pkl  → docs/1.2/book.js
python -m options_surface_lab.build   # data.pkl  → docs/1.1/
python covered_call/local_server.py   # http://127.0.0.1:8765/
```

Committing and pushing `docs/` republishes the site.

To re-pull from LSEG — needs Workspace running and an app key in
`lseg-data.config.json`, which is gitignored:

```bash
python -m wheel.fetch
python -m pmcc.fetch
python -m covered_call.fetch
python -m options_surface_lab.fetch
```

The published pages never touch LSEG. `docs/data.html` says so, and says it
out loud on github.io rather than failing quietly. The one page that changes
on its own, `/nightly/`, is redrawn by a GitHub Action, not by the browser.

---

## Nightly — the page that redraws itself

An in-class activity: the other pages are pulled once and baked, while
`/nightly/` is re-queried from LSEG every weeknight and committed back.

```
.github/workflows/nightly.yml   22:30 UTC Mon-Fri, or "Run workflow" on the Actions tab
nightly/refresh.py              platform session -> 2 get_history requests (AAPL.O, SPY)
                                -> docs/nightly/aapl-vol.html (Plotly) + docs/nightly/meta.json
docs/nightly/index.html         the page: frames the chart, reads meta.json for the tiles
```

A GitHub runner has no Workspace app, so the workflow opens an LSEG
*platform* session from three repository secrets: `LSEG_APP_KEY`,
`LSEG_USERNAME` and `LSEG_PASSWORD`. Run by hand with those unset,
`python -m nightly.refresh` uses the Workspace desktop session in
`lseg-data.config.json`. Pages deploys from `main:/docs`, so the bot's commit
is the deploy. The course server pushes `price_history.json` to the same
branch every day, so the job rebases before it pushes. The VIX would be the
natural benchmark, but this account is not permissioned for CBOE indices, so
SPY stands in.

---

## Graphical identity — "Paper"

Warm paper ground, ink text. Serif for prose, mono for anything numeric.
Established in 1.1 and carried forward.

```
PAPER  #FAF8F3      NAV        #1D6091   Prussian blue
CARD   #FFFFFF      MARGIN     #C1440E   vermilion
RULE   #DDD7CA      AVAILABLE  #2C7A2C   moss
INK    #1A1A1A      QUOTE      #7A6A55   drab
```

1.1 assigned its two accents by argument: the mid is everywhere so it got the
quiet colour, a real trade is rare so it got the loud one. 1.2 keeps the same
logic — the requirement lines are the thing that can stop you trading, so they
are the ones in vermilion.

1.4 keeps the logic: vermilion is the wheel, moss is cash with puts sold on
it, blue is shares (solid with calls written, dotted bare), and the wheel's own
put and call legs wear moss and blue on every chart.

1.3 compares four books, and encodes them by structure rather than by four
unrelated hues: colour is what is held long (blue shares, vermilion LEAPS),
dash is whether calls are written against it (solid yes, dotted no). Two hues
pass the palette validator outright; the dash carries the other half.

The 1.2 chart series were checked rather than chosen by eye: all-pairs
lightness, chroma, normal-vision separation and contrast against the plot
surface pass. Blue↔green sits in the colour-vision-deficiency warn band, so
every series also carries a dash pattern, a direct end-label, and a row in the
ledger table — identity is never colour alone.
