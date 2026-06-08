# Decisione: lo storage della memoria è markdown nel repo

Data: 2026-01-15
Presenti: team core

Abbiamo discusso dove vive la memoria di progetto. Due opzioni: un database
(SQLite/Postgres) oppure file markdown versionati nel repo stesso.

Scelta: **markdown nel repo, niente database.** Motivi:
- version history, branching e collaborazione "gratis" da git;
- la memoria viaggia con il codice e si revisiona nella stessa PR;
- zero infrastruttura da gestire, zero dipendenze runtime.

Conseguenza: tutto sotto `.memory/`, pagine atomiche (un concetto = un file)
per minimizzare i conflitti di merge. L'indice (BM25, grafo) è un artefatto
rigenerabile, quindi NON va committato.
