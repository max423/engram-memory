# engram — memoria di progetto curata, git-native, token-minimal

Una knowledge base markdown di **decisioni** che vive nel repo, cresce da sola a
ogni merge ed è versionata in git. Principio unico: **il deterministico lo fa il
codice; l'LLM tocca solo la sintesi** → il costo in token è proporzionale al
*cambiamento*, non alla dimensione del wiki.

Zero dipendenze, **Python 3.9+ stdlib only**.

---

## Quickstart

```bash
./install.sh                 # mette `mem` sul PATH (~/.local/bin) + esegue i test
mem init .                   # crea .memory/  (--template software|research|product)
# droppa una decisione in .memory/raw/, es. 2026-06-08-scelta.md
mem ingest                   # compila le fonti nuove in pagine bozza (offline, 0 token)
mem index && mem lint        # ricostruisci indici + salute (esce !=0 sui problemi)
mem search "i tuoi termini"  # ricerca BM25 (+ --type/--tag/--backlinks)
mem install-hooks .          # auto-aggiornamento al merge su main
```

Ogni comando gira anche come `python3 core/mem.py <cmd>`. C'è un `.memory/` di
esempio (4 decisioni + 1 concetto, collegati e citati) per provare subito.

## Architettura

```
LLM (solo sintesi)  → compile(source) · reconcile(diff, pagine)   contesto minimo
CORE CLI (0 token)  → init·index·search(BM25)·lint·graph·detect·review·merge…
STORAGE (git)       → .memory/ : raw/ · wiki/{decisions,concepts,entities,synthesis}
                                 · schema.md · index.md · log.md · index/ (gitignored)
```

### Layout del repo

```
bin/mem · install.sh        # wrapper su PATH + setup plug-and-play
core/
  mem.py                    # CLI unica (init·index·search·lint·graph·detect·
                            #  reconcile·ingest·review·add-synthesis·merge·install-hooks)
  change_detect.py          # Fase 1 reconcile: COSA toccare (SHA-256 + segnali), 0 token
  reconcile.py              # Fase 2 reconcile: COME modificare (patch + retry, chiamata LLM)
  memlib/                   # libreria stdlib: frontmatter · pages · bm25 · graph · store
                            #  · compile · llm · index_store · ranking
hooks/post-merge            # al merge su main: Fase 1 + ingest + auto-commit
plugin/                     # plugin Claude Code: /mem:ingest · /mem:query · /mem:lint
tests/                      # run.py (49 unit test) · eval.py (scorecard) · bench.py
.memory/                    # memoria di esempio
```

### Il reconcile in 2 fasi

**Fase 1 — COSA toccare (codice, 0 token).** Rileva le fonti nuove/cambiate
(SHA-256) e seleziona le poche pagine impattate con 5 segnali: `sources:`, BM25,
backlink del grafo, **source-overlap**, **Adamic-Adar** (score additivi). Quando
nessuna fonte è cambiata, ritorna subito senza toccare il wiki.

**Fase 2 — COME modificare (LLM, 1 chiamata, contesto minimo).** Riceve schema +
fonte + pagine candidate e classifica ogni pagina
`no-op / update / add / contradiction / deprecate`, applicando patch chirurgiche
(`str_replace` tolleranti a spazi/virgolette/trattini, con retry se il match
manca/è ambiguo). Le pagine seguono la macchina a stati
`draft → active → stale → contradicted → archived`.

## Backend LLM — col tuo abbonamento, senza API key

La sintesi passa per Claude Code, non per l'API Anthropic:
- **Interattivo** (in sessione): comandi plugin `/mem:ingest` · `/mem:query` · `/mem:lint`.
- **Headless** (terminale/hook/CI): `mem ingest --backend llm`, `mem reconcile --apply`
  shellano `claude -p`. (Non annidabile in una sessione attiva → lì usa il plugin.)

Senza `--backend llm`, `mem ingest` usa il backend **offline** deterministico
(estrattivo, 0 token): pagine `draft` da rifinire — tiene il loop runnable ovunque.

## Comandi utili

```bash
mem detect                   # cosa è cambiato (0 token); il "reconcile plan"
mem reconcile --apply        # Fase 2 sulle fonti cambiate (via claude -p)
mem review                   # coda di revisione: pagine contradicted/stale + anti-drift
mem add-synthesis --title T --links a,b   # archivia una risposta come pagina synthesis/
mem merge                    # risolve conflitti git su index.md/log.md per unione
```

## Test, valutazione, performance

```bash
python3 tests/run.py         # 49 unit test (zero dipendenze)
python3 tests/eval.py        # "recupera la cosa giusta?" → recall/MRR + salute + anti-drift
python3 tests/bench.py       # benchmark 50→2000 pagine
```

Sull'esempio: **recall@1 1.00 · recall@3 1.00 · MRR 1.00**, salute pulita → `PASS`.
`search` ~9 ms a 2000 pagine; pagine candidate **costanti (8)** a ogni scala
(località dei token). Funziona su una memoria tua:
`python3 tests/eval.py --memory /path/.memory --labels tue.json`.

---

## Decisioni di design

| Dimensione | Scelta |
|---|---|
| **Scopo** | Memoria di *decisioni curate* (pattern LLM Wiki di Karpathy), non auto-doc del codice. L'utente decide cosa è fonte (drop in `raw/`); il sistema la processa. |
| **Forma** | Core CLI deterministico (0 token per il 90% delle operazioni) + thin layer LLM solo per la sintesi. |
| **Aggiornamento** | Al **merge** sul branch canonico (hook), non a ogni commit di ogni branch. |
| **Storage** | Tutto markdown nel repo, versionato. Niente database. |
| **Differenziatore** | token-efficiency + git-native + pipeline di reconcile al merge. |

**Ciclo di vita git.** La memoria vive in git, quindi eredita branch/fork/merge.
Il reconcile scatta **solo al merge** → i feature branch non sporcano la memoria, e
l'aggiornamento è revisionabile nella PR. Conflitti mitigati da: **pagine atomiche**
(un concetto = un file), **log append-only**, **edit chirurgici**, e `mem merge`
per i conflitti residui su `index.md`/`log.md`.

**Anti-drift** (il vero rischio: il wiki che "rilegge il proprio output"):
`sources:` obbligatorio su ogni pagina; in reconcile l'LLM rilegge la **fonte
aggiornata**, mai la vecchia pagina; patch chirurgiche (diff piccoli, rollback via
git); lint su staleness; human-in-the-loop sulla PR.

**Differenziazione.** Lo spazio è affollato (DeepWiki, ~20 cloni del pattern
Karpathy, e prodotti maturi come `nashsu/llm_wiki`), ma nessuno combina
**token-efficiency + git-native + reconcile guidato da hook al merge** in una CLI
a zero dipendenze installabile in un comando. È quello l'IP.

## Convenzioni di lavoro

- Core in **Python 3.9+ stdlib only**, zero dipendenze runtime.
- Ogni pagina wiki = un concetto (atomica): soft cap ~400 righe, hard cap ~800.
- `log.md` append-only, prefisso `## [YYYY-MM-DD] <op> | <titolo>` (grep-abile).
- Ogni operazione del core produce diff piccoli e puliti.
- Frontmatter obbligatorio: `id · type · status · title · tags · sources · created · updated`.
  Tipi: `decision · concept · entity · synthesis`. Stati: `draft · active · stale ·
  contradicted · archived`.

## Plugin Claude Code

Comandi thin che pilotano la CLI (la sintesi gira nella sessione, col tuo
abbonamento — niente API key):

| Comando | Cosa fa |
|---|---|
| `/mem:ingest [raw/file.md]` | Compila le fonti nuove/cambiate in pagine wiki. |
| `/mem:query <domanda>` | Risponde dalla memoria, index-first, citando le pagine. |
| `/mem:lint [fix]` | Salute + anti-drift; opzionalmente applica correzioni chirurgiche. |

Prerequisito: `./install.sh` mette `mem` sul PATH. Se assente, i comandi funzionano
anche via `python3 core/mem.py …`.

## Come è costruito

Composto forkando un core MIT e reimplementando pattern (mai copiando codice
non-permissivo):

- **Fork base** → `praneybehl/llm-wiki-plugin` (BM25 + lint, stdlib, MIT).
- **Idee** → change-detect SHA-256 (`ktrysmt`), hook al merge (`balukosuri`),
  schema decision/memory (`Oshayr`), principi di compilazione (`virgiliojr94/book-to-skill`).
- **Studiati, non copiati** → macchina a stati di `synthadoc` (AGPL) e relevance a
  4 segnali + review system di `nashsu/llm_wiki` (GPL).

Dettaglio attribuzioni in [`NOTICE`](NOTICE).

## Stato

Funzionante e testato (49 test, eval `PASS`): core deterministico, Fase 1, ingest
offline + LLM, Fase 2 reconcile (patch tolleranti + retry), hook al merge con
**auto-commit** (testato end-to-end con un merge vero), plug-and-play, plugin
Claude Code, review queue, `add-synthesis`, scenario templates, ranking a 4 segnali.
**Aperto:** provare un reconcile LLM reale via `claude -p` da terminale (non
annidabile in sessione).

## Licenza

MIT. Compone codice da `praneybehl/llm-wiki-plugin` (MIT); reimplementa pattern da
altri progetti — vedi [`NOTICE`](NOTICE).
