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

## Feature 3: Stale Open Issues

An open issue that nobody has touched in months is a different problem depending on how it
got there. This feature separates issues that were **never answered** at all from ones that
had a real discussion and then **went quiet**, and compares those two outcomes across labels.

### How it works

For every open issue, the program finds the most recent non-bot event and measures how long
ago that was. Bot activity is ignored on purpose: a stale-bot reminder makes a dead issue look
alive, which is exactly what we are trying to detect.

Two clocks are kept, because "somebody touched this issue" and "somebody answered this issue"
are different things. The **substantive** clock moves only on events where a person engaged:
a comment, a close, a reopen, an assignment, a retitle. The **touch** clock moves on any
non-bot event at all, metadata included. Both start at the opening date, since filing the
issue is itself somebody doing something.

The substantive clock is the default, and the difference is not academic. In this dataset one
maintainer relabelled 83 open issues on 2024-10-13, a week before the data was exported. On
the touch clock all 83 look freshly active; on the substantive clock 54 of them are still
silent, several for over a year. Counting that sweep as attention takes the stale share from
61% down to 26% and the never-answered count from 21 down to 3 - so the looser reading does
not merely blur the result, it reverses it.

Time is measured against the **dataset's own snapshot date** (the latest timestamp anywhere in
the data file), not against today's date. The data file is a frozen export, so using today
would mark every open issue stale and make the `--days` input meaningless.

Issues silent for at least N days are then split into two groups: those where nobody other
than the author ever commented, and those that did get replies before going quiet. Issues with
recent activity are kept as a comparison group so the per-label shares mean something.

### How to run it

```bash
python run.py --feature 3
```

The inactivity window defaults to 90 days. To choose your own:

```bash
python run.py --feature 3 --days 180
```

An optional label filter narrows the analysis to one part of the project:

```bash
python run.py --feature 3 --days 180 --label kind/bug
```

To judge silence the way GitHub's own "updated" timestamp does, counting every non-bot event
including labels and mentions, switch clocks:

```bash
python run.py --feature 3 --activity any
```

### What it shows

The console prints the snapshot date used, which clock is in force, how many open issues are
stale, and the split between never-answered and went-quiet. It then reports how many stale
issues were touched inside the window by bookkeeping alone - the ones that would read as
active on the looser clock - and names the days those touches cluster on, which is what bulk
triage looks like from the outside. It then lists the never-answered share for the busiest
labels, the longest-ignored issues, and the longest-abandoned discussions, each with issue
numbers, dates, and GitHub links. It also counts "monologues" - issues where the author kept
commenting and nobody ever replied.

Two charts accompany the output: a per-label breakdown shown as shares rather than raw counts,
so a label with 400 open issues can be compared fairly against one with 30, and a distribution
of how long the silence has lasted for each of the two stale groups.

### Limitations

Silence is not the same as neglect. Some issues need no reply, some are tracked elsewhere, and
some were quietly fixed without anyone closing them. The results point at where attention has
not been going, not at who is at fault.

Which events count as substantive is a judgement call, not a fact. A retitle is treated as
engagement and a label is not, and reasonable people would draw that line elsewhere; both
readings are available through `--activity` so the choice is visible rather than buried.
The bot list covers the common automation accounts and may miss a project-specific one - and
note that a human doing bulk automation-like work, as happened here on 2024-10-13, is not a
bot and should not be filtered as one. Separating the two clocks is what handles that case.
