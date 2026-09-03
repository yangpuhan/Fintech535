# Fintech 535

MENG FinTech · Algorithmic Trading II

One site, built up over the semester. Each assignment adds a module and a
section rather than a new project.

## Assignments

| # | Module | Published | What it does |
|---|---|---|---|
| 1.1 | [`options_surface_lab/`](options_surface_lab/) | **https://yangpuhan.github.io/Fintech535/** | Expired UUUU option contracts from LSEG. Listed options are a sparse cloud, not a filled sheet — and the closing mid is not a price anyone paid. |

---

## How it is put together

GitHub Pages serves files and nothing else, so there is no server to compute a
figure on demand. Every (as-of date, right) combination is rendered ahead of
time to one JSON bundle, and the page fetches the bundle it needs when a
control changes.

The controls all stay live — as-of date, call/put, and the three layer
switches — because the switching happens in the browser. A viewer loads about
90 KB per view rather than the whole 10 MB.

Python does the data work and the drawing; the browser does the switching.
There is no second copy of the plotting logic.

```
options_surface_lab/
  ric.py       build and parse OPRA RICs for expired contracts
  fetch.py     the LSEG pull  →  data.pkl        (run once, by hand)
  data.pkl     the cache: 626 contracts, 12 expiries, 7 fields
  panel.py     pickle → tidy long table → one row per (date, contract) → statistics
  theme.py     the graphical identity, and the two field roles
  figures.py   every Plotly figure
  build.py     → docs/                            (what Pages serves)
```

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m options_surface_lab.build      # rebuild docs/
python -m http.server --directory docs   # then open localhost:8000
```

Committing and pushing `docs/` republishes the site.

To re-pull from LSEG — needs Workspace running and an app key in
`lseg-data.config.json`, which is gitignored:

```bash
python -m options_surface_lab.fetch
```

---

## Two things the brief gets wrong about the data

**There is no settlement price.** `SETTLE` is rejected on this RIC space —
`the universe does not support the following fields: [SETTLE]` — and
`TR.SettlementPrice` comes back empty. The brief now says as much, and names
`MID_PRICE`, the closing NBBO midpoint, as the mark. That is what this app
uses.

**The RIC scheme in Appendix A is wrong for puts.** It says the `^` suffix
"repeats the month letter". For calls it does. For puts it does not:

```
UUUUT212601500.U^T26   put code in the suffix    →  universe is not found
UUUUT212601500.U^H26   call code in the suffix   →  resolves
        ↑         ↑
        T = Aug put (body)
                  H = Aug call (chain suffix)
```

The suffix names the expiry *chain*, and the chain is keyed off the call code
whatever the contract's own right is. Following the appendix literally returns
zero puts — with no error, just an empty frame. `ric.py` builds the suffix from
the call code and parses the right off the body.

---

## What the numbers say

Busiest session in the window, 2026-07-10, calls:

| | |
|---|---|
| listed cells on the grid | 226 |
| carried a closing mid | 150 |
| actually traded | 114 |
| **% mid with no trade** | **44%** |
| **median \|MID_PRICE − TRDPRC_1\|** | **$0.033** (5%) |
| never traded, of the whole grid | 63% |
| nothing quoted at all | 20% |

30 of those 114 trades have no mid at all — by the close the bid had gone away,
so there was nothing left to take a midpoint of. The holes are not only in the
mark; they are in the evidence too.

---

## Graphical identity — "Paper"

Warm paper ground, ink text, two accents. Serif for prose, mono for anything
numeric. Defined once in `theme.py`.

The accent assignment carries the argument: the **mid** (`MID_PRICE`) is nearly
everywhere, so it gets muted Prussian blue; a **real trade** (`TRDPRC_1`) is
rare, so it gets vermilion. The rare thing gets the loud colour, so the eye
lands on how few real prints there are.

```
PAPER  #FAF8F3      MARK   #2D5F7C   Prussian blue · MID_PRICE
CARD   #FFFFFF      PRINT  #C1440E   vermilion · TRDPRC_1
RULE   #DDD7CA      WASH   #EFEBE2   a listed cell that never quoted
INK    #1A1A1A      MUTED  #6E6A63
```
