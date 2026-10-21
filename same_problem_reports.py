"""Find evidence of users independently reporting the same issue.

This is a deliberately conservative, inspectable text classifier. It does NOT
prove that two users share a root cause or that a closed issue remains broken.
"""

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Optional

import matplotlib.pyplot as plt

import config
from data_loader import DataLoader
from model import State

# Each rule requires a personal/experiential statement. Matches are presented
# as evidence for human review, never as a proven count of affected users.
REPORT_RULES = [
    (
        "same-problem",
        re.compile(
            r"\b(?:i|we)(?:'m|'re|'ve| am| are| have| had| was| were)?\s*"
            r"(?:also|still|just|currently|recently|now|too|exactly|indeed|personally|\s){0,4}\s*"
            r"(?:have|had|hit|see|saw|get|got|face|faced|encounter|encountered|experience|experienced|"
            r"am having|are having|am seeing|are seeing|am getting|are getting|am experiencing|are experiencing|"
            r"having|seeing|getting|experiencing|running into|ran into|struggling with)\s+"
            r"(?:the|a|this|that|exactly|very|same|identical|similar|\s){0,5}\s*"
            r"(?:same|identical|similar)\s+(?:issue|problem|bug|error|behavior|behaviour|failure|thing)\b",
            re.I,
        ),
    ),
    (
        "same-problem",
        re.compile(
            r"\b(?:i|we)(?:'m|'re|'ve| am| are| have| had)?\s*"
            r"(?:also|still|just|currently|recently|now|too|\s){0,4}\s*"
            r"(?:have|had|hit|see|saw|get|got|face|faced|encounter|encountered|experience|experienced|"
            r"am having|are having|am seeing|are seeing|am getting|are getting|am experiencing|are experiencing|"
            r"having|seeing|getting|experiencing|running into|ran into|struggling with)\s+"
            r"(?:(?:this|that)\s+(?:issue|problem|bug|error|behavior|behaviour|failure|exception|traceback|too)|"
            r"(?:this|that|it)\s+as well|it\s+too)\b",
            re.I,
        ),
    ),
    (
        "same-problem",
        re.compile(
            r"^(?:same (?:issue|problem|bug|error|behavior|behaviour|thing)(?: (?:here|for me|on my end|too))?|"
            r"same here|same for me|similar (?:issue|problem) (?:here|for me)|"
            r"having the same (?:issue|problem|bug|error)|"
            r"(?:this|it) (?:also |still )?happens (?:to|for) me)\b",
            re.I,
        ),
    ),
    (
        "same-problem",
        re.compile(
            r"\b(?:i|we)(?:'ve| have| had| am| are| 'm| 're)?\s*"
            r"(?:also|still|recently|currently|just|\s){0,4}\s*"
            r"(?:got|have|had|am having|are having|having|seeing|getting|experienced|experiencing|"
            r"notic(?:ed|ing)|suffer(?:ed|ing) from)\s+(?:the |a |this |that )?"
            r"(?:same|similar|identical)\s+(?:issue|problem|bug|error|behavio(?:r|ur)|failure)\b",
            re.I,
        ),
    ),
    (
        "direct-experience",
        re.compile(
            r"\b(?:we(?:'ve| have)?\s+also\s+(?:started\s+)?(?:hitting|seeing|getting|experiencing|having)\s+this|"
            r"(?:this|it)\s+(?:is|was|keeps)\s+happening\s+(?:to me|to us|on my|for me)|"
            r"(?:this|it)\s+(?:happened|happens)\s+to me|"
            r"i\s+(?:just|also|recently)?\s*(?:came across|ran into|hit)\s+this\s+(?:myself|too)|"
            r"(?:i|we)\s+(?:also\s+)?started\s+(?:hitting|seeing)\s+this)\b",
            re.I,
        ),
    ),
    (
        "reproduction",
        re.compile(
            r"\b(?:i|we)\s+(?:can|could|was able to|am able to|have|had|still can)\s+"
            r"(?:also\s+)?(?:reproduce|reproduced|replicate|replicated|confirm)\s+"
            r"(?:this|it|the|same|issue|problem|bug|error)\b",
            re.I,
        ),
    ),
    ("reproduction", re.compile(r"^reproducible\s+(?:with|on|using)\b", re.I)),
    (
        "direct-experience",
        re.compile(
            r"^(?:this is happening\b|just came across this myself\b|"
            r"(?:i|we) (?:just |also |recently )?came across this myself\b)",
            re.I,
        ),
    ),
    (
        "same-problem",
        re.compile(
            r"\b(?:i|we)(?:'m|'re| am| are| have been| were)?\s+"
            r"(?:also\s+)?affected\b",
            re.I,
        ),
    ),
    (
        "reproduction",
        re.compile(
            r"\b(?:this|it|the (?:issue|bug|problem))\s+"
            r"(?:also\s+)?(?:reproduces|happens|occurs|persists|still happens)\s+"
            r"(?:reliably|consistently|every time|on|for|when|with|here|to me|for me)\b",
            re.I,
        ),
    ),
    (
        "direct-experience",
        re.compile(
            r"\b(?:i|we)(?:'m|'re| am| are| have been| had been| was| were)?\s*"
            r"(?:also|still|currently|now|recently|just|\s){0,3}\s*"
            r"(?:seeing|getting|having|experiencing|facing|hitting|encountering|running into)\s+"
            r"(?:this|that|it|the same|a similar)(?:\s+(?:error|failure|issue|problem|behavior|behaviour))?\b",
            re.I,
        ),
    ),
    (
        "persistent-problem",
        re.compile(
            r"\b(?:still (?:broken|failing|fails|doesn't work|does not work|happening|reproducible)|"
            r"still (?:not working|seeing this|having this|getting this)|"
            r"(?:it|this) (?:still|continues? to) (?:fail|fails|happen|reproduce|occur|break)|"
            r"(?:same|similar) (?:issue|problem|error) (?:persists|continues))\b",
            re.I,
        ),
    ),
    (
        "firsthand-error",
        re.compile(
            r"\b(?:i|we)(?:'m|'re| am| are)?\s*"
            r"(?:also|still|just|\s){0,3}\s*"
            r"(?:get|got|see|saw|hit|encountered|encounter|am getting|are getting|getting|seeing)\s+"
            r"(?:the|this|that|same)\s+(?:exact\s+)?(?:error|traceback|exception|failure)\b",
            re.I,
        ),
    ),
    (
        "firsthand-error",
        re.compile(
            # Any named program/command or generic tool reference; no project names.
            r"\b(?:[A-Za-z][A-Za-z0-9_.+-]{1,49}|(?:the|this|my)\s+(?:app|application|tool|command|"
            r"program|package|library|plugin|client|service))\s+"
            r"(?:still\s+)?(?:fails|failed|breaks|broke|crashes|crashed)\s+"
            r"(?:for me|on my (?:machine|computer|system|setup)|on our (?:machines|systems))\b",
            re.I,
        ),
    ),
]

# Statements clearly describing fixed, historical or hypothetical events are
# not treated as evidence of a problem *continuing* after issue closure.
FIXED = re.compile(
    r"\b(?:fixed (?:it|this|the issue|the problem|my issue)|"
    r"(?:it|this|the issue|the problem) (?:is|was|has been|got) (?:fixed|resolved)|"
    r"(?:i|we) (?:fixed|resolved) (?:it|this)|"
    r"(?:it|this) (?:works|worked) (?:now|after)|"
    r"(?:no longer|not anymore) (?:happens|fails|broken|an issue)|"
    r"(?:upgrad(?:ed|ing)|updat(?:e|ed|ing)|downgrad(?:ed|ing)|reinstall(?:ed|ing)|changing|switching)\b.{0,75}\b"
    r"(?:fixed|resolved|solved|works now|worked|went away))\b",
    re.I,
)

NOT_A_REPORT = re.compile(
    r"\b(?:cannot|can't|can not|couldn't|could not|unable to) (?:reproduce|replicate)|"
    r"\b(?:i|we) (?:don't|do not|didn't|did not|haven't|have not) (?:have|see|experience|get|reproduce)|"
    r"\bnot (?:actually )?(?:the )?same (?:issue|problem|error|thing)|"
    r"\b(?:i['’]m|i am|we['’]re|we are) not (?:seeing|having|getting|experiencing|hitting|reproducing)|"
    r"\bno longer (?:have|see|experience|get)|"
    r"\b(?:if|whether) (?:anyone|somebody|someone|you) (?:can|could|is|has|have) (?:reproduce|experiencing|seeing)|"
    r"\b(?:can|could) (?:anyone|someone|somebody|you) (?:reproduce|confirm)|"
    r"\b(?:not sure|unsure|wondering) (?:if|whether) (?:this|it|the issue) (?:is|was) the same\b",
    re.I,
)

BOT_NAME = re.compile(
    r"(?:\[bot\]$|^dependabot(?:\[bot\])?$|^github-actions(?:\[bot\])?$|^renovate(?:\[bot\])?$|^stale(?:\[bot\])?$)",
    re.I,
)
FENCE = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~")
INLINE_CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r"^\s*(?:>|&gt;)\s?.*$", re.M)
HTML_COMMENT = re.compile(r"<!--[\s\S]*?-->")
# On DATE, USER wrote: introduces quoted material from an email thread.
EMAIL_QUOTE = re.compile(r"(?im)^on\s+.{8,140}\s+wrote:\s*$")
WORD_RE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class Detection:
    rule: str
    excerpt: str
    status: str  # 'current', 'historical', or 'unclear'


def clean_comment(comment: str) -> str:
    """Remove quoted/code material so that quoted reports aren't credited to author."""
    if not comment:
        return ""
    text = HTML_COMMENT.sub(" ", comment)
    text = FENCE.sub(" ", text)
    text = INLINE_CODE.sub(" ", text)
    text = QUOTED.sub(" ", text)
    text = EMAIL_QUOTE.split(text, 1)[0]
    return text


def classify_comment(comment: str) -> Optional[Detection]:
    """Find first-hand evidence; distinguish ongoing from historical reports.

    Sentence/clause-level checks avoid rejecting an entire long comment because
    one unrelated sentence says 'cannot reproduce'. They are still heuristics.
    """
    text = clean_comment(comment)
    if not text.strip():
        return None
    sentences = [part.strip() for part in WORD_RE.split(text) if part.strip()]
    for sentence in sentences:
        # A report followed by a fix in the same sentence is historical evidence.
        fixed_in_sentence = bool(FIXED.search(sentence))
        clauses = re.split(r"(?i)\s*;\s*|\s*,?\s+but\s+|\s+however\s*,?\s*", sentence)
        for clause in clauses:
            clause = clause.strip()
            # Questions, hypotheticals, and suggested actions aren't reports.
            if (
                not clause
                or (
                    sentence.endswith("?")
                    and re.match(
                        r"(?i)^(?:anyone|does|did|can|could|would|what|why|how|is|are|do)\b",
                        clause,
                    )
                )
                or re.match(r"(?i)^(?:if|assuming|suppose|imagine)\b", clause)
                or re.search(
                    r"\b(?:if|suppose|assuming|imagine)\s+(?:i|we)\b", clause, re.I
                )
                or clause.lower().startswith(
                    (
                        "does anyone",
                        "anyone else",
                        "is anyone",
                        "can anyone",
                        "could anyone",
                    )
                )
                or NOT_A_REPORT.search(clause)
                or re.search(
                    r"\b(?:i|we)\s+can\s+confirm\s+(?:this|it)\s+(?:is|was|has been)\s+(?:fixed|resolved|working)",
                    clause,
                    re.I,
                )
            ):
                continue
            for rule, pattern in REPORT_RULES:
                match = pattern.search(clause)
                if not match:
                    continue
                # A moderator classifying a duplicate isn't necessarily affected.
                if (
                    rule == "same-problem"
                    and re.search(
                        r"\bsame (?:issue|problem|bug|error) as (?:#\d+|https?://|another issue|this issue)",
                        clause,
                        re.I,
                    )
                    and not re.search(
                        r"\b(?:for me|i (?:have|had|am)|we (?:have|had|are))\b",
                        clause,
                        re.I,
                    )
                ):
                    continue
                historical = fixed_in_sentence or bool(
                    re.search(
                        r"\b(?:used to|previously|back then|last year|in the past)\b|"
                        r"\b(?:i|we) (?:had|was having|were having|was getting|were getting|"
                        r"was seeing|were seeing|previously had|saw|experienced)\b",
                        clause,
                        re.I,
                    )
                )
                # A later sentence explaining that an upgrade or fix worked
                # makes this report historical, unless they explicitly say it
                # is still happening afterward.
                remaining = text[text.find(sentence) + len(sentence) :]
                if FIXED.search(remaining) and not re.search(
                    r"\b(?:still (?:broken|happening|failing|getting|seeing|having)|"
                    r"(?:not|never) fixed|problem (?:persists|remains))\b",
                    remaining,
                    re.I,
                ):
                    historical = True
                if historical:
                    status = "historical"
                elif re.search(
                    r"\b(?:still|currently|now|again|keeps?|continue|reproduc(?:es|ible)|"
                    r"happening|failing|fails|crashes|crashing|breaks|getting|seeing|have|having|am|are|"
                    r"can reproduce|on my (?:machine|computer|system|setup))\b",
                    clause,
                    re.I,
                ) or re.search(r"\bsame (?:issue|problem|here|for me)\b", clause, re.I):
                    status = "current"
                else:
                    status = "unclear"
                return Detection(rule, clause[:260], status)
    return None


def is_eligible_author(author: str, creator: str) -> bool:
    return bool(
        author
        and not BOT_NAME.search(author)
        and author.casefold() != (creator or "").casefold()
    )


@dataclass(frozen=True)
class Report:
    author: str
    date: Optional[datetime]
    evidence: Detection
    after_closure_days: Optional[int]


@dataclass
class IssueResult:
    issue: object
    reports: list
    postclosure_reports: list


def latest_closure(issue) -> Optional[datetime]:
    """Return last dated closure only for an issue closed in the snapshot.

    If a reopen occurs after that closure, we cannot call later comments
    post-closure reports. Sorting also guards against non-chronological JSON.
    """
    if issue.state != State.closed:
        return None
    events = sorted(
        (
            e
            for e in issue.events
            if e.event_date and e.event_type in {"closed", "reopened"}
        ),
        key=lambda event: event.event_date,
    )
    if not events or events[-1].event_type != "closed":
        return None
    return events[-1].event_date


def analyze_issue(issue) -> IssueResult:
    closure = latest_closure(issue)
    reports_by_author = {}
    postclosure_by_author = {}
    comments = sorted(
        (e for e in issue.events if e.event_type == "commented" and e.event_date),
        key=lambda e: e.event_date,
    )
    for event in comments:
        if not is_eligible_author(event.author, issue.creator):
            continue
        detection = classify_comment(event.comment or "")
        if detection is None:
            continue
        author_id = event.author.casefold()
        if author_id not in reports_by_author:
            reports_by_author[author_id] = Report(
                event.author, event.event_date, detection, None
            )
        if closure and event.event_date > closure and detection.status == "current":
            days = (event.event_date - closure).days
            # Distinct people, not repeat comments. Keep earliest qualifying report.
            if author_id not in postclosure_by_author:
                postclosure_by_author[author_id] = Report(
                    event.author, event.event_date, detection, days
                )
    return IssueResult(
        issue, list(reports_by_author.values()), list(postclosure_by_author.values())
    )


class SameProblemReportsAnalysis:
    """Issue-wide corroboration and evidence after the final recorded closure."""

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
        corroborated = sorted(
            (r for r in results if len(r.reports) >= 2),
            key=lambda r: (-len(r.reports), r.issue.number),
        )
        closed_candidates = sorted(
            (r for r in results if r.postclosure_reports),
            key=lambda r: (-len(r.postclosure_reports), r.issue.number),
        )
        print(
            f"Analyzed {len(results)} issues"
            + (f" labeled {self.label}" if self.label else "")
            + "."
        )
        print(f"Issues with 2+ distinct reporting commenters: {len(corroborated)}")
        print(
            f"Closed issues with 1+ possible post-closure report: {len(closed_candidates)}"
        )
        print("\nPossible post-closure reports (review the evidence):")
        for r in closed_candidates[:12]:
            print(
                f"  #{r.issue.number}: {len(r.postclosure_reports)} reporter(s) "
                f"{r.issue.url or ''}"
            )
            for report in r.postclosure_reports[:2]:
                print(
                    f"     {report.author}, {report.after_closure_days} days after closure, "
                    f"{report.evidence.status}: {report.evidence.excerpt[:140]}"
                )
        # How long after a recorded closure are similar experiences reported?
        delays = [
            report.after_closure_days
            for r in closed_candidates
            for report in r.postclosure_reports
        ]
        delayed = [
            sum(days <= 30 for days in delays),
            sum(30 < days <= 180 for days in delays),
            sum(180 < days <= 365 for days in delays),
            sum(days > 365 for days in delays),
        ]
        fig, ax = plt.subplots(figsize=(8, 4.8))
        ax.bar(["0–30", "31–180", "181–365", "366+"], delayed)
        ax.set(
            xlabel="Days after final recorded closure",
            ylabel="Detected reporting accounts",
            title="When do similar-problem reports appear after closure?",
        )
        fig.text(
            0.5,
            0.02,
            "Based on the loaded issue dataset. Signals for review, not verified unresolved bugs.",
            ha="center",
            fontsize=9,
        )
        fig.tight_layout(rect=[0, 0.07, 1, 1])
        plt.show()
