# platform-audit

English | [Italiano](README.it.md) | [Français](README.fr.md)

A Claude Code skill that audits a whole codebase and returns a work plan, not an opinion. It runs real commands across 11 phases, opens every hit before it counts, and computes a health score from the findings register with a script, so two audits of the same code give the same number.

## What it covers

Reconnaissance, then architecture and dependencies, security and supply chain, dead code, data layer, performance, SEO and AI discoverability, observability, tests, UX and accessibility, privacy and data protection, and AI/LLM integrations (with an EU AI Act triage flag, not a legal opinion).

Three modes: `full` (all phases), `lite` (a time-boxed pre-release check) and `re-audit` (re-verifies a previous register and shows the score trend).

## What you get

A Markdown report, generated from a JSON findings register, with an executive summary, a findings register (ID, evidence, remediation, effort, acceptance criterion), a priority matrix, a three-sprint plan, a risk register for S0 and S1 items, and an audit log that makes the next re-audit reproducible.

## Install

Copy the folder into your skills directory:

```bash
git clone https://github.com/<owner>/platform-audit ~/.claude/skills/platform-audit
```

Then ask Claude Code for "a platform audit" in a repository. The skill asks for the code location, an optional running URL, the mode and the focus areas before it starts.

## Scoring

The findings register is a JSON file next to the report (schema in `register.schema.json`, example in `examples/register.example.json`). `scripts/audit_score.py` validates it, computes the score and writes two generated blocks into the report: the summary and the register table. The report is never parsed, so a formatting slip cannot hide a finding. Python 3.9 or later, standard library only; output in English or, with `--lang it`, Italian.

The score cannot hide a risk. Any open S0 caps it at 3,9 and any open S1 at 7,9. Phases that do not apply need a written reason, printed with the score; phases that apply but were not run are declared in the register and lower the coverage; coverage below 100% caps the score at 7,9, an unchecked Security phase at 5,9, and declaring a phase not checked can never raise the score. "Production grade" therefore needs full coverage and no open S0 or S1. Whether the AI phase applies is declared, never inferred.

```bash
python3 scripts/audit_score.py register.json                                # print the summary
python3 scripts/audit_score.py register.json --report report.md --write     # write the blocks between the markers
python3 scripts/audit_score.py register.json --report report.md --check     # exit 1 if the report is stale
python3 scripts/audit_score.py register.json --threshold 6.0                # exit 2 below the threshold, useful as a CI gate
python3 -m unittest discover -s tests                                       # run the tests
```

The report needs the markers `<!-- score:start -->` / `<!-- score:end -->` and `<!-- register:start -->` / `<!-- register:end -->`. An invalid register (unknown keys, bad severity or status, malformed or duplicate ID, findings outside the declared scope) stops the script with exit 1 and a list of the problems; with `--write`, that list replaces the score block.

The audit report is written in the language you use to ask for it.

## Limits

The skill inspects and documents; it does not fix code. Phases 10 and 11 flag questions for counsel and never issue legal conclusions. When a scanner cannot be installed, the phase is checked by hand and the report says so.

## License

MIT. Made by Pan.
