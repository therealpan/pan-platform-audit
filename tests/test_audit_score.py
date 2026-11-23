"""Tests for the audit score on a sample register."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "audit_score.py"
REPORT = """# Sample audit

## Status

| ID | Sev. | Status | Done | Left |
|---|---|---|---|---|
| P2-01 | S0 | resolved | key rotated | nothing |
| P7-01 | S1 | resolved in the technical part, notice still open | logs cleaned | notice |

{start}
stale
{end}

## Register

| ID | Phase | Area | Finding | Sev. | Evidence | Remediation |
|---|---|---|---|---|---|---|
| P2-01 | 2 | SSH | key in the repo | S0 | file:1 | rotate |
| P2-02 | 2 | Token | no expiry | S2 | file:2 | add |
| P7-01 | 7 | Logs | email in logs | S1 | file:3 | mask |
| P8-01 | 8 | Tests | uncovered path | S2 | file:4 | write |
| P8-02 | 8 | Tests | skipped tests | S3 | file:5 | re-enable |
| P8-03 | 8 | Tests | weak assertions | S3 | a \\| b | strengthen |
| P8-04 | 8 | Tests | third minor | S3 | file:7 | fix |
"""
EN = ("<!-- score:start -->", "<!-- score:end -->")
IT = ("<!-- punteggio:inizio -->", "<!-- punteggio:fine -->")


class AuditScore(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.file = self.dir / "report.md"
        self.prepare(EN)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def prepare(self, markers):
        start, end = markers
        self.file.write_text(REPORT.format(start=start, end=end), encoding="utf-8")

    def run_script(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(self.file), *arguments],
            capture_output=True,
            text=True,
        )

    def data(self, *arguments):
        result = self.run_script("--json", *arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_initial_score(self):
        d = self.data("--ignore-status")
        phases = {f["phase"]: f["score"] for f in d["phases"]}
        self.assertEqual(phases[2], 3.0)  # S0: cap 3
        self.assertEqual(phases[7], 6.0)  # S1: cap 6
        self.assertEqual(phases[8], 8.0)  # 10 - 1 (one S2) - 1 (three S3, max 1)
        self.assertEqual(phases[1], 10.0)
        # 10 phases, weights 100: 25*3 + 10*6 + 10*8 + 55*10 = 765 -> 7,65 -> 7,7
        self.assertEqual(d["overall"], 7.7)
        self.assertEqual(d["band"], "production with hardening")
        self.assertNotIn(11, phases)

    def test_closed_leave_and_partial_stay(self):
        d = self.data()
        phases = {f["phase"]: f["score"] for f in d["phases"]}
        self.assertEqual(phases[2], 9.0)  # S0 resolved, one S2 left
        self.assertEqual(phases[7], 6.0)  # resolved only in part: stays open
        self.assertEqual(d["partial"], ["P7-01"])
        self.assertEqual((d["open"], d["closed"]), (6, 1))

    def test_not_applicable_and_ai(self):
        d = self.data("--ignore-status", "--not-applicable", "6,9", "--ai")
        weights = {f["phase"]: f["weight"] for f in d["phases"]}
        self.assertNotIn(6, weights)
        self.assertEqual(round(sum(weights.values())), 100)
        self.assertAlmostEqual(weights[11] / weights[1], 10 / 9, places=1)

    def test_write_and_check(self):
        self.assertEqual(self.run_script("--check").returncode, 1)
        self.assertEqual(self.run_script("--write").returncode, 0)
        self.assertEqual(self.run_script("--check").returncode, 0)
        text = self.file.read_text(encoding="utf-8")
        self.assertIn("out of 10, band", text)
        self.assertIn("| P8-04 |", text)

    def test_threshold(self):
        self.assertEqual(self.run_script("--threshold", "9.5").returncode, 2)
        self.assertEqual(self.run_script("--threshold", "6.0").returncode, 0)

    def test_italian_output_aliases_and_markers(self):
        self.prepare(IT)
        d = self.data("--ignora-stati", "--lang", "it")
        self.assertEqual(d["band"], "produzione con irrobustimento")
        self.assertEqual(self.run_script("--scrivi", "--lang", "it").returncode, 0)
        self.assertEqual(self.run_script("--verifica", "--lang", "it").returncode, 0)
        self.assertIn("su 10, fascia", self.file.read_text(encoding="utf-8"))
        self.assertEqual(self.run_script("--soglia", "9.5").returncode, 2)

    def test_missing_markers(self):
        self.file.write_text(REPORT.format(start="", end=""), encoding="utf-8")
        self.assertEqual(self.run_script("--write").returncode, 1)


if __name__ == "__main__":
    unittest.main()
