# engram — memoria di progetto curata, git-native, token-minimal

Una knowledge base markdown di **decisioni** che vive nel repo, cresce da sola a
ogni merge e versionata in git. Principio unico: **il deterministico lo fa il
codice; l'LLM tocca solo la sintesi** → il costo in token è proporzionale al
*cambiamento*, non alla dimensione del wiki.

Zero dipendenze, **Python 3.9+ stdlib only**. Design completo:
[`brief`](brief-progetto-memoria-wiki.md) · [`spec`](spec-memoria-wiki-mvp.md) ·
[`CLAUDE.md`](CLAUDE.md) · limiti onesti: [`WEAKNESSES.md`](WEAKNESSES.md).

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

**Reconcile in 2 fasi.** *Fase 1 (codice, 0 token):* rileva le fonti nuove/cambiate
(SHA-256) e seleziona le poche pagine impattate con 5 segnali — `sources:`, BM25,
backlink, source-overlap, Adamic-Adar. *Fase 2 (LLM, 1 chiamata, contesto minimo):*
classifica ogni pagina `no-op/update/add/contradiction/deprecate` e applica patch
chirurgiche (str_replace tolleranti + retry). Anti-drift: si rilegge la fonte, mai
la vecchia pagina.

## Backend LLM — col tuo abbonamento, senza API key

La sintesi passa per Claude Code, non per l'API Anthropic:
- **Interattivo** (in sessione): comandi plugin `/mem:ingest` · `/mem:query` · `/mem:lint`.
- **Headless** (terminale/hook/CI): `mem ingest --backend llm`, `mem reconcile --apply`
  shellano `claude -p`. (Non annidabile in una sessione attiva → lì usa il plugin.)

Senza `--backend llm`, `mem ingest` usa il backend **offline** deterministico
(estrattivo, 0 token): pagine `draft` da rifinire. Il fallback che tiene il loop
runnable ovunque.

## Comandi utili in più

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

## Stato

Tutto funzionante e testato: core deterministico, Fase 1, ingest offline+LLM,
Fase 2 reconcile (patch tolleranti + retry), hook al merge con **auto-commit**
(testato end-to-end), plug-and-play, plugin Claude Code, review queue, synthesis,
scenario templates. **Aperto:** provare un reconcile LLM reale via `claude -p` da
terminale (non annidabile in sessione) — vedi [`WEAKNESSES.md`](WEAKNESSES.md).

## Licenza

MIT. Compone codice da `praneybehl/llm-wiki-plugin` (MIT); reimplementa pattern da
altri progetti (incl. idee studiate da `nashsu/llm_wiki`, GPL — non copiato). Vedi
[`NOTICE`](NOTICE).
