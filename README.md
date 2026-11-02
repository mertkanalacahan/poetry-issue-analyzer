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

How long does a new issue wait before someone from the Poetry team replies to it? This feature measures the time from when each issue was created to the first comment from a developer, and finds the issues that never got a developer reply at all.

This is different from Feature 3 (stale open issues): Feature 3 looks at whether *anyone* is still active on *open* issues, while this feature looks at *developer* replies across *all* issues, open and closed.

### How it works

The data file has no field saying who is a maintainer, so developers are inferred from their actions. Anyone who labeled, closed, reopened, assigned, milestoned or locked an issue **that someone else created** counts as a developer. Actions on a person's own issue are ignored, because Poetry's issue templates add labels like `status/triage` under the creator's name and anyone can close their own issue. Counting those would wrongly mark hundreds of ordinary users as developers. Bot accounts are ignored too.

For each issue, the program finds the earliest comment by a developer other than the issue's creator and measures the wait. Issues without one are counted as never answered, and their waiting time is measured up to the dataset's snapshot date (the latest timestamp in the file) so results are the same no matter when the program is run.

### How to run it

```bash
python run.py --feature 2
```

To analyze only issues with a particular label:

```bash
python run.py --feature 2 --label kind/bug
```

Developers are always inferred from all issues, so filtering by label does not change who counts as a developer.

### What it shows

The console prints the number of developers found, how many issues were answered or never answered, the median, mean and 90th-percentile time to first reply, and the share answered within 1, 7 and 30 days. It also lists the slowest first replies, the open issues that have waited longest without a developer reply (measured up to the dataset's snapshot date), and which developers most often replied first, each with issue numbers and GitHub links. Closed issues are left out of the waiting list because they are no longer waiting for a reply; they are still counted in the "closed without a developer comment" total.

Two charts accompany the output: a distribution of time to first developer reply with a separate bar for issues that were never answered, and a per-label breakdown showing what share of each common label was answered within 7 days, answered later, or never answered.

### Limitations

Developer detection is an inference. A maintainer who never labels, closes or assigns other people's issues will not be detected, and an outside contributor with triage access will be counted as a developer. Replies made somewhere else, such as in a pull request or on Discord, are not visible in this data. Issues closed without a comment (for example as duplicates) count as never answered, even though a developer did act on them.