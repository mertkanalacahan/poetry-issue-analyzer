"""Team 5 tests for feature 2: developer response time."""
import contextlib
import io
import unittest
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")

import developer_response_time as drt
from tests.helpers import event, issue, utc

SNAPSHOT = utc(2024, 12, 31)


class FindDevelopersTests(unittest.TestCase):

    def test_actions_on_other_peoples_issues_make_a_developer(self):
        issues = [issue([event("labeled", utc(2024, 1, 2), "Maint")])]
        self.assertEqual(drt.find_developers(issues), {"maint"})

    def test_actions_on_own_issue_and_bot_actions_are_ignored(self):
        issues = [issue([event("closed", utc(2024, 1, 2), "reporter"),
                         event("labeled", utc(2024, 1, 2), "github-actions[bot]")])]
        self.assertEqual(drt.find_developers(issues), set())


class AnalyzeIssueTests(unittest.TestCase):

    def test_first_developer_comment_gives_the_wait(self):
        i = issue([event("commented", utc(2024, 1, 3), "maint"),
                   event("commented", utc(2024, 1, 10), "maint")])
        record = drt.analyze_issue(i, {"maint"}, SNAPSHOT)
        self.assertEqual(record.status, drt.ANSWERED)
        self.assertAlmostEqual(record.days, 2.0)
        self.assertEqual(record.responder, "maint")

    def test_comment_from_non_developer_does_not_count(self):
        i = issue([event("commented", utc(2024, 1, 3), "random-user")])
        record = drt.analyze_issue(i, {"maint"}, SNAPSHOT)
        self.assertEqual(record.status, drt.NEVER_ANSWERED)

    def test_issue_without_creation_date_is_skipped(self):
        i = issue([])
        i.created_date = None
        self.assertIsNone(drt.analyze_issue(i, {"maint"}, SNAPSHOT))

    def test_reply_after_issue_was_closed_is_not_a_first_response(self):
        # DEFECT: issue closed by its author after 1 day; a developer comment
        # posted a year later is reported as a 366-day "first reply".
        i = issue([event("closed", utc(2024, 1, 2), "reporter"),
                   event("commented", utc(2025, 1, 1), "maint")],
                  state="closed")
        record = drt.analyze_issue(i, {"maint"}, SNAPSHOT)
        self.assertNotEqual(
            record.status, drt.ANSWERED,
            f"a reply posted after closure was counted as a {record.days:.0f}-day first response")


class HelperTests(unittest.TestCase):

    def test_bucket_boundaries(self):
        # 1 day is NOT "< 1 day"; 7 days starts "1-4 weeks".
        self.assertEqual(drt.bucket_counts([0.5, 1, 6.9, 7, 400]),
                         [1, 2, 1, 0, 0, 1])

    def test_label_breakdown_splits_fast_slow_never(self):
        rows = [drt.ResponseRecord(issue([], labels=["a"]), drt.ANSWERED, 2, "m"),
                drt.ResponseRecord(issue([], labels=["a"]), drt.ANSWERED, 30, "m"),
                drt.ResponseRecord(issue([], labels=["a"]), drt.NEVER_ANSWERED, 90, None)]
        self.assertEqual(drt.label_breakdown(rows), [("a", [1, 1, 1])])

    def test_format_days_uses_hours_below_one_day(self):
        self.assertEqual(drt.format_days(0.5), "12.0 hours")
        self.assertEqual(drt.format_days(3), "3.0 days")


class RunTests(unittest.TestCase):

    def run_analysis(self, issues, label=None):
        out = io.StringIO()
        with patch.object(drt.DataLoader, "get_issues", return_value=issues), \
             patch.object(drt.config, "get_parameter", return_value=label), \
             patch.object(drt.plt, "show"), contextlib.redirect_stdout(out):
            drt.DeveloperResponseAnalysis().run()
        drt.plt.close("all")
        return out.getvalue()

    def test_unknown_label_prints_message(self):
        text = self.run_analysis([issue([])], label="no-such-label")
        self.assertIn("No issues found for label 'no-such-label'", text)

    def test_summary_counts_answered_and_unanswered(self):
        issues = [issue([event("labeled", utc(2024, 1, 2), "maint"),
                         event("commented", utc(2024, 1, 2), "maint")], number=1),
                  issue([], number=2)]
        text = self.run_analysis(issues)
        self.assertIn("Analyzed 2 issues | 1 answered | 1 never answered", text)


if __name__ == "__main__":
    unittest.main()
