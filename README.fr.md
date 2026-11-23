# platform-audit

[English](README.md) | [Italiano](README.it.md) | Français

Une skill pour Claude Code qui audite l'ensemble d'une base de code et rend un plan de travail, pas un avis. Elle exécute de vraies commandes en 11 phases, ouvre chaque résultat avant de le compter et calcule le score de santé à partir du registre des constats avec un script : deux audits du même code donnent le même chiffre.

## Ce qu'elle couvre

Reconnaissance, puis architecture et dépendances, sécurité et chaîne d'approvisionnement logicielle, code mort, couche de données, performances, SEO et visibilité auprès des systèmes d'IA, observabilité, tests, UX et accessibilité, vie privée et protection des données, intégrations IA et LLM (avec un premier tri au regard de l'AI Act européen, qui n'est pas un avis juridique).

Trois modes : `full` (toutes les phases), `lite` (un contrôle rapide avant mise en production) et `re-audit` (revérifie un registre précédent et montre l'évolution du score).

## Ce que vous obtenez

Un rapport en Markdown avec une synthèse pour la direction, un registre des constats (ID, preuve, correction, estimation en heures, critère d'acceptation), une matrice de priorités, un plan sur trois sprints, un registre des risques pour les constats S0 et S1, et un journal d'audit qui rend le prochain audit reproductible.

## Installation

Copiez le dossier dans votre répertoire de skills :

```bash
git clone https://github.com/<owner>/platform-audit ~/.claude/skills/platform-audit
```

Demandez ensuite à Claude Code « un audit de la plateforme » dans un dépôt. Avant de commencer, la skill demande où se trouve le code, une URL en service si elle existe, le mode et les zones à privilégier.

Le rapport est rédigé dans la langue de votre demande.

## Score

`scripts/audit_score.py` lit le registre des constats dans le rapport et applique la grille de `SKILL.md`. Python 3.9 ou plus récent, bibliothèque standard uniquement. Les messages du script sont en anglais par défaut, en italien avec `--lang it`.

```bash
python3 scripts/audit_score.py rapport.md                 # affiche le bloc de synthèse
python3 scripts/audit_score.py rapport.md --write         # écrit le bloc entre <!-- score:start --> et <!-- score:end -->
python3 scripts/audit_score.py rapport.md --check         # sort avec 1 si le bloc et le registre divergent
python3 scripts/audit_score.py rapport.md --threshold 6.0 # sort avec 2 sous le seuil, utile en CI
python3 -m unittest discover -s tests                     # lance les tests
```

## Limites

La skill inspecte et documente ; elle ne corrige pas le code. Dans les phases vie privée et IA, elle signale les questions à soumettre à un juriste et ne rend aucune conclusion juridique. Si un outil d'analyse ne peut pas être installé, la phase est vérifiée à la main et le rapport l'indique.

## Licence

MIT. Made by Pan.
