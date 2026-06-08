---
id: reconcile-al-merge
type: decision
status: active
title: Reconcile solo al merge sul branch canonico
tags: [reconcile, git, hook, architettura]
sources:
  - raw/2026-03-10-reconcile-al-merge.md
created: 2026-03-10
updated: 2026-03-10
---

# Reconcile solo al merge sul branch canonico

La memoria si aggiorna **solo al merge verso `main`** (hook su PR merge / push),
non a ogni commit di ogni branch. Così la memoria è una timeline pulita di
decisioni vincenti, e l'aggiornamento si revisiona nella PR.

## Le due fasi

1. **Fase 1 — COSA toccare (codice, token-zero).** Trova le pagine candidate
   via `sources:`, BM25 sul diff e backlink del grafo. Vedi [[ricerca-bm25]].
2. **Fase 2 — COME modificare (LLM, contesto minimo).** Riceve diff + quelle
   poche pagine + schema e decide no-op / update / add / contradiction /
   deprecate, applicando patch chirurgiche.

Poggia su [[storage-git-native]] (pagine atomiche, diff piccoli) e implementa
le garanzie [[anti-drift]].
