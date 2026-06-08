---
id: anti-drift
type: concept
status: active
title: Anti-drift
tags: [anti-drift, qualita, sources]
sources:
  - raw/2026-03-10-reconcile-al-merge.md
created: 2026-03-10
updated: 2026-03-10
---

# Anti-drift

Il fallimento #1 di questi sistemi è che il wiki "rilegge il proprio output" e
amplifica gli errori. Le mitigazioni, quasi tutte deterministiche:

- **`sources:` obbligatorio**: ogni claim risale a una fonte in `raw/`. Il lint
  rifiuta pagine senza fonte.
- **Re-read della fonte, non della pagina**: in [[reconcile-al-merge]] l'LLM
  riceve il raw aggiornato, mai la vecchia pagina come verità.
- **Patch chirurgiche** (`str_replace`-style), mai riscrittura totale → diff
  pulito, rollback via git (vedi [[storage-git-native]]).
- **Lint su staleness**: si flagga un claim più vecchio della fonte che cita.
- **Human-in-the-loop sulla PR**: niente entra in `main` senza review.
