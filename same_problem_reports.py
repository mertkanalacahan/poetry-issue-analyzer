"""Find first-hand same-problem reports in issue comments.

Results are evidence for maintainer review, not proof of identical root causes.
"""
from dataclasses import dataclass
from datetime import datetime
import re
from textwrap import shorten

import matplotlib.pyplot as plt

import config
from data_loader import DataLoader
from model import State

PROBLEM = r"(?:issue|issues|problem|bug|error|failure|exception|behavior|behaviour|thing)"
SPEAKER = r"(?:i|we|i'm|we're|i've|we've)"
EXPERIENCE = r"(?:have|had|hit|got|get|see|saw|face|faced|facing|encounter|encountered|encountering|experience|experienced|experiencing|having|seeing|getting|hitting|running into|ran into)"
REPORT_PATTERNS = [
    ("same problem", rf"\b{SPEAKER}\s+(?:(?:am|are|have|was|were)\s+)?(?:(?:also|still|just|too|recently)\s+)?{EXPERIENCE}\s+(?:(?:exactly|very)\s+)?(?:the|a|this|that)?\s*(?:(?:exactly|very)\s+)?(?:same|similar|identical)\s+{PROBLEM}\b"),
    ("same problem", rf"\b{SPEAKER}\s+(?:(?:am|are|have|was|were)\s+)?(?:(?:also|still|just|recently)\s+)?{EXPERIENCE}\s+(?:this|that)\s+{PROBLEM}\b"),
    ("same problem", rf"\b{SPEAKER}\s+(?:also\s+)?(?:have|had|got|get|see|saw)\s+(?:this|that|it)\s+(?:too|as well)\b"),
    ("same problem", rf"^(?:same here|same for me|same {PROBLEM}(?: here| for me| too| on)?|similar {PROBLEM} (?:here|for me)|having the same {PROBLEM})\b"),
    ("reproduced", rf"\b{SPEAKER}\s+(?:also\s+)?(?:can|could|was able to|am able to|have|had)\s+(?:also\s+)?(?:reproduce|reproduced|replicate|replicated|confirm)\s+(?:this|it|the|same|issue|problem|bug|error)\b"),
    ("reproduced", r"\b(?:this|it)\s+(?:also\s+)?(?:reproduces|happens|occurs|persists)\s+(?:reliably|consistently|every time|on|for|when|with|here|to me)\b"),
    ("direct experience", rf"\b{SPEAKER}\s+(?:(?:am|are|was|were|have been)\s+)?(?:(?:also|still|currently|now|recently|just)\s+)?(?:seeing|getting|having|experiencing|facing|hitting|encountering|running into)\s+(?:this|that|it|the same|a similar)(?:\s+(?:error|failure|issue|problem))?\b"),
    ("direct experience", r"\b(?:this|it)\s+(?:(?:is|was|keeps|still)\s+)?(?:happening|happens|happened)\s+(?:to me|to us|for me)\b"),
    ("direct experience", rf"\b{SPEAKER}\s+(?:(?:just|also|recently)\s+)?(?:came across|ran into|hit)\s+this\s+(?:myself|too)\b"),
    ("direct experience", rf"\b(?:{SPEAKER}\s+(?:just\s+|recently\s+)?|just\s+)(?:ran into|hit|encountered)\s+(?:this|the same)\s+{PROBLEM}\b"),
    ("direct experience", rf"\b{SPEAKER}\s+(?:(?:am|are|have been)\s+)?(?:also\s+)?affected\b"),
    ("persistent problem", r"\b(?:still\s+(?:broken|failing|fails|happening|reproducible|not working|seeing this|having this|getting this|doesn.t work|does not work)|(?:it|this)\s+(?:still|continues? to)\s+(?:fail|fails|happen|reproduce|occur|break)|(?:same|similar)\s+(?:issue|problem|error)\s+(?:persists|continues))\b"),
    ("direct experience", rf"\b{SPEAKER}\s+(?:(?:am|are|also|still|just)\s+)?(?:get|got|see|saw|hit|encountered|encounter|getting|seeing)\s+(?:the|this|that|same)\s+(?:exact\s+)?(?:error|traceback|exception|failure)\b"),
    ("direct experience", r"\b(?:[a-z][\w.+-]{1,49}|(?:the|this|my)\s+(?:app|application|tool|command|program|package|library|plugin|client|service))\s+(?:still\s+)?(?:fails|failed|breaks|broke|crashes|crashed)\s+(?:for me|on my (?:machine|computer|system|setup)|on our (?:machines|systems))\b"),
    ("direct experience", r"\bwe\s+have\s+also\s+started\s+(?:hitting|seeing|getting|experiencing|having)\s+this\s+(?:issue|problem|bug|error)\b"),
    ("direct experience", r"^this\s+is\s+happening\b"),
    ("direct experience", r"^just\s+came\s+across\s+this\s+myself\b"),
    ("same problem", r"^same\s+thing\s+(?:on|with|for|here|too)\b"),
    ("same problem", rf"\b{SPEAKER}\s+(?:(?:am|are|have|was|were)\s+)?(?:(?:also|still|just|recently)\s+)?(?:ran into|running into|hit|got|see|saw|encountered|experienced)\s+(?:this|it)\s+(?:too|as well)\b"),
    ("reproduced", r"^reproducible\s+(?:with|on|using)\b"),
]
# Additional high-specificity expressions found in a held-out issue-level review.
# These are project-independent: they describe a person's experience, not Poetry.
REPORT_PATTERNS += [
    ("direct experience", rf"\b{SPEAKER}\s+(?:(?:am|are|have)\s+)?(?:(?:still|also|currently)\s+)?(?:running\s+into|running\s+in|run\s+into)\s+(?:this|the\s+same)\s+{PROBLEM}\b"),
    ("direct experience", rf"\b{SPEAKER}\s+(?:(?:am|are|have|was|were)\s+)?(?:(?:still|also|currently)\s+)?(?:see|seeing|get|getting|hit|hitting|have|having)\s+(?:(?:the|this|that|a)\s+)?(?:same|exact|identical)\s+(?:error|bug|issue|failure|warning|problem|traceback)\b"),
    ("direct experience", rf"\b{SPEAKER}\s+(?:(?:am|are|have|was|were)\s+)?(?:(?:still|also|currently)\s+)?(?:see|seeing|get|getting|hit|hitting|have|having)\s+(?:(?:the|this|that|a)\s+)?(?:error|failure|warning|traceback|exception)\b"),
    ("same problem", rf"\b{SPEAKER}\s+(?:have|had)\s+the\s+same\s+(?:when|while)\b"),
    ("direct experience", r"^(?:this|the)\s+(?:issue|problem|bug|error)\s+(?:still\s+(?:exists|occurs|happens)|persists)\b"),
    ("direct experience", rf"\b{SPEAKER}\s+(?:(?:am|are)\s+)?having\s+(?:some|the|a)\s+(?:trouble|difficulty|problems?)\s+(?:with|installing|running|using)\b"),
    ("same problem", r"^same\s+(?:error|issue|problem)(?:\s|$)"),
    ("historical experience", r"\b(?:fixed|resolved|solved)\s+(?:the|this|my)\s+(?:issue|bug|problem)\s+for\s+me\b|\b(?:following\s+)?(?:command|solution|workaround)\s+fixed\s+(?:the|my|this)\s+(?:issue|problem|bug)\s+for\s+me\b"),
]
# Additional straightforward ways to report the same experience.
REPORT_PATTERNS += [
    ("same problem", rf"\b{SPEAKER}\s+(?:am|are|was|were)\s+having\s+(?:the\s+)?(?:exact|identical|very)\s+same\s+{PROBLEM}\b"),
    ("same problem", rf"\b{SPEAKER}\s+(?:was|were)\s+(?:seeing|getting|having)\s+(?:this|the)\s+same\s+(?:error|problem|issue|bug)\b"),
    ("direct experience", rf"\b{SPEAKER}\s+(?:also\s+)?(?:hit|encountered|got)\s+this\s+(?:when|while|after|on)\b"),
    ("reproduced", rf"\b{SPEAKER}\s+(?:(?:have|has)\s+)?(?:just\s+)?(?:tested|verified|reproduced)\s+this\s+(?:and|but)\s+(?:the\s+same\s+)?(?:issue|bug|problem)\s+(?:still\s+)?(?:occurs|exists|persists)\b"),
    ("historical experience", rf"\b{SPEAKER}\s+can\s+confirm\s*,?\s+.{0,90}?\bfixes\s+this\s+(?:issue|problem|bug)\b"),
]
# A few ordinary ways of reporting an experience that earlier rules missed.
# These do not rely on product names, GitHub issue numbers, or learned weights.
REPORT_PATTERNS += [
    ("same problem", rf"\b{SPEAKER}\s+(?:(?:am|are|was|were)\s+)?(?:have|had|having|see|seeing|get|getting|experience|experiencing)\s+(?:(?:the|this|a)\s+)?(?:exact|exactly)\s+same\s+{PROBLEM}\b"),
    ("reproduced", rf"\b(?:i|we)\s+(?:(?:can|could|have|had)\s+)?(?:reproduce|reproduced|replicate|replicated|recreate|recreated)\s+(?:on|with|using|in)\b|^reproduced\s+(?:on|with|using|in)\b"),
    ("persistent problem", r"^this\s+is\s+still\s+(?:a|an|the)\s+(?:issue|problem|bug)\b"),
    ("direct experience", r"\b(?:it(?:'s| is)\s+)?happening\s+(?:the\s+)?same\s+to\s+(?:me|us)\b"),
    ("direct experience", rf"\b{SPEAKER}\s+(?:(?:am|are|was|were)\s+)?(?:experiencing|seeing|having)\s+something\s+(?:like|similar\s+to)\s+this\b"),
    ("direct experience", rf"\b{SPEAKER}\s+(?:just\s+)?(?:ran|run)\s+into\s+this\s+(?:when|while|after)\b"),
    ("direct experience", rf"\b{SPEAKER}\s+(?:(?:just|also|recently)\s+)?(?:ran|run)\s+into\s+this\b"),
]
REPORT_PATTERNS = [(label, re.compile(pattern, re.I)) for label, pattern in REPORT_PATTERNS]

DENIAL = re.compile(
    r"\b(?:can't|cannot|couldn't|can not|could not|unable to)\s+(?:reproduce|replicate)|"
    rf"\b{SPEAKER}\s+(?:don't|do not|didn't|did not|haven't|have not)\s+(?:have|see|experience|get|reproduce)|"
    r"\b(?:i(?:'m| am)|we(?:'re| are))\s+not\s+(?:seeing|having|getting|experiencing|reproducing)|"
    r"\bnot\s+(?:actually\s+)?(?:the\s+)?same\s+(?:issue|problem|error|thing)|"
    r"\bno longer\s+(?:have|see|experience|get)|"
    r"\b(?:can|could)\s+(?:anyone|someone|you)\s+(?:reproduce|confirm)", re.I)
UNRELATED = re.compile(r"\b(?:unrelated|not related|isn't related|is not related)\s+to\s+(?:the\s+|this\s+)?(?:original\s+)?(?:issue|problem|report)\b", re.I)
RESOLVED = re.compile(
    r"\b(?:fixed|resolved|solved)\s+(?:it|this|my issue|the issue|the problem)|"
    r"\b(?:it|this|the issue|the problem)\s+(?:is|was|has been|got)\s+(?:now\s+)?(?:fixed|resolved|solved)|"
    r"\b(?:updat(?:e|ed|ing)|upgrad(?:ed|ing)|downgrad(?:ed|ing)|reinstall(?:ed|ing)|switching)\b.{0,75}\b(?:fixed|solved|resolved|worked|works now)|"
    r"\b(?:it|this)\s+(?:works|worked)\s+(?:now|after)\b|"
    r"(?<!be )\bsolved\s+with\b|"
    r"\b(?:it|this)\s+(?:does\s+)?seem\s+to\s+(?:be\s+)?(?:work\s+fine|work\s+now|fixed|resolved|solved)\b|"
    r"\bno\s+longer\s+(?:occurs|occurring|happens|happening|reproducible)\b|"
    r"\b(?:managed|was able)\s+to\s+(?:workaround|work\s+around)\b", re.I)
ONGOING = re.compile(
    r"\b(?:still|currently)\s+(?:(?:am|are|is)\s+)?(?:getting|having|seeing|experiencing|happening|failing|fails|broken|happens|occurs)|"
    r"\b(?:not|never)\s+(?:fixed|resolved)\b|"
    r"\b(?:it|this)\s+(?:still\s+)?(?:fails|keeps failing|keeps happening)\b|"
    r"\b(?:issue|bug|problem|error)\s+still\s+(?:exists|occurs|persists|happens)\b", re.I)
PAST = re.compile(rf"\b(?:used to|previously|back then|in the past|last year|last week|happened to me)\b|\b{SPEAKER}\s+(?:had|was having|were having|was getting|were getting|was seeing|were seeing|saw|experienced)\b", re.I)
BOT = re.compile(r"\[bot\]$|^(?:dependabot|renovate|stale|github-actions)$", re.I)
SPLIT_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
SPLIT_CLAUSES = re.compile(r"\s*;\s*|\s*,?\s+but\s+|\s+however\s*,?\s*", re.I)

@dataclass(frozen=True)
class Detection:
    rule: str
    excerpt: str
    status: str

def clean_comment(comment):
    if not comment:
        return ""
    text = comment.replace("’", "'")
    text = re.sub(r"<!--[\s\S]*?-->", " ", text)
    text = re.sub(r"```[\s\S]*?```|~~~[\s\S]*?~~~", " ", text)
    text = re.sub(r"`[^`\n]*`", " ", text)
    text = re.sub(r"^\s*(?:>|&gt;)\s?.*$", "", text, flags=re.M)
    text = re.split(r"(?im)^on\s+.{8,140}\s+wrote:\s*$", text, maxsplit=1)[0]
    return text

def _not_a_report(clause, sentence):
    if DENIAL.search(clause):
        return True
    if re.match(r"^(?:if|assuming|suppose|imagine)\b", clause, re.I):
        return True
    if re.search(r"\b(?:if|suppose|assuming|imagine)\s+(?:i|we)\b", clause, re.I):
        return True
    if re.match(r"^(?:anyone|does|did|can|could|would|what|why|how|is|are|do)\b", clause, re.I) and sentence.endswith("?"):
        return True
    if re.match(r"^(?:can|could|would|please)\s+(?:you|someone|anyone)\b", clause, re.I):
        return True
    if re.match(r"^(?:anyone else|is anyone|can anyone|could anyone|does anyone)\b", clause, re.I):
        return True
    if re.search(rf"\b{SPEAKER}\s+can\s+confirm\s+(?:this|it)\s+(?:is|was|has been)\s+(?:fixed|resolved|working)", clause, re.I):
        return True
    if re.search(rf"\bsame\s+(?:issue|problem|bug|error)\s+as\s+(?:#\d+|@\w+|https?://|another issue|this issue)", clause, re.I) and not re.search(rf"\b{SPEAKER}\s+(?:have|had|am|are)\b|\bfor me\b", clause, re.I):
        return True
    return False

def classify_comment(comment):
    text = clean_comment(comment)
    for sentence in filter(None, (s.strip() for s in SPLIT_SENTENCES.split(text))):
        if UNRELATED.search(sentence):
            continue
        for clause in SPLIT_CLAUSES.split(sentence):
            clause = clause.strip()
            if not clause or _not_a_report(clause, sentence):
                continue
            for rule, pattern in REPORT_PATTERNS:
                if not pattern.search(clause):
                    continue
                updates = []
                for match in RESOLVED.finditer(text):
                    updates.append((match.start(), "historical"))
                for match in ONGOING.finditer(text):
                    updates.append((match.start(), "current"))
                if updates:
                    status = max(updates)[1]
                elif rule == "historical experience" or PAST.search(clause):
                    status = "historical"
                elif re.search(rf"\b{SPEAKER}\s+(?:had|was|were)\b", clause, re.I):
                    status = "historical"
                elif re.search(r"\b(?:same|this|it|have|having|getting|seeing|am|are|can|fails|crashes|broken|currently|now)\b", clause, re.I):
                    status = "current"
                else:
                    status = "unclear"
                return Detection(rule, clause[:260], status)
    return None


# A person can post multiple comments. We count their account only once.
def is_eligible_author(author, creator):
    return bool(author and author.casefold() != (creator or "").casefold() and not BOT.search(author))


@dataclass(frozen=True)
class Report:
    author: str
    date: datetime
    evidence: Detection
    after_closure_days: int | None


@dataclass
class IssueResult:
    issue: object
    reports: list
    postclosure_reports: list


def latest_closure(issue):
    """Find the last recorded closure only if the issue is still closed."""
    if issue.state != State.closed:
        return None
    events = sorted((event for event in issue.events
                     if event.event_date and event.event_type in {"closed", "reopened"}),
                    key=lambda event: event.event_date)
    if not events or events[-1].event_type != "closed":
        return None
    return events[-1].event_date


def analyze_issue(issue):
    """Collect one report per outside account, keeping post-closure evidence.

    A later success does not erase a person's earlier report. The timestamp
    describes when the comment was POSTED, not necessarily when the bug occurred.
    """
    closure = latest_closure(issue)
    reports = {}
    after_closure = {}
    comments = sorted((event for event in issue.events
                       if event.event_type == "commented" and event.event_date),
                      key=lambda event: event.event_date)
    for event in comments:
        if not is_eligible_author(event.author, issue.creator):
            continue
        evidence = classify_comment(event.comment or "")
        if evidence is None:
            continue
        author = event.author.casefold()
        reports.setdefault(author, Report(event.author, event.event_date, evidence, None))
        if closure and event.event_date > closure:
            # Historical, current, and unclear first-hand reports all count.
            # We are screening comments posted after closure, not proving
            # the problem was unresolved at the time of the comment.
            after_closure.setdefault(
                author, Report(event.author, event.event_date, evidence,
                               (event.event_date - closure).days))
    return IssueResult(issue, list(reports.values()), list(after_closure.values()))


def equal_time_windows(delays, window_days=180):
    """Count account–issue reports in consecutive equal-length day intervals."""
    if not delays:
        return ["0–179"], [0]
    counts = [0] * (max(delays) // window_days + 1)
    for delay in delays:
        counts[delay // window_days] += 1
    labels = [f"{i * window_days}–{(i + 1) * window_days - 1}"
              for i in range(len(counts))]
    return labels, counts


class SameProblemReportsAnalysis:
    """Rank post-closure candidate issues and show two project-level charts."""

    def __init__(self):
        self.label = config.get_parameter("label")

    def run(self):
        issues = DataLoader().get_issues()
        if self.label:
            issues = [issue for issue in issues if self.label in issue.labels]
        if not issues:
            print(f"No issues found for label {self.label!r}.")
            return

        results = [analyze_issue(issue) for issue in issues]
        candidates = sorted((r for r in results if r.postclosure_reports),
                            key=lambda r: (-len(r.postclosure_reports), r.issue.number))
        repeated = [r for r in candidates if len(r.postclosure_reports) >= 2]
        three_plus = sum(len(r.postclosure_reports) >= 3 for r in repeated)

        print(f"\nSAME-PROBLEM REPORTS | {self.label or 'all labels'}")
        print("Question: Which closed issues received similar-problem reports after closure?")
        print("Method: Screen firsthand comments; count each outside account once per issue.")
        print(f"Analyzed {len(results):,} issues | {len(candidates)} flagged | "
              f"{len(repeated)} with 2+ reporters | {three_plus} with 3+")

        # List every distinct account and its first qualifying comment date.
        # One excerpt per issue keeps the report navigable without hiding evidence.
        print("\nMost independently reported (top 8):")
        chosen = (repeated or candidates)[:8]
        if not chosen:
            print("  None found.")
        for result in chosen:
            sample = result.postclosure_reports[0]
            title = shorten(result.issue.title or "(untitled)", width=76, placeholder="...")
            quote = shorten(" ".join(sample.evidence.excerpt.split()),
                            width=90, placeholder="...")
            closure = latest_closure(result.issue)
            print(f"  #{result.issue.number}: {title} "
                  f"({len(result.postclosure_reports)} accounts)")
            print(f"    Closed: {closure.date().isoformat()}")
            for report in result.postclosure_reports:
                print(f"      {report.author}: {report.date.date().isoformat()} "
                      f"(+{report.after_closure_days}d)")
            print(f'    Example ({sample.author}): "{quote}"')
            print(f"    {result.issue.url or '(no URL)'}")

        # Also show extreme delays, independently of the account-count ranking.
        print("\nLongest-delayed reports (top 5; different issues):")
        longest_per_issue = [
            (max(r.postclosure_reports, key=lambda report: report.after_closure_days), r)
            for r in candidates
        ]
        longest_per_issue.sort(
            key=lambda item: (-item[0].after_closure_days, item[1].issue.number)
        )
        if not longest_per_issue:
            print("  None found.")
        for report, result in longest_per_issue[:5]:
            title = shorten(result.issue.title or "(untitled)", width=76, placeholder="...")
            quote = shorten(" ".join(report.evidence.excerpt.split()),
                            width=90, placeholder="...")
            closure = latest_closure(result.issue)
            print(f"  #{result.issue.number}: {title}")
            print(f"    Closed: {closure.date().isoformat()} | "
                  f"{report.author}: {report.date.date().isoformat()} "
                  f"(+{report.after_closure_days}d)")
            print(f'    Example: "{quote}"')
            print(f"    {result.issue.url or '(no URL)'}")

        issue_counts = [len(r.postclosure_reports) for r in candidates]
        priority_counts = [sum(n == 1 for n in issue_counts),
                           sum(n == 2 for n in issue_counts),
                           sum(n >= 3 for n in issue_counts)]
        delays = [report.after_closure_days for r in candidates
                  for report in r.postclosure_reports]
        labels, time_counts = equal_time_windows(delays)
        print("\nNote: Matches need review, not proven bugs. Dates are comment dates, "
              "not necessarily incident dates.")

        # Panel 1: give maintainers a reason to prioritize corroborated issues.
        # Panel 2: equal 180-day intervals, so no open-ended last bucket.
        width = max(12, min(17, 8 + len(labels) * 0.48))
        fig, (priority_ax, timing_ax) = plt.subplots(1, 2, figsize=(width, 5.3))
        fig.suptitle("Potential Problem Reports After Issue Closure")

        bars = priority_ax.bar(["1", "2", "3+"], priority_counts)
        priority_ax.set(xlabel="Different reporting accounts per issue",
                        ylabel="Closed issues flagged",
                        title="How much independent evidence per issue?")
        priority_ax.bar_label(bars, padding=3)
        priority_ax.set_ylim(0, max(priority_counts + [1]) * 1.17)

        bars = timing_ax.bar(range(len(time_counts)), time_counts)
        timing_ax.set_xticks(range(len(labels)), labels, rotation=50, ha="right")
        timing_ax.set(xlabel="Days from closure to comment (180-day windows)",
                      ylabel="Account–issue reports",
                      title="When were reports posted?")
        timing_ax.bar_label(bars, padding=2, fontsize=8)
        timing_ax.set_ylim(0, max(time_counts + [1]) * 1.19)
        fig.text(0.5, 0.015,
                 "Candidate reports, not verified defects. Later fixes do not erase reports. "
                 "Issue observation periods differ.",
                 ha="center", fontsize=9)
        fig.tight_layout(rect=[0, 0.085, 1, 0.94])
        plt.show()
