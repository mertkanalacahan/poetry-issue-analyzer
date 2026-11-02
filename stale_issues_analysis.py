"""Find open issues that have gone silent, and tell neglect apart from abandonment.

An issue is "stale" when nothing human has happened on it for N days. The clock
is read against the dataset's own snapshot date, not today's date, so the result
is the same whenever the analysis is re-run.

Two clocks run side by side. The *substantive* clock moves only when somebody
engages with the issue: a comment, a close, a reopen, an assignment, a retitle.
The *touch* clock moves on any event at all, metadata included. They disagree
more than you would expect, because one maintainer relabelling a hundred old
issues in an afternoon moves every touch clock and not one substantive clock.
Reporting both is the point: the gap between them is where silent issues hide.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import re
import sys
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
TOP_SWEEPS = 3

# Bookkeeping, not engagement. Labels and milestones are filing; referenced and
# cross-referenced are something happening on another issue; mentions and
# subscriptions are side effects of that. None of them is a human answering the
# person who opened the issue, so none of them moves the substantive clock.
PASSIVE_EVENTS = frozenset({
    "labeled", "unlabeled", "milestoned", "demilestoned",
    "subscribed", "unsubscribed", "mentioned",
    "cross-referenced", "referenced",
    "locked", "unlocked", "pinned", "unpinned",
})

# How much has to happen before an issue counts as alive.
STRICT = "strict"   # only substantive events; the default
ANY = "any"         # any non-bot event, which is how GitHub reads "updated"
ACTIVITY_MODES = (STRICT, ANY)
DEFAULT_ACTIVITY = STRICT

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
    last_touch: datetime
    touch_days: int
    responders: int
    creator_comments: int
    cohort: str

    @property
    def is_monologue(self):
        """Author kept talking; nobody ever answered."""
        return self.cohort == NEVER_ANSWERED and self.creator_comments > 0

    @property
    def touched_since(self):
        """Something happened after the last real activity, but it was filing."""
        return self.touch_days < self.silent_days


def analyze_issue(issue, asof, days, activity=DEFAULT_ACTIVITY):
    """Measure one open issue's silence and place it in a cohort.

    Both clocks start at the opening date, because filing the issue is itself
    somebody doing something. From there the touch clock moves on any non-bot
    event, while the substantive clock moves only on events outside
    PASSIVE_EVENTS. Under the default strict mode the cohorts are drawn from
    the substantive clock, so a bulk relabel cannot pass for attention;
    activity="any" collapses the two and restores GitHub's looser reading.

    A reply only counts as an *answer* when it comes from someone other than
    the author, in either mode.
    """
    creator = (issue.creator or "").casefold()
    opened = as_utc(issue.created_date)
    last_touch = opened
    last_substantive = opened
    responders = set()
    creator_comments = 0

    for event in issue.events:
        if is_bot(event.author):
            continue
        when = as_utc(event.event_date)
        if when is not None:
            if last_touch is None or when > last_touch:
                last_touch = when
            if (event.event_type not in PASSIVE_EVENTS
                    and (last_substantive is None or when > last_substantive)):
                last_substantive = when
        if event.event_type != "commented":
            continue
        author = (event.author or "").casefold()
        if not author:
            continue
        if author == creator:
            creator_comments += 1
        else:
            responders.add(author)

    last_activity = last_touch if activity == ANY else last_substantive
    if last_activity is None or last_touch is None:
        return None

    silent_days = max((asof - last_activity).days, 0)
    touch_days = max((asof - last_touch).days, 0)
    if silent_days < days:
        cohort = ACTIVE
    elif responders:
        cohort = WENT_QUIET
    else:
        cohort = NEVER_ANSWERED
    return IssueRecord(issue, last_activity, silent_days, last_touch, touch_days,
                       len(responders), creator_comments, cohort)


def bookkeeping_sweeps(masked, top=TOP_SWEEPS):
    """Days when many silent issues were touched but still not answered.

    A maintainer working through a backlog of labels in one afternoon shows up
    here as a single date against a large count. That is worth naming in the
    output: it is the reason the strict and loose readings disagree at all.
    """
    tally = Counter(record.last_touch.date().isoformat() for record in masked)
    return tally.most_common(top)


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


def keep_output_printable():
    """Survive an issue title the output stream cannot encode.

    Poetry titles carry emoji and typographic dashes. Piping this report on
    Windows hands us a cp1252 stream, where the first such title raises
    mid-print and truncates the analysis with no error anyone can see.
    Substituting that one glyph costs a character; raising costs the rest of
    the report.
    """
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(errors="replace")
    except (ValueError, OSError):
        pass


def validated_activity(value):
    """Accept the --activity input or explain the problem instead of crashing."""
    if value is None:
        return DEFAULT_ACTIVITY
    mode = str(value).strip().casefold()
    if mode not in ACTIVITY_MODES:
        print(f"--activity must be one of {', '.join(ACTIVITY_MODES)}, got {value!r}.")
        return None
    return mode


def _style(axis):
    axis.set_axisbelow(True)
    axis.tick_params(colors=INK_MUTED, length=0, labelsize=9)
    for spine in axis.spines.values():
        spine.set_visible(False)


def draw_charts(records, ranked, days, asof, activity=DEFAULT_ACTIVITY):
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
    clock = ("Labels, mentions and cross-references do not count as activity"
             if activity == STRICT else "Any non-bot event counts as activity")
    figure.text(0.5, 0.015,
                f"Measured against the dataset snapshot of {asof.date().isoformat()}, "
                f"not today. {clock}. Bot events are ignored. Open issues only.",
                ha="center", fontsize=9, color=INK_MUTED)
    figure.tight_layout(rect=[0, 0.05, 1, 0.9])
    plt.show()


class StaleIssuesAnalysis:
    """Flag silent open issues and compare neglect against abandonment."""

    def __init__(self):
        self.days = config.get_parameter("days", DEFAULT_DAYS)
        self.label = config.get_parameter("label")
        self.activity = config.get_parameter("activity", DEFAULT_ACTIVITY)

    def run(self):
        keep_output_printable()
        days = validated_days(self.days)
        if days is None:
            return
        activity = validated_activity(self.activity)
        if activity is None:
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
                   (analyze_issue(issue, asof, days, activity)
                    for issue in open_issues)
                   if record is not None]
        if not records:
            print("No open issues carry a usable date.")
            return

        stale = [record for record in records if record.cohort != ACTIVE]
        ignored = [record for record in stale if record.cohort == NEVER_ANSWERED]
        quiet = [record for record in stale if record.cohort == WENT_QUIET]
        monologues = [record for record in ignored if record.is_monologue]
        total = len(records)

        masked = [record for record in stale if record.touch_days < days]

        print(f"\nSTALE OPEN ISSUES | silent {days}+ days | {self.label or 'all labels'}")
        print("Question: Which open issues have gone silent, and were they ignored "
              "outright or abandoned mid-discussion?")
        print("Method: Measure days since the last qualifying non-bot event against the "
              "dataset snapshot,")
        print("        then split stale issues by whether anyone other than the author "
              "ever replied.")
        print(f"Snapshot: {asof.date().isoformat()} | {total:,} open issues analyzed")
        print(f"Clock: {activity}", end="")
        if activity == STRICT:
            print(" - labels, milestones, mentions, subscriptions and cross-references")
            print("       do not count as activity. Pass --activity any to count every "
                  "non-bot event.")
        else:
            print(" - every non-bot event counts, labels and mentions included.")
            print("       This is GitHub's own reading of an issue being updated, and it "
                  "lets a bulk")
            print("       relabel hide silence. Pass --activity strict for the stricter "
                  "reading.")
        print(f"Stale: {len(stale):,} ({len(stale) / total * 100:.1f}%) | "
              f"never answered {len(ignored):,} | went quiet {len(quiet):,} | "
              f"still active {total - len(stale):,}")
        if ignored:
            print(f"Of the never-answered, {len(monologues):,} are monologues: the author "
                  "kept commenting and nobody replied.")

        if masked:
            print(f"\nLooks active, is not: {len(masked):,} of the {len(stale):,} stale "
                  f"issues were touched inside the")
            print(f"{days}-day window, but only by bookkeeping - nobody replied. On the "
                  "loose clock every one")
            print("of these would read as active.")
            sweeps = [row for row in bookkeeping_sweeps(masked) if row[1] > 1]
            if sweeps:
                print("Busiest such days, which is what bulk triage looks like:")
                for date_text, count in sweeps:
                    print(f"  {date_text}  {count:,} silent issues touched")

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
            if record.touched_since:
                print(f"    Last touched {record.last_touch.date().isoformat()} "
                      f"({record.touch_days:,}d ago), bookkeeping only")
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
            if record.touched_since:
                print(f"    Last touched {record.last_touch.date().isoformat()} "
                      f"({record.touch_days:,}d ago), bookkeeping only")
            print(f"    {issue.url or '(no URL)'}")

        print("\nNote: silence is measured from the dataset snapshot, not today. "
              "An unanswered issue is not\nnecessarily an ignored one; some need no reply.")
        draw_charts(records, ranked, days, asof, activity)
