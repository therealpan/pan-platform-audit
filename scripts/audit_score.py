#!/usr/bin/env python3
"""audit_score: the health score of a platform audit, computed without a model.

Reads the findings register from a Markdown report (the table with the ID and
severity columns) and computes the score with the platform-audit rubric. There
is one source of truth: the register. The summary block is generated from it
and is never written by hand.

    python3 audit_score.py report.md
    python3 audit_score.py report.md --not-applicable 6,9 --ai
    python3 audit_score.py report.md --write        update the block in the report
    python3 audit_score.py report.md --check        exit 1 if the block is stale
    python3 audit_score.py report.md --threshold 6.0  exit 2 below the threshold
    python3 audit_score.py report.md --json
    python3 audit_score.py report.md --lang it      output in Italian

Rubric. Each phase starts at 10; subtract 1 per S2 (max 3) and 0,5 per S3
(max 1); any S1 caps the phase at 6, any S0 at 3; the score is the minimum of
the cap and 10 minus the deductions. Only open findings count. Weights:
security 25; architecture, data, tests, performance, observability, privacy 10;
UX, SEO, dead code 5. When phase 11 (AI) applies it weighs 10 and the others are
rescaled to 90. A phase marked not applicable leaves the calculation and its
weight is redistributed proportionally.

Standard library only. Italian option names (--scrivi, --verifica, --soglia,
--non-applicabili, --senza-ai, --ignora-stati) and the Italian markers are
accepted as aliases.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

WEIGHTS = {1: 10, 2: 25, 3: 5, 4: 10, 5: 10, 6: 5, 7: 10, 8: 10, 9: 5, 10: 10, 11: 10}
AI_PHASE = 11

TEXT = {
    "en": {
        "phases": {
            1: "Architecture and dependencies",
            2: "Security and supply chain",
            3: "Dead code",
            4: "Data layer",
            5: "Performance",
            6: "SEO and GEO",
            7: "Observability",
            8: "Tests",
            9: "UX and accessibility",
            10: "Privacy",
            11: "AI and LLM",
        },
        "bands": [
            "production grade",
            "production with hardening",
            "not ready, plan required",
            "stop and stabilise",
        ],
        "headline": 'Overall score: **{score} out of 10, band "{band}"**. '
        "Open findings: {open} ({s0} S0, {s1} S1, {s2} S2, {s3} S3); closed: {closed}.",
        "header": "| Phase | Weight | S0 | S1 | S2 | S3 | Score | Contribution |",
        "partial": "Closed only in part, counted as open: {ids}.",
        "footer": "Computed by `audit_score.py` from the findings register: do not edit by hand.",
        "no_register": "audit_score: no register found (a table with ID, Finding and severity is required)",
        "no_markers": "audit_score: the report lacks the markers {start} and {end}",
        "stale": "audit_score: the score block does not match the register, run --write",
        "checked": "✓ block up to date: {score} out of 10",
        "written": "✓ block written: {score} out of 10",
        "below": "audit_score: {score} below the threshold {threshold}",
    },
    "it": {
        "phases": {
            1: "Architettura e dipendenze",
            2: "Sicurezza e supply chain",
            3: "Codice morto",
            4: "Dati",
            5: "Prestazioni",
            6: "SEO e GEO",
            7: "Osservabilità",
            8: "Test",
            9: "UX e accessibilità",
            10: "Privacy",
            11: "AI e LLM",
        },
        "bands": [
            "livello produzione",
            "produzione con irrobustimento",
            "non pronta, serve un piano",
            "fermarsi e stabilizzare",
        ],
        "headline": 'Punteggio complessivo: **{score} su 10, fascia "{band}"**. '
        "Finding aperti: {open} ({s0} S0, {s1} S1, {s2} S2, {s3} S3); chiusi: {closed}.",
        "header": "| Fase | Peso | S0 | S1 | S2 | S3 | Punteggio | Contributo |",
        "partial": "Chiusi solo in parte, contati come aperti: {ids}.",
        "footer": "Calcolato da `audit_score.py` sul registro dei finding: non modificare a mano.",
        "no_register": "audit_score: nessun registro trovato (serve una tabella con ID, Finding e severità)",
        "no_markers": "audit_score: nel rapporto mancano i marcatori {start} e {end}",
        "stale": "audit_score: il blocco del punteggio non corrisponde al registro, lanciare --write",
        "checked": "✓ blocco aggiornato: {score} su 10",
        "written": "✓ blocco scritto: {score} su 10",
        "below": "audit_score: {score} sotto la soglia {threshold}",
    },
}
BAND_MINIMUMS = [Decimal("8.0"), Decimal("6.0"), Decimal("4.0"), Decimal("-1")]
MARKERS = [
    ("<!-- score:start -->", "<!-- score:end -->"),
    ("<!-- punteggio:inizio -->", "<!-- punteggio:fine -->"),
]
CLOSED = re.compile(r"^\s*(risolt|resolved|chius|closed|superat|superseded)", re.I)
PARTIAL = re.compile(r"apert|open|parzial|partial|residu|nella parte|regred|regress", re.I)
ID = re.compile(r"^P(\d{1,2})-(\d+)$")


def cells(row: str) -> list:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", row)]


def tables(text: str):
    """Every Markdown table as (headers, rows)."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) - 1:
        if (
            lines[i].lstrip().startswith("|")
            and re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", lines[i + 1])
            and "-" in lines[i + 1]
        ):
            head = [c.lower() for c in cells(lines[i])]
            body = []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                body.append(cells(lines[i]))
                i += 1
            yield head, body
        else:
            i += 1


def column(head: list, *names) -> int:
    for index, cell in enumerate(head):
        if any(cell == n or cell.startswith(n) for n in names):
            return index
    return -1


def read(text: str):
    """(findings, states): findings = {id: severity}, states = {id: status text}."""
    findings, states = {}, {}
    for head, body in tables(text):
        c_id = column(head, "id")
        c_sev = column(head, "sev", "severity", "severità", "severita")
        c_state = column(head, "stato", "status")
        c_finding = column(head, "finding")
        if c_id < 0:
            continue
        for row in body:
            if len(row) <= c_id:
                continue
            ident = row[c_id].strip("`* ")
            if not ID.match(ident):
                continue
            if c_state >= 0 and len(row) > c_state:
                states[ident] = row[c_state]
            if c_finding >= 0 and c_sev >= 0 and len(row) > c_sev:
                found = re.search(r"S([0-3])", row[c_sev])
                if found:
                    findings[ident] = int(found.group(1))
    return findings, states


def is_open(state: str | None) -> bool:
    if not state:
        return True
    return not CLOSED.search(state) or bool(PARTIAL.search(state))


def round1(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def european(value: Decimal) -> str:
    return str(value).replace(".", ",")


def count_open(findings: dict, states: dict):
    """Open findings per phase and severity, plus closed ones and those closed only in part."""
    counts = {phase: [0, 0, 0, 0] for phase in WEIGHTS}
    closed, partial = 0, []
    for ident, severity in findings.items():
        phase = int(ID.match(ident).group(1))
        if phase not in WEIGHTS:
            continue
        state = states.get(ident)
        if not is_open(state):
            closed += 1
            continue
        if state and CLOSED.search(state):
            partial.append(ident)
        counts[phase][severity] += 1
    return counts, closed, sorted(partial)


def normalised_weights(phases: list) -> dict:
    """Weights as percentages over applicable phases; with the AI phase the others drop to 90."""
    weights = {f: Decimal(WEIGHTS[f]) for f in phases}
    if AI_PHASE in weights:
        for f in weights:
            if f != AI_PHASE:
                weights[f] *= Decimal("0.9")
    total = sum(weights.values())
    return {f: w / total * 100 for f, w in weights.items()}


def phase_score(s0: int, s1: int, s2: int, s3: int) -> Decimal:
    points = Decimal(10) - min(Decimal(3), Decimal(s2)) - min(Decimal(1), Decimal("0.5") * s3)
    if s1:
        points = min(points, Decimal(6))
    if s0:
        points = min(points, Decimal(3))
    return points


def compute(findings: dict, states: dict, not_applicable: set, ai: bool | None, lang: str) -> dict:
    counts, closed, partial = count_open(findings, states)
    if ai is None:
        ai = sum(counts[AI_PHASE]) > 0
    phases = [f for f in WEIGHTS if f not in not_applicable and (f != AI_PHASE or ai)]
    weights = normalised_weights(phases)
    rows, total = [], Decimal(0)
    for f in phases:
        points = phase_score(*counts[f])
        contribution = points * weights[f] / 100
        total += contribution
        rows.append(
            {
                "phase": f,
                "name": TEXT[lang]["phases"][f],
                "weight": weights[f],
                "s": counts[f],
                "score": points,
                "contribution": contribution,
            }
        )
    overall = round1(total)
    band = next(
        TEXT[lang]["bands"][i] for i, minimum in enumerate(BAND_MINIMUMS) if overall >= minimum
    )
    return {
        "rows": rows,
        "overall": overall,
        "band": band,
        "closed": closed,
        "open": sum(sum(r["s"]) for r in rows),
        "partial": partial,
        "by_severity": [sum(r["s"][i] for r in rows) for i in range(4)],
    }


def block(result: dict, lang: str) -> str:
    t = TEXT[lang]
    s = result["by_severity"]
    lines = [
        t["headline"].format(
            score=european(result["overall"]),
            band=result["band"],
            open=result["open"],
            s0=s[0],
            s1=s[1],
            s2=s[2],
            s3=s[3],
            closed=result["closed"],
        ),
        "",
        t["header"],
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in result["rows"]:
        lines.append(
            f"| {r['phase']}. {r['name']} | {european(round1(r['weight']))} | {r['s'][0]} | {r['s'][1]} | "
            f"{r['s'][2]} | {r['s'][3]} | {european(round1(r['score']))} | "
            f"{european(r['contribution'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))} |"
        )
    if result["partial"]:
        lines += ["", t["partial"].format(ids=", ".join(result["partial"]))]
    lines += ["", t["footer"]]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Health score of a platform audit, computed from the findings register."
    )
    p.add_argument("report", type=Path)
    p.add_argument(
        "--not-applicable",
        "--non-applicabili",
        dest="not_applicable",
        default="",
        help="excluded phases, comma separated (e.g. 6,9)",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--ai", dest="ai", action="store_true", default=None, help="phase 11 applies"
    )
    group.add_argument(
        "--no-ai", "--senza-ai", dest="ai", action="store_false", help="phase 11 does not apply"
    )
    p.add_argument(
        "--ignore-status",
        "--ignora-stati",
        dest="ignore_status",
        action="store_true",
        help="count every finding as open (initial score)",
    )
    p.add_argument(
        "--write", "--scrivi", dest="write", action="store_true",
        help="update the block between the markers in the report",
    )
    p.add_argument(
        "--check", "--verifica", dest="check", action="store_true",
        help="exit 1 if the block in the report is stale",
    )
    p.add_argument(
        "--threshold", "--soglia", dest="threshold", type=Decimal,
        help="exit 2 if the score is below this threshold",
    )
    p.add_argument("--lang", choices=sorted(TEXT), default="en", help="output language")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    t = TEXT[args.lang]

    text = args.report.read_text(encoding="utf-8")
    findings, states = read(text)
    if not findings:
        print(t["no_register"], file=sys.stderr)
        return 1
    excluded = {int(x) for x in args.not_applicable.split(",") if x.strip()}
    result = compute(findings, {} if args.ignore_status else states, excluded, args.ai, args.lang)
    text_block = block(result, args.lang)

    if args.json:
        print(
            json.dumps(
                {
                    "overall": float(result["overall"]),
                    "band": result["band"],
                    "open": result["open"],
                    "closed": result["closed"],
                    "by_severity": result["by_severity"],
                    "partial": result["partial"],
                    "phases": [
                        {
                            "phase": r["phase"],
                            "name": r["name"],
                            "weight": float(round1(r["weight"])),
                            "s0": r["s"][0],
                            "s1": r["s"][1],
                            "s2": r["s"][2],
                            "s3": r["s"][3],
                            "score": float(r["score"]),
                        }
                        for r in result["rows"]
                    ],
                },
                ensure_ascii=False,
                indent=1,
            )
        )
    elif not (args.write or args.check):
        print(text_block)

    if args.write or args.check:
        markers = next(((a, b) for a, b in MARKERS if a in text and b in text), None)
        if markers is None:
            start, end = MARKERS[0]
            print(t["no_markers"].format(start=start, end=end), file=sys.stderr)
            return 1
        start, end = markers
        before, rest = text.split(start, 1)
        old, after = rest.split(end, 1)
        score = european(result["overall"])
        if args.check:
            if old.strip() != text_block.strip():
                print(t["stale"], file=sys.stderr)
                return 1
            print(t["checked"].format(score=score))
        else:
            args.report.write_text(f"{before}{start}\n{text_block}\n{end}{after}", encoding="utf-8")
            print(t["written"].format(score=score))
    if args.threshold is not None and result["overall"] < args.threshold:
        print(
            t["below"].format(score=european(result["overall"]), threshold=european(args.threshold)),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
