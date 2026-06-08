# Decisione: feature flag con un file YAML in repo

Data: 2026-06-08

Per attivare/disattivare funzionalità senza deploy dedicati, valutate due
opzioni: un servizio esterno (es. LaunchDarkly) oppure un file di config
versionato nel repo.

Scelta: **flags in un file `flags.yaml` versionato nel repo**, letto all'avvio.
Motivi:
- zero costi e zero dipendenze esterne;
- i flag si revisionano nella PR esattamente come il codice;
- coerente con la linea "tutto ciò che conta vive in git".

Limite accettato: cambiare un flag richiede un commit (niente toggle a runtime).
Se in futuro serviranno toggle a runtime o rollout percentuali, si rivaluterà
un servizio esterno.
