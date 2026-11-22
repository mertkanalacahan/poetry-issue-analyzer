"""Team 5 tests for feature 3: stale open issues."""
import contextlib
import io
import unittest
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")

import stale_issues_analysis as sia
from tests.helpers import event, issue, utc

SNAPSHOT = utc(2024, 12, 31)


class AnalyzeIssueTests(unittest.TestCase):

    def test_no_reply_from_others_is_never_answered(self):
        i = issue([event("commented", utc(2024, 1, 2), "reporter")])
        record = sia.analyze_issue(i, SNAPSHOT, 90)
        self.assertEqual(record.cohort, sia.NEVER_ANSWERED)
        self.assertTrue(record.is_monologue)

    def test_reply_then_silence_is_went_quiet(self):
        i = issue([event("commented", utc(2024, 1, 2), "helper")])
        self.assertEqual(sia.analyze_issue(i, SNAPSHOT, 90).cohort, sia.WENT_QUIET)

    def test_recent_activity_is_active(self):
        i = issue([event("commented", utc(2024, 12, 1), "helper")])
        self.assertEqual(sia.analyze_issue(i, SNAPSHOT, 90).cohort, sia.ACTIVE)

    def test_threshold_boundary(self):
        # Exactly `days` of silence counts as stale; one day less does not.
        i = issue([], created=utc(2024, 10, 2))   # 90 days before the snapshot
        self.assertEqual(sia.analyze_issue(i, SNAPSHOT, 90).cohort, sia.NEVER_ANSWERED)
        self.assertEqual(sia.analyze_issue(i, SNAPSHOT, 91).cohort, sia.ACTIVE)

    def test_labeling_only_moves_clock_in_any_mode(self):
        i = issue([event("labeled", utc(2024, 12, 20), "maint")])
        self.assertEqual(sia.analyze_issue(i, SNAPSHOT, 90, sia.STRICT).cohort, sia.NEVER_ANSWERED)
        self.assertEqual(sia.analyze_issue(i, SNAPSHOT, 90, sia.ANY).cohort, sia.ACTIVE)

    def test_bot_events_do_not_reset_silence(self):
        i = issue([event("commented", utc(2024, 12, 20), "stale[bot]")])
        self.assertEqual(sia.analyze_issue(i, SNAPSHOT, 90, sia.ANY).cohort, sia.NEVER_ANSWERED)


class InputValidationTests(unittest.TestCase):

    def test_days_validation(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sia.validated_days("30"), 30)
            self.assertIsNone(sia.validated_days(0))
            self.assertIsNone(sia.validated_days("abc"))

    def test_activity_validation(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sia.validated_activity(None), sia.STRICT)
            self.assertEqual(sia.validated_activity(" ANY "), sia.ANY)
            self.assertIsNone(sia.validated_activity("sometimes"))

    def test_mode_named_in_readme_is_accepted(self):
        # DEFECT: README calls the default clock "substantive", but only
        # "strict" is accepted, so the documented name is rejected.
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNotNone(sia.validated_activity("substantive"))


class HelperTests(unittest.TestCase):

    def test_never_answered_share(self):
        counts = {sia.NEVER_ANSWERED: 1, sia.WENT_QUIET: 1, sia.ACTIVE: 2}
        self.assertEqual(sia.never_answered_share(counts), 25.0)
        self.assertEqual(sia.never_answered_share(dict.fromkeys(sia.COHORTS, 0)), 0.0)

    def test_unlabeled_issues_are_grouped(self):
        record = sia.analyze_issue(issue([], labels=[]), SNAPSHOT, 90)
        self.assertEqual(sia.label_breakdown([record])[0][0], sia.UNLABELED)


class RunTests(unittest.TestCase):

    def run_analysis(self, issues, **params):
        out = io.StringIO()
        lookup = lambda name, default=None: params.get(name, default)
        with patch.object(sia.DataLoader, "get_issues", return_value=issues), \
             patch.object(sia.config, "get_parameter", side_effect=lookup), \
             patch.object(sia.plt, "show"), contextlib.redirect_stdout(out):
            sia.StaleIssuesAnalysis().run()
        sia.plt.close("all")
        return out.getvalue()

    def test_report_counts_stale_issues(self):
        issues = [issue([], number=1),
                  issue([event("commented", utc(2024, 12, 30), "helper")], number=2)]
        text = self.run_analysis(issues)
        self.assertIn("STALE OPEN ISSUES | silent 90+ days", text)

    def test_closed_issues_only_prints_message(self):
        text = self.run_analysis([issue([], state="closed")])
        self.assertIn("No open issues found", text)


if __name__ == "__main__":
    unittest.main()
