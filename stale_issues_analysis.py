"""Find open issues that have gone silent, and tell neglect apart from abandonment.

An issue is "stale" when nothing human has happened on it for N days. The clock
is read against the dataset's own snapshot date, not today's date, so the result
is the same whenever the analysis is re-run.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from textwrap import shorten

import matplotlib.pyplot as plt

import config
from data_loader import DataLoader
from model import State

DEFAULT_DAYS = 90
TOP_LABELS = 10
WINDOW_DAYS = 90
MAX_WINDOWS = 12
UNLABELED = "(no label)"

# Automated accounts keep dead issues looking alive. A stale-bot nag is not
# attention, so bot events never reset the silence clock.
BOT = re.compile(r"\[bot\]$|^(?:dependabot|renovate|stale|github-actions)$", re.I)

NEVER_ANSWERED = "never answered"
WENT_QUIET = "went quiet"
ACTIVE = "active"
COHORTS = (NEVER_ANSWERED, WENT_QUIET, ACTIVE)
STALE_COHORTS = (NEVER_ANSWERED, WENT_QUIET)

# Categorical slots 1-3 of the validated palette; one hue per cohort, held fixed
# across both panels so a colour always means the same thing.
COHORT_COLORS = {NEVER_ANSWERED: "#2a78d6", WENT_QUIET: "#eb6834", ACTIVE: "#1baf7a"}
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#e5e5e2"


def is_bot(author):
    return bool(author and BOT.search(author.strip()))


def as_utc(moment):
    """Normalise so naive and aware timestamps can be compared."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def snapshot_date(issues):
    """The latest timestamp anywhere in the data: when collection stopped.

    Staleness is measured from here rather than from datetime.now(). The data
    file is a frozen export, so "today" would mark every open issue stale and
    leave the --days input with nothing to do.
    """
    moments = []
    for issue in issues:
        moments.append(as_utc(issue.created_date))
        moments.append(as_utc(issue.updated_date))
        moments.extend(as_utc(event.event_date) for event in issue.events)
    moments = [moment for moment in moments if moment is not None]
    return max(moments) if moments else None


@dataclass
class IssueRecord:
    issue: object
    last_activity: datetime
    silent_days: int
    responders: int
    creator_comments: int
    cohort: str

    @property
    def is_monologue(self):
        """Author kept talking; nobody ever answered."""
        return self.cohort == NEVER_ANSWERED and self.creator_comments > 0


def analyze_issue(issue, asof, days):
    """Measure one open issue's silence and place it in a cohort.

    Activity means any non-bot event, which is what "no comments or updates"
    means on GitHub: a label or an assignment is somebody touching the issue.
    A reply, however, only counts as an answer when it comes from someone other
    than the author.
    """
    creator = (issue.creator or "").casefold()
    last_activity = as_utc(issue.created_date)
    responders = set()
    creator_comments = 0

    for event in issue.events:
        if is_bot(event.author):
            continue
        when = as_utc(event.event_date)
        if when is not None and (last_activity is None or when > last_activity):
            last_activity = when
        if event.event_type != "commented":
            continue
        author = (event.author or "").casefold()
        if not author:
            continue
        if author == creator:
            creator_comments += 1
        else:
            responders.add(author)

    if last_activity is None:
        return None

    silent_days = max((asof - last_activity).days, 0)
    if silent_days < days:
        cohort = ACTIVE
    elif responders:
        cohort = WENT_QUIET
    else:
        cohort = NEVER_ANSWERED
    return IssueRecord(issue, last_activity, silent_days, len(responders),
                       creator_comments, cohort)


def label_breakdown(records, top=TOP_LABELS):
    """Cohort counts per label, ranked by how many open issues carry the label."""
    totals = {}
    for record in records:
        for label in (record.issue.labels or [UNLABELED]):
            counts = totals.setdefault(label, dict.fromkeys(COHORTS, 0))
            counts[record.cohort] += 1
    ranked = sorted(totals.items(),
                    key=lambda item: (-sum(item[1].values()), item[0]))
    return ranked[:top]


def never_answered_share(counts):
    total = sum(counts.values())
    return counts[NEVER_ANSWERED] / total * 100 if total else 0.0


def equal_day_windows(groups, window_days=WINDOW_DAYS, max_windows=MAX_WINDOWS):
    """Bucket every cohort's silence durations into shared equal-width windows.

    Issues can sit untouched for years, so a fixed window size would produce
    dozens of unreadable bars. The window doubles until the bars fit; every
    window still covers an identical number of days, so no bucket is open-ended.
    """
    everything = [value for values in groups.values() for value in values]
    if not everything:
        return [], {name: [] for name in groups}, window_days
    while (max(everything) // window_days
           - min(everything) // window_days + 1) > max_windows:
        window_days *= 2
    base = min(everything) // window_days * window_days
    span = (max(everything) - base) // window_days + 1
    labels = [f"{base + i * window_days}-{base + (i + 1) * window_days - 1}"
              for i in range(span)]
    counts = {name: [0] * span for name in groups}
    for name, values in groups.items():
        for value in values:
            counts[name][(value - base) // window_days] += 1
    return labels, counts, window_days


def validated_days(value):
    """Accept the --days input or explain the problem instead of crashing."""
    try:
        days = int(value)
    except (TypeError, ValueError, OverflowError):
        print(f"--days must be a whole number of days, got {value!r}.")
        return None
    if days < 1:
        print(f"--days must be at least 1, got {days}.")
        return None
    return days


def _style(axis):
    axis.set_axisbelow(True)
    axis.tick_params(colors=INK_MUTED, length=0, labelsize=9)
    for spine in axis.spines.values():
        spine.set_visible(False)


def draw_charts(records, ranked, days, asof):
    """Panel 1: who gets ignored. Panel 2: how long the silence runs."""
    figure, (label_ax, timing_ax) = plt.subplots(1, 2, figsize=(14.5, 6.4))
    figure.patch.set_facecolor(SURFACE)
    figure.suptitle(f"Open Issues With No Activity For {days}+ Days", color=INK)

    # Shares rather than raw counts: a label with 400 open issues would
    # otherwise dwarf every other bar and only restate which label is popular.
    rows = list(reversed(ranked))
    positions = range(len(rows))
    left = [0.0] * len(rows)
    for cohort in COHORTS:
        shares = [counts[cohort] / (sum(counts.values()) or 1) * 100
                  for _, counts in rows]
        bars = label_ax.barh(positions, shares, left=left, height=0.68,
                             color=COHORT_COLORS[cohort], label=cohort,
                             edgecolor=SURFACE, linewidth=1.5)
        for bar, share in zip(bars, shares):
            # Only label a segment wide enough to hold the text.
            if share >= 9:
                label_ax.text(bar.get_x() + share / 2,
                              bar.get_y() + bar.get_height() / 2,
                              f"{share:.0f}%", ha="center", va="center",
                              color=INK, fontsize=9)
        left = [running + share for running, share in zip(left, shares)]

    label_ax.set_yticks(list(positions),
                        [f"{shorten(name, width=22, placeholder='...')}  "
                         f"(n={sum(counts.values())})" for name, counts in rows])
    label_ax.set_xlim(0, 100)
    label_ax.set_xlabel("Share of that label's open issues (%)", color=INK_MUTED)
    label_ax.set_title(f"Which areas go unanswered?  (top {len(rows)} labels)",
                       color=INK, fontsize=11)
    label_ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    _style(label_ax)

    windows, counts, window = equal_day_windows(
        {cohort: [record.silent_days for record in records
                  if record.cohort == cohort] for cohort in STALE_COHORTS})
    width = 0.42
    for offset, cohort in zip((-width / 2, width / 2), STALE_COHORTS):
        bars = timing_ax.bar([index + offset for index in range(len(windows))],
                             counts[cohort], width * 0.94,
                             color=COHORT_COLORS[cohort], label=cohort,
                             edgecolor=SURFACE, linewidth=1.5)
        timing_ax.bar_label(bars, padding=2, fontsize=8, color=INK_MUTED)

    timing_ax.set_xticks(range(len(windows)), windows, rotation=45, ha="right")
    timing_ax.set_xlabel(f"Days since last human activity ({window}-day windows)",
                         color=INK_MUTED)
    timing_ax.set_ylabel("Stale open issues", color=INK_MUTED)
    timing_ax.set_title("How long has the silence lasted?", color=INK, fontsize=11)
    timing_ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    _style(timing_ax)

    handles, names = label_ax.get_legend_handles_labels()
    figure.legend(handles, names, loc="upper center", ncol=len(COHORTS),
                  frameon=False, bbox_to_anchor=(0.5, 0.945),
                  labelcolor=INK_MUTED, fontsize=9)
    figure.text(0.5, 0.015,
                f"Measured against the dataset snapshot of {asof.date().isoformat()}, "
                "not today. Bot events are ignored. Open issues only.",
                ha="center", fontsize=9, color=INK_MUTED)
    figure.tight_layout(rect=[0, 0.05, 1, 0.9])
    plt.show()


class StaleIssuesAnalysis:
    """Flag silent open issues and compare neglect against abandonment."""

    def __init__(self):
        self.days = config.get_parameter("days", DEFAULT_DAYS)
        self.label = config.get_parameter("label")

    def run(self):
        days = validated_days(self.days)
        if days is None:
            return

        issues = DataLoader().get_issues()
        asof = snapshot_date(issues)
        if asof is None:
            print("No dated issues found, so inactivity cannot be measured.")
            return

        open_issues = [issue for issue in issues if issue.state == State.open]
        if self.label:
            open_issues = [issue for issue in open_issues
                           if self.label in (issue.labels or [])]
        if not open_issues:
            scope = f" for label {self.label!r}" if self.label else ""
            print(f"No open issues found{scope}.")
            return

        records = [record for record in
                   (analyze_issue(issue, asof, days) for issue in open_issues)
                   if record is not None]
        if not records:
            print("No open issues carry a usable date.")
            return

        stale = [record for record in records if record.cohort != ACTIVE]
        ignored = [record for record in stale if record.cohort == NEVER_ANSWERED]
        quiet = [record for record in stale if record.cohort == WENT_QUIET]
        monologues = [record for record in ignored if record.is_monologue]
        total = len(records)

        print(f"\nSTALE OPEN ISSUES | silent {days}+ days | {self.label or 'all labels'}")
        print("Question: Which open issues have gone silent, and were they ignored "
              "outright or abandoned mid-discussion?")
        print("Method: Measure days since the last non-bot event against the dataset "
              "snapshot, then split")
        print("        stale issues by whether anyone other than the author ever replied.")
        print(f"Snapshot: {asof.date().isoformat()} | {total:,} open issues analyzed")
        print(f"Stale: {len(stale):,} ({len(stale) / total * 100:.1f}%) | "
              f"never answered {len(ignored):,} | went quiet {len(quiet):,} | "
              f"still active {total - len(stale):,}")
        if ignored:
            print(f"Of the never-answered, {len(monologues):,} are monologues: the author "
                  "kept commenting and nobody replied.")

        ranked = label_breakdown(records)
        print(f"\nNever-answered share by label (top {len(ranked)} by open volume):")
        for name, counts in sorted(ranked,
                                   key=lambda item: -never_answered_share(item[1])):
            label_text = shorten(name, width=26, placeholder="...")
            print(f"  {label_text:<28} {never_answered_share(counts):5.1f}% never answered  "
                  f"({counts[NEVER_ANSWERED]:,} of {sum(counts.values()):,} open)")

        print("\nLongest-ignored issues (never answered, top 8):")
        ignored.sort(key=lambda record: (-record.silent_days, record.issue.number))
        if not ignored:
            print("  None found.")
        for record in ignored[:8]:
            issue = record.issue
            title = shorten(issue.title or "(untitled)", width=76, placeholder="...")
            opened = as_utc(issue.created_date)
            print(f"  #{issue.number}: {title}")
            print(f"    Opened {opened.date().isoformat() if opened else '(unknown)'} | "
                  f"silent {record.silent_days:,}d | author {issue.creator or '(unknown)'}"
                  + (f" | {record.creator_comments} self-comment(s)"
                     if record.creator_comments else ""))
            print(f"    {issue.url or '(no URL)'}")

        print("\nLongest-abandoned discussions (went quiet, top 5):")
        quiet.sort(key=lambda record: (-record.silent_days, record.issue.number))
        if not quiet:
            print("  None found.")
        for record in quiet[:5]:
            issue = record.issue
            title = shorten(issue.title or "(untitled)", width=76, placeholder="...")
            print(f"  #{issue.number}: {title}")
            print(f"    Last activity {record.last_activity.date().isoformat()} | "
                  f"silent {record.silent_days:,}d | {record.responders} responder(s)")
            print(f"    {issue.url or '(no URL)'}")

        print("\nNote: silence is measured from the dataset snapshot, not today. "
              "An unanswered issue is not\nnecessarily an ignored one; some need no reply.")
        draw_charts(records, ranked, days, asof)
