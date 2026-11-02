# ENPM611 Project Application Template

This is the template for the ENPM611 class project. Use this template in conjunction with the provided data to implement an application that analyzes GitHub issues for the [poetry](https://github.com/python-poetry/poetry/issues) Open Source project and generates interesting insights.

This application template implements some of the basic functions:

- `data_loader.py`: Utility to load the issues from the provided data file and returns the issues in a runtime data structure (e.g., objects)
- `model.py`: Implements the data model into which the data file is loaded. The data can then be accessed by accessing the fields of objects.
- `config.py`: Supports configuring the application via the `config.json` file. You can add other configuration paramters to the `config.json` file.
- `run.py`: This is the module that will be invoked to run your application. Based on the `--feature` command line parameter, one of the three analyses you implemented will be run. You need to extend this module to call other analyses.

With the utility functions provided, you should focus on implementing creative analyses that generate intersting and insightful insights.

In addition to the utility functions, an example analysis has also been implemented in `example_analysis.py`. It illustrates how to use the provided utility functions and how to produce output.

## Setup

To get started, your team should create a fork of this repository. Then, every team member should clone your repository to their local computer. 


### Install dependencies

In the root directory of the application, create a virtual environment, activate that environment, and install the dependencies like so:

```
pip install -r requirements.txt
```

### Download and configure the data file

Download the data file (in `json` format) from the project assignment in Canvas and update the `config.json` with the path to the file. Note, you can also specify an environment variable by the same name as the config setting (`ENPM611_PROJECT_DATA_PATH`) to avoid committing your personal path to the repository.


### Run an analysis

With everything set up, you should be able to run the existing example analysis:

```
python run.py --feature 0
```

That will output basic information about the issues to the command line.


## VSCode run configuration

To make the application easier to debug, runtime configurations are provided to run each of the analyses you are implementing. When you click on the run button in the left-hand side toolbar, you can select to run one of the three analyses or run the file you are currently viewing. That makes debugging a little easier. This run configuration is specified in the `.vscode/launch.json` if you want to modify it.

The `.vscode/settings.json` also customizes the VSCode user interface sligthly to make navigation and debugging easier. But that is a matter of preference and can be turned off by removing the appropriate settings.

## Feature 1: Same-Problem Reports

When a GitHub issue is closed, that doesn't necessarily mean people have stopped encountering the problem. This feature looks for closed issues where other users have continued reporting similar problems, helping maintainers identify issues that might deserve another look.

### How it works

The program reads issue comments and looks for phrases that suggest someone personally experienced the problem, such as "same issue here" or "I'm getting this error too". It uses text-matching rules rather than AI and tries to ignore questions, quoted text, bots, and other comments that aren't actual reports.

It then checks which reports were posted after the issue's last closure and counts each reporting account only once per issue.

### How to run it

```bash
python run.py --feature 1
```

To analyze only issues with a particular label:

```bash
python run.py --feature 1 --label kind/bug
```

### What it shows

The console lists the issues with the most independent reports after closure, along with usernames, dates, example comments, and GitHub links. It also highlights unusually late reports.

Two charts show how many reporting accounts each flagged issue has and how long after closure the reports were posted.

### Limitations

The program looks for common ways people describe problems, so it can miss unusual wording or mistake unrelated comments for genuine reports. A comment posted after closure also doesn't necessarily mean the problem first occurred after closure.

The results are meant to help maintainers find issues worth investigating, not automatically determine whether a bug is still present.

## Feature 2: Developer Response Time

How long does an issue wait before a developer answers it? The data file has no maintainer field, so this feature infers developers from their behaviour and measures the gap between opening an issue and their first comment.

### How it works

A developer is any account that labeled, closed, reopened, assigned or locked an issue someone else created. Actions on one's own issue are ignored, because issue templates add labels under the creator's name and anyone can close their own report. Developers are inferred from the whole dataset, so a `--label` filter cannot hide them.

For each issue the program takes the earliest comment by a developer other than the creator. Issues that never received one are measured up to the dataset's snapshot date rather than today, so results do not drift as time passes.

### How to run it

```bash
python run.py --feature 2
```

To analyze only issues with a particular label:

```bash
python run.py --feature 2 --label kind/bug
```

### What it shows

The console reports the median, mean and 90th-percentile wait, the share answered within a day, a week and a month, how many never-answered issues are still open, the slowest first replies, and who replies first most often.

Two charts show the distribution of reply times with a separate bar for issues that never got one, and the fast, slow and never-replied split across the busiest labels.

### Limitations

Developer status is inferred from triage activity, not read from the data, so the list can include an active triager or miss a quiet maintainer. Replies made in pull requests or chat are invisible here, so an issue can look ignored when it was not.

## Feature 3: Stale Open Issues

An open issue that nobody has touched in months is a different problem depending on how it got there. This feature separates issues that were **never answered** at all from ones that had a real discussion and then **went quiet**, and compares those two outcomes across labels.

### How it works

For every open issue the program finds the most recent non-bot event and measures how long ago it was. Bot activity is ignored on purpose: a stale-bot reminder makes a dead issue look alive.

Two clocks are kept. The **substantive** clock, the default, moves only when a person engaged: a comment, close, reopen, assignment or retitle. The **touch** clock moves on any non-bot event, metadata included. The gap matters: one maintainer relabelled 83 open issues shortly before the export, and counting that sweep as attention moves the stale share from 61% to 26%. Time is measured against the dataset's snapshot date, because the export is frozen.

### How to run it

```bash
python run.py --feature 3
```

The window defaults to 90 days; an optional label filter narrows it:

```bash
python run.py --feature 3 --days 180 --label kind/bug
```

To count every non-bot event instead, switch clocks:

```bash
python run.py --feature 3 --activity any
```

### What it shows

The console prints the snapshot date, the active clock, the stale count, and the never-answered versus went-quiet split. It then names the issues touched by bookkeeping alone, the never-answered share per label, the longest-ignored issues, and "monologues" where nobody ever replied.

Two charts show the per-label breakdown as shares rather than raw counts, and how long the silence has lasted for each stale group.

### Limitations

Silence is not the same as neglect. Some issues need no reply, some are tracked elsewhere, and some were quietly fixed without being closed. Which events count as substantive is a judgement call, so both readings stay available through `--activity`.
