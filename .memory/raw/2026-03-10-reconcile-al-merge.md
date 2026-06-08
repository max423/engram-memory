# Decisione: il reconcile scatta solo al merge sul branch canonico

Data: 2026-03-10

Quando deve aggiornarsi la memoria? Opzioni: a ogni commit di ogni branch,
oppure solo al merge verso `main`.

Scelta: **solo al merge verso il branch canonico** (hook su PR merge / push a
`main`). Motivi:
- i feature branch e gli esperimenti non sporcano la memoria;
- la memoria è una timeline pulita di decisioni "vincenti", non di tentativi;
- l'aggiornamento è revisionabile nella PR stessa.

Il reconcile è in due fasi: (1) il codice trova le pagine impattate a token
zero — via `sources:`, BM25 sul diff e backlink del grafo; (2) l'LLM, con
contesto minimo (diff + quelle poche pagine + schema), decide per ogni pagina
no-op / update / add / contradiction / deprecate e applica patch chirurgiche.
Anti-drift: in fase 2 si rilegge la fonte aggiornata, mai la vecchia pagina.
