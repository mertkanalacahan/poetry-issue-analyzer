"""Tests for Stale Issues: cohorts, the snapshot clock, input handling, charts.

Run with: python -m unittest discover -v
"""

import contextlib
from datetime import datetime, timedelta, timezone
import io
import unittest
from unittest.mock import patch

from model import Issue
from stale_issues_analysis import (
    ACTIVE, NEVER_ANSWERED, WENT_QUIET, StaleIssuesAnalysis, analyze_issue,
    as_utc, equal_day_windows, is_bot, label_breakdown, never_answered_share,
    snapshot_date, validated_days,
)

ASOF = datetime(2024, 1, 1, tzinfo=timezone.utc)
OPENED = '2023-01-01T00:00:00+00:00'


def make_issue(events, state='open', creator='reporter', labels=None, number=99,
               created=OPENED):
    def event(typ, date, author='someone', comment=''):
        return dict(event_type=typ, event_date=date, author=author, comment=comment)
    return Issue(dict(number=number, title='Installing Poetry fails',
                      url='https://github.com/python-poetry/poetry/issues/99',
                      state=state, creator=creator, created_date=created,
                      updated_date=created,
                      labels=['kind/bug'] if labels is None else labels,
                      events=[event(*row) for row in events]))


def days_before(count):
    return (ASOF - timedelta(days=count)).isoformat()


def anchor():
    """Pin the snapshot to ASOF.

    The snapshot is the latest timestamp in the dataset, so a lone issue is
    always its own snapshot and can never be stale. Real data has thousands of
    issues; this closed one plays that role without joining the open-issue counts.
    """
    return make_issue([('commented', days_before(0), 'helper')],
                      state='closed', number=1000)


def params(days=90, label=None):
    """Stand in for config.get_parameter, which this analysis calls twice."""
    def fake(name, default=None):
        return {'days': days, 'label': label}.get(name, default)
    return fake


def run_analysis(issues, days=90, label=None):
    with patch('stale_issues_analysis.config.get_parameter',
               side_effect=params(days, label)), \
         patch('stale_issues_analysis.DataLoader') as loader, \
         patch('stale_issues_analysis.plt.show') as show:
        loader.return_value.get_issues.return_value = issues
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            StaleIssuesAnalysis().run()
        return output.getvalue(), show


# ---------------------------------------------------------------------------
# Cohort classification
# ---------------------------------------------------------------------------

class CohortTests(unittest.TestCase):
    def test_no_reply_ever_is_never_answered(self):
        record = analyze_issue(make_issue([]), ASOF, 90)
        self.assertEqual(record.cohort, NEVER_ANSWERED)
        self.assertEqual(record.silent_days, 365)
        self.assertEqual(record.responders, 0)
        self.assertFalse(record.is_monologue)

    def test_discussion_then_silence_is_went_quiet(self):
        record = analyze_issue(
            make_issue([('commented', days_before(200), 'helper', 'Try this.')]),
            ASOF, 90)
        self.assertEqual(record.cohort, WENT_QUIET)
        self.assertEqual(record.responders, 1)
        self.assertEqual(record.silent_days, 200)

    def test_recent_activity_is_active(self):
        record = analyze_issue(
            make_issue([('commented', days_before(10), 'helper', 'Looking.')]),
            ASOF, 90)
        self.assertEqual(record.cohort, ACTIVE)

    def test_author_talking_to_themselves_is_a_monologue(self):
        record = analyze_issue(
            make_issue([('commented', days_before(300), 'reporter', 'Any update?'),
                        ('commented', days_before(250), 'reporter', 'Still broken.')]),
            ASOF, 90)
        self.assertEqual(record.cohort, NEVER_ANSWERED)
        self.assertEqual(record.creator_comments, 2)
        self.assertEqual(record.responders, 0)
        self.assertTrue(record.is_monologue)
        # The clock still follows the author's last comment.
        self.assertEqual(record.silent_days, 250)

    def test_author_name_matched_case_insensitively(self):
        record = analyze_issue(
            make_issue([('commented', days_before(200), 'REPORTER', 'Ping.')],
                       creator='reporter'),
            ASOF, 90)
        self.assertEqual(record.responders, 0)
        self.assertEqual(record.cohort, NEVER_ANSWERED)

    def test_repeat_responder_counted_once(self):
        record = analyze_issue(
            make_issue([('commented', days_before(300), 'helper', 'One.'),
                        ('commented', days_before(200), 'helper', 'Two.')]),
            ASOF, 90)
        self.assertEqual(record.responders, 1)

    def test_non_comment_events_count_as_activity_but_not_as_answers(self):
        record = analyze_issue(
            make_issue([('labeled', days_before(5), 'maintainer')]), ASOF, 90)
        self.assertEqual(record.cohort, ACTIVE)
        self.assertEqual(record.responders, 0)

    def test_unsorted_events_use_the_latest(self):
        record = analyze_issue(
            make_issue([('commented', days_before(10), 'helper', 'Recent.'),
                        ('commented', days_before(300), 'helper', 'Old.')]),
            ASOF, 90)
        self.assertEqual(record.silent_days, 10)

    def test_missing_event_date_is_skipped(self):
        record = analyze_issue(
            make_issue([('commented', None, 'helper', 'No date.')]), ASOF, 90)
        self.assertEqual(record.silent_days, 365)
        self.assertEqual(record.responders, 1)

    def test_blank_author_is_ignored(self):
        record = analyze_issue(
            make_issue([('commented', days_before(200), '', 'Ghost.')]), ASOF, 90)
        self.assertEqual(record.responders, 0)
        self.assertEqual(record.cohort, NEVER_ANSWERED)

    def test_issue_without_any_date_is_dropped(self):
        self.assertIsNone(analyze_issue(make_issue([], created=None), ASOF, 90))


class BoundaryTests(unittest.TestCase):
    def test_exactly_n_days_is_stale(self):
        record = analyze_issue(make_issue([], created=days_before(90)), ASOF, 90)
        self.assertEqual(record.silent_days, 90)
        self.assertEqual(record.cohort, NEVER_ANSWERED)

    def test_one_day_short_is_active(self):
        record = analyze_issue(make_issue([], created=days_before(89)), ASOF, 90)
        self.assertEqual(record.cohort, ACTIVE)

    def test_activity_after_snapshot_does_not_go_negative(self):
        record = analyze_issue(make_issue([], created=days_before(-5)), ASOF, 90)
        self.assertEqual(record.silent_days, 0)


# ---------------------------------------------------------------------------
# Bots must not make a dead issue look alive
# ---------------------------------------------------------------------------

class BotTests(unittest.TestCase):
    def test_known_bots_recognised(self):
        for name in ['dependabot', 'renovate', 'stale', 'github-actions',
                     'sweep-ai[bot]', 'Dependabot']:
            self.assertTrue(is_bot(name), name)

    def test_people_are_not_bots(self):
        for name in ['alice', 'robotlover', 'stale-fan', '', None]:
            self.assertFalse(is_bot(name), name)

    def test_bot_comment_does_not_reset_the_clock(self):
        record = analyze_issue(
            make_issue([('commented', days_before(2), 'stale[bot]',
                         'This issue has been marked stale.')]),
            ASOF, 90)
        self.assertEqual(record.cohort, NEVER_ANSWERED)
        self.assertEqual(record.silent_days, 365)

    def test_bot_comment_is_not_an_answer(self):
        record = analyze_issue(
            make_issue([('commented', days_before(300), 'github-actions', 'Hello.')]),
            ASOF, 90)
        self.assertEqual(record.responders, 0)


# ---------------------------------------------------------------------------
# The snapshot clock
# ---------------------------------------------------------------------------

class SnapshotTests(unittest.TestCase):
    def test_latest_timestamp_wins(self):
        issues = [make_issue([('commented', days_before(300), 'helper')]),
                  make_issue([('commented', days_before(3), 'helper')])]
        self.assertEqual(snapshot_date(issues), ASOF - timedelta(days=3))

    def test_bot_events_still_define_the_snapshot(self):
        # Collection horizon is about the export, not about who was talking.
        issues = [make_issue([('commented', days_before(1), 'stale[bot]')])]
        self.assertEqual(snapshot_date(issues), ASOF - timedelta(days=1))

    def test_empty_dataset_has_no_snapshot(self):
        self.assertIsNone(snapshot_date([]))

    def test_naive_and_aware_timestamps_mix_without_error(self):
        issue = make_issue([('commented', '2023-06-01T00:00:00', 'helper')],
                           created='2023-01-01T00:00:00+00:00')
        asof = snapshot_date([issue])
        self.assertIsNotNone(asof)
        self.assertEqual(analyze_issue(issue, asof, 90).silent_days, 0)

    def test_as_utc_passes_none_through(self):
        self.assertIsNone(as_utc(None))


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

class BreakdownTests(unittest.TestCase):
    def test_issue_counted_under_each_label(self):
        records = [analyze_issue(make_issue([], labels=['kind/bug', 'area/cli']),
                                 ASOF, 90)]
        ranked = dict(label_breakdown(records))
        self.assertEqual(ranked['kind/bug'][NEVER_ANSWERED], 1)
        self.assertEqual(ranked['area/cli'][NEVER_ANSWERED], 1)

    def test_unlabelled_issues_are_grouped(self):
        records = [analyze_issue(make_issue([], labels=[]), ASOF, 90)]
        self.assertIn('(no label)', dict(label_breakdown(records)))

    def test_ranked_by_open_volume_and_capped(self):
        records = [analyze_issue(make_issue([], labels=['common'], number=n), ASOF, 90)
                   for n in range(5)]
        records.append(analyze_issue(make_issue([], labels=['rare']), ASOF, 90))
        ranked = label_breakdown(records, top=1)
        self.assertEqual([name for name, _ in ranked], ['common'])

    def test_share_is_a_percentage(self):
        counts = {NEVER_ANSWERED: 1, WENT_QUIET: 1, ACTIVE: 2}
        self.assertAlmostEqual(never_answered_share(counts), 25.0)

    def test_share_of_nothing_is_zero(self):
        self.assertEqual(never_answered_share(dict.fromkeys(
            [NEVER_ANSWERED, WENT_QUIET, ACTIVE], 0)), 0.0)


class WindowTests(unittest.TestCase):
    def test_buckets_start_at_the_first_observation(self):
        labels, counts, window = equal_day_windows(
            {NEVER_ANSWERED: [90, 100, 180], WENT_QUIET: [95]}, window_days=90)
        self.assertEqual(window, 90)
        self.assertEqual(labels, ['90-179', '180-269'])
        self.assertEqual(counts[NEVER_ANSWERED], [2, 1])
        self.assertEqual(counts[WENT_QUIET], [1, 0])

    def test_boundaries_are_equal_width(self):
        labels, counts, _ = equal_day_windows({NEVER_ANSWERED: [0, 89, 90]},
                                              window_days=90)
        self.assertEqual(labels, ['0-89', '90-179'])
        self.assertEqual(counts[NEVER_ANSWERED], [2, 1])

    def test_window_widens_so_bars_stay_readable(self):
        labels, counts, window = equal_day_windows(
            {NEVER_ANSWERED: [0, 5000], WENT_QUIET: [100]}, window_days=90)
        self.assertLessEqual(len(labels), 12)
        self.assertEqual(window, 720)
        self.assertEqual(sum(counts[NEVER_ANSWERED]), 2)

    def test_no_data_gives_no_windows(self):
        labels, counts, _ = equal_day_windows({NEVER_ANSWERED: [], WENT_QUIET: []})
        self.assertEqual(labels, [])
        self.assertEqual(counts, {NEVER_ANSWERED: [], WENT_QUIET: []})


# ---------------------------------------------------------------------------
# User input
# ---------------------------------------------------------------------------

class DaysInputTests(unittest.TestCase):
    def test_accepts_numbers_and_numeric_strings(self):
        self.assertEqual(validated_days(30), 30)
        self.assertEqual(validated_days('45'), 45)

    def test_rejects_zero_and_negatives(self):
        for value in [0, -1]:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertIsNone(validated_days(value))
            self.assertIn('at least 1', output.getvalue())

    def test_rejects_nonsense_without_crashing(self):
        for value in ['soon', None, 3.5e400]:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertIsNone(validated_days(value))
            self.assertIn('--days', output.getvalue())

    def test_bad_input_stops_before_loading_data(self):
        with patch('stale_issues_analysis.config.get_parameter',
                   side_effect=params(days=0)), \
             patch('stale_issues_analysis.DataLoader') as loader:
            with contextlib.redirect_stdout(io.StringIO()):
                StaleIssuesAnalysis().run()
            loader.assert_not_called()


# ---------------------------------------------------------------------------
# End-to-end behaviour of python run.py --feature 3
# ---------------------------------------------------------------------------

class IntegrationTests(unittest.TestCase):
    def test_reports_cohorts_and_draws_chart(self):
        issues = [anchor(),
                  make_issue([], number=1),
                  make_issue([('commented', days_before(200), 'helper')], number=2),
                  make_issue([('commented', days_before(5), 'helper')], number=3)]
        output, show = run_analysis(issues)
        self.assertIn('3 open issues analyzed', output)
        self.assertIn('never answered 1', output)
        self.assertIn('went quiet 1', output)
        self.assertIn('still active 1', output)
        self.assertIn('#1', output)
        show.assert_called_once()

    def test_closed_issues_are_excluded(self):
        issues = [make_issue([], state='closed', number=1),
                  make_issue([], number=2)]
        output, _ = run_analysis(issues)
        self.assertIn('1 open issues analyzed', output)

    def test_label_filter_narrows_the_scope(self):
        issues = [make_issue([], labels=['kind/bug'], number=1),
                  make_issue([], labels=['area/cli'], number=2)]
        output, _ = run_analysis(issues, label='area/cli')
        self.assertIn('1 open issues analyzed', output)
        self.assertIn('area/cli', output)

    def test_unknown_label_reports_nothing_and_skips_chart(self):
        output, show = run_analysis([make_issue([])], label='does/not/exist')
        self.assertIn('No open issues found', output)
        show.assert_not_called()

    def test_all_issues_closed_skips_chart(self):
        output, show = run_analysis([make_issue([], state='closed')])
        self.assertIn('No open issues found', output)
        show.assert_not_called()

    def test_empty_dataset_is_handled(self):
        output, show = run_analysis([])
        self.assertIn('cannot be measured', output)
        show.assert_not_called()

    def test_monologue_is_called_out(self):
        issues = [anchor(),
                  make_issue([('commented', days_before(200), 'reporter', 'Ping.')])]
        output, _ = run_analysis(issues)
        self.assertIn('monologue', output)
        self.assertIn('1 self-comment(s)', output)

    def test_days_input_changes_the_answer(self):
        issues = [anchor(), make_issue([('commented', days_before(100), 'helper')])]
        lenient, _ = run_analysis(issues, days=365)
        strict, _ = run_analysis(issues, days=30)
        self.assertIn('still active 1', lenient)
        self.assertIn('went quiet 1', strict)

    def test_snapshot_date_is_printed_for_reproducibility(self):
        issues = [make_issue([('commented', days_before(0), 'helper')])]
        output, _ = run_analysis(issues)
        self.assertIn(f'Snapshot: {ASOF.date().isoformat()}', output)

    def test_no_stale_issues_still_renders(self):
        issues = [make_issue([('commented', days_before(1), 'helper')])]
        output, show = run_analysis(issues)
        self.assertIn('Stale: 0', output)
        self.assertIn('None found.', output)
        show.assert_called_once()


if __name__ == '__main__':
    unittest.main()
