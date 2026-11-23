# platform-audit

[English](README.md) | Italiano | [Français](README.fr.md)

Una skill per Claude Code che esegue l'audit di un intero codice sorgente e restituisce un piano di lavoro, non un parere. Lancia comandi reali in 11 fasi, apre ogni risultato prima di contarlo e calcola il punteggio di salute dal registro dei finding con uno script: due audit dello stesso codice danno lo stesso numero.

## Cosa copre

Ricognizione, poi architettura e dipendenze, sicurezza e supply chain, codice morto, dati, prestazioni, SEO e reperibilità da parte dei sistemi AI, osservabilità, test, UX e accessibilità, privacy e protezione dei dati, integrazioni AI e LLM (con una prima classificazione secondo l'AI Act europeo, che non è un parere legale).

Tre modalità: `full` (tutte le fasi), `lite` (un controllo rapido prima del rilascio) e `re-audit` (riverifica un registro precedente e mostra l'andamento del punteggio).

## Cosa si ottiene

Un rapporto in Markdown con sintesi per la direzione, registro dei finding (ID, evidenza, rimedio, stima in ore, criterio di accettazione), matrice delle priorità, piano su tre sprint, registro dei rischi per i finding S0 e S1, e un registro dell'audit che rende riproducibile quello successivo.

## Installazione

Copia la cartella nella directory delle skill:

```bash
git clone https://github.com/<owner>/platform-audit ~/.claude/skills/platform-audit
```

Poi chiedi a Claude Code "un audit della piattaforma" dentro un repository. Prima di partire la skill chiede dove sta il codice, un eventuale URL in esecuzione, la modalità e le aree su cui concentrarsi.

Il rapporto è scritto nella lingua in cui chiedi l'audit.

## Punteggio

`scripts/audit_score.py` legge il registro dei finding dal rapporto e applica la rubrica di `SKILL.md`. Serve Python 3.9 o successivo, solo libreria standard. Con `--lang it` scrive in italiano; accetta anche le opzioni in italiano.

```bash
python3 scripts/audit_score.py rapporto.md --lang it              # stampa il blocco di sintesi
python3 scripts/audit_score.py rapporto.md --lang it --scrivi     # scrive il blocco fra i marcatori
python3 scripts/audit_score.py rapporto.md --lang it --verifica   # esce con 1 se blocco e registro non coincidono
python3 scripts/audit_score.py rapporto.md --soglia 6.0           # esce con 2 sotto la soglia, utile in CI
python3 -m unittest discover -s tests                             # lancia i test
```

I marcatori sono `<!-- score:start -->` e `<!-- score:end -->`; vanno bene anche `<!-- punteggio:inizio -->` e `<!-- punteggio:fine -->`.

## Limiti

La skill ispeziona e documenta, non corregge il codice. Nelle fasi su privacy e AI segnala le questioni da sottoporre a un legale e non dà conclusioni giuridiche. Se uno scanner non si installa, la fase si controlla a mano e il rapporto lo dichiara.

## Licenza

MIT. Made by Pan.
