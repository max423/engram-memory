# index.md — content catalogue (read this FIRST)

> One line per page: slug + 1-line summary. Index-first navigation: the query
> path reads this before opening any page, so it spends tokens only on what
> matters. Maintained by the LLM on every ingest.

## decisions

- [[storage-git-native]] — la memoria è markdown nel repo, niente database.
- [[ricerca-bm25]] — selezione pagine con BM25 lessicale, niente embedding.
- [[reconcile-al-merge]] — la memoria si aggiorna solo al merge su `main`, in 2 fasi.
- [[feature-flags-yaml]] — feature flag in un `flags.yaml` versionato, non un servizio esterno.

## concepts

- [[anti-drift]] — perché il wiki non deve rileggere il proprio output, e come si evita.

## entities

_(nessuna ancora)_

## synthesis

_(nessuna ancora)_
