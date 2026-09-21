# Fintech 535

MENG FinTech · Algorithmic Trading II

One site, built up over the semester. Each assignment adds a module and a
page rather than a new project.

**Published: https://yangpuhan.github.io/Fintech535/**

## Assignments

| # | Module | Page | What it does |
|---|---|---|---|
| 1.2 | [`covered_call/`](covered_call/) | **[/](https://yangpuhan.github.io/Fintech535/)** | Ten weeks of a mechanical AAPL covered call on hourly LSEG bars: blotter, ledger, Reg T, and the evidence for filling at the mid. |
| 1.1 | [`options_surface_lab/`](options_surface_lab/) | [/1.1/](https://yangpuhan.github.io/Fintech535/1.1/) | Expired UUUU option contracts. Listed options are a sparse cloud, not a filled sheet — and the closing mid is not a price anyone paid. |
|  | — | [/data.html](https://yangpuhan.github.io/Fintech535/data.html) | Provenance, chain resolution, and the live/no-live connection state. |

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

python -m covered_call.build          # data.pkl  → docs/book.js
python -m options_surface_lab.build   # data.pkl  → docs/1.1/
python covered_call/local_server.py   # http://127.0.0.1:8765/
```

Committing and pushing `docs/` republishes the site.

To re-pull from LSEG — needs Workspace running and an app key in
`lseg-data.config.json`, which is gitignored:

```bash
python -m covered_call.fetch
python -m options_surface_lab.fetch
```

The published site never touches LSEG. `docs/data.html` says so, and says it
out loud on github.io rather than failing quietly.

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

The three chart series were checked rather than chosen by eye: all-pairs
lightness, chroma, normal-vision separation and contrast against the plot
surface pass. Blue↔green sits in the colour-vision-deficiency warn band, so
every series also carries a dash pattern, a direct end-label, and a row in the
ledger table — identity is never colour alone.
