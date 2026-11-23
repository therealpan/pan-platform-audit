"""Tests for the audit score on JSON registers."""

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "audit_score.py"
EXAMPLE = ROOT / "examples" / "register.example.json"
REPORT = """# Audit

<!-- score:start -->
old
<!-- score:end -->

## Findings register

<!-- register:start -->
old
<!-- register:end -->
"""


def finding(ident, severity, status="open", **extra):
    item = {
        "id": ident,
        "phase": int(ident[1:].split("-")[0]),
        "severity": severity,
        "status": status,
        "area": "area",
        "finding": f"finding {ident}",
        "evidence": "file:1",
        "remediation": "fix",
    }
    item.update(extra)
    return item


def register(*findings, ai=False, not_applicable=(), not_checked=()):
    return {
        "schema_version": 1,
        "scope": {
            "ai": ai,
            "not_applicable": [
                {"phase": n, "reason": "nothing to examine"} for n in not_applicable
            ],
            "not_checked": list(not_checked),
        },
        "findings": list(findings),
    }


# The sample of the original tests: 25*3 + 10*6 + 10*8 + 55*10 = 765 -> 7,65 -> 7,7
SAMPLE = register(
    finding("P2-01", "S0", "resolved", closed_on="2026-11-20"),
    finding("P2-02", "S2"),
    finding("P7-01", "S1"),
    finding("P8-01", "S2"),
    finding("P8-02", "S3"),
    finding("P8-03", "S3", evidence="a | b"),
    finding("P8-04", "S3"),
)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.file = self.dir / "register.json"
        self.report = self.dir / "report.md"
        self.report.write_text(REPORT, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def save(self, data):
        self.file.write_text(json.dumps(data), encoding="utf-8")

    def run_script(self, *arguments, path=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(path or self.file), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )

    def data(self, register_data, *arguments):
        self.save(register_data)
        result = self.run_script("--json", *arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def fails(self, register_data, expected, *arguments):
        if register_data is not None:
            self.save(register_data)
        result = self.run_script(*arguments)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(expected, result.stderr)
        return result


class Scoring(Base):
    def test_phase_scores_and_s0_cap(self):
        d = self.data(SAMPLE, "--ignore-status")
        phases = {f["phase"]: f["score"] for f in d["phases"]}
        self.assertEqual((phases[2], phases[7], phases[8], phases[1]), (3.0, 6.0, 8.0, 10.0))
        self.assertEqual((d["average"], d["overall"]), (7.7, 3.9))
        self.assertEqual(d["band"], "stop and stabilise")
        self.assertNotIn(11, phases)

    def test_closed_findings_leave_and_s1_caps(self):
        d = self.data(SAMPLE)
        # 25*9 + 10*6 + 10*8 + 55*10 = 915 -> 9,2, capped at 7,9 by the open S1
        self.assertEqual((d["average"], d["overall"], d["closed"]), (9.2, 7.9, 1))
        self.assertEqual(d["band"], "production with hardening")

    def test_single_s0_is_never_production_grade(self):
        d = self.data(register(finding("P2-01", "S0")))
        self.assertEqual((d["average"], d["overall"]), (8.3, 3.9))
        self.assertEqual(d["band"], "stop and stabilise")

    def test_single_s1_is_not_production_grade(self):
        d = self.data(register(finding("P4-01", "S1")))
        self.assertEqual((d["average"], d["overall"]), (9.6, 7.9))

    def test_regressed_counts_as_open(self):
        d = self.data(register(finding("P2-01", "S0", "regressed")))
        self.assertEqual(d["overall"], 3.9)

    def test_superseded_closes(self):
        d = self.data(
            register(
                finding("P2-01", "S1", "superseded", superseded_by="P2-02"), finding("P2-02", "S3")
            )
        )
        self.assertEqual((d["closed"], d["band"]), (1, "production grade"))

    def test_empty_register_is_a_clean_audit(self):
        d = self.data(register())
        self.assertEqual(
            (d["overall"], d["band"], d["coverage"]), (10.0, "production grade", 100.0)
        )

    def test_ai_weights_and_not_applicable(self):
        d = self.data(register(ai=True, not_applicable=[6, 9]))
        weights = {f["phase"]: f["weight"] for f in d["phases"]}
        self.assertNotIn(6, weights)
        self.assertEqual(round(sum(weights.values())), 100)
        self.assertAlmostEqual(weights[11] / weights[1], 10 / 9, places=1)
        self.assertEqual(d["coverage"], 100.0)

    def test_not_checked_without_findings_lowers_coverage_and_caps(self):
        d = self.data(register(finding("P9-01", "S3"), not_checked=[6]))
        self.assertEqual((d["coverage"], d["overall"]), (95.0, 7.9))
        self.assertIn("coverage", d["caps"])
        self.assertNotIn(6, {f["phase"] for f in d["phases"]})

    def test_security_not_checked_caps_lower(self):
        d = self.data(register(not_checked=[2]))
        self.assertEqual((d["overall"], d["band"]), (5.9, "not ready, plan required"))

    def test_findings_in_unchecked_phase_cap_and_stay_in_the_average(self):
        d = self.data(register(finding("P5-01", "S0"), not_checked=[5]))
        self.assertEqual(d["overall"], 3.9)
        row = next(f for f in d["phases"] if f["phase"] == 5)
        self.assertEqual((row["score"], row["checked"]), (3.0, False))

    def test_not_checked_never_raises_the_score(self):
        phases = [1, 3, 4, 5, 6, 7, 8, 9, 10]
        items = []
        for p in phases:
            items += [finding(f"P{p}-0{i}", "S2") for i in range(1, 4)]
            items += [finding(f"P{p}-0{i}", "S3") for i in range(4, 6)]
        checked = self.data(register(*items))
        unchecked = self.data(register(*items, not_checked=[1, 4, 5, 7, 8, 10]))
        self.assertLessEqual(unchecked["overall"], checked["overall"])
        self.assertEqual(unchecked["average"], checked["average"])

    def test_threshold(self):
        self.save(SAMPLE)
        self.assertEqual(self.run_script("--threshold", "8.0").returncode, 2)
        self.assertEqual(self.run_script("--threshold", "6,0").returncode, 0)

    def test_registers_used_in_tests_match_the_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        if not hasattr(jsonschema, "Draft202012Validator"):
            self.skipTest("jsonschema too old for draft 2020-12")
        schema = json.loads((ROOT / "register.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        for data in (SAMPLE, json.loads(EXAMPLE.read_text(encoding="utf-8")), register(ai=True)):
            jsonschema.validate(data, schema)
        bad = register(finding("P2-01", "S0", "resolved"))
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)

    def test_example_register_is_valid(self):
        result = self.run_script(path=EXAMPLE)
        self.assertEqual(result.returncode, 0, result.stderr)


class Report(Base):
    def test_write_and_check(self):
        self.save(SAMPLE)
        self.assertEqual(self.run_script("--report", str(self.report), "--check").returncode, 1)
        result = self.run_script("--report", str(self.report), "--write")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.run_script("--report", str(self.report), "--check").returncode, 0)
        text = self.report.read_text(encoding="utf-8")
        self.assertIn("out of 10, band", text)
        self.assertIn("| P8-03 |", text)
        self.assertIn("a \\| b", text)
        self.assertLess(text.index("| P7-01 |"), text.index("| P8-01 |"))  # S1 before S2

    def test_check_detects_a_hand_edit_of_the_table(self):
        self.save(SAMPLE)
        self.run_script("--report", str(self.report), "--write")
        text = self.report.read_text(encoding="utf-8").replace("| S1 |", "| S3 |")
        self.report.write_text(text, encoding="utf-8")
        self.assertEqual(self.run_script("--report", str(self.report), "--check").returncode, 1)

    def test_write_on_invalid_register_replaces_the_score(self):
        self.report.write_text(
            REPORT.replace("old\n<!-- score:end", "10,0 production grade\n<!-- score:end"),
            encoding="utf-8",
        )
        bad = register(finding("P2-01", "S9"))
        self.fails(bad, "severity", "--report", str(self.report), "--write")
        text = self.report.read_text(encoding="utf-8")
        self.assertIn("Score not computed", text)
        self.assertNotIn("production grade", text)

    def test_marker_text_in_a_finding_cannot_break_the_report(self):
        sneaky = finding(
            "P9-01", "S3", finding="see <!-- score:start --> and <!-- register:end -->"
        )
        self.save(register(sneaky))
        self.assertEqual(self.run_script("--report", str(self.report), "--write").returncode, 0)
        self.save(register(sneaky, finding("P2-01", "S0")))
        self.assertEqual(self.run_script("--report", str(self.report), "--write").returncode, 0)
        text = self.report.read_text(encoding="utf-8")
        self.assertEqual(text.count("<!-- score:start -->"), 1)
        self.assertIn("stop and stabilise", text)
        self.assertEqual(self.run_script("--report", str(self.report), "--check").returncode, 0)

    def test_unusual_line_breaks_survive_write_and_check(self):
        self.save(register(finding("P9-01", "S3", finding="a\rb\u2028c\td  e")))
        self.assertEqual(self.run_script("--report", str(self.report), "--write").returncode, 0)
        self.assertEqual(self.run_script("--report", str(self.report), "--check").returncode, 0)
        self.assertIn("| a b c d e |", self.report.read_text(encoding="utf-8"))

    def test_invalid_write_replaces_both_blocks(self):
        self.save(register(finding("P9-01", "S3")))
        self.run_script("--report", str(self.report), "--write")
        self.fails(
            register(finding("P9-01", "S7")), "severity", "--report", str(self.report), "--write"
        )
        text = self.report.read_text(encoding="utf-8")
        self.assertIn("Register table not generated", text)
        self.assertNotIn("| P9-01 |", text)

    def test_overlapping_markers(self):
        self.report.write_text(
            "<!-- score:start -->\n<!-- register:start -->\n<!-- score:end -->\n"
            "<!-- register:end -->\n",
            encoding="utf-8",
        )
        self.fails(SAMPLE, "not overlapping", "--report", str(self.report), "--write")

    def test_markers_are_required(self):
        self.report.write_text("# no markers\n", encoding="utf-8")
        self.fails(SAMPLE, "marker pairs", "--report", str(self.report), "--write")
        self.report.write_text(REPORT + "\n<!-- score:start -->\n", encoding="utf-8")
        self.fails(SAMPLE, "marker pairs", "--report", str(self.report), "--check")

    def test_write_needs_report(self):
        self.fails(SAMPLE, "need --report", "--write")

    def test_italian(self):
        self.save(SAMPLE)
        result = self.run_script("--rapporto", str(self.report), "--scrivi", "--lang", "it")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.report.read_text(encoding="utf-8")
        self.assertIn("su 10, fascia", text)
        self.assertIn("| Severità |", text)
        self.assertIn("risolto 2026-11-20", text)
        self.assertEqual(self.run_script("--soglia", "9,5", "--lang", "it").returncode, 2)
        self.assertEqual(
            self.run_script(
                "--rapporto", str(self.report), "--verifica", "--lang", "it"
            ).returncode,
            0,
        )


class Validation(Base):
    def broken(self, mutate, expected):
        data = copy.deepcopy(SAMPLE)
        mutate(data)
        self.fails(data, expected)

    def test_schema_violations(self):
        cases = {
            "unknown top key": (lambda d: d.update(extra=1), "unknown keys extra"),
            "missing scope": (lambda d: d.pop("scope"), "missing scope"),
            "version": (lambda d: d.update(schema_version=2), "schema_version must be 1"),
            "ai missing": (lambda d: d["scope"].pop("ai"), "scope: missing ai"),
            "ai not bool": (lambda d: d["scope"].update(ai="no"), "scope.ai must be"),
            "phase list": (lambda d: d["scope"].update(not_checked=[3, 3]), "scope.not_checked"),
            "na plain list": (
                lambda d: d["scope"].update(not_applicable=[6]),
                "not_applicable must",
            ),
            "na no reason": (
                lambda d: d["scope"].update(not_applicable=[{"phase": 6, "reason": " "}]),
                "not_applicable must",
            ),
            "na extra key": (
                lambda d: d["scope"].update(not_applicable=[{"phase": 6, "reason": "x", "y": 1}]),
                "not_applicable must",
            ),
            "resolved without date": (
                lambda d: d["findings"][0].pop("closed_on"),
                "resolved needs closed_on",
            ),
            "superseded without target": (
                lambda d: d["findings"][1].update(status="superseded"),
                "superseded needs superseded_by",
            ),
            "arabic digits": (
                lambda d: d["findings"][1].update(id="P2-\u0660\u0662"),
                "not in the form",
            ),
            "phase list bool": (
                lambda d: d["scope"].update(not_checked=[True]),
                "scope.not_checked",
            ),
            "findings not list": (lambda d: d.update(findings={}), "findings must be a list"),
            "finding not object": (lambda d: d["findings"].append("x"), "is not an object"),
            "unknown finding key": (
                lambda d: d["findings"][0].update(sev="S0"),
                "unknown keys sev",
            ),
            "missing evidence": (lambda d: d["findings"][0].pop("evidence"), "missing evidence"),
            "empty finding": (lambda d: d["findings"][0].update(finding=" "), "finding must be"),
            "bad id": (lambda d: d["findings"][0].update(id="p2-01"), "is not in the form"),
            "short id": (lambda d: d["findings"][0].update(id="P2-1"), "is not in the form"),
            "phase mismatch": (lambda d: d["findings"][0].update(phase=4), "phase must be"),
            "phase bool": (lambda d: d["findings"][0].update(phase=True, id="P1-01"), "phase must"),
            "severity": (lambda d: d["findings"][0].update(severity="High"), "severity must"),
            "severity case": (lambda d: d["findings"][0].update(severity="s0"), "severity must"),
            "status": (lambda d: d["findings"][0].update(status="closed"), "status must"),
            "date": (lambda d: d["findings"][0].update(closed_on="20/11/2026"), "closed_on"),
            "impossible date": (
                lambda d: d["findings"][0].update(closed_on="2026-13-45"),
                "closed_on",
            ),
            "duplicate": (lambda d: d["findings"][2].update(id="P2-02", phase=2), "duplicate id"),
            "superseded target": (
                lambda d: d["findings"][0].update(status="superseded", superseded_by="P9-09"),
                "superseded_by must be",
            ),
            "superseded status": (
                lambda d: d["findings"][1].update(superseded_by="P2-01"),
                "status is not superseded",
            ),
        }
        for name, (mutate, expected) in cases.items():
            with self.subTest(name=name):
                self.broken(mutate, expected)

    def test_scope_contradictions(self):
        self.fails(register(not_applicable=[2]), "always applies")
        self.fails(register(not_applicable=[6], not_checked=[6]), "both not applicable")
        self.fails(register(ai=True, not_applicable=[11]), "phase 11 is listed")
        self.fails(register(ai=False, not_checked=[11]), "phase 11 is listed")
        self.fails(register(finding("P6-01", "S2"), not_applicable=[6]), "declared not applicable")
        self.fails(register(finding("P11-01", "S1")), "AI finding while scope.ai is false")

    def test_superseded_chain(self):
        data = register(
            finding("P2-01", "S0", "superseded", superseded_by="P2-02"),
            finding("P2-02", "S0", "superseded", superseded_by="P2-01"),
        )
        self.fails(data, "itself superseded")

    def test_duplicate_json_keys(self):
        for text in (
            '{"schema_version": 1, "scope": {"ai": false, "not_applicable": [], '
            '"not_checked": []}, "findings": [], "findings": []}',
            json.dumps(register(finding("P2-01", "S0"))).replace(
                '"severity": "S0"', '"severity": "S0", "severity": "S3"'
            ),
        ):
            with self.subTest(text=text[-40:]):
                self.file.write_text(text, encoding="utf-8")
                self.fails(None, "duplicate key")

    def test_deep_nesting(self):
        self.file.write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
        self.fails(None, "nested too deeply")

    def test_bad_inputs(self):
        self.file.write_text("{not json", encoding="utf-8")
        self.fails(None, "not valid JSON")
        missing = self.run_script(path=self.dir / "none.json")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("cannot read", missing.stderr)
        self.fails(SAMPLE, "not a valid threshold", "--threshold", "nan")
        self.fails(SAMPLE, "not a valid threshold", "--threshold", "11")
        self.file.write_text("[]", encoding="utf-8")
        self.fails(None, "top level")

    def test_every_error_is_listed(self):
        data = register(finding("P2-01", "S9"), finding("P2-01", "S0", status="done"))
        result = self.fails(data, "severity")
        self.assertIn("status must be", result.stderr)


if __name__ == "__main__":
    unittest.main()
