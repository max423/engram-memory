# Spec MVP — Memoria di progetto curata, git-native, token-minimal

> Un prodotto installabile in qualsiasi codebase con un comando, che mantiene una
> knowledge base di decisioni/memoria che cresce automaticamente, consumando il
> minor numero possibile di token LLM.

---

## 1. Il principio guida: "il token è la risorsa scarsa"

La tua scelta — *meno token possibile* — non è un dettaglio: è l'architettura.

La regola è una sola: **tutto ciò che è deterministico lo fa il codice, l'LLM
tocca solo la sintesi.** Concretamente, l'LLM NON deve mai:

- leggere l'intero wiki per rispondere o aggiornare,
- ricalcolare backlink, indici, orfani, statistiche,
- decidere *quali* pagine sono rilevanti (lo fa la ricerca deterministica),
- ri-processare fonti già processate.

L'LLM viene invocato **solo** per: compilare una nuova fonte in pagina, e
aggiornare le poche pagine impattate da un cambiamento — ricevendo in input solo
il diff + quelle pagine, mai il resto.

Effetto: un commit che tocca una decisione costa ~1-3k token, non 100k.

---

## 2. Forma del prodotto: core CLI deterministico + thin wrapper

Dato il vincolo token, la forma migliore è un **core CLI agnostico** (zero LLM
per il 90% delle operazioni) con sopra un **sottile plugin Claude Code** che lo
richiama solo per i passi di sintesi.

```
┌─────────────────────────────────────────────────────┐
│  THIN LLM LAYER  (solo sintesi, contesto minimo)     │
│  - compile(source, schema)      → pagina markdown    │
│  - reconcile(diff, [pagine])    → patch chirurgiche  │
│     ↑ invocato dalla CLI, una chiamata per evento     │
├─────────────────────────────────────────────────────┤
│  CORE CLI DETERMINISTICO  (zero token)               │
│  index · search(BM25) · graph/backlinks · diff       │
│  context-selector · lint · stats · git-hooks         │
├─────────────────────────────────────────────────────┤
│  STORAGE: markdown in git  ( /.memory/ )             │
│  raw/  ·  wiki/  ·  schema.md  ·  index/             │
└─────────────────────────────────────────────────────┘
```

Perché così:

- il core gira in CI o in locale **senza chiamare alcun modello**;
- il layer LLM è dietro un'interfaccia, quindi monti Claude Code oggi e domani
  qualunque altro agente/modello (anche uno piccolo e economico);
- l'utente "installa in un comando" la CLI; il plugin Claude Code è opzionale per
  l'uso conversazionale.

---

## 3. Storage: convenzione git-native

Tutto vive nel repo, versionato, niente database:

```
/.memory/
  schema.md            # tipi di nodo e di relazione (config del dominio)
  raw/                 # fonti grezze immutabili (decisioni, post-mortem, note)
  wiki/
    decisions/         # pagine compilate
    concepts/
    entities/
    synthesis/         # risposte/sintesi rifilate
  index/
    index.json         # frontmatter di tutte le pagine (per ricerca senza leggerle)
    bm25.idx           # indice full-text
    graph.json         # nodi + archi (wikilink) + backlink calcolati
```

Ogni pagina ha frontmatter YAML con: `id`, `type`, `tags`, `sources:` (link alla
fonte raw — chiave anti-drift), `updated`, `links:`. Il core legge **solo i
frontmatter** dall'`index.json` per decidere cosa è rilevante: zero token.

---

## 4. Il flusso "memoria curata + hook su commit/PR"

"Curata" e "automatica" si conciliano così: **l'utente decide cosa è una fonte,
il sistema la processa da solo.** Il trigger non è ogni commit, ma un input curato.

### Cosa fa scattare l'aggiornamento (scegli una convenzione)

1. **File-based** (consigliato): un file nuovo/modificato dentro `/.memory/raw/`.
   Tu droppi una nota/decisione lì → l'hook la compila.
2. **Tag nel commit/PR**: un commit con trailer `Wiki: <slug>` o una sezione
   `## Decision` nella descrizione della PR.
3. **Path-based**: cambiamenti a file marcati (es. `docs/adr/*.md`).

### Pipeline (post-commit locale o GitHub Action su PR)

```
git event
  │
  ▼
[CORE] git diff → rileva fonti raw nuove/cambiate              (0 token)
  │   nessuna fonte curata toccata? → esci subito              (0 token)
  ▼
[CORE] context-selector: per ogni fonte, trova via BM25+graph
        le ≤N pagine wiki potenzialmente impattate             (0 token)
  ▼
[LLM]  compile/reconcile: riceve SOLO {diff fonte + quelle N
        pagine + schema} → produce patch chirurgiche           (~1-3k token)
  ▼
[CORE] applica patch, ricalcola backlink/index/graph, lint     (0 token)
  ▼
[CORE] commit automatico "memory: update da <source>"          (0 token)
```

Su PR: il bot committa l'aggiornamento del wiki **sulla stessa PR**, così la
memoria è revisionabile come codice prima del merge.

---

## 5. Anti-drift (il vero problema, non la fattibilità)

Il fallimento #1 di questi sistemi è che il wiki "legge il proprio output" e
amplifica errori. Mitigazioni, tutte deterministiche tranne dove indicato:

- **`sources:` obbligatorio**: ogni claim risale a una fonte raw. Lint rifiuta
  pagine senza fonte.
- **Re-read della fonte, non della pagina**: in `reconcile`, l'LLM riceve il
  *raw source*, non la vecchia pagina come verità.
- **Patch chirurgiche** (`str_replace`-style), mai riscrittura totale → diff
  pulito, rollback facile via git.
- **Lint su staleness**: il core flagga claim più vecchi della fonte che citano.
- **Human-in-the-loop su PR**: niente va in `main` senza review.

---

## 6. Token budget (perché questo design vince)

| Operazione                         | Token LLM        |
|------------------------------------|------------------|
| Commit che non tocca fonti curate  | **0**            |
| Ricerca / query sul wiki           | 0 (BM25) + 1 chiamata solo per la sintesi finale |
| Ingest di 1 nuova decisione        | ~1–3k            |
| Ricalcolo grafo/indici/backlink    | **0**            |
| Lint completo                      | **0**            |

Confronto: gli strumenti "rigenera tutto il wiki" costano decine-centinaia di k
token per ogni refresh. Qui il costo è proporzionale al *cambiamento*, non alla
*dimensione del wiki*.

---

## 7. MVP — taglio minimo per validare (1–2 settimane)

Fai solo questo, in quest'ordine:

1. **CLI core** in Python stdlib (zero dipendenze): `init`, `index`, `search`,
   `lint`. Storage markdown + `index.json`. → tutto deterministico, testabile.
2. **`ingest` con LLM**: compila una fonte da `raw/` in una pagina, aggiorna
   index/grafo. Una sola chiamata modello, contesto minimo.
3. **Git hook** `post-commit` che processa solo le fonti nuove in `raw/`.
4. **Plugin Claude Code** thin: 3 comandi (`/mem:ingest`, `/mem:query`,
   `/mem:lint`) che chiamano la CLI.

Rimanda: typed graph layer, GitHub Action su PR, modello-router cheap/expensive,
visualizzazione grafo. Sono migliorie, non MVP.

### Criterio di successo dell'MVP
Su un repo reale: droppi 10 decisioni in `raw/`, fai commit, e il wiki si popola
da solo con pagine collegate e citate, spendendo < 30k token totali; una query
risponde citando le pagine giuste.

---

## 8. Rischi onesti

- **Affidabilità del reconcile automatico** su monorepo grandi: è la parte dura,
  va testata presto su un repo vero.
- **Mercato affollato**: la differenziazione è *token-efficiency + git-native +
  curated*, non "ennesimo wiki generator". Va comunicata bene.
- **Convenzione del trigger**: se è troppo implicita, l'utente non capisce cosa
  diventa memoria. Tienila esplicita (drop in `raw/`).

---

## 9. Prossimi passi possibili

- Scaffolding del repo della CLI core (struttura + `init`/`index`/`lint` già
  funzionanti, zero LLM).
- `schema.md` di esempio per un progetto software (tipi di nodo + relazioni).
- Definizione esatta della convenzione di trigger e del formato frontmatter.
