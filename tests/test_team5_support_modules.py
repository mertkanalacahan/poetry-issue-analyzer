"""Team 5 tests for the support modules: config.py, data_loader.py and model.py."""
import argparse
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import config
import data_loader
from model import Event, Issue, State


class ConfigFileLookupTests(unittest.TestCase):

    def test_finds_config_json_in_a_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "config.json"), "w") as f:
                json.dump({"team5_key": "value"}, f)
            child = os.path.join(tmp, "a", "b")
            os.makedirs(child)
            with patch("os.getcwd", return_value=child):
                path = config._get_default_path()
        self.assertEqual(path, os.path.abspath(os.path.join(tmp, "config.json")))

    def test_returns_none_when_no_config_file_exists(self):
        with patch("os.path.isfile", return_value=False):
            self.assertIsNone(config._get_default_path())

    def test_missing_config_file_gives_empty_config(self):
        with patch.object(config, "_config", None), \
             patch.object(config, "_get_default_path", return_value=None):
            config._init_config()
            self.assertEqual(config._config, {})

    def test_config_file_values_are_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open(path, "w") as f:
                json.dump({"team5_from_file": 7}, f)
            with patch.object(config, "_config", None), \
                 patch.object(config, "_get_default_path", return_value=path):
                self.assertEqual(config.get_parameter("team5_from_file"), 7)


class ConfigParameterTests(unittest.TestCase):

    def test_unknown_parameter_without_default_is_none(self):
        with patch.object(config, "_config", {}):
            self.assertIsNone(config.get_parameter("team5_not_set_anywhere"))

    def test_environment_variable_takes_precedence_over_file(self):
        with patch.object(config, "_config", {"team5_pref": "file"}), \
             patch.dict(os.environ, {"team5_pref": "env"}):
            self.assertEqual(config.get_parameter("team5_pref"), "env")

    def test_non_string_values_are_returned_unchanged(self):
        self.assertEqual(config.convert_to_typed_value(5), 5)
        self.assertEqual(config.convert_to_typed_value([1, 2]), [1, 2])

    def test_command_line_args_are_copied_into_config(self):
        args = argparse.Namespace(team5_feature=2, team5_label="kind/bug", team5_none=None)
        with patch.object(config, "_config", {}), patch.dict(os.environ, {}):
            config.overwrite_from_args(args)
            self.assertEqual(config.get_parameter("team5_feature"), 2)
            self.assertEqual(config.get_parameter("team5_label"), "kind/bug")
            self.assertNotIn("team5_none", os.environ)


class DataLoaderCachingTests(unittest.TestCase):

    def test_get_issues_loads_once_and_reuses_the_result(self):
        sample = [{"state": "open", "number": 3, "events": []}]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "data.json")
            with open(path, "w") as f:
                json.dump(sample, f)
            with patch.dict(os.environ, {"ENPM611_PROJECT_DATA_PATH": path}), \
                 patch.object(data_loader, "_ISSUES", None):
                loader = data_loader.DataLoader()
                out = io.StringIO()
                with redirect_stdout(out):
                    first = loader.get_issues()
                with patch.object(loader, "_load") as reload:
                    second = loader.get_issues()
                    reload.assert_not_called()
        self.assertIs(first, second)
        self.assertEqual(first[0].number, 3)
        self.assertIn("Loaded 1 issues", out.getvalue())


class ModelParsingTests(unittest.TestCase):

    def test_event_with_bad_date_keeps_other_fields(self):
        e = Event({"event_type": "commented", "author": "a",
                   "event_date": "not a date", "comment": "hi"})
        self.assertIsNone(e.event_date)
        self.assertEqual(e.comment, "hi")

    def test_issue_with_bad_number_and_dates_uses_defaults(self):
        i = Issue({"state": "closed", "number": "abc",
                   "created_date": None, "updated_date": "garbage"})
        self.assertEqual(i.state, State.closed)
        self.assertEqual(i.number, -1)
        self.assertIsNone(i.created_date)
        self.assertIsNone(i.updated_date)


if __name__ == "__main__":
    unittest.main()