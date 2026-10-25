"""Tests for Same Problem Reports: language detection, history, and charts.

Run with: python -m unittest discover -v
"""

import contextlib
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
from io import StringIO
import unittest
from unittest.mock import patch

import matplotlib.pyplot as plt

from model import Issue

CLOSED = "2024-01-01T00:00:00+00:00"
from same_problem_reports import (
    SameProblemReportsAnalysis, analyze_issue, classify_comment,
    clean_comment, equal_time_windows, is_eligible_author, latest_closure,
)


# ---------------------------------------------------------------------------
# Basic detection, event timelines, and command integration
# ---------------------------------------------------------------------------

def make_issue(events, state='closed', creator='reporter', labels=None):
    def event(typ, date, author='someone', comment=''):
        return dict(event_type=typ, event_date=date, author=author, comment=comment)
    return Issue(dict(number=99, title='Installing Poetry fails',
                      url='https://github.com/python-poetry/poetry/issues/99',
                      state=state, creator=creator,
                      created_date='2023-01-01T00:00:00+00:00',
                      labels=labels or ['kind/bug'],
                      events=[event(*row) for row in events]))


class CommentDetectionTests(unittest.TestCase):
    def test_clear_reports(self):
        for phrase in [
            'I have the same problem.',
            'I have this problem.',
            'I have this too.',
            'Same issue here.',
            'I am getting the same error.',
            'I am still having this issue.',
            'I can reproduce this issue.',
            'I can confirm this bug.',
            'This reproduces reliably on Ubuntu.',
            'I am seeing this too.',
            'We are facing a similar problem.',
            'We have also started hitting this problem recently.',
            'This still fails for me.',
            'Poetry still crashes for me.',
            'NovaTool still crashes for me.',
            'the application crashes on my machine.',
            'This happened to me last week.',
            'This is happening without Oh-My-Zsh.',
            'Just came across this myself, on Poetry 1.1.2.',
        ]:
            with self.subTest(phrase=phrase):
                self.assertIsNotNone(classify_comment(phrase))

    def test_nonreports(self):
        for phrase in [
            'Can anyone reproduce this?',
            'Does anyone else have the same issue?',
            'If I had the same issue, what should I do?',
            'I cannot reproduce this issue.',
            'I do not have the same issue.',
            "I'm not seeing this issue on Windows.",
            'It is not actually the same thing.',
            'Same issue as #123, closing this one.',
            'If the issue persists please open a new issue.',
            'This solution does not work for me.',
            'I can confirm this is fixed in version 1.2.',
            'Any updates?',
            'I have this line in the config file.',
            'In config.yaml I have this line:',
            'I have it.',
        ]:
            with self.subTest(phrase=phrase):
                self.assertIsNone(classify_comment(phrase))

    def test_historical_versus_current(self):
        fixed = classify_comment('I had the same issue, but upgrading fixed it.')
        self.assertIsNotNone(fixed)
        self.assertEqual(fixed.status, 'historical')
        self.assertEqual(classify_comment('I have the same issue. Updating solved it.').status, 'historical')
        self.assertEqual(classify_comment('I was having the same issue before.').status, 'historical')
        current = classify_comment('I am still getting the same error on 1.7.')
        self.assertIsNotNone(current)
        self.assertEqual(current.status, 'current')
        self.assertEqual(classify_comment('the application crashes on my machine.').status, 'current')

    def test_ongoing_and_resolved_order(self):
        # The final status matters more than an earlier reference to the past.
        self.assertEqual(classify_comment(
            "I had this issue last month, and I'm still getting it today.").status,
            'current')
        self.assertEqual(classify_comment(
            'I had the same problem before. It still happens today.').status,
            'current')
        self.assertEqual(classify_comment(
            'I have the same issue, but it is now resolved.').status,
            'historical')
        self.assertEqual(classify_comment(
            'I have the same issue. It is fixed now.').status,
            'historical')

    def test_solved_after_reporting_is_historical(self):
        # Examples based on real GitHub comments initially misclassified.
        self.assertEqual(classify_comment(
            'Same here, but solved with a config change.').status, 'historical')
        self.assertEqual(classify_comment(
            'I have the same issue. It does seem to work fine now.').status, 'historical')
        self.assertEqual(classify_comment(
            'I have the same issue. It does seem to be fixed in 1.2.').status, 'historical')

    def test_suggested_solution_is_not_a_success(self):
        # Someone asking a question has not confirmed that the problem was fixed.
        result = classify_comment(
            'I have the same issue. Could this be solved with an upgrade?')
        self.assertIsNotNone(result)
        self.assertEqual(result.status, 'current')

    def test_later_recurrence_overrides_earlier_fix(self):
        self.assertEqual(classify_comment(
            'I had the same issue. Solved with an update. But it still fails.').status,
            'current')

    def test_unrelated_error_is_not_corroboration(self):
        self.assertIsNone(classify_comment(
            "The application fails for me but isn't related to the original report."))

    def test_additional_realistic_phrasing(self):
        # These patterns must work with unfamiliar software names too.
        for comment in [
            "I'm having exactly the same problem.",
            "We've also encountered the same error.",
            "I ran into a similar issue yesterday.",
            "NovaTool crashes for me.",
            "Just ran into this issue today.",
            "I just ran into this problem yesterday.",
        ]:
            with self.subTest(comment=comment):
                self.assertIsNotNone(classify_comment(comment))

    def test_reference_is_not_necessarily_firsthand(self):
        self.assertIsNone(classify_comment('Same issue as @someone.'))
        self.assertIsNotNone(classify_comment('I have the same issue as @someone.'))

    def test_past_occurrence_is_not_ongoing(self):
        self.assertEqual(classify_comment('This happened to me last week.').status, 'historical')
        self.assertEqual(classify_comment(
            'I have the same issue, but it is now resolved.').status, 'historical')

    def test_local_negation(self):
        evidence = classify_comment('I cannot reproduce X, but I have the same issue with Y.')
        self.assertIsNotNone(evidence)
        self.assertIn('I have the same issue', evidence.excerpt)

    def test_quoted_text_and_code_ignored(self):
        self.assertIsNone(classify_comment('> I have the same issue\nI recommend upgrading.'))
        self.assertIsNone(classify_comment('```\nI have the same issue\n```\nTry pip.'))
        self.assertIsNone(classify_comment('`I have the same issue` is what they wrote.'))
        self.assertIsNone(classify_comment('On Thursday, October 11, 2024 John wrote:\nI have the same issue'))

    def test_report_after_quote_is_preserved(self):
        self.assertIsNotNone(classify_comment('> Original reporter had the same issue\nI have the same issue too.'))

    def test_empty_and_invalid_author(self):
        self.assertIsNone(classify_comment(''))
        self.assertFalse(is_eligible_author('', 'reporter'))
        self.assertFalse(is_eligible_author('Reporter', 'reporter'))
        self.assertFalse(is_eligible_author('dependabot[bot]', 'reporter'))
        self.assertFalse(is_eligible_author('github-actions[bot]', 'reporter'))
        self.assertTrue(is_eligible_author('anotherUser', 'reporter'))


class TimelineTests(unittest.TestCase):
    CLOSED = '2023-02-01T12:00:00+00:00'
    LATER = '2023-05-01T12:00:00+00:00'

    def test_final_closure(self):
        issue = make_issue([('closed', self.CLOSED),
                            ('commented', self.LATER, 'alice', 'I have the same problem.')])
        self.assertEqual(latest_closure(issue), datetime(2023, 2, 1, 12, tzinfo=timezone.utc))
        result = analyze_issue(issue)
        self.assertEqual(len(result.postclosure_reports), 1)
        self.assertEqual(result.postclosure_reports[0].after_closure_days, 89)

    def test_repeat_comment_is_one_user(self):
        issue = make_issue([('closed', self.CLOSED),
                            ('commented', self.LATER, 'Alice', 'Same issue here.'),
                            ('commented', '2023-06-01T00:00:00+00:00', 'alice', 'I can reproduce this.')])
        self.assertEqual(len(analyze_issue(issue).reports), 1)
        self.assertEqual(len(analyze_issue(issue).postclosure_reports), 1)

    def test_reporter_and_bots_excluded(self):
        issue = make_issue([('closed', self.CLOSED),
                            ('commented', self.LATER, 'reporter', 'Same issue here.'),
                            ('commented', self.LATER, 'renovate[bot]', 'Same issue here.')])
        self.assertFalse(analyze_issue(issue).reports)

    def test_fixed_experience_is_still_a_postclosure_report(self):
        issue = make_issue([('closed', self.CLOSED),
                            ('commented', self.LATER, 'alice', 'I had the same issue, but upgrading fixed it.')])
        result = analyze_issue(issue)
        self.assertEqual(len(result.reports), 1)
        self.assertEqual(len(result.postclosure_reports), 1)

    def test_unclear_firsthand_wording_is_still_evidence(self):
        issue = make_issue([('closed', self.CLOSED),
                            ('commented', self.LATER, 'alice', 'I ran into this yesterday.')])
        self.assertEqual(len(analyze_issue(issue).postclosure_reports), 1)

    def test_open_issue_has_no_postclosure(self):
        issue = make_issue([('closed', self.CLOSED),
                            ('reopened', '2023-03-01T00:00:00+00:00'),
                            ('commented', self.LATER, 'alice', 'I have the same issue.')], state='open')
        self.assertIsNone(latest_closure(issue))
        self.assertFalse(analyze_issue(issue).postclosure_reports)

    def test_reclosed_uses_latest_date(self):
        issue = make_issue([('closed', self.CLOSED),
                            ('commented', '2023-03-01T00:00:00+00:00', 'alice', 'I have the same issue.'),
                            ('reopened', '2023-04-01T00:00:00+00:00'),
                            ('closed', '2023-06-01T00:00:00+00:00'),
                            ('commented', '2023-06-15T00:00:00+00:00', 'bob', 'Same issue here.')])
        r = analyze_issue(issue)
        self.assertEqual(len(r.reports), 2)
        self.assertEqual(len(r.postclosure_reports), 1)
        self.assertEqual(r.postclosure_reports[0].author, 'bob')

    def test_unsorted_events(self):
        issue = make_issue([('commented', self.LATER, 'alice', 'Same issue here.'),
                            ('closed', self.CLOSED)])
        self.assertEqual(len(analyze_issue(issue).postclosure_reports), 1)

    def test_missing_closure(self):
        issue = make_issue([('commented', self.LATER, 'alice', 'Same issue here.')])
        self.assertIsNone(latest_closure(issue))
        self.assertFalse(analyze_issue(issue).postclosure_reports)

    def test_missing_comment_date(self):
        issue = make_issue([('closed', self.CLOSED),
                            ('commented', None, 'alice', 'Same issue here.')])
        self.assertFalse(analyze_issue(issue).reports)

    def test_nonreport_comment_is_not_counted(self):
        issue = make_issue([('closed', self.CLOSED),
                            ('commented', self.LATER, 'alice', 'Please upload a traceback.')])
        self.assertEqual(len(analyze_issue(issue).reports), 0)

    def test_long_history_is_processed_normally(self):
        issue = make_issue([('commented', self.LATER, 'alice', 'Same issue here.')] +
                           [('commented', self.LATER, 'bob', 'Discussion only.')] * 35 +
                           [('closed', self.CLOSED)])
        result = analyze_issue(issue)
        self.assertEqual(len(result.reports), 1)
        self.assertEqual(len(result.postclosure_reports), 1)


class IntegrationTests(unittest.TestCase):
    def test_selected_label_and_chart(self):
        issue = make_issue([('closed', TimelineTests.CLOSED),
                            ('commented', TimelineTests.LATER, 'alice', 'Same issue here.')])
        with patch('same_problem_reports.config.get_parameter', return_value='kind/bug'), \
             patch('same_problem_reports.DataLoader') as loader, \
             patch('same_problem_reports.plt.show') as show:
            loader.return_value.get_issues.return_value = [issue]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                SameProblemReportsAnalysis().run()
            self.assertIn('#99', output.getvalue())
            show.assert_called_once()

    def test_no_label_scans_everything(self):
        issue = make_issue([('closed', TimelineTests.CLOSED)])
        with patch('same_problem_reports.config.get_parameter', return_value=None), \
             patch('same_problem_reports.DataLoader') as loader, \
             patch('same_problem_reports.plt.show') as show:
            loader.return_value.get_issues.return_value = [issue]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                SameProblemReportsAnalysis().run()
            self.assertIn('Analyzed 1 issues', output.getvalue())
            show.assert_called_once()

    def test_unknown_label(self):
        issue = make_issue([])
        with patch('same_problem_reports.config.get_parameter', return_value='unknown'), \
             patch('same_problem_reports.DataLoader') as loader, \
             patch('same_problem_reports.plt.show') as show:
            loader.return_value.get_issues.return_value = [issue]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                SameProblemReportsAnalysis().run()
            self.assertIn('No issues found', output.getvalue())
            show.assert_not_called()


# ---------------------------------------------------------------------------
# Regression tests for known mistakes and output
# ---------------------------------------------------------------------------

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
        self.assertIn('1 with 2+ reporters', summary)
        self.assertIn('#42: Example issue', summary)
        self.assertIn('+7d', summary)
        self.assertIn('Example (alice):', summary)
        self.assertIn('Closed: 2024-01-05', summary)
        self.assertIn('alice: 2024-01-12 (+7d)', summary)
        self.assertIn('bob: 2024-01-15 (+10d)', summary)
        self.assertIn('https://example.org/issues/42', summary)
        self.assertNotIn('Days 0–179:', summary)

    def test_long_delays_are_easy_to_find_without_changing_main_ranking(self):
        # One issue has more reporters, but another issue has a much later
        # report. Both should be easily discoverable in the console output.
        frequent = fake_issue([
            ('closed', '2024-01-05T00:00:00+00:00', 'maintainer', ''),
            ('commented', '2024-01-10T00:00:00+00:00', 'alice', 'Same issue here.'),
            ('commented', '2024-01-11T00:00:00+00:00', 'bob', 'I have the same issue.'),
        ])
        unusual = fake_issue([
            ('closed', '2024-01-05T00:00:00+00:00', 'maintainer', ''),
            ('commented', '2025-10-05T00:00:00+00:00', 'charlie', 'Same problem here.'),
        ])
        unusual.number = 43
        unusual.title = 'Very old issue with another report'
        unusual.url = 'https://github.com/python-poetry/poetry/issues/43'
        with patch('same_problem_reports.config.get_parameter', return_value='kind/bug'), \
             patch('same_problem_reports.DataLoader') as loader, \
             patch('same_problem_reports.plt.show'):
            loader.return_value.get_issues.return_value = [frequent, unusual]
            capture = StringIO()
            with redirect_stdout(capture):
                SameProblemReportsAnalysis().run()
        output = capture.getvalue()
        priority_section = output.split('Most independently reported')[1].split('Longest-delayed reports')[0]
        self.assertIn('#42:', priority_section)
        self.assertNotIn('#43:', priority_section)
        delayed_section = output.split('Longest-delayed reports')[1].split('Note:')[0]
        self.assertIn('#43: Very old issue with another report', delayed_section)
        self.assertIn('https://github.com/python-poetry/poetry/issues/43', delayed_section)
        self.assertIn('charlie', delayed_section)
        self.assertLess(delayed_section.index('#43:'), delayed_section.index('#42:'))

    def test_accounts_dates_and_delayed_evidence_without_duplicates(self):
        issue = fake_issue([
            ('closed', '2024-01-05T00:00:00+00:00', 'maintainer', ''),
            ('commented', '2024-01-12T00:00:00+00:00', 'alice', 'Same issue here.'),
            ('commented', '2024-01-13T00:00:00+00:00', 'Alice', 'I have the same issue.'),
            ('commented', '2024-01-20T00:00:00+00:00', 'bob', 'Same problem here.'),
        ])
        with patch('same_problem_reports.config.get_parameter', return_value=None), \
             patch('same_problem_reports.DataLoader') as loader, \
             patch('same_problem_reports.plt.show'):
            loader.return_value.get_issues.return_value = [issue]
            capture = StringIO()
            with redirect_stdout(capture):
                SameProblemReportsAnalysis().run()
        output = capture.getvalue()
        main = output.split('Most independently reported')[1].split('Longest-delayed reports')[0]
        self.assertIn('(2 accounts)', main)
        self.assertIn('Closed: 2024-01-05', main)
        self.assertIn('alice: 2024-01-12 (+7d)', main)
        self.assertIn('bob: 2024-01-20 (+15d)', main)
        self.assertNotIn('Alice: 2024-01-13', main)
        delayed = output.split('Longest-delayed reports')[1].split('Note:')[0]
        self.assertIn('Closed: 2024-01-05 | bob: 2024-01-20 (+15d)', delayed)

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
        self.assertIn('0 with 2+ reporters', summary)
        self.assertIn('None found.', summary)
        self.assertNotIn('#42:', summary)


# ---------------------------------------------------------------------------
# Inclusive post-closure reports and equal 180-day chart windows
# ---------------------------------------------------------------------------

def issue_with_comments(*comments):
    """Comment rows: (date, username, text)."""
    return fake_issue([('closed', CLOSED, 'maintainer', '')] +
                      [('commented', date, user, text)
                       for date, user, text in comments])


class InclusiveReportTests(unittest.TestCase):
    def test_later_success_does_not_erase_earlier_report(self):
        issue = issue_with_comments(
            ('2024-01-05T00:00:00+00:00', 'alice', 'I have the same issue.'),
            ('2024-01-06T00:00:00+00:00', 'alice', 'Updating fixed it for me.'),
        )
        result = analyze_issue(issue)
        self.assertEqual(len(result.postclosure_reports), 1)
        self.assertEqual(result.postclosure_reports[0].after_closure_days, 4)

    def test_fix_followup_does_not_erase_other_users(self):
        issue = issue_with_comments(
            ('2024-01-05T00:00:00+00:00', 'alice', 'Same issue here.'),
            ('2024-01-06T00:00:00+00:00', 'bob', 'I have the same problem.'),
            ('2024-01-07T00:00:00+00:00', 'alice', 'I managed to fix it.'),
        )
        self.assertEqual(len(analyze_issue(issue).postclosure_reports), 2)

    def test_historical_report_posted_after_closure_still_counts(self):
        issue = issue_with_comments(
            ('2024-02-01T00:00:00+00:00', 'alice',
             'I had the same issue, but upgrading fixed it.'),
        )
        found = analyze_issue(issue).postclosure_reports
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].evidence.status, 'historical')

    def test_one_account_even_after_multiple_reports_and_fix(self):
        issue = issue_with_comments(
            ('2024-01-05T00:00:00+00:00', 'Alice', 'I have the same problem.'),
            ('2024-01-06T00:00:00+00:00', 'alice', 'That fixed it.'),
            ('2024-01-10T00:00:00+00:00', 'ALICE', 'Same issue here again.'),
        )
        found = analyze_issue(issue).postclosure_reports
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].after_closure_days, 4)

    def test_questions_and_copied_quotes_not_counted(self):
        issue = issue_with_comments(
            ('2024-01-05T00:00:00+00:00', 'alice', 'Any updates?'),
            ('2024-01-06T00:00:00+00:00', 'bob',
             '> I have the same issue.\nPlease post logs.'),
            ('2024-01-07T00:00:00+00:00', 'charlie', 'I cannot reproduce this.'),
        )
        self.assertEqual(len(analyze_issue(issue).postclosure_reports), 0)

    def test_report_before_last_closure_not_counted(self):
        issue = fake_issue([
            ('closed', '2024-01-01T00:00:00+00:00', 'maintainer', ''),
            ('commented', '2024-01-05T00:00:00+00:00', 'alice', 'Same issue here.'),
            ('reopened', '2024-01-10T00:00:00+00:00', 'maintainer', ''),
            ('closed', '2024-02-01T00:00:00+00:00', 'maintainer', ''),
        ])
        self.assertEqual(len(analyze_issue(issue).reports), 1)
        self.assertEqual(len(analyze_issue(issue).postclosure_reports), 0)


class EqualWindowTests(unittest.TestCase):
    def test_equal_180_day_boundaries(self):
        labels, counts = equal_time_windows([0, 179, 180, 359, 360, 539, 540])
        self.assertEqual(labels,
                         ['0–179', '180–359', '360–539', '540–719'])
        self.assertEqual(counts, [2, 2, 2, 1])

    def test_empty_has_one_zero_bar(self):
        self.assertEqual(equal_time_windows([]), (['0–179'], [0]))

    def test_chart_has_both_panels_and_equal_time_buckets(self):
        first = issue_with_comments(
            ('2024-01-02T00:00:00+00:00', 'alice', 'Same issue here.'),
            ('2024-07-01T00:00:00+00:00', 'bob', 'Same issue here.'),
        )
        second = issue_with_comments(
            ('2024-01-02T00:00:00+00:00', 'charlie', 'Same problem here.'),
        )
        second.number = 43
        with patch('same_problem_reports.config.get_parameter', return_value='kind/bug'), \
             patch('same_problem_reports.DataLoader') as loader, \
             patch('same_problem_reports.plt.show'):
            loader.return_value.get_issues.return_value = [first, second]
            with redirect_stdout(StringIO()):
                SameProblemReportsAnalysis().run()
        fig = plt.gcf()
        try:
            self.assertEqual(len(fig.axes), 2)
            self.assertEqual([int(b.get_height()) for b in fig.axes[0].patches],
                             [1, 1, 0])
            self.assertEqual([int(b.get_height()) for b in fig.axes[1].patches],
                             [2, 1])
        finally:
            plt.close(fig)


if __name__ == "__main__":
    unittest.main()
