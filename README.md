# Memoria di progetto curata — git-native, token-minimal

Una **memoria di progetto curata** che vive dentro qualsiasi codebase: una
knowledge base markdown di decisioni e note, versionata in git, che cresce da
sola a ogni merge e consuma **il minimo di token possibile**.

Il principio è uno: **tutto ciò che è deterministico lo fa il codice; l'LLM
tocca solo la sintesi.** Il costo in token è proporzionale al *cambiamento*, non
alla *dimensione* del wiki.

> Contesto completo di design: [`brief-progetto-memoria-wiki.md`](brief-progetto-memoria-wiki.md)
> · spec MVP: [`spec-memoria-wiki-mvp.md`](spec-memoria-wiki-mvp.md)
> · primer per Claude Code: [`CLAUDE.md`](CLAUDE.md).

## Architettura

```
THIN LLM LAYER    → compile(source) · reconcile(diff, pagine)   [contesto minimo]
                       core/reconcile.py  (Fase 2 — STUB, l'unica chiamata LLM)
CORE CLI (0 token) → init · index · search(BM25) · lint · graph  (core/mem.py)
                       change-detect (Fase 1, deterministica)    (core/change_detect.py)
STORAGE (git)      → /.memory/ : raw/ · wiki/ · schema.md · index.md · log.md · index/
```

### Layout del repo

```
bin/mem             # wrapper: mette `mem` sul PATH (auto-discovery di .memory/)
install.sh          # setup plug-and-play (link su PATH + init + hook + smoke test)
core/
  mem.py            # CLI unica: init · index · search · lint · graph · detect ·
                    #            reconcile · ingest · install-hooks · merge
  change_detect.py  # Fase 1 del reconcile: COSA toccare (SHA-256 + 3 segnali), 0 token
  reconcile.py      # Fase 2 del reconcile: COME modificare (STUB chiamata LLM)
  memlib/           # libreria condivisa, stdlib only
    frontmatter.py · pages.py · bm25.py · graph.py · store.py · compile.py
hooks/post-merge    # STUB: al merge su main, processa solo le fonti nuove e committa
plugin/             # thin plugin Claude Code: /mem:ingest · /mem:query · /mem:lint
tests/              # suite unittest (test_core.py) + benchmark (bench.py) + run.py
.memory/            # la memoria di esempio (3 decisioni + 1 concetto già compilati)
  raw/  wiki/{decisions,concepts,entities,synthesis}/  schema.md  index.md  log.md
  index/            # artefatti generati (git-ignored): index.json · bm25.idx · graph.json
```

## Installazione plug-and-play (zero dipendenze, Python 3.9+)

```bash
./install.sh                 # mette `mem` su ~/.local/bin, esegue i test
./install.sh /path/to/repo   # in più: crea .memory/ e installa l'hook lì
```

Poi, in qualsiasi repo:

```bash
mem init .                   # crea .memory/
# droppa una decisione in .memory/raw/, es. 2026-06-08-scelta.md
mem ingest                   # compila le fonti nuove in pagine BOZZA (offline, 0 token)
mem index && mem lint        # ricostruisci gli indici, controlla la salute
mem search "i tuoi termini"  # ricerca BM25
mem detect                   # cosa è cambiato dall'ultimo snapshot (0 token)
mem install-hooks .          # aggancia l'hook al merge su main
```

Senza installare, ogni comando gira anche come `python3 core/mem.py <cmd>`.

### Provare subito sul `.memory/` di esempio

```bash
python3 core/mem.py index                                  # index.json, bm25.idx, graph.json
python3 core/mem.py search "merge hook reconcile" --top 3  # BM25 + filtri + backlink
python3 core/mem.py search "ricerca" --type decision
python3 core/mem.py search "" --backlinks storage-git-native
python3 core/mem.py lint                                   # esce !=0 se trova problemi
python3 core/mem.py graph                                  # hub, orfani, link rotti
```

## Test, valutazione e performance

```bash
python3 tests/run.py         # 25 unit test (unittest, zero dipendenze)
python3 tests/eval.py        # "funziona davvero?": scorecard PASS/FAIL
python3 tests/eval.py --judge  # + giudice di fedeltà LLM (da terminale vero)
python3 tests/bench.py       # benchmark su wiki da 50 → 2000 pagine
```

I **test** provano la correttezza deterministica (frontmatter, wikilink, BM25,
grafo, compile, change-detect, plumbing reconcile, end-to-end CLI).

La **valutazione** (`tests/eval.py`) risponde alla domanda diversa "*la memoria
recupera la cosa giusta?*", con soglie e PASS/FAIL su:
1. **Recupero** — query etichettate (parafrasi, non keyword) → recall@1/@3, MRR;
2. **Salute** — lint pulito, 0 orfani, ogni pagina cita una fonte esistente, link integri;
3. **Anti-drift** — muta una fonte su una copia usa-e-getta e verifica che il
   change-detect la rilevi e ranki #1 la pagina che la cita;
4. **Fedeltà** (opt-in `--judge`) — il modello giudica se ogni claim della pagina
   è sostenuto dalla sua fonte.

Sul `.memory/` di esempio oggi: **recall@1 0.90 · recall@3 1.00 · MRR 0.95**,
salute pulita, anti-drift centrato → `RESULT: PASS`. Funziona anche su una
memoria tua: `python3 tests/eval.py --memory /path/.memory --labels tue.json`.

Performance e limiti onesti in **[`WEAKNESSES.md`](WEAKNESSES.md)**: `search`
resta ~9 ms a 2000 pagine e le pagine candidate restano **costanti (8)** a ogni
scala (località dei token).

### Il cuore: il reconcile in due fasi

**Fase 1 — COSA toccare (deterministica, 0 token).** Rileva le fonti curate
nuove/cambiate (SHA-256, opzionalmente filtrate da un ref git) e per ognuna
seleziona le poche pagine impattate combinando tre segnali: `sources:`, BM25 sul
contenuto, e backlink del grafo.

```bash
python3 core/change_detect.py --update-snapshot   # registra gli hash correnti
python3 core/change_detect.py                      # ora: nessun cambiamento → 0 token
# ...modifica o aggiungi una fonte in .memory/raw/...
python3 core/change_detect.py                      # mostra il "reconcile plan"
```

**Fase 2 — COME modificare (LLM, una chiamata, contesto minimo).** `reconcile`
assembla il contesto minimo (schema + fonte + pagine candidate) e — qui è lo
**stub** — chiamerebbe l'LLM per classificare ogni pagina come
`no-op / update / add / contradiction / deprecate` e applicare patch chirurgiche.
Il plumbing deterministico (apply_patch `str_replace`, status machine, log) è già
reale; manca solo la chiamata al modello.

```bash
mem reconcile                 # dry-run: mostra contesto e stima token
mem reconcile --show-context
```

### Backend LLM — col tuo abbonamento, senza API key

La "chiamata al modello" **non** è l'API Anthropic: la sintesi passa per Claude
Code e usa il tuo abbonamento (es. Max). Due modi, a seconda di dove sei:

- **Interattivo** (dentro una sessione Claude Code): i comandi plugin
  `/mem:ingest` · `/mem:query` — Claude *è* il layer LLM e sintetizza
  direttamente, leggendo il contesto minimo selezionato dal core.
- **Headless** (terminale normale / hook al merge / CI): `mem ingest --backend
  llm` e `mem reconcile --apply` shellano `claude -p` ([core/memlib/llm.py](core/memlib/llm.py)),
  anch'esso sul tuo abbonamento. L'SDK `anthropic` (con API key) serve solo dove
  Claude Code non è installato.

`mem ingest` **senza** `--backend llm` usa il backend **offline**: deterministico
ed estrattivo (titolo, scelta, punti chiave, `sources:`, `status: draft`), zero
token. È il fallback che tiene il loop runnable senza nulla installato; l'output
è una bozza da rifinire.

> Nota: `claude -p` non può annidarsi dentro una sessione Claude Code già attiva.
> Lì usa il comando plugin; il path headless è per terminali/hook reali.

## Stato

- ✅ **Core deterministico** (`init/index/search/lint/graph/detect`) — verificato (25 test).
- ✅ **Fase 1 change-detect** — token zero, località candidati provata dal benchmark.
- ✅ **Ingest** — offline (estrattivo, 0 token) **e** LLM (`--backend llm` via `claude -p`).
- ✅ **Fase 2 reconcile** (`mem reconcile --apply`) — applier reale (patch tolleranti + retry) + chiamata LLM cablata.
- ✅ **Hook al merge** (`hooks/post-merge`) — Fase 1 + Fase 2 ingest + **auto-commit**, testato end-to-end con un merge vero (backend offline di default).
- ✅ **Plug-and-play** — `install.sh` + `mem` su PATH + `mem install-hooks` (incide il path della CLI) + plugin Claude Code.
- 🔧 **Da provare sul campo** — un reconcile LLM reale via `claude -p` da terminale (vedi `WEAKNESSES.md`).
- 🔌 **Hook al merge** (`hooks/post-merge`) — Fase 1 attiva; Fase 2 + auto-commit = STUB.
- 🔌 **Plugin Claude Code** (`/mem:ingest|query|lint`) — comandi thin che pilotano la CLI.

Il differenziatore — e quindi dove investire — è completare `reconcile.py` e
l'hook. Il resto è plumbing riusabile e già in piedi.

## Licenza

MIT. Compone codice da `praneybehl/llm-wiki-plugin` (MIT) e reimplementa pattern
da altri progetti — vedi [`NOTICE`](NOTICE).
