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
core/
  mem.py            # CLI deterministica: init · index · search · lint · graph
  change_detect.py  # Fase 1 del reconcile: COSA toccare (SHA-256 + 3 segnali), 0 token
  reconcile.py      # Fase 2 del reconcile: COME modificare (STUB chiamata LLM)
  memlib/           # libreria condivisa, stdlib only
    frontmatter.py · pages.py · bm25.py · graph.py · store.py
hooks/post-merge    # STUB: al merge su main, processa solo le fonti nuove e committa
plugin/             # thin plugin Claude Code: /mem:ingest · /mem:query · /mem:lint
.memory/            # la memoria di esempio (3 decisioni + 1 concetto già compilati)
  raw/  wiki/{decisions,concepts,entities,synthesis}/  schema.md  index.md  log.md
  index/            # artefatti generati (git-ignored): index.json · bm25.idx · graph.json
```

## Provare lo scaffold (zero dipendenze, Python 3.9+)

Tutta la parte deterministica gira subito sul `.memory/` di esempio:

```bash
# 1. costruisci gli indici (index.json, bm25.idx, graph.json)
python3 core/mem.py index

# 2. ricerca BM25 + filtri + backlink (token zero)
python3 core/mem.py search "merge hook reconcile" --top 3
python3 core/mem.py search "ricerca" --type decision
python3 core/mem.py search "" --backlinks storage-git-native

# 3. salute strutturale + anti-drift (esce !=0 se trova problemi)
python3 core/mem.py lint

# 4. grafo dei wikilink (hub, orfani, link rotti)
python3 core/mem.py graph

# 5. bootstrap di una memoria nuova altrove (idempotente)
python3 core/mem.py init /percorso/al/progetto
```

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

**Fase 2 — COME modificare (LLM, una chiamata, contesto minimo).** `reconcile.py`
assembla il contesto minimo (schema + fonte + pagine candidate) e — qui è lo
**stub** — chiamerebbe l'LLM per classificare ogni pagina come
`no-op / update / add / contradiction / deprecate` e applicare patch chirurgiche.
Il plumbing deterministico (apply_patch `str_replace`, status machine, log) è già
reale; manca solo la chiamata al modello.

```bash
python3 core/reconcile.py            # dry-run: mostra contesto e stima token
python3 core/reconcile.py --show-context
```

## Stato

- ✅ **Core deterministico** (`init/index/search/lint/graph`) — funzionante e verificato.
- ✅ **Fase 1 change-detect** (`change_detect.py`) — funzionante, token zero.
- 🔌 **Fase 2 reconcile** (`reconcile.py`) — plumbing reale, chiamata LLM = STUB con TODO.
- 🔌 **Hook al merge** (`hooks/post-merge`) — Fase 1 attiva; Fase 2 + auto-commit = STUB.
- 🔌 **Plugin Claude Code** (`/mem:ingest|query|lint`) — comandi thin che pilotano la CLI.

Il differenziatore — e quindi dove investire — è completare `reconcile.py` e
l'hook. Il resto è plumbing riusabile e già in piedi.

## Licenza

MIT. Compone codice da `praneybehl/llm-wiki-plugin` (MIT) e reimplementa pattern
da altri progetti — vedi [`NOTICE`](NOTICE).
