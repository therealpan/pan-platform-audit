# platform-audit

English | [Italiano](README.it.md) | [Français](README.fr.md)

A Claude Code skill that audits a whole codebase and returns a work plan, not an opinion. It runs real commands across 11 phases, opens every hit before it counts, and computes a health score from the findings register with a script, so two audits of the same code give the same number.

## What it covers

Reconnaissance, then architecture and dependencies, security and supply chain, dead code, data layer, performance, SEO and AI discoverability, observability, tests, UX and accessibility, privacy and data protection, and AI/LLM integrations (with an EU AI Act triage flag, not a legal opinion).

Three modes: `full` (all phases), `lite` (a time-boxed pre-release check) and `re-audit` (re-verifies a previous register and shows the score trend).

## What you get

One Markdown report with an executive summary, a findings register (ID, evidence, remediation, effort, acceptance criterion), a priority matrix, a three-sprint plan, a risk register for S0 and S1 items, and an audit log that makes the next re-audit reproducible.

## Install

Copy the folder into your skills directory:

```bash
git clone https://github.com/<owner>/platform-audit ~/.claude/skills/platform-audit
```

Then ask Claude Code for "a platform audit" in a repository. The skill asks for the code location, an optional running URL, the mode and the focus areas before it starts.

## Scoring

`scripts/audit_score.py` reads the findings register from the report and applies the rubric in `SKILL.md`. Python 3.9 or later, standard library only. Output in English by default, in Italian with `--lang it`.

```bash
python3 scripts/audit_score.py report.md                 # print the summary block
python3 scripts/audit_score.py report.md --write         # write the block between <!-- score:start --> and <!-- score:end -->
python3 scripts/audit_score.py report.md --check         # exit 1 if block and register disagree
python3 scripts/audit_score.py report.md --threshold 6.0 # exit 2 below the threshold, useful as a CI gate
python3 -m unittest discover -s tests                    # run the tests
```

The audit report is written in the language you use to ask for it.

## Limits

The skill inspects and documents; it does not fix code. Phases 10 and 11 flag questions for counsel and never issue legal conclusions. When a scanner cannot be installed, the phase is checked by hand and the report says so.

## License

MIT. Made by Pan.
