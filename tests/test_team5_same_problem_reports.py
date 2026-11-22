"""Team 5 tests for feature 1: same-problem reports after closure."""
import contextlib
from datetime import datetime
import io
import unittest
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")

import same_problem_reports as spr
from tests.helpers import event, issue, utc


class ClassifyCommentTests(unittest.TestCase):

    def test_firsthand_reports_are_detected(self):
        for text in ["Same here.", "I'm having the same issue.",
                     "We are also affected.", "Still broken in 1.8.3"]:
            with self.subTest(text=text):
                self.assertIsNotNone(spr.classify_comment(text))

    def test_denials_and_questions_are_not_reports(self):
        for text in ["I could not reproduce it on 1.8.",
                     "I haven't seen this issue.",
                     "Is anyone else having the same issue?",
                     "My colleague is having the same issue."]:
            with self.subTest(text=text):
                self.assertIsNone(spr.classify_comment(text))

    def test_quoted_and_code_text_is_ignored(self):
        self.assertIsNone(spr.classify_comment("> I'm having the same issue.\nThanks!"))
        self.assertIsNone(spr.classify_comment("```\nI'm having the same issue\n```"))

    def test_plus_one_style_report_is_detected(self):
        # DEFECT: a very common GitHub report style is missed.
        self.assertIsNotNone(spr.classify_comment("+1, same problem on macOS"))


class AnalyzeIssueTests(unittest.TestCase):

    def closed_issue(self, comments):
        events = [event("closed", utc(2024, 1, 2), "maint")]
        events += [event("commented", when, author, text) for when, author, text in comments]
        return issue(events, state="closed")

    def test_each_account_counted_once_after_closure(self):
        i = self.closed_issue([(utc(2024, 2, 1), "bob", "Same here."),
                               (utc(2024, 3, 1), "bob", "Same here."),
                               (utc(2024, 3, 2), "carol", "I'm having the same issue.")])
        result = spr.analyze_issue(i)
        self.assertEqual(sorted(r.author for r in result.postclosure_reports), ["bob", "carol"])
        self.assertEqual(result.postclosure_reports[0].after_closure_days, 30)

    def test_creator_bots_and_pre_closure_comments_are_excluded(self):
        i = issue([event("commented", utc(2024, 1, 1), "bob", "Same here."),
                   event("closed", utc(2024, 1, 2), "maint"),
                   event("commented", utc(2024, 2, 1), "reporter", "Same here."),
                   event("commented", utc(2024, 2, 1), "stale[bot]", "Same here.")],
                  state="closed")
        result = spr.analyze_issue(i)
        self.assertEqual(result.postclosure_reports, [])
        self.assertEqual([r.author for r in result.reports], ["bob"])

    def test_reopened_issue_has_no_closure(self):
        i = issue([event("closed", utc(2024, 1, 2), "maint"),
                   event("reopened", utc(2024, 1, 3), "maint")], state="closed")
        self.assertIsNone(spr.latest_closure(i))

    def test_mixed_naive_and_aware_dates_do_not_crash(self):
        # DEFECT: features 2 and 3 normalise timezones; feature 1 raises TypeError.
        i = self.closed_issue([(datetime(2024, 2, 1), "bob", "Same here.")])
        try:
            spr.analyze_issue(i)
        except TypeError as error:
            self.fail(f"analyze_issue crashed on mixed timezones: {error}")


class EqualTimeWindowsTests(unittest.TestCase):

    def test_empty_and_boundary_values(self):
        self.assertEqual(spr.equal_time_windows([]), (["0–179"], [0]))
        labels, counts = spr.equal_time_windows([0, 179, 180])
        self.assertEqual(counts, [2, 1])
        self.assertEqual(labels, ["0–179", "180–359"])


class RunTests(unittest.TestCase):

    def run_analysis(self, issues, label=None):
        out = io.StringIO()
        with patch.object(spr.DataLoader, "get_issues", return_value=issues), \
             patch.object(spr.config, "get_parameter", return_value=label), \
             patch.object(spr.plt, "show"), contextlib.redirect_stdout(out):
            spr.SameProblemReportsAnalysis().run()
        spr.plt.close("all")
        return out.getvalue()

    def test_flagged_issue_is_printed(self):
        i = issue([event("closed", utc(2024, 1, 2), "maint"),
                   event("commented", utc(2024, 2, 1), "bob", "Same here.")],
                  state="closed", number=42)
        text = self.run_analysis([i])
        self.assertIn("1 flagged", text)
        self.assertIn("#42", text)

    def test_label_filter_with_unlabeled_issue_does_not_crash(self):
        # DEFECT: features 2 and 3 use (issue.labels or []); feature 1 does not.
        i = issue([])
        i.labels = None
        try:
            text = self.run_analysis([i], label="kind/bug")
        except TypeError as error:
            self.fail(f"--label crashed on an issue with labels=None: {error}")
        self.assertIn("No issues found", text)


if __name__ == "__main__":
    unittest.main()
