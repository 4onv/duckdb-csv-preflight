import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import csv_preflight


SCRIPT = Path(csv_preflight.__file__).resolve()
REFERENCE = "id,amount,date\n1,50,2026-11-20\n2,35,2026-11-21\n"


class PreflightTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(TemporaryDirectory(prefix="csv preflight test "))
        self.root = Path(folder)
        self.reference = self.write("reference's input.csv", REFERENCE)

    def write(self, name, content):
        path = self.root / name
        path.write_bytes(content.encode("utf-8"))
        return name

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), *args],
            cwd=self.root, capture_output=True, text=True, encoding="utf-8", check=False,
        )

    def run_check(self, *files):
        result = self.run_cli("check", self.reference, *files, "--sample-size", "-1", "--json")
        self.assertEqual(result.stderr, "")
        return result.returncode, json.loads(result.stdout)

    def test_matching_file_and_ordered_batches(self):
        same = self.write("same.csv", "id,amount,date\n7,19,2026-11-22\n8,95,2026-11-23\n")
        another = self.write("other.csv", REFERENCE)
        status, report = self.run_check(same, another)
        self.assertEqual(status, 0)
        self.assertEqual(report["version"], 1)
        self.assertEqual(report["changed_files"], 0)
        self.assertEqual([item["path"] for item in report["files"]], [same, another])
        self.assertTrue(all(item["changes"] == [] for item in report["files"]))

    def test_detects_dialect_and_schema_drift(self):
        data = "id;amount;currency\n5;unknown;USD\n6;missing;EUR\n"
        changed = self.write("changed.csv", data)
        status, report = self.run_check(changed)
        self.assertEqual(status, 1)
        self.assertEqual(report["changed_files"], 1)
        changes = report["files"][0]["changes"]
        self.assertIn({"kind": "dialect", "field": "delimiter", "before": ",", "after": ";"}, changes)
        self.assertIn({"kind": "column_removed", "column": "date", "before": "DATE"}, changes)
        self.assertIn({"kind": "column_added", "column": "currency", "after": "VARCHAR"}, changes)
        self.assertIn({"kind": "column_type", "column": "amount", "before": "BIGINT", "after": "VARCHAR"}, changes)
        self.assertEqual((self.root / changed).read_bytes(), data.encode("utf-8"))

    def test_shared_column_reordering_with_added_column(self):
        changed = self.write("reordered.csv", "amount,currency,id,date\n50,USD,1,2026-11-20\n35,EUR,2,2026-11-21\n")
        status, report = self.run_check(changed)
        self.assertEqual(status, 1)
        changes = report["files"][0]["changes"]
        self.assertIn({
            "kind": "column_order", "before": ["id", "amount", "date"],
            "after": ["amount", "id", "date"],
        }, changes)

    def test_newline_drift(self):
        changed = self.write("crlf.csv", REFERENCE.replace("\n", "\r\n"))
        status, report = self.run_check(changed)
        self.assertEqual(status, 1)
        self.assertEqual(report["files"][0]["changes"], [
            {"kind": "dialect", "field": "newline", "before": r"\n", "after": r"\r\n"},
        ])

    def test_input_error_takes_precedence_but_keeps_other_results(self):
        changed = self.write("changed.csv", REFERENCE.replace(",", ";"))
        status, report = self.run_check("missing.csv", changed)
        self.assertEqual(status, 2)
        self.assertEqual(report["errors"], 1)
        self.assertEqual(report["changed_files"], 1)
        self.assertIn("error", report["files"][0])
        self.assertNotIn("changes", report["files"][0])

    def test_unreadable_reference_does_not_report_no_drift(self):
        result = self.run_cli("check", "missing.csv", self.reference, "--json")
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertIn("error", report["reference"])
        self.assertNotIn("changes", report["files"][0])

    def test_rejects_glob_paths_and_bad_sample_sizes(self):
        glob_name = self.write("input[1].csv", REFERENCE)
        status, report = self.run_check(glob_name)
        self.assertEqual(status, 2)
        self.assertIn("glob metacharacters", report["files"][0]["error"])
        result = self.run_cli("check", self.reference, glob_name, "--sample-size", "0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("use -1 or an integer", result.stderr)

    def test_demo_is_labeled_and_works_without_input(self):
        result = self.run_cli("demo", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["synthetic"])
        self.assertEqual(report["changed_files"], 1)
        self.assertEqual(report["errors"], 0)


if __name__ == "__main__":
    unittest.main()
