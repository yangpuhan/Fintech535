# Fintech 535

MENG FinTech · Algorithmic Trading II

One Reflex site, built up over the semester. Each assignment adds a module and
a page rather than a new project, so `rxconfig.py` and `requirements.txt` stay
at the root and everything shares the same theme.

## Assignments

| # | Module | What it does |
|---|---|---|
| 1.1 | [`options_surface_lab/`](options_surface_lab/) | Expired UUUU option contracts from LSEG. Listed options are a sparse cloud, not a filled sheet — and the number an exchange marks a contract at is not the price anyone paid. |

Each module keeps the instructor's brief next to the code — 1.1's is in
[`options_surface_lab/README.md`](options_surface_lab/README.md).

**Published site:** https://yangpuhan.github.io/Fintech535/

---

## Two builds of the same thing

Reflex is full-stack — the figures live in `rx.State` on a Python backend and
reach the browser over a websocket. GitHub Pages serves files and nothing else,
so the Reflex app cannot run there.

So there are two builds, and neither duplicates the plotting logic:

| | Reflex app | Static build |
|---|---|---|
| entry | `reflex run` | `docs/` on GitHub Pages |
| figures | `option_surface_plots.py` | the same functions, dumped to JSON |
| controls | server-side event handlers | the same controls, switched in the browser |

`build_site.py` calls the identical figure functions and writes one JSON bundle
per (as-of date, right); the page fetches the bundle it needs. Every control on
the Reflex page still works on the static one.

---

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
reflex run
```

Then open http://localhost:3000. The page reads
`options_surface_lab/option_surface_data.pkl`, which is committed — no LSEG
session or credentials needed to render the site.

For a static version with no dev server (useful for a demo):

```bash
python -m options_surface_lab.build_preview
open options_surface_lab/options_surface_preview.html
```

To rebuild the published site into `docs/` (commit and push to deploy):

```bash
python -m options_surface_lab.build_site
```

To re-pull from LSEG (needs Workspace running and a valid app key in
`lseg-data.config.json`, which is gitignored):

```bash
python -m options_surface_lab.option_surface_fetch
```

---

## The field the brief asks for does not exist

The brief names `SETTLE` as the exchange mark. On this universe LSEG answers:

```
TSCC.QS.UserRequestError.90006
The universe does not support the following fields: [SETTLE]
```

Every `SETTLE` column came back all-NaN and was dropped by the starter's
`dropna(how="all", axis=1)`, which is why the original cache held nothing but
`TRDPRC_1` — and why the two required statistics were `0%` and `n/a`.

`THEO_VALUE` is the substitute. It plays exactly the role the brief describes
for SETTLE — a model-ish number that prints on more series than trades do:

| as-of | listed call cells | carried a mark | actually traded |
|---|---|---|---|
| 2026-06-12 | 275 | 142 | 80 |
| 2026-07-10 | 226 | 208 | 114 |
| 2026-08-14 | 85 | 83 | 64 |

`BID` and `ASK` came along on the same pull, so "what would you actually get
filled at" has a real answer rather than a shrug, and `IMP_VOLT` is already
cached for the volatility surface in 1.2.

## And the RIC scheme is wrong for puts

Appendix A says the `^` suffix "repeats the month letter and year". For calls
it does. For puts it does not, and following the brief returns
`TS.Interday.UserRequestError.70005, The universe is not found` on every put:

```
UUUUT212601500.U^T26   put code in the suffix    -> not found
UUUUT212601500.U^H26   call code in the suffix   -> resolves
        ↑         ↑
        T = Aug put (body)
                  H = Aug call (chain suffix)
```

The suffix names the expiry *chain*, which is keyed off the call code whatever
the contract's own right. The first pull followed the brief and came back with
313 calls and zero puts.

**Roles used throughout the code:** `THEO_VALUE` is the mark, `TRDPRC_1` is
evidence that someone traded. Both names live in
[`option_surface_theme.py`](options_surface_lab/option_surface_theme.py) as
`MARK_FIELD` / `PRINT_FIELD` so the naming never drifts.

---

## Files

| File | What it is |
|---|---|
| `options_surface_app.py` | The Reflex page |
| `option_surface_data.pkl` | LSEG cache — 313 expired contracts, 8 fields, 12 expiries |
| `option_surface_utils.py` | RIC parsing, tidy/long reshape, sparsity statistics |
| `option_surface_plots.py` | Every Plotly figure |
| `option_surface_theme.py` | The palette and field roles, in one place |
| `option_surface_fetch.py` | The LSEG pull (only runs if you ask it to) |
| `build_preview.py` | Static HTML build of the same figures |

`class_1.py` is the original in-class starter, kept for reference. It is no
longer the Reflex entry point — `rxconfig.py` points at
`options_surface_lab.options_surface_app`.

---

## Graphical identity — "Paper"

Warm paper ground, ink text, two accents, serif for prose and mono for
anything numeric. Defined once in `option_surface_theme.py`.

The accent assignment carries the argument: the **mark** (`THEO_VALUE`) is
everywhere, so it gets muted Prussian blue; a **real trade** (`TRDPRC_1`) is
rare, so it gets vermilion. The rare thing gets the loud colour, so the eye
lands on how few real prints there are.

```
PAPER  #FAF8F3      MARK   #2D5F7C   Prussian blue
CARD   #FFFFFF      PRINT  #C1440E   vermilion
RULE   #DDD7CA      WASH   #EFEBE2   a listed cell that never quoted
INK    #1A1A1A      MUTED  #6E6A63
```
