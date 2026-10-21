"""Tests for the Same Problem Reports feature (stdlib unittest)."""

import contextlib
from datetime import datetime, timezone
import io
import unittest
from unittest.mock import patch

from model import Issue
from same_problem_reports import (
    SameProblemReportsAnalysis,
    analyze_issue,
    classify_comment,
    clean_comment,
    is_eligible_author,
    latest_closure,
)


def make_issue(events, state="closed", creator="reporter", labels=None):
    def event(typ, date, author="someone", comment=""):
        return dict(event_type=typ, event_date=date, author=author, comment=comment)

    return Issue(
        dict(
            number=99,
            title="Installing Poetry fails",
            url="https://github.com/python-poetry/poetry/issues/99",
            state=state,
            creator=creator,
            created_date="2023-01-01T00:00:00+00:00",
            labels=labels or ["kind/bug"],
            events=[event(*row) for row in events],
        )
    )


class CommentDetectionTests(unittest.TestCase):
    def test_clear_reports(self):
        for phrase in [
            "I have the same problem.",
            "I have this problem.",
            "I have this too.",
            "Same issue here.",
            "I am getting the same error.",
            "I am still having this issue.",
            "I can reproduce this issue.",
            "I can confirm this bug.",
            "This reproduces reliably on Ubuntu.",
            "I am seeing this too.",
            "We are facing a similar problem.",
            "We have also started hitting this problem recently.",
            "This still fails for me.",
            "Poetry still crashes for me.",
            "NovaTool still crashes for me.",
            "the application crashes on my machine.",
            "This happened to me last week.",
            "This is happening without Oh-My-Zsh.",
            "Just came across this myself, on Poetry 1.1.2.",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIsNotNone(classify_comment(phrase))

    def test_nonreports(self):
        for phrase in [
            "Can anyone reproduce this?",
            "Does anyone else have the same issue?",
            "If I had the same issue, what should I do?",
            "I cannot reproduce this issue.",
            "I do not have the same issue.",
            "I'm not seeing this issue on Windows.",
            "It is not actually the same thing.",
            "Same issue as #123, closing this one.",
            "If the issue persists please open a new issue.",
            "This solution does not work for me.",
            "I can confirm this is fixed in version 1.2.",
            "Any updates?",
            "I have this line in the config file.",
            "In config.yaml I have this line:",
            "I have it.",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIsNone(classify_comment(phrase))

    def test_historical_versus_current(self):
        fixed = classify_comment("I had the same issue, but upgrading fixed it.")
        self.assertIsNotNone(fixed)
        self.assertEqual(fixed.status, "historical")
        self.assertEqual(
            classify_comment("I have the same issue. Updating solved it.").status,
            "historical",
        )
        self.assertEqual(
            classify_comment("I was having the same issue before.").status, "historical"
        )
        current = classify_comment("I am still getting the same error on 1.7.")
        self.assertIsNotNone(current)
        self.assertEqual(current.status, "current")
        self.assertEqual(
            classify_comment("the application crashes on my machine.").status, "current"
        )

    def test_local_negation(self):
        evidence = classify_comment(
            "I cannot reproduce X, but I have the same issue with Y."
        )
        self.assertIsNotNone(evidence)
        self.assertIn("I have the same issue", evidence.excerpt)

    def test_quoted_text_and_code_ignored(self):
        self.assertIsNone(
            classify_comment("> I have the same issue\nI recommend upgrading.")
        )
        self.assertIsNone(classify_comment("```\nI have the same issue\n```\nTry pip."))
        self.assertIsNone(
            classify_comment("`I have the same issue` is what they wrote.")
        )
        self.assertIsNone(
            classify_comment(
                "On Thursday, October 11, 2024 John wrote:\nI have the same issue"
            )
        )

    def test_report_after_quote_is_preserved(self):
        self.assertIsNotNone(
            classify_comment(
                "> Original reporter had the same issue\nI have the same issue too."
            )
        )

    def test_empty_and_invalid_author(self):
        self.assertIsNone(classify_comment(""))
        self.assertFalse(is_eligible_author("", "reporter"))
        self.assertFalse(is_eligible_author("Reporter", "reporter"))
        self.assertFalse(is_eligible_author("dependabot[bot]", "reporter"))
        self.assertFalse(is_eligible_author("github-actions[bot]", "reporter"))
        self.assertTrue(is_eligible_author("anotherUser", "reporter"))


class TimelineTests(unittest.TestCase):
    CLOSED = "2023-02-01T12:00:00+00:00"
    LATER = "2023-05-01T12:00:00+00:00"

    def test_final_closure(self):
        issue = make_issue(
            [
                ("closed", self.CLOSED),
                ("commented", self.LATER, "alice", "I have the same problem."),
            ]
        )
        self.assertEqual(
            latest_closure(issue), datetime(2023, 2, 1, 12, tzinfo=timezone.utc)
        )
        result = analyze_issue(issue)
        self.assertEqual(len(result.postclosure_reports), 1)
        self.assertEqual(result.postclosure_reports[0].after_closure_days, 89)

    def test_repeat_comment_is_one_user(self):
        issue = make_issue(
            [
                ("closed", self.CLOSED),
                ("commented", self.LATER, "Alice", "Same issue here."),
                (
                    "commented",
                    "2023-06-01T00:00:00+00:00",
                    "alice",
                    "I can reproduce this.",
                ),
            ]
        )
        self.assertEqual(len(analyze_issue(issue).reports), 1)
        self.assertEqual(len(analyze_issue(issue).postclosure_reports), 1)

    def test_reporter_and_bots_excluded(self):
        issue = make_issue(
            [
                ("closed", self.CLOSED),
                ("commented", self.LATER, "reporter", "Same issue here."),
                ("commented", self.LATER, "renovate[bot]", "Same issue here."),
            ]
        )
        self.assertFalse(analyze_issue(issue).reports)

    def test_fixed_comment_not_ongoing(self):
        issue = make_issue(
            [
                ("closed", self.CLOSED),
                (
                    "commented",
                    self.LATER,
                    "alice",
                    "I had the same issue, but upgrading fixed it.",
                ),
            ]
        )
        result = analyze_issue(issue)
        self.assertEqual(len(result.reports), 1)
        self.assertEqual(len(result.postclosure_reports), 0)

    def test_unresolved_wording_only(self):
        issue = make_issue(
            [
                ("closed", self.CLOSED),
                ("commented", self.LATER, "alice", "I ran into this yesterday."),
            ]
        )
        self.assertEqual(len(analyze_issue(issue).postclosure_reports), 0)

    def test_open_issue_has_no_postclosure(self):
        issue = make_issue(
            [
                ("closed", self.CLOSED),
                ("reopened", "2023-03-01T00:00:00+00:00"),
                ("commented", self.LATER, "alice", "I have the same issue."),
            ],
            state="open",
        )
        self.assertIsNone(latest_closure(issue))
        self.assertFalse(analyze_issue(issue).postclosure_reports)

    def test_reclosed_uses_latest_date(self):
        issue = make_issue(
            [
                ("closed", self.CLOSED),
                (
                    "commented",
                    "2023-03-01T00:00:00+00:00",
                    "alice",
                    "I have the same issue.",
                ),
                ("reopened", "2023-04-01T00:00:00+00:00"),
                ("closed", "2023-06-01T00:00:00+00:00"),
                ("commented", "2023-06-15T00:00:00+00:00", "bob", "Same issue here."),
            ]
        )
        r = analyze_issue(issue)
        self.assertEqual(len(r.reports), 2)
        self.assertEqual(len(r.postclosure_reports), 1)
        self.assertEqual(r.postclosure_reports[0].author, "bob")

    def test_unsorted_events(self):
        issue = make_issue(
            [
                ("commented", self.LATER, "alice", "Same issue here."),
                ("closed", self.CLOSED),
            ]
        )
        self.assertEqual(len(analyze_issue(issue).postclosure_reports), 1)

    def test_missing_closure(self):
        issue = make_issue([("commented", self.LATER, "alice", "Same issue here.")])
        self.assertIsNone(latest_closure(issue))
        self.assertFalse(analyze_issue(issue).postclosure_reports)

    def test_missing_comment_date(self):
        issue = make_issue(
            [("closed", self.CLOSED), ("commented", None, "alice", "Same issue here.")]
        )
        self.assertFalse(analyze_issue(issue).reports)

    def test_nonreport_comment_is_not_counted(self):
        issue = make_issue(
            [
                ("closed", self.CLOSED),
                ("commented", self.LATER, "alice", "Please upload a traceback."),
            ]
        )
        self.assertEqual(len(analyze_issue(issue).reports), 0)

    def test_long_history_is_processed_normally(self):
        issue = make_issue(
            [("commented", self.LATER, "alice", "Same issue here.")]
            + [("commented", self.LATER, "bob", "Discussion only.")] * 35
            + [("closed", self.CLOSED)]
        )
        result = analyze_issue(issue)
        self.assertEqual(len(result.reports), 1)
        self.assertEqual(len(result.postclosure_reports), 1)


class IntegrationTests(unittest.TestCase):
    def test_selected_label_and_chart(self):
        issue = make_issue(
            [
                ("closed", TimelineTests.CLOSED),
                ("commented", TimelineTests.LATER, "alice", "Same issue here."),
            ]
        )
        with (
            patch("same_problem_reports.config.get_parameter", return_value="kind/bug"),
            patch("same_problem_reports.DataLoader") as loader,
            patch("same_problem_reports.plt.show") as show,
        ):
            loader.return_value.get_issues.return_value = [issue]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                SameProblemReportsAnalysis().run()
            self.assertIn("#99", output.getvalue())
            show.assert_called_once()

    def test_no_label_scans_everything(self):
        issue = make_issue([("closed", TimelineTests.CLOSED)])
        with (
            patch("same_problem_reports.config.get_parameter", return_value=None),
            patch("same_problem_reports.DataLoader") as loader,
            patch("same_problem_reports.plt.show") as show,
        ):
            loader.return_value.get_issues.return_value = [issue]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                SameProblemReportsAnalysis().run()
            self.assertIn("Analyzed 1 issues", output.getvalue())
            show.assert_called_once()

    def test_unknown_label(self):
        issue = make_issue([])
        with (
            patch("same_problem_reports.config.get_parameter", return_value="unknown"),
            patch("same_problem_reports.DataLoader") as loader,
            patch("same_problem_reports.plt.show") as show,
        ):
            loader.return_value.get_issues.return_value = [issue]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                SameProblemReportsAnalysis().run()
            self.assertIn("No issues found", output.getvalue())
            show.assert_not_called()


if __name__ == "__main__":
    unittest.main()
