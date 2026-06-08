---
id: ricerca-bm25
type: decision
status: active
title: Ricerca BM25, niente embedding
tags: [ricerca, bm25, token-minimal]
sources:
  - raw/2026-02-03-ricerca-bm25.md
created: 2026-02-03
updated: 2026-02-03
---

# Ricerca BM25, niente embedding

La selezione delle pagine rilevanti usa **BM25 lessicale, stdlib, senza
embedding**, finché il wiki resta sotto le ~centinaia di pagine.

## Perché

- Deterministica e token-zero: gira in CI/locale senza modelli.
- Zero dipendenze e zero costo di refresh degli embedding a ogni cambiamento.
- A questa scala, BM25 + navigazione index-first è sufficiente.

È un pilastro di [[storage-git-native]]: l'indice è un artefatto rigenerabile,
non parte della verità versionata.

## Upgrade rimandato

Ricerca ibrida BM25 + vettoriale con re-rank LLM, solo se la scala lo richiede.
Non fa parte dell'MVP.
