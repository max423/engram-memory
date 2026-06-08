---
id: storage-git-native
type: decision
status: active
title: Storage git-native, niente database
tags: [storage, git, architettura]
sources:
  - raw/2026-01-15-storage-in-git.md
created: 2026-01-15
updated: 2026-01-15
---

# Storage git-native, niente database

La memoria è **markdown versionato nel repo** (`.memory/`), non un database.
Si eredita da git version history, branching e revisione nella stessa PR del
codice, a costo infrastrutturale zero.

## Implicazioni

- **Pagine atomiche**: un concetto = un file → conflitti di merge minimi.
- **Indice rigenerabile**: BM25 e grafo (vedi [[ricerca-bm25]]) sono artefatti
  derivati, git-ignorati, ricostruibili da `mem index`.
- Abilita la pipeline di [[reconcile-al-merge]] e le garanzie [[anti-drift]].

## Conseguenze

Niente query SQL, niente migrazioni: ogni operazione del core produce un diff
piccolo e leggibile, e il rollback è un `git revert`. Lo stesso principio guida
scelte affini, come i [[feature-flags-yaml]] versionati nel repo.
