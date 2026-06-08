---
id: feature-flags-yaml
type: decision
status: active
title: Feature flag in un file YAML versionato
tags: [feature-flags, config, git]
sources:
  - raw/2026-06-08-feature-flags.md
created: 2026-06-08
updated: 2026-06-08
---

# Feature flag in un file YAML versionato

I feature flag vivono in un `flags.yaml` **versionato nel repo** e letto
all'avvio, invece che in un servizio esterno (es. LaunchDarkly).

## Perché

- Zero costi e zero dipendenze esterne.
- Ogni cambio di flag si revisiona nella PR come il codice.
- Coerente con la stessa logica di [[storage-git-native]]: ciò che conta è in
  git, non in un sistema a parte.

## Limite accettato

Cambiare un flag richiede un commit: niente toggle a runtime né rollout
percentuali. Se serviranno, si rivaluterà un servizio esterno — decisione da
ingerire come nuova fonte, che metterebbe questa pagina in stato `contradicted`.
