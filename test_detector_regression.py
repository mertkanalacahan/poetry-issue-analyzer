"""Small black-box regression suite for Feature 1."""
from datetime import datetime, timezone
from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from model import Issue
from same_problem_reports import (SameProblemReportsAnalysis, classify_comment,
                                  analyze_issue, latest_closure)


def fake_issue(events, state='closed'):
    return Issue({
        'number': 42, 'title': 'Example issue', 'url': 'https://example.org/issues/42',
        'creator': 'creator', 'labels': ['kind/bug'], 'state': state,
        'created_date': '2024-01-01T00:00:00+00:00',
        'events': [dict(event_type=kind, event_date=when, author=who, comment=comment)
                   for kind, when, who, comment in events],
    })


class DetectorRegressionTests(unittest.TestCase):
    def test_clear_ongoing_reports(self):
        for sentence in [
            'I am having the exact same issue.',
            "I'm still running into this issue.",
            'This issue still exists in version 4.3.',
            'I have the same when I use the CLI.',
            'I am getting the same error.',
            'NovaTool crashes for me.',
            'Same issue here.',
        ]:
            with self.subTest(sentence=sentence):
                evidence = classify_comment(sentence)
                self.assertIsNotNone(evidence)
                self.assertEqual(evidence.status, 'current')

    def test_resolved_reports_are_historical(self):
        for sentence in [
            'I had the same issue, but upgrading fixed it.',
            'I have the same issue, but it is now resolved.',
            'I saw the same issue. It is fixed now.',
            'I was getting this same error before.',
        ]:
            with self.subTest(sentence=sentence):
                result = classify_comment(sentence)
                self.assertIsNotNone(result)
                self.assertEqual(result.status, 'historical')

    def test_nonreports(self):
        for sentence in [
            'Does anyone else have this issue?',
            'If I had the same issue, what would happen?',
            'I cannot reproduce this problem.',
            'Same issue as #123, closing as duplicate.',
            'I have this line in the config file.',
            'I see the issue now.',
            'Feel free to reopen if the issue still occurs.',
            'You could try creating a fresh environment to see whether the problem persists.',
            '> I have the same issue.\nThis is a quoted report.',
        ]:
            with self.subTest(sentence=sentence):
                self.assertIsNone(classify_comment(sentence))

    def test_deduplicated_accounts(self):
        issue = fake_issue([
            ('closed','2024-01-05T00:00:00+00:00','maintainer',''),
            ('commented','2024-01-09T00:00:00+00:00','alice','I have the same issue.'),
            ('commented','2024-01-10T00:00:00+00:00','Alice','Same issue here.'),
            ('commented','2024-01-11T00:00:00+00:00','creator','Same issue here.'),
            ('commented','2024-01-12T00:00:00+00:00','github-actions[bot]','Same issue here.'),
        ])
        found = analyze_issue(issue)
        self.assertEqual(len(found.reports), 1)
        self.assertEqual(len(found.postclosure_reports), 1)
        self.assertEqual(found.postclosure_reports[0].after_closure_days, 4)

    def test_reopen_then_close_again(self):
        issue = fake_issue([
            ('commented','2024-01-06T00:00:00+00:00','bob','I have the same issue.'),
            ('closed','2024-01-05T00:00:00+00:00','maintainer',''),
            ('reopened','2024-01-08T00:00:00+00:00','maintainer',''),
            ('closed','2024-01-15T00:00:00+00:00','maintainer',''),
            ('commented','2024-01-16T00:00:00+00:00','alice','I have the same issue.'),
        ])
        result = analyze_issue(issue)
        self.assertEqual(len(result.reports), 2)
        self.assertEqual(len(result.postclosure_reports), 1)
        self.assertEqual(result.postclosure_reports[0].author, 'alice')

    def test_open_issue_has_no_final_closure(self):
        issue = fake_issue([
            ('closed','2024-01-05T00:00:00+00:00','maintainer',''),
            ('reopened','2024-01-08T00:00:00+00:00','maintainer',''),
            ('commented','2024-01-09T00:00:00+00:00','bob','I have the same issue.'),
        ], state='open')
        self.assertIsNone(latest_closure(issue))
        self.assertEqual(len(analyze_issue(issue).postclosure_reports), 0)


class SummaryOutputTests(unittest.TestCase):
    def test_multiple_postclosure_reporters_appear_first(self):
        # The user's actionable finding is the shortlist, not a plain issue count.
        repeated_issue = fake_issue([
            ('closed', '2024-01-05T00:00:00+00:00', 'maintainer', ''),
            ('commented', '2024-01-12T00:00:00+00:00', 'alice', 'I have the same issue.'),
            ('commented', '2024-01-15T00:00:00+00:00', 'bob', 'Same issue here.'),
        ])
        with patch('same_problem_reports.config.get_parameter', return_value='kind/bug'), \
             patch('same_problem_reports.DataLoader') as loader, \
             patch('same_problem_reports.plt.show'):
            loader.return_value.get_issues.return_value = [repeated_issue]
            capture = StringIO()
            with redirect_stdout(capture):
                SameProblemReportsAnalysis().run()
        summary = capture.getvalue()
        self.assertIn('1 issues have 2+ post-closure reporters', summary)
        self.assertIn('#42: Example issue', summary)
        self.assertIn('7 days after closure', summary)
        self.assertIn('0-30 days: 2', summary)

    def test_zero_reports_do_not_crash(self):
        issue = fake_issue([('closed', '2024-01-05T00:00:00+00:00', 'maintainer', '')])
        with patch('same_problem_reports.config.get_parameter', return_value=None), \
             patch('same_problem_reports.DataLoader') as loader, \
             patch('same_problem_reports.plt.show'):
            loader.return_value.get_issues.return_value = [issue]
            capture = StringIO()
            with redirect_stdout(capture):
                SameProblemReportsAnalysis().run()
        summary = capture.getvalue()
        self.assertIn('0 issues have 2+ post-closure reporters', summary)
        self.assertIn('0-30 days: 0', summary)
        self.assertNotIn('#42:', summary)


if __name__ == '__main__':
    unittest.main()
