#!/usr/bin/env python3
"""audit_score: the health score of a platform audit, computed without a model.

The findings register lives in a JSON file with a strict schema (see
register.schema.json). The script validates it, computes the score with the
pan-platform-audit rubric and, with --report, writes two generated blocks into the
Markdown report: the summary block and the findings register table. The report
is never parsed: the JSON file is the only source.

    python3 audit_score.py register.json                        print the summary block
    python3 audit_score.py register.json --report report.md --write
    python3 audit_score.py register.json --report report.md --check
    python3 audit_score.py register.json --threshold 6.0        exit 2 below the threshold
    python3 audit_score.py register.json --json
    python3 audit_score.py register.json --lang it              output in Italian

Phase score. Each phase starts at 10; subtract 1 per S2 (max 3) and 0,5 per S3
(max 1); any S1 caps the phase at 6, any S0 at 3. Only open findings count.

Weights. Security 25; architecture, data, tests, performance, observability,
privacy 10; UX, SEO, dead code 5. When phase 11 (AI) applies it weighs 10 and
the others are rescaled to 90.

Scope, declared in the register. Phase 11 applies or not ("ai"). A phase that
does not apply to the product ("not_applicable", each with a written reason
that the summary prints) leaves the calculation and may hold no findings;
Security always applies. A phase that applies but was not run,
or only in part ("not_checked"), lowers the coverage. Without findings it leaves
the average; with open findings it stays in the average with its phase score,
so declaring a phase not checked can never raise the score.

Overall caps. Any open S0 caps the score at 3,9; any open S1 at 7,9; coverage
below 100% at 7,9; Security not checked at 5,9.

Any schema violation, including a duplicate key in a JSON object, stops the
script with exit 1 and computes nothing; with --write, both generated blocks in
the report are replaced by the list of problems. A resolved finding needs
closed_on; a superseded one needs superseded_by, pointing to a finding that is
not itself superseded. Text outside the markers is never read or checked.

Standard library only. Italian option names (--rapporto, --scrivi, --verifica,
--soglia, --ignora-stati) are accepted as aliases.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

SCHEMA_VERSION = 1
WEIGHTS = {1: 10, 2: 25, 3: 5, 4: 10, 5: 10, 6: 5, 7: 10, 8: 10, 9: 5, 10: 10, 11: 10}
AI_PHASE = 11
SECURITY_PHASE = 2
CAP_S0 = Decimal("3.9")
CAP_S1 = Decimal("7.9")
CAP_COVERAGE = Decimal("7.9")
CAP_SECURITY_UNCHECKED = Decimal("5.9")
FULL_COVERAGE = Decimal(100)
MAX_SCORE = Decimal(10)
SEVERITIES = ("S0", "S1", "S2", "S3")
OPEN_STATUSES = ("open", "regressed")
CLOSED_STATUSES = ("resolved", "superseded")
ID = re.compile(r"P([1-9]|1[01])-[0-9]{2,3}")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
TOP_KEYS = {"schema_version", "scope", "findings"}
SCOPE_KEYS = {"ai", "not_applicable", "not_checked"}
REQUIRED = ("id", "phase", "severity", "status", "area", "finding", "evidence", "remediation")
OPTIONAL = ("effort_h", "acceptance", "dependencies", "closed_on", "superseded_by", "note")
SCORE_MARKERS = ("<!-- score:start -->", "<!-- score:end -->")
REGISTER_MARKERS = ("<!-- register:start -->", "<!-- register:end -->")

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
        "caps": {
            "s0": "open S0 findings cap the score at 3,9",
            "s1": "open S1 findings cap the score at 7,9",
            "coverage": "coverage below 100% caps the score at 7,9",
            "security": "Security not checked caps the score at 5,9",
        },
        "headline": 'Overall score: **{score} out of 10, band "{band}"**. '
        "Open findings: {open} ({s0} S0, {s1} S1, {s2} S2, {s3} S3); closed: {closed}.",
        "average": "Weighted average before caps: {average}. Caps applied: {caps}.",
        "no_caps": "none",
        "coverage": "Coverage: {coverage}% of the applicable weight checked. AI phase: {ai}.",
        "ai_yes": "applies",
        "ai_no": "does not apply",
        "not_checked": "Not checked: {phases}.",
        "not_applicable": "Not applicable: {phases}.",
        "score_header": "| Phase | Weight | S0 | S1 | S2 | S3 | Score | Contribution |",
        "unchecked_row": " (not checked)",
        "footer": "Computed by `audit_score.py` from the findings register: do not edit by hand.",
        "register_header": "| ID | Phase | Area | Finding | Severity | Status | Evidence | "
        "Remediation | Effort (h) | Acceptance criterion | Dependencies |",
        "register_footer": "Generated by `audit_score.py` from `{file}`: edit the JSON file, "
        "not this table.",
        "status": {
            "open": "open",
            "regressed": "regressed",
            "resolved": "resolved",
            "superseded": "superseded",
        },
        "invalid": "the register is not valid, nothing computed:",
        "invalid_block": "**Score not computed: the findings register is not valid.** "
        "Fix these problems in the JSON file and run the script again:",
        "stale": "the generated blocks do not match the register, run --write",
        "checked": "✓ blocks up to date: {score} out of 10",
        "written": "✓ blocks written: {score} out of 10",
        "below": "{score} below the threshold {threshold}",
        "e_file": "cannot read {path}",
        "e_json": "not valid JSON: {error}",
        "e_top": "the top level must be an object with schema_version, scope and findings",
        "e_keys": "{where}: unknown keys {keys}",
        "e_missing": "{where}: missing {keys}",
        "e_version": "schema_version must be {version}",
        "e_ai": "scope.ai must be true or false",
        "e_phase_list": "scope.{key} must be a list of distinct phase numbers from 1 to 11",
        "e_overlap": "phases {phases} are both not applicable and not checked",
        "e_security_na": "phase 2 (Security) always applies: it can be not checked, never "
        "not applicable",
        "e_ai_na": "phase 11 is listed as not applicable or not checked while scope.ai is false; "
        "with ai false leave it out of both lists",
        "e_ai_scope": "scope.ai is true but phase 11 is listed as not applicable",
        "e_nothing": "no phase left to score",
        "e_findings": "findings must be a list of objects",
        "e_finding_type": "findings[{index}] is not an object",
        "e_text": "{where}: {key} must be a non-empty string",
        "e_id": "{where}: id '{value}' is not in the form P<phase>-<nn> (e.g. P2-01)",
        "e_phase": "{where}: phase must be the number in the id ({expected})",
        "e_severity": "{where}: severity must be one of S0, S1, S2, S3",
        "e_status": "{where}: status must be one of open, regressed, resolved, superseded",
        "e_date": "{where}: closed_on must be a date YYYY-MM-DD",
        "e_superseded": "{where}: superseded_by must be the id of another finding in the register",
        "e_superseded_status": "{where}: superseded_by is set but status is not superseded",
        "e_duplicate": "{id}: duplicate id",
        "e_dup_key": "duplicate key '{key}' in a JSON object",
        "e_depth": "the JSON is nested too deeply",
        "e_na_item": 'scope.not_applicable must list objects {"phase": n, "reason": '
        '"..."} with distinct phases from 1 to 11 and a non-empty reason',
        "e_closed_on": "{where}: status resolved needs closed_on",
        "e_needs_target": "{where}: status superseded needs superseded_by",
        "e_chain": "{where}: superseded_by points to a finding that is itself superseded",
        "e_not_replaced": "could not replace the generated blocks in the report: fix the markers",
        "register_invalid": "**Register table not generated: the findings register is not "
        "valid.** See the score block.",
        "e_excluded": "{id}: finding in phase {phase}, declared not applicable",
        "e_ai_findings": "{id}: AI finding while scope.ai is false",
        "e_threshold": "'{value}' is not a valid threshold (a number from 0 to 10)",
        "e_needs_report": "--write and --check need --report",
        "e_markers": "the report needs the marker pairs {score} and {register}, each once, "
        "each start before its end, the two pairs not overlapping",
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
        "caps": {
            "s0": "S0 aperti: punteggio al massimo 3,9",
            "s1": "S1 aperti: punteggio al massimo 7,9",
            "coverage": "copertura sotto il 100%: punteggio al massimo 7,9",
            "security": "sicurezza non verificata: punteggio al massimo 5,9",
        },
        "headline": 'Punteggio complessivo: **{score} su 10, fascia "{band}"**. '
        "Finding aperti: {open} ({s0} S0, {s1} S1, {s2} S2, {s3} S3); chiusi: {closed}.",
        "average": "Media pesata prima dei tetti: {average}. Tetti applicati: {caps}.",
        "no_caps": "nessuno",
        "coverage": "Copertura: {coverage}% del peso applicabile verificato. Fase AI: {ai}.",
        "ai_yes": "applicabile",
        "ai_no": "non applicabile",
        "not_checked": "Non verificate: {phases}.",
        "not_applicable": "Non applicabili: {phases}.",
        "score_header": "| Fase | Peso | S0 | S1 | S2 | S3 | Punteggio | Contributo |",
        "unchecked_row": " (non verificata)",
        "footer": "Calcolato da `audit_score.py` sul registro dei finding: non modificare a mano.",
        "register_header": "| ID | Fase | Area | Finding | Severità | Stato | Evidenza | "
        "Rimedio | Stima (h) | Criterio di accettazione | Dipendenze |",
        "register_footer": "Generato da `audit_score.py` da `{file}`: modificare il file JSON, "
        "non questa tabella.",
        "status": {
            "open": "aperto",
            "regressed": "regredito",
            "resolved": "risolto",
            "superseded": "superato",
        },
        "invalid": "il registro non è valido, nessun calcolo:",
        "invalid_block": "**Punteggio non calcolato: il registro dei finding non è valido.** "
        "Correggere questi problemi nel file JSON e rilanciare lo script:",
        "stale": "i blocchi generati non corrispondono al registro, lanciare --write",
        "checked": "✓ blocchi aggiornati: {score} su 10",
        "written": "✓ blocchi scritti: {score} su 10",
        "below": "{score} sotto la soglia {threshold}",
        "e_file": "impossibile leggere {path}",
        "e_json": "JSON non valido: {error}",
        "e_top": "il livello superiore deve essere un oggetto con schema_version, scope e findings",
        "e_keys": "{where}: chiavi sconosciute {keys}",
        "e_missing": "{where}: mancano {keys}",
        "e_version": "schema_version deve essere {version}",
        "e_ai": "scope.ai deve essere true o false",
        "e_phase_list": "scope.{key} deve essere un elenco di numeri di fase distinti da 1 a 11",
        "e_overlap": "le fasi {phases} sono sia non applicabili sia non verificate",
        "e_security_na": "la fase 2 (Sicurezza) si applica sempre: può essere non verificata, "
        "mai non applicabile",
        "e_ai_na": "la fase 11 è elencata come non applicabile o non verificata con scope.ai "
        "false; con ai false va tolta da entrambi gli elenchi",
        "e_ai_scope": "scope.ai è true ma la fase 11 è elencata come non applicabile",
        "e_nothing": "nessuna fase da calcolare",
        "e_findings": "findings deve essere un elenco di oggetti",
        "e_finding_type": "findings[{index}] non è un oggetto",
        "e_text": "{where}: {key} deve essere un testo non vuoto",
        "e_id": "{where}: l'id '{value}' non ha la forma P<fase>-<nn> (es. P2-01)",
        "e_phase": "{where}: phase deve essere il numero nell'id ({expected})",
        "e_severity": "{where}: severity deve essere S0, S1, S2 o S3",
        "e_status": "{where}: status deve essere open, regressed, resolved o superseded",
        "e_date": "{where}: closed_on deve essere una data AAAA-MM-GG",
        "e_superseded": "{where}: superseded_by deve essere l'id di un altro finding del registro",
        "e_superseded_status": "{where}: superseded_by è indicato ma lo stato non è superseded",
        "e_duplicate": "{id}: id ripetuto",
        "e_dup_key": "chiave '{key}' ripetuta in un oggetto JSON",
        "e_depth": "il JSON è annidato troppo in profondità",
        "e_na_item": 'scope.not_applicable deve elencare oggetti {"phase": n, "reason": '
        '"..."} con fasi distinte da 1 a 11 e una motivazione non vuota',
        "e_closed_on": "{where}: lo stato resolved richiede closed_on",
        "e_needs_target": "{where}: lo stato superseded richiede superseded_by",
        "e_chain": "{where}: superseded_by punta a un finding a sua volta superato",
        "e_not_replaced": "impossibile sostituire i blocchi generati nel rapporto: correggere i "
        "marcatori",
        "register_invalid": "**Tabella del registro non generata: il registro dei finding non "
        "è valido.** Vedere il blocco del punteggio.",
        "e_excluded": "{id}: finding nella fase {phase}, dichiarata non applicabile",
        "e_ai_findings": "{id}: finding AI con scope.ai false",
        "e_threshold": "'{value}' non è una soglia valida (un numero da 0 a 10)",
        "e_needs_report": "--scrivi e --verifica richiedono --rapporto",
        "e_markers": "il rapporto deve contenere una sola volta le coppie di marcatori {score} e "
        "{register}, ciascun inizio prima della sua fine, senza sovrapposizioni",
    },
}
BAND_MINIMUMS = [Decimal("8.0"), Decimal("6.0"), Decimal("4.0"), Decimal("-1")]


class Invalid(Exception):
    def __init__(self, errors: list):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Scope:
    ai: bool
    not_applicable: frozenset
    not_checked: frozenset
    reasons: tuple = ()


# ---------------------------------------------------------------- validation


def keys_errors(obj: dict, allowed: set, required: tuple, where: str, t: dict) -> list:
    errors = []
    unknown = sorted(set(obj) - allowed)
    if unknown:
        errors.append(t["e_keys"].format(where=where, keys=", ".join(unknown)))
    missing = [k for k in required if k not in obj]
    if missing:
        errors.append(t["e_missing"].format(where=where, keys=", ".join(missing)))
    return errors


def phase_set(value: object, key: str, t: dict) -> tuple:
    """(set of phases, errors) for a scope list."""
    error = [t["e_phase_list"].format(key=key)]
    if not isinstance(value, list):
        return frozenset(), error
    phases = [v for v in value if type(v) is int and v in WEIGHTS]
    if len(phases) != len(value) or len(set(phases)) != len(phases):
        return frozenset(), error
    return frozenset(phases), []


def na_set(value: object, t: dict) -> tuple:
    """(phases, ((phase, reason), ...), errors) for scope.not_applicable."""
    error = [t["e_na_item"]]
    if not isinstance(value, list):
        return frozenset(), (), error
    pairs = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"phase", "reason"}:
            return frozenset(), (), error
        phase, reason = item["phase"], item["reason"]
        if type(phase) is not int or phase not in WEIGHTS:
            return frozenset(), (), error
        if not isinstance(reason, str) or not reason.strip():
            return frozenset(), (), error
        pairs.append((phase, reason.strip()))
    phases = [p for p, _ in pairs]
    if len(set(phases)) != len(phases):
        return frozenset(), (), error
    return frozenset(phases), tuple(sorted(pairs)), []


def read_scope(raw: object, t: dict) -> tuple:
    """(Scope or None, errors)."""
    if not isinstance(raw, dict):
        return None, [t["e_missing"].format(where="scope", keys=", ".join(sorted(SCOPE_KEYS)))]
    errors = keys_errors(raw, SCOPE_KEYS, tuple(sorted(SCOPE_KEYS)), "scope", t)
    if errors:
        return None, errors
    ai = raw["ai"]
    if type(ai) is not bool:
        errors.append(t["e_ai"])
    na, reasons, e1 = na_set(raw["not_applicable"], t)
    nc, e2 = phase_set(raw["not_checked"], "not_checked", t)
    errors += e1 + e2
    if errors:
        return None, errors
    if na & nc:
        errors.append(t["e_overlap"].format(phases=", ".join(map(str, sorted(na & nc)))))
    if SECURITY_PHASE in na:
        errors.append(t["e_security_na"])
    if not ai and AI_PHASE in na | nc:
        errors.append(t["e_ai_na"])
    if ai and AI_PHASE in na:
        errors.append(t["e_ai_scope"])
    return Scope(ai, na, nc, reasons), errors


def text_field(item: dict, key: str, where: str, t: dict) -> list:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        return [t["e_text"].format(where=where, key=key)]
    return []


def id_errors(item: dict, where: str, t: dict) -> list:
    ident = item.get("id")
    match = ID.fullmatch(ident) if isinstance(ident, str) else None
    if not match:
        return [t["e_id"].format(where=where, value=ident)]
    expected = int(match.group(1))
    if type(item.get("phase")) is not int or item.get("phase") != expected:
        return [t["e_phase"].format(where=where, expected=expected)]
    return []


def valid_date(value: object) -> bool:
    if not isinstance(value, str) or not DATE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def status_errors(item: dict, where: str, t: dict) -> list:
    """The fields a status needs, and no closing field on an open finding."""
    status, errors = item.get("status"), []
    if "superseded_by" in item and status != "superseded":
        errors.append(t["e_superseded_status"].format(where=where))
    if status == "resolved" and "closed_on" not in item:
        errors.append(t["e_closed_on"].format(where=where))
    if status == "superseded" and "superseded_by" not in item:
        errors.append(t["e_needs_target"].format(where=where))
    return errors


def finding_errors(item: dict, where: str, t: dict) -> list:
    """Schema checks on one finding, independent of the others."""
    errors = keys_errors(item, set(REQUIRED) | set(OPTIONAL), REQUIRED, where, t)
    for key in ("area", "finding", "evidence", "remediation"):
        if key in item:
            errors += text_field(item, key, where, t)
    for key in ("effort_h", "acceptance", "dependencies", "note"):
        if key in item and not isinstance(item[key], str):
            errors += [t["e_text"].format(where=where, key=key)]
    errors += id_errors(item, where, t)
    if item.get("severity") not in SEVERITIES:
        errors.append(t["e_severity"].format(where=where))
    status = item.get("status")
    if status not in OPEN_STATUSES + CLOSED_STATUSES:
        errors.append(t["e_status"].format(where=where))
    if "closed_on" in item and not valid_date(item["closed_on"]):
        errors.append(t["e_date"].format(where=where))
    errors += status_errors(item, where, t)
    return errors


def register_errors(findings: list, scope: Scope, t: dict) -> list:
    """Cross-finding checks: duplicates, references, scope."""
    errors, ids = [], [f["id"] for f in findings]
    statuses = {f["id"]: f["status"] for f in findings}
    for ident in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(t["e_duplicate"].format(id=ident))
    for index, item in enumerate(findings):
        where = f"findings[{index}] ({item['id']})"
        target = item.get("superseded_by")
        if "superseded_by" in item and (target not in ids or target == item["id"]):
            errors.append(t["e_superseded"].format(where=where))
        elif "superseded_by" in item and statuses.get(target) == "superseded":
            errors.append(t["e_chain"].format(where=where))
        if item["phase"] in scope.not_applicable:
            errors.append(t["e_excluded"].format(id=item["id"], phase=item["phase"]))
        if item["phase"] == AI_PHASE and not scope.ai:
            errors.append(t["e_ai_findings"].format(id=item["id"]))
    return errors


def load(raw: object, t: dict) -> tuple:
    """(findings, scope) from the parsed JSON; raises Invalid with every problem found."""
    if not isinstance(raw, dict):
        raise Invalid([t["e_top"]])
    errors = keys_errors(raw, TOP_KEYS, tuple(sorted(TOP_KEYS)), "register", t)
    if errors:
        raise Invalid(errors)
    if raw["schema_version"] != SCHEMA_VERSION or type(raw["schema_version"]) is not int:
        errors.append(t["e_version"].format(version=SCHEMA_VERSION))
    scope, scope_errors = read_scope(raw["scope"], t)
    errors += scope_errors
    findings = raw["findings"]
    if not isinstance(findings, list):
        raise Invalid([*errors, t["e_findings"]])
    for index, item in enumerate(findings):
        if not isinstance(item, dict):
            errors.append(t["e_finding_type"].format(index=index))
            continue
        errors += finding_errors(item, f"findings[{index}]", t)
    if errors or scope is None:
        raise Invalid(errors)
    errors += register_errors(findings, scope, t)
    if errors:
        raise Invalid(errors)
    return findings, scope


# ---------------------------------------------------------------- scoring


def round1(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def european(value: Decimal) -> str:
    return str(value).replace(".", ",")


def normalised_weights(phases: list) -> dict:
    """Weights as percentages over the given phases; with the AI phase the others drop to 90."""
    weights = {f: Decimal(WEIGHTS[f]) for f in phases}
    if AI_PHASE in weights:
        for f in weights:
            if f != AI_PHASE:
                weights[f] *= Decimal("0.9")
    total = sum(weights.values(), Decimal(0))
    return {f: w / total * 100 for f, w in weights.items()}


def phase_score(s0: int, s1: int, s2: int, s3: int) -> Decimal:
    points = MAX_SCORE - min(Decimal(3), Decimal(s2)) - min(Decimal(1), Decimal("0.5") * s3)
    if s1:
        points = min(points, Decimal(6))
    if s0:
        points = min(points, Decimal(3))
    return points


def count_open(findings: list, ignore_status: bool) -> tuple:
    counts = {phase: [0, 0, 0, 0] for phase in WEIGHTS}
    closed = 0
    for item in findings:
        if not ignore_status and item["status"] in CLOSED_STATUSES:
            closed += 1
            continue
        counts[item["phase"]][SEVERITIES.index(item["severity"])] += 1
    return counts, closed


def caps_for(by_severity: list, coverage: Decimal, scope: Scope) -> list:
    caps = []
    if by_severity[0]:
        caps.append(("s0", CAP_S0))
    if by_severity[1]:
        caps.append(("s1", CAP_S1))
    if round1(coverage) < FULL_COVERAGE:
        caps.append(("coverage", CAP_COVERAGE))
    if SECURITY_PHASE in scope.not_checked:
        caps.append(("security", CAP_SECURITY_UNCHECKED))
    return caps


def compute(findings: list, scope: Scope, ignore_status: bool, t: dict) -> dict:
    applicable = [
        f for f in WEIGHTS if f not in scope.not_applicable and (f != AI_PHASE or scope.ai)
    ]
    checked = [f for f in applicable if f not in scope.not_checked]
    counts, closed = count_open(findings, ignore_status)
    # A not-checked phase stays in the average when it has open findings, so that declaring
    # it not checked can never raise the score; without findings it leaves the average.
    scored = [f for f in applicable if f in checked or any(counts[f])]
    if not scored:
        raise Invalid([t["e_nothing"]])
    coverage = sum((normalised_weights(applicable)[f] for f in checked), Decimal(0))
    weights = normalised_weights(scored)
    rows = []
    for f in scored:
        points = phase_score(*counts[f])
        rows.append(
            {
                "phase": f,
                "name": t["phases"][f],
                "checked": f in checked,
                "weight": weights[f],
                "s": counts[f],
                "score": points,
                "contribution": points * weights[f] / 100,
            }
        )
    by_severity = [sum(r["s"][i] for r in rows) for i in range(4)]
    average = round1(sum((r["contribution"] for r in rows), Decimal(0)))
    caps = caps_for(by_severity, coverage, scope)
    overall = min([average] + [value for _, value in caps])
    band = next(t["bands"][i] for i, minimum in enumerate(BAND_MINIMUMS) if overall >= minimum)
    return {
        "rows": rows,
        "average": average,
        "overall": overall,
        "band": band,
        "caps": [name for name, value in caps if value < average],
        "coverage": round1(coverage),
        "ai": scope.ai,
        "not_checked": sorted(scope.not_checked),
        "not_applicable": sorted(scope.not_applicable),
        "reasons": dict(scope.reasons),
        "closed": closed,
        "open": sum(by_severity),
        "by_severity": by_severity,
    }


# ---------------------------------------------------------------- rendering


def phase_names(phases: list, t: dict) -> str:
    return ", ".join(f"{f}. {t['phases'][f]}" for f in phases)


def score_block(result: dict, t: dict) -> str:
    s = result["by_severity"]
    caps = "; ".join(t["caps"][name] for name in result["caps"]) or t["no_caps"]
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
        t["average"].format(average=european(result["average"]), caps=caps),
        t["coverage"].format(
            coverage=european(result["coverage"]), ai=t["ai_yes"] if result["ai"] else t["ai_no"]
        ),
    ]
    if result["not_checked"]:
        lines.append(t["not_checked"].format(phases=phase_names(result["not_checked"], t)))
    if result["not_applicable"]:
        reasons = result["reasons"]
        named = ", ".join(
            f"{f}. {t['phases'][f]} ({cell(reasons[f])})" for f in result["not_applicable"]
        )
        lines.append(t["not_applicable"].format(phases=named))
    lines += ["", t["score_header"], "|---|---|---|---|---|---|---|---|"]
    for r in result["rows"]:
        name = r["name"] + ("" if r["checked"] else t["unchecked_row"])
        weight = european(round1(r["weight"]))
        score = european(round1(r["score"]))
        contribution = european(r["contribution"].quantize(Decimal("0.01"), ROUND_HALF_UP))
        s0, s1, s2, s3 = r["s"]
        lines.append(
            f"| {r['phase']}. {name} | {weight} | {s0} | {s1} | {s2} | {s3} | "
            f"{score} | {contribution} |"
        )
    lines += ["", t["footer"]]
    return "\n".join(lines)


def cell(value: object) -> str:
    """A table cell: every line break flattened, pipes escaped, HTML comments neutralised."""
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    text = text.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    return re.sub(r"(?<!\\)\|", r"\\|", text)


def register_block(findings: list, t: dict, source: str) -> str:
    order = sorted(findings, key=lambda f: (SEVERITIES.index(f["severity"]), f["phase"], f["id"]))
    lines = [t["register_header"], "|---|---|---|---|---|---|---|---|---|---|---|"]
    for f in order:
        status = t["status"][f["status"]]
        if f.get("closed_on"):
            status += f" {f['closed_on']}"
        if f.get("superseded_by"):
            status += f" → {f['superseded_by']}"
        values = [
            f["id"],
            f["phase"],
            f["area"],
            f["finding"],
            f["severity"],
            status,
            f["evidence"],
            f["remediation"],
            f.get("effort_h", ""),
            f.get("acceptance", ""),
            f.get("dependencies", ""),
        ]
        lines.append("| " + " | ".join(cell(v) for v in values) + " |")
    lines += ["", t["register_footer"].format(file=cell(source))]
    return "\n".join(lines)


def as_json(result: dict) -> dict:
    keys = ("band", "caps", "ai", "not_checked", "not_applicable", "open", "closed")
    data = {key: result[key] for key in keys}
    data.update(
        overall=float(result["overall"]),
        average=float(result["average"]),
        coverage=float(result["coverage"]),
        by_severity=result["by_severity"],
        phases=[
            {
                "phase": r["phase"],
                "name": r["name"],
                "checked": r["checked"],
                "weight": float(round1(r["weight"])),
                "s0": r["s"][0],
                "s1": r["s"][1],
                "s2": r["s"][2],
                "s3": r["s"][3],
                "score": float(r["score"]),
            }
            for r in result["rows"]
        ],
    )
    return data


# ---------------------------------------------------------------- report blocks


def split_block(text: str, markers: tuple) -> tuple | None:
    """(before, inside, after) for one marker pair, or None if absent or out of order."""
    start, end = markers
    if text.count(start) != 1 or text.count(end) != 1:
        return None
    a, b = text.index(start), text.index(end)
    if b < a:
        return None
    return text[: a + len(start)], text[a + len(start) : b], text[b:]


def replace_block(text: str, markers: tuple, content: str) -> str:
    parts = split_block(text, markers)
    if parts is None:
        return text
    before, _, after = parts
    return f"{before}\n{content}\n{after}"


def block_matches(text: str, markers: tuple, content: str) -> bool:
    parts = split_block(text, markers)
    return parts is not None and parts[1].strip() == content.strip()


def markers_ok(text: str) -> bool:
    """Both marker pairs present once, each in order, and not overlapping."""
    if split_block(text, SCORE_MARKERS) is None or split_block(text, REGISTER_MARKERS) is None:
        return False
    spans = sorted((text.index(a), text.index(b)) for a, b in (SCORE_MARKERS, REGISTER_MARKERS))
    return spans[0][1] < spans[1][0]


def check_markers(text: str, t: dict) -> None:
    if not markers_ok(text):
        raise Invalid(
            [
                t["e_markers"].format(
                    score=" ".join(SCORE_MARKERS), register=" ".join(REGISTER_MARKERS)
                )
            ]
        )


# ---------------------------------------------------------------- command line


def parse_threshold(value: str | None, t: dict) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(value.replace(",", "."))
    except InvalidOperation:
        number = None
    if number is None or not number.is_finite() or not 0 <= number <= MAX_SCORE:
        raise Invalid([t["e_threshold"].format(value=value)])
    return number


class DuplicateKey(ValueError):
    pass


def no_duplicates(pairs: list) -> dict:
    keys = [k for k, _ in pairs]
    for key in keys:
        if keys.count(key) > 1:
            raise DuplicateKey(key)
    return dict(pairs)


def read_json(path: Path, t: dict) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise Invalid([t["e_file"].format(path=path)]) from error
    try:
        return json.loads(text, object_pairs_hook=no_duplicates)
    except DuplicateKey as error:
        raise Invalid([t["e_dup_key"].format(key=error.args[0])]) from error
    except json.JSONDecodeError as error:
        raise Invalid([t["e_json"].format(error=error)]) from error
    except RecursionError as error:
        raise Invalid([t["e_depth"]]) from error


def read_report(args, t: dict) -> str | None:
    if not (args.write or args.check):
        return None
    if args.report is None:
        raise Invalid([t["e_needs_report"]])
    try:
        text = args.report.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise Invalid([t["e_file"].format(path=args.report)]) from error
    check_markers(text, t)
    return text


def fail(errors: list, args, t: dict) -> int:
    print(f"audit_score: {t['invalid']}", file=sys.stderr)
    for line in errors:
        print(f"  - {line}", file=sys.stderr)
    if not (args.write and args.report is not None):
        return 1
    try:
        text = args.report.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 1
    if not markers_ok(text):
        print(f"audit_score: {t['e_not_replaced']}", file=sys.stderr)
        return 1
    notice = "\n".join([t["invalid_block"], "", *[f"- {cell(e)}" for e in errors]])
    text = replace_block(text, SCORE_MARKERS, notice)
    text = replace_block(text, REGISTER_MARKERS, t["register_invalid"])
    args.report.write_text(text, encoding="utf-8")
    return 1


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Health score of a platform audit, computed from the JSON findings register."
    )
    p.add_argument("register", type=Path, help="the JSON findings register")
    p.add_argument("--report", "--rapporto", type=Path, default=None, help="the Markdown report")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--write", "--scrivi", action="store_true", help="write the generated blocks in the report"
    )
    mode.add_argument(
        "--check", "--verifica", action="store_true", help="exit 1 if the blocks are stale"
    )
    p.add_argument(
        "--threshold", "--soglia", default=None, help="exit 2 below this score (6.0 or 6,0)"
    )
    p.add_argument(
        "--ignore-status",
        "--ignora-stati",
        action="store_true",
        help="count every finding as open (initial score)",
    )
    p.add_argument("--lang", choices=sorted(TEXT), default="en", help="output language")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    return p


def main() -> int:
    args = parser().parse_args()
    t = TEXT[args.lang]
    try:
        threshold = parse_threshold(args.threshold, t)
        findings, scope = load(read_json(args.register, t), t)
        result = compute(findings, scope, args.ignore_status, t)
        report = read_report(args, t)
    except Invalid as error:
        return fail(error.errors, args, t)

    summary = score_block(result, t)
    table = register_block(findings, t, args.register.name)
    score = european(result["overall"])
    if report is None:
        print(json.dumps(as_json(result), ensure_ascii=False, indent=1) if args.json else summary)
    elif args.check:
        fresh = block_matches(report, SCORE_MARKERS, summary)
        if not (fresh and block_matches(report, REGISTER_MARKERS, table)):
            print(f"audit_score: {t['stale']}", file=sys.stderr)
            return 1
        print(t["checked"].format(score=score))
    else:
        report = replace_block(report, SCORE_MARKERS, summary)
        args.report.write_text(replace_block(report, REGISTER_MARKERS, table), encoding="utf-8")
        print(t["written"].format(score=score))
    if threshold is not None and result["overall"] < threshold:
        below = t["below"].format(score=score, threshold=european(threshold))
        print(f"audit_score: {below}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
