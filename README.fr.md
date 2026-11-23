# pan-platform-audit

[English](README.md) | [Italiano](README.it.md) | Français

Une skill pour Claude Code qui audite l'ensemble d'une base de code et rend un plan de travail, pas un avis. Elle exécute de vraies commandes en 11 phases, ouvre chaque résultat avant de le compter et calcule le score de santé à partir du registre des constats avec un script : deux audits du même code donnent le même chiffre.

## Ce qu'elle couvre

Reconnaissance, puis architecture et dépendances, sécurité et chaîne d'approvisionnement logicielle, code mort, couche de données, performances, SEO et visibilité auprès des systèmes d'IA, observabilité, tests, UX et accessibilité, vie privée et protection des données, intégrations IA et LLM (avec un premier tri au regard de l'AI Act européen, qui n'est pas un avis juridique).

Trois modes : `full` (toutes les phases), `lite` (un contrôle rapide avant mise en production) et `re-audit` (revérifie un registre précédent et montre l'évolution du score).

## Ce que vous obtenez

Un rapport en Markdown, généré à partir d'un registre des constats en JSON, avec une synthèse pour la direction, un registre des constats (ID, preuve, correction, estimation en heures, critère d'acceptation), une matrice de priorités, un plan sur trois sprints, un registre des risques pour les constats S0 et S1, et un journal d'audit qui rend le prochain audit reproductible.

## Installation

Copiez le dossier dans votre répertoire de skills :

```bash
git clone https://github.com/therealpan/pan-platform-audit ~/.claude/skills/pan-platform-audit
```

Demandez ensuite à Claude Code « un audit de la plateforme » dans un dépôt. Avant de commencer, la skill demande où se trouve le code, une URL en service si elle existe, le mode et les zones à privilégier.

Le rapport est rédigé dans la langue de votre demande.

## Score

Le registre des constats est un fichier JSON placé à côté du rapport (schéma dans `register.schema.json`, exemple dans `examples/register.example.json`). `scripts/audit_score.py` le valide, calcule le score et écrit deux blocs générés dans le rapport : la synthèse et le tableau du registre. Le rapport n'est jamais analysé, donc une erreur de mise en forme ne peut pas masquer un constat. Python 3.9 ou plus récent, bibliothèque standard uniquement ; messages en anglais, ou en italien avec `--lang it`.

Le score ne peut pas masquer un risque. Un S0 ouvert le plafonne à 3,9, un S1 ouvert à 7,9. Les phases non applicables exigent une justification écrite, affichée avec le score ; les phases applicables mais non menées se déclarent dans le registre et réduisent la couverture ; une couverture inférieure à 100 % plafonne le score à 7,9, une phase Sécurité non vérifiée à 5,9, et déclarer une phase non vérifiée ne peut jamais l'augmenter. Le niveau « production grade » exige donc une couverture complète et aucun S0 ni S1 ouvert. L'applicabilité de la phase IA se déclare, elle ne se déduit pas des constats.

```bash
python3 scripts/audit_score.py register.json                                # affiche la synthèse
python3 scripts/audit_score.py register.json --report rapport.md --write    # écrit les blocs entre les marqueurs
python3 scripts/audit_score.py register.json --report rapport.md --check    # sort avec 1 si le rapport n'est pas à jour
python3 scripts/audit_score.py register.json --threshold 6.0                # sort avec 2 sous le seuil, utile en CI
python3 -m unittest discover -s tests                                       # lance les tests
```

Le rapport doit contenir les marqueurs `<!-- score:start -->` / `<!-- score:end -->` et `<!-- register:start -->` / `<!-- register:end -->`. Un registre invalide (clés inconnues, sévérité ou statut non admis, ID mal formé ou en double, constat hors du périmètre déclaré) arrête le script avec le code 1 et la liste des problèmes ; avec `--write`, cette liste remplace le bloc du score.

## Limites

La skill inspecte et documente ; elle ne corrige pas le code. Dans les phases vie privée et IA, elle signale les questions à soumettre à un juriste et ne rend aucune conclusion juridique. Si un outil d'analyse ne peut pas être installé, la phase est vérifiée à la main et le rapport l'indique.

## Licence

MIT. Made by Pan.
