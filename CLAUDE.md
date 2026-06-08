# CLAUDE.md — Progetto "memoria di progetto curata"

> Primer per Claude Code. Leggi questo file all'inizio di ogni sessione.
> Il contesto completo (architettura, decisioni, survey, MVP) è in
> **`brief-progetto-memoria-wiki.md`** — leggilo prima di lavorare.

## Cos'è il progetto

Un prodotto che mantiene una **memoria di progetto curata** dentro qualsiasi
codebase: una knowledge base markdown di decisioni/note che cresce da sola a ogni
merge, versionata in git, ottimizzata per **consumare il minimo di token**.

## Principi non negoziabili

1. **Token-minimal**: tutto ciò che è deterministico lo fa il codice (indice,
   ricerca BM25, grafo, lint, change-detection). L'LLM tocca **solo la sintesi**,
   con contesto minimo (diff + poche pagine candidate, mai l'intero wiki).
2. **Git-native**: storage = markdown nel repo. Niente database.
3. **Memoria curata**: l'utente decide cosa è una fonte (drop in `raw/`); il
   sistema la processa. Non auto-documentazione del codice.
4. **Aggiornamento al merge**: il reconcile scatta su merge verso il branch
   canonico, non su ogni commit di ogni branch.
5. **Anti-drift**: ogni claim ha `sources:`; in reconcile si rilegge la fonte
   aggiornata, mai la vecchia pagina come verità; patch chirurgiche (`str_replace`).

## Architettura (sintesi)

```
THIN LLM LAYER   → compile(source) · reconcile(diff, pagine)   [contesto minimo]
CORE CLI (0 token)→ index · search(BM25) · graph · diff · lint · git-hooks
STORAGE (git)    → /.memory/ : raw/ · wiki/ · schema.md · index.md · log.md · index/
```

Reconcile in 2 fasi: **(1)** il codice trova le pagine impattate (sources, BM25,
backlink) a token zero; **(2)** l'LLM decide per ogni pagina no-op/update/add/
contradiction/deprecate e applica patch. Le pagine hanno una macchina a stati
`draft → active → stale → contradicted → archived` (vedi brief §5).

## Strategia di build (NON partire da zero)

Comporre forkando il core e rubando pezzi:

- **Fork base** → `praneybehl/llm-wiki-plugin` (BM25+lint puliti, stdlib, MIT).
- **Fase 1 change-detect** → idea da `ktrysmt/llmwiki` (SHA-256 + differential merge).
- **Hook al merge** → pattern da `balukosuri/docs-from-code`.
- **Schema decision/memory** → da `Oshayr/LLM-Wiki`.
- **Ingestion PDF** → `scripts/extract.py` da `virgiliojr94/book-to-skill`.
- **Studia (non forkare)** → `axoviq-ai/synthadoc` (AGPL+CLA) per la macchina a stati.

## Stato attuale

MVP plug-and-play in piedi (vedi `README.md` e `WEAKNESSES.md`). Verificato con
20 test (`tests/run.py`) e benchmark (`tests/bench.py`).

Funzionante:
- **CLI unica** `core/mem.py`: `init · index · search · lint · graph · detect ·
  reconcile · ingest · install-hooks`. Wrapper `bin/mem` + `install.sh`.
- **Fase 1 change-detect** `core/change_detect.py`: SHA-256 + 3 segnali (sources/
  BM25/grafo), token zero; località candidati costante (8) provata dal benchmark.
- **Ingest offline** `core/memlib/compile.py`: backend deterministico (estrattivo)
  che chiude il loop senza API key → pagine `draft`.
- Libreria condivisa `core/memlib/` (frontmatter · pages · bm25 · graph · store ·
  compile), stdlib only, Py 3.9+.
- `.memory/` di esempio: 3 decisioni + 1 concetto, collegati e citati, lint pulito.

- **Sintesi LLM cablata senza API key** `core/memlib/llm.py`: passa per Claude
  Code (abbonamento). Due modi: interattivo via plugin `/mem:ingest` (Claude è il
  layer LLM); headless via `claude -p` (`mem ingest --backend llm`,
  `mem reconcile --apply`). `claude -p` non si annida in una sessione attiva → lì
  si usa il comando plugin.

Miglioramenti landati (vedi `WEAKNESSES.md`):
- **Patch di reconcile robuste**: `apply_patch` ancorato/tollerante allo spazio
  (APPLIED/NOT_FOUND/AMBIGUOUS) + loop di retry che ri-chiede al modello.
- **Indice persistito validato** `core/memlib/index_store.py`: detect/search
  saltano il wiki quando è immutato (cache ~2x; O(change) se nessuna fonte cambia).
- **Tokenizer normalizzato** (stopword IT/EN + stemmer leggero): recall@1 0.90→1.00.
- **`mem merge`**: risoluzione deterministica dei conflitti su index.md/log.md (union).

Ancora aperto: il loop patch di reconcile va provato sul campo (path `claude -p`
dal terminale); hook Fase 2 opt-in; backend offline = estrattivo per scelta.

## Convenzioni di lavoro

- Codice del core: Python 3.10+ **stdlib only**, zero dipendenze runtime.
- Ogni pagina wiki = un concetto (atomica), soft cap ~400 righe, hard cap ~800.
- `log.md` append-only con prefisso `## [YYYY-MM-DD] <op> | <titolo>`.
- Tieni il wiki in git; ogni operazione del core deve produrre diff piccoli e puliti.
- Aggiorna questo `CLAUDE.md` e il brief quando cambiano decisioni di design.
