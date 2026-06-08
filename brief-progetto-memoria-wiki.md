# Brief di progetto — Memoria di progetto curata, git-native, token-minimal

> Documento di riferimento unico. Consolida sintesi, architettura, gestione del
> ciclo di vita git (branch/fork/conflitti), strategia di build e piano MVP.

---

## 1. In una frase

Un prodotto che mantiene una **memoria di progetto curata** dentro qualsiasi
codebase — una knowledge base markdown di decisioni e note che **cresce da sola**
a ogni merge, resta versionata in git e consuma **il minimo di token possibile**.

## 2. Il problema

Le memorie di progetto scritte a mano vengono abbandonate: mantenerle è noioso.
Gli strumenti LLM esistenti o fanno snapshot del codice da rigenerare ogni volta
(costosi in token), o richiedono ingest manuale. Manca un sistema che si
auto-mantenga in modo affidabile **ed economico**.

## 3. Decisioni chiave

| Dimensione        | Scelta |
|-------------------|--------|
| **Scopo**         | Memoria/decisioni curate (pattern "LLM Wiki" di Karpathy), non auto-doc del codice. L'utente decide cosa è una fonte; il sistema la processa. |
| **Forma**         | Core CLI deterministico (token-zero) + thin layer LLM solo per la sintesi. |
| **Aggiornamento** | Automatico via hook git, **al merge** verso il branch canonico. |
| **Storage**       | Tutto markdown nel repo, versionato. Niente database. |
| **Differenziatore** | Token-efficiency + git-native + pipeline di *reconcile* vera. |

---

## 4. Architettura

Principio guida: **tutto ciò che è deterministico lo fa il codice; l'LLM tocca
solo la sintesi.** Effetto: il costo in token è proporzionale al *cambiamento*,
non alla *dimensione* del wiki.

```
┌─────────────────────────────────────────────────────┐
│  THIN LLM LAYER  (solo sintesi, contesto minimo)     │
│  - compile(source, schema)      → pagina markdown    │
│  - reconcile(diff, [pagine])    → patch chirurgiche  │
├─────────────────────────────────────────────────────┤
│  CORE CLI DETERMINISTICO  (zero token)               │
│  index · search(BM25) · graph/backlinks · diff       │
│  context-selector · lint · stats · git-hooks         │
├─────────────────────────────────────────────────────┤
│  STORAGE: markdown in git  ( /.memory/ )             │
│  raw/ · wiki/ · schema.md · index/                   │
└─────────────────────────────────────────────────────┘
```

### Storage git-native

```
/.memory/
  schema.md            # tipi di nodo e di relazione (config del dominio)
  raw/                 # fonti grezze immutabili (decisioni, post-mortem, note)
  wiki/
    decisions/  concepts/  entities/  synthesis/
  index/
    index.json         # frontmatter di tutte le pagine (ricerca senza leggerle)
    bm25.idx · graph.json
  index.md             # catalogo content-oriented: pagina + summary 1 riga (index-first)
  log.md               # registro cronologico append-only (vedi sotto)
```

Ogni pagina ha frontmatter con `id, type, status, tags, sources:, updated, links:`.
Il `sources:` (link alla fonte raw) è la chiave anti-drift; `status` guida la
macchina a stati (sezione 5). Il core legge **solo i frontmatter** dall'indice per
decidere cosa è rilevante: zero token.

**`log.md` — formato grep-able (da Karpathy).** Append-only, ogni voce con prefisso
consistente `## [2026-04-02] ingest | Titolo`, così la timeline si interroga con
unix puro: `grep "^## \[" log.md | tail -5`. Registro a token zero, zero conflitti
di merge (si scrive solo in fondo). Vale anche per `index.md`, catalogo che l'LLM
aggiorna a ogni ingest e che la query legge **per primo** per trovare le pagine
rilevanti prima di aprirle.

---

## 5. Il flusso di reconcile (il cuore del prodotto)

Dopo una modifica, due fasi.

**Fase 1 — COSA toccare (codice, zero token).** Trova le pagine candidate via:
(a) legame `sources:`, (b) vicinanza semantica BM25 sul diff, (c) backlink del
grafo. Risultato: poche pagine (3–8), non l'intero wiki.

**Fase 2 — COME modificare (LLM, una chiamata, contesto minimo).** Riceve *solo*
il diff + quelle pagine + lo schema, e per ogni pagina decide un'**azione**:

- **no-op** → non si tocca nulla (il caso più frequente, ~95% dei commit)
- **update** → patch chirurgica `str_replace` sulla sezione
- **add** → nuova pagina/sezione con almeno un link in entrata
- **contradiction** → flag + proposta di riconciliazione (mai sovrascrittura silenziosa)
- **deprecate** → pagina marcata obsoleta, non cancellata

### Macchina a stati delle pagine (da synthadoc v0.6)
Più robusto di semplici categorie: ogni pagina ha un campo `status` che percorre un
ciclo di vita formale, con transizioni **automatiche e auditabili**:

```
draft ──(lint pulito)──▶ active ──(SHA-256 fonte cambiato)──▶ stale
                           │                                     │
                           └──(fonte in conflitto ingerita)──▶ contradicted
                                                                 │
                                          (riconciliata / superata)──▶ archived
```

Ogni transizione è **loggata** (chi/quando/perché) e idealmente con il **costo LLM
per pagina** (`ingest_cost_usd`), così hai un audit di quando un contenuto è stato
davvero rivisto, non solo di chi ha toccato il file per ultimo. Le azioni della
Fase 2 *guidano* queste transizioni (es. `contradiction` → stato `contradicted`).
Override manuali (`activate`, `archive`, `restore`) quando l'automazione non basta.

**Principi di compilazione (dalla casella `book-to-skill`)**: densità > completezza
· mai testo grezzo, sempre sintesi · caricamento on-demand (index-first) · contenuto
più importante front-loaded. Sono la spec di come deve comportarsi questo passo.

### Anti-drift
`sources:` obbligatorio · in reconcile l'LLM rilegge **la fonte aggiornata**, mai
la vecchia pagina come verità · patch chirurgiche (diff puliti, rollback via git)
· lint su staleness · human-in-the-loop sulla PR.

**Bias dell'ordine di ingestion (rischio reale, oltre ~50 fonti).** Il wiki tende a
polarizzarsi verso le fonti *iniziali*, e il lint a passata singola sfora il
contesto. Mitigazione (da brtrx): lint a **batch di 5** con scratchpad persistente
tra sessioni e sequenza **randomizzata** (non per ordine di ingestion), per far
emergere le contraddizioni trasversali che le passate ordinate mancano.

---

## 6. Gestione del ciclo di vita git (branch · fork · conflitti)

La memoria vive in git, quindi eredita branch/fork/merge del codice. Si gestisce
con una sola decisione di fondo più alcune mitigazioni nello storage.

### Decisione di fondo: il reconcile scatta SOLO al merge sul branch canonico
Non su ogni commit di ogni branch, ma **sul merge verso `main`/produzione** (hook
su PR merge o push a `main`). Conseguenze:

- i feature branch e gli esperimenti **non toccano la memoria**;
- la memoria è un'unica timeline pulita di decisioni "vincenti", non un registro
  di ogni tentativo;
- l'aggiornamento della memoria è revisionabile nella PR stessa.

### Fork
Un fork è una copia del repo → si porta **uno snapshot della memoria** al momento
del fork. Da lì:

- *fork che diverge come progetto a sé* → giusto così: la sua memoria riflette le
  sue decisioni, non va sincronizzata;
- *fork che contribuisce a monte* → le modifiche alla memoria viaggiano nella PR e
  vengono revisionate come il codice;
- *fork che fa pull da upstream* → possibili conflitti sulle pagine (vedi sotto).

### Conflitti di merge sulla memoria — mitigazioni
- **Pagine atomiche** (un concetto = un file): modifiche a decisioni diverse →
  file diversi → zero conflitti. È la difesa principale.
- **Log append-only**: si modifica solo in fondo → niente conflitti sul log.
- **Edit chirurgici** (non riscritture): diff piccoli, git spesso risolve da solo.
- **Conflitto residuo** → trattato come conflitto di codice; opzione `mem:merge`
  che dà all'LLM le due versioni + le due fonti e produce la riconciliazione
  (riusa la logica di reconcile).

### "Codice normale" vs "produzione"
La memoria canonica è legata al **branch di produzione**: riflette ciò che è in
produzione. I feature branch possono accumulare decisioni provvisorie in locale,
ma diventano memoria ufficiale solo al merge in produzione. Così la memoria non
racconta mai cose non ancora vere.

### Alternativa architetturale (da valutare)
Tenere la memoria **fuori dall'albero del codice** (branch dedicato `memory` o
repo/submodule separato). Pro: immune ai merge del codice. Contro: perde
l'accoppiamento "decisione ↔ versione del codice" e la revisione nella stessa PR.
Sensata per memoria di sole decisioni globali; meno per memoria legata a parti
specifiche del codice.

---

## 7. Differenziazione

Lo spazio è affollato (DeepWiki ~16k stelle; ~20 cloni del pattern Karpathy), ma
**nessuno combina token-efficiency + git-native + pipeline di reconcile guidata da
hook al merge** in un prodotto installabile in un comando. I pezzi esistono sparsi
(synthadoc ha la macchina a stati, ktrysmt il change-detect, balukosuri l'hook); la
**composizione** di tutto in un MVP token-minimal e git-lifecycle-aware è l'IP.

> **Validazione dalla fonte.** Karpathy nel gist originale (un "idea file", non
> un'implementazione, per disegno) conferma le scelte di fondo: architettura raw /
> wiki / schema=`CLAUDE.md`, operazioni ingest / query / lint, index-first senza
> embedding fino a ~centinaia di pagine, e — testuale — *"the wiki is just a git
> repo of markdown files: version history, branching, collaboration for free"*. Il
> progetto non duplica nulla di canonico: instanzia un pattern nato per essere
> instanziato.

Strumenti di riferimento mappati durante la ricerca:

| Repo | Cosa offre già | Uso per noi |
|------|----------------|-------------|
| `praneybehl/llm-wiki-plugin` | Core token-minimal pulito (BM25, lint, stats), MIT | **Base di fork** |
| `ktrysmt/llmwiki` | Change-detection SHA-256 + differential merge, MIT | Ruba la Fase 1 |
| `balukosuri/docs-from-code` | Hook post-commit → wiki + freshness SHA | Ruba il pattern hook |
| `Oshayr/LLM-Wiki` | Page-type decision/memory + git integration, MIT | Ruba lo schema memoria |
| `virgiliojr94/book-to-skill` | Estrazione PDF in cascata + principi di densità, MIT | Ruba `extract.py` + linee guida Fase 2 |
| `tobi/qmd` | Ricerca markdown ibrida BM25+vettoriale + re-rank LLM, on-device, CLI+MCP | Upgrade di ricerca quando BM25 puro non basta |
| `axoviq-ai/synthadoc` | Hook system + queue + **macchina a stati a 5** + audit costo | **Studia, non forkare** (AGPL+CLA) |
| `noirblue/Mnemosyne` (spec) | Versione "infrastruttura" a 7 layer, core Rust + satelliti Python | Riferimento di dove può arrivare; non per l'MVP |

> **Nota su `book-to-skill`**: non è una base di fork (è uno snapshot statico
> PDF→skill, niente git/reconcile). Ma dona due cose: (a) `scripts/extract.py`,
> ingestion PDF robusta `pdftotext → PyPDF2 → pdfminer`, riutilizzabile pari pari
> per `ingest` se tra le fonti curate ci sono PDF; (b) i principi di compilazione
> token-minimal che diventano la spec della Fase 2 — *densità > completezza*, *mai
> testo grezzo, sempre sintesi*, *caricamento on-demand*, *file principale
> front-loaded*.

---

## 8. Strategia di build: comporre, non partire da zero

1. **Forka `praneybehl/llm-wiki-plugin`** come core (codice verificato, pulito,
   MIT, zero dipendenze). Già pronti: BM25 search e lint.
2. **Ruba la change-detection da `ktrysmt`** (SHA-256 + differential merge) → Fase 1.
3. **Ruba il pattern hook da `balukosuri`** (merge → reconcile → auto-commit).
4. **Ruba i page-type decision/memory da `Oshayr`** → schema.
5. **Studia `synthadoc`** per architettura hook/queue; non forkarlo (licenza).

Da irrobustire nel core forkato: il parser frontmatter è "YAML-ish" fatto a mano
(fragile); `--cache` è dichiarato ma non implementato; **nessuna logica git** —
quello è il layer greenfield (il differenziatore).

---

## 9. MVP (1–2 settimane)

In quest'ordine:

1. **Core CLI** Python stdlib: `init`, `index`, `search`, `lint` (deterministici).
2. **`ingest` con LLM**: compila una fonte raw in pagina, aggiorna index/grafo.
3. **Hook** al merge su `main`: processa solo le fonti curate nuove/cambiate.
4. **Thin plugin Claude Code**: 3 comandi (`/mem:ingest`, `/mem:query`, `/mem:lint`).

Rimanda: typed graph layer, GitHub Action su PR completa, modello-router
cheap/expensive, `mem:merge`, visualizzazione grafo.

### Criterio di successo
Su un repo reale: droppi 10 decisioni in `raw/`, fai merge, il wiki si popola da
solo con pagine collegate e citate, spendendo **< 30k token totali**; una query
risponde citando le pagine giuste.

---

## 10. Rischi onesti

- **Affidabilità del reconcile** su monorepo grandi: la parte dura, da testare
  presto su un repo vero.
- **Conflitti di merge** su wiki molto attivi: mitigati dalle pagine atomiche, ma
  da validare sul campo.
- **Mercato affollato**: la differenziazione va comunicata (token + git-native +
  reconcile), non "ennesimo wiki generator".
- **Convenzione del trigger**: tienila esplicita (drop in `raw/`) o l'utente non
  capisce cosa diventa memoria.
- **Bias dell'ordine di ingestion** (oltre ~50 fonti): wiki polarizzato verso le
  fonti iniziali + lint che sfora il contesto. Mitigato da lint a batch randomizzato
  con scratchpad persistente (sezione 5), ma da validare sul campo.

---

## 11. Prossimi passi possibili

- Scaffold concreto del fork: core di praneybehl + stub `change_detect.py`,
  `reconcile.py`, hook di merge, README di architettura.
- `schema.md` di esempio per progetto software (tipi di nodo + relazioni).
- Definizione esatta della convenzione di trigger e del formato frontmatter.
