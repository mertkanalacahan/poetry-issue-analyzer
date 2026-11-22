"""Team 5 tests for run.py, config.py and data_loader.py."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import config
import data_loader

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SAMPLE = [{
    "url": "https://github.com/python-poetry/poetry/issues/1",
    "creator": "reporter", "labels": ["kind/bug"], "state": "closed",
    "assignees": [], "title": "Sample", "text": "", "number": 1,
    "created_date": "2024-01-01T00:00:00+00:00",
    "updated_date": "2024-03-01T00:00:00+00:00",
    "timeline_url": "",
    "events": [
        {"event_type": "labeled", "author": "maint", "event_date": "2024-01-02T00:00:00+00:00", "label": "kind/bug"},
        {"event_type": "commented", "author": "maint", "event_date": "2024-01-03T00:00:00+00:00", "comment": "Thanks"},
        {"event_type": "closed", "author": "maint", "event_date": "2024-01-04T00:00:00+00:00"},
        {"event_type": "commented", "author": "bob", "event_date": "2024-03-01T00:00:00+00:00", "comment": "Same here."},
    ],
}]


def run_program(args, data_path):
    """Run `python run.py ...` like a user would and capture the result."""
    env = dict(os.environ, MPLBACKEND="Agg", ENPM611_PROJECT_DATA_PATH=data_path)
    return subprocess.run([sys.executable, "run.py", *args], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)


class RunPyTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data = os.path.join(cls.tmp.name, "sample.json")
        with open(cls.data, "w") as f:
            json.dump(SAMPLE, f)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_each_feature_runs_end_to_end(self):
        for feature, heading in [("1", "SAME-PROBLEM REPORTS"),
                                 ("2", "DEVELOPER RESPONSE TIME"),
                                 ("3", "STALE OPEN ISSUES")]:
            with self.subTest(feature=feature):
                result = run_program(["--feature", feature], self.data)
                self.assertEqual(result.returncode, 0, result.stderr)
                if feature != "3":   # the only issue is closed, so feature 3 prints a message
                    self.assertIn(heading, result.stdout)

    def test_missing_data_file_gives_a_clear_message(self):
        # DEFECT: a wrong data path ends in a FileNotFoundError traceback.
        result = run_program(["--feature", "2"], os.path.join(self.tmp.name, "missing.json"))
        self.assertNotIn("Traceback", result.stderr,
                         "missing data file crashed with a traceback")

    def test_invalid_feature_number_is_reported_as_an_error(self):
        # DEFECT: --feature 4 prints "Need to specify ..." and exits with status 0.
        result = run_program(["--feature", "4"], self.data)
        self.assertNotEqual(result.returncode, 0,
                            "an invalid --feature value exits as if it succeeded")


class ConfigTests(unittest.TestCase):

    def test_typed_value_conversion(self):
        self.assertEqual(config.convert_to_typed_value("90"), 90)
        self.assertEqual(config.convert_to_typed_value("kind/bug"), "kind/bug")
        self.assertIsNone(config.convert_to_typed_value(None))

    def test_set_and_get_parameter_round_trip(self):
        with patch.dict(os.environ, {}, clear=False):
            config.set_parameter("team5_days", 30)
            config.set_parameter("team5_label", "kind/bug")
            self.assertEqual(config.get_parameter("team5_days"), 30)
            self.assertEqual(config.get_parameter("team5_label"), "kind/bug")
            self.assertEqual(config.get_parameter("team5_absent", "fallback"), "fallback")


class DataLoaderTests(unittest.TestCase):

    def test_loads_issues_from_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sample.json")
            with open(path, "w") as f:
                json.dump(SAMPLE, f)
            with patch.dict(os.environ, {"ENPM611_PROJECT_DATA_PATH": path}), \
                 patch.object(data_loader, "_ISSUES", None):
                issues = data_loader.DataLoader()._load()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].number, 1)
        self.assertEqual(len(issues[0].events), 4)


if __name__ == "__main__":
    unittest.main()
