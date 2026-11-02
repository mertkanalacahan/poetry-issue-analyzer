# Poetry Issue Analyzer

A Python application developed for ENPM611 Software Engineering to analyze GitHub issue activity from the [Poetry project](https://github.com/python-poetry/poetry/issues). It uses the issue and event dataset provided for the course to investigate problems that may persist after closure, developer response times, and inactivity among open issues.

The application provides three analyses with console summaries and Matplotlib visualizations. Results describe the provided dataset, not live GitHub activity.

## Setup

### Requirements

- Python 3.11 or newer
- Dependencies listed in `requirements.txt` (`python-dateutil`, `pandas`, and `matplotlib`)
- The Poetry issue dataset supplied through the course's Canvas assignment

Clone the repository and open its directory:

```bash
git clone https://github.com/mertkanalacahan/poetry-issue-analyzer.git
cd poetry-issue-analyzer
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it in **Windows PowerShell**:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or on **macOS/Linux**:

```bash
source .venv/bin/activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

### Configure the dataset

Download the JSON dataset from the project assignment in Canvas. The dataset is not included in this repository.

Set `ENPM611_PROJECT_DATA_PATH` in `config.json` to the location of the downloaded file:

```json
{
  "ENPM611_PROJECT_DATA_PATH": "path/to/poetry_issues_all.json"
}
```

Alternatively, set the `ENPM611_PROJECT_DATA_PATH` environment variable; it takes precedence over `config.json`. For example, in Windows PowerShell:

```powershell
$env:ENPM611_PROJECT_DATA_PATH = "C:\path\to\poetry_issues_all.json"
```

Use the actual path on your machine. Do not commit a personal dataset path or the dataset itself.

### Run the analyses

From the repository root, with the virtual environment activated:

```bash
python run.py --feature 1
python run.py --feature 2
python run.py --feature 3
```

Optional arguments for each feature are documented below. The original template example is also available with `python run.py --feature 0`.

## Feature 1: Same-Problem Reports

**Question:** Which closed issues continue to receive reports of the same problem, and which deserve another look from maintainers?

### How it works

The analysis examines issue comments for phrases suggesting that the commenter personally encountered the problem, such as “same issue here” or “I'm getting this error too.” It uses text-matching rules rather than AI and attempts to exclude questions, quoted text, bots, and comments that do not describe firsthand experience.

It identifies reports made after each issue's most recent closure and counts each reporting account at most once per issue. Issues are ranked by the number of distinct reporting accounts.

### How to run it

Analyze all issues:

```bash
python run.py --feature 1
```

Filter to issues with a particular label:

```bash
python run.py --feature 1 --label kind/bug
```

### Output

The console identifies closed issues with independent reports after closure, including usernames, dates, example comments, and links to the original GitHub issues. It also highlights reports posted unusually long after closure.

Two charts show the number of independent reporting accounts per flagged issue and the timing of reports after closure.

### Limitations

Text matching can miss unusual descriptions or incorrectly classify unrelated comments as reports. A comment posted after closure does not prove that the problem first occurred after closure, or that the bug is still present. The results identify issues worth investigating rather than confirmed unresolved defects.

## Feature 2: Developer Response Time

**Question:** How long do Poetry issues take to receive their first developer reply?

### How it works

The dataset has no explicit maintainer field, so the analysis infers developer accounts from administrative activity on issues opened by other people. This includes actions such as labeling, assigning, closing, reopening, or locking issues. Accounts are inferred from the full dataset even when a label filter is applied.

For each issue, the analysis finds the earliest comment by an inferred developer other than the issue creator and measures the elapsed time from issue creation. Issues without a detected developer reply are counted separately. For open issues still awaiting one, elapsed time is measured against the dataset's snapshot date rather than the current date.

### How to run it

Analyze all issues:

```bash
python run.py --feature 2
```

Filter to a particular label:

```bash
python run.py --feature 2 --label kind/bug
```

### Output

The console reports the median, mean, and 90th-percentile response times for issues with detected developer replies; the share of those issues answered within a day, week, or month; and the number of issues without a detected developer reply. It also lists the slowest first replies, open issues still waiting as of the dataset snapshot, and developers who replied first most often.

Two charts show the distribution of first-reply times, including a separate category for issues without a detected reply, and the fast, slow, and never-replied breakdown for the busiest labels.

### Limitations

Developer status is inferred from issue activity, so the analysis may classify an active triager as a developer or miss a maintainer who did not perform those actions. Replies outside the issue comments, such as in pull requests or chat, are not represented. Therefore, a missing detected reply does not necessarily mean nobody responded to or resolved the issue.

## Feature 3: Stale Open Issues

**Question:** Which open issues have gone inactive, and were they never answered or did they become quiet after discussion?

### How it works

The analysis measures inactivity for open issues against the dataset's snapshot date, excluding bot events. It distinguishes between issues that received no response from another person and issues that received discussion but later became inactive.

Two activity definitions are available. The default **substantive** clock is updated by human engagement such as comments, closing, reopening, assignment, or retitling. The **any** activity clock also counts other non-bot events, including metadata changes. This distinction prevents administrative activity alone from automatically being treated as renewed discussion.

### How to run it

Use the default inactivity threshold of 90 days:

```bash
python run.py --feature 3
```

Change the threshold and filter by label:

```bash
python run.py --feature 3 --days 180 --label kind/bug
```

Count every non-bot event rather than substantive activity only:

```bash
python run.py --feature 3 --activity any
```

### Output

The console shows the dataset snapshot date, selected activity definition, number of stale open issues, and the never-answered versus went-quiet breakdown. It also identifies issues affected by administrative activity, compares the never-answered share across labels, and lists the longest-inactive issues and issues without replies from another person.

Two charts compare stale-issue groups across labels using proportions and show how long the issues in each stale group have been inactive.

### Limitations

Inactivity does not necessarily indicate neglect. Some issues require no reply, are addressed elsewhere, or are fixed without being closed. The choice of events that count as meaningful activity affects the results; the `--activity` option allows both interpretations to be examined.

## Team contributions

- **@mertkanalacahan** — Implemented Feature 1 (Same-Problem Reports) and consolidated the README.
- **@vchinnad-md** — Implemented Feature 2 (Developer Response Time) and its tests.
- **@goku007xx** — Implemented Feature 3 (Stale Open Issues) and its tests.

All three team members participated in code review, with each reviewing another member's pull request.
