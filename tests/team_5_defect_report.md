# Team 5 Defect Report: Poetry Issue Analyzer

**Repository tested:** https://github.com/mertkanalacahan/poetry-issue-analyzer

**How to run the suite (from the project root):**

```bash
python -m unittest discover
```

Each defect below is exposed by exactly one failing test in `tests/`. The suite ran 183 tests with 7 failures, one per defect. The full output is in `team_5_test_failures.txt`.

**Common preconditions:** Python 3.11+, dependencies from `requirements.txt` installed, commands run from the project root. Unit tests build `Issue`/`Event` objects in memory with `tests/helpers.py`. The end-to-end tests run `run.py` in a subprocess against a small temporary JSON file. Neither needs the course dataset.

| ID | Title | Module / feature | Severity |
|----|-------|------------------|----------|
| D1 | Reply posted after closure is counted as the first developer reply | `developer_response_time.py` (Feature 2) | High |
| D2 | Mixed timezone-aware and naive dates crash Feature 1 | `same_problem_reports.py` (Feature 1) | Medium |
| D3 | `--label` crashes Feature 1 when an issue's labels are `null` | `same_problem_reports.py` (Feature 1) | Medium |
| D4 | Missing data file ends in a raw traceback | `run.py` / `data_loader.py` | Medium |
| D5 | Invalid `--feature` value exits with status 0 and a misleading message | `run.py` | Low |
| D6 | Mode name in the README (`substantive`) is rejected by the program | `stale_issues_analysis.py` / `run.py` (Feature 3) | Low |
| D7 | "+1"-style same-problem comments are not detected | `same_problem_reports.py` (Feature 1) | Low |

---

## D1. A reply posted after the issue was closed counts as the "first developer reply"

- **Affected module / feature:** `developer_response_time.py`, `first_developer_reply()` / `analyze_issue()` (Feature 2: developer response time)
- **Associated test case:** `tests/test_team5_developer_response_time.py` → `AnalyzeIssueTests.test_reply_after_issue_was_closed_is_not_a_first_response`
- **Preconditions / test data:**
  - Issue created 2024-01-01 by `reporter`, state `closed`
  - Event 1: `closed` on 2024-01-02 by `reporter`
  - Event 2: `commented` on 2025-01-01 by `maint`, where `maint` is in the developer set
- **Steps to reproduce:**
  1. Build the issue above.
  2. Call `analyze_issue(issue, {"maint"}, snapshot)`.
  3. Inspect `record.status` and `record.days`.
- **Expected result:** The issue was closed before any developer replied, so a comment one year later is not a response to an open issue. The issue should not be reported as `answered` after a 366-day wait.
- **Actual result:** `record.status == "answered"` with `record.days == 366`. `first_developer_reply()` considers every developer comment and never checks the closing date. These post-closure comments inflate the "slowest first replies" list and the reported mean and 90th percentile.
- **Relevant failure output:**
  ```
  FAIL: test_reply_after_issue_was_closed_is_not_a_first_response
    File "tests/test_team5_developer_response_time.py", line 55, in test_reply_after_issue_was_closed_is_not_a_first_response
  AssertionError: 'answered' == 'answered' : a reply posted after closure was counted as a 366-day first response
  ```

---

## D2. Feature 1 crashes when timezone-aware and naive dates are mixed

- **Affected module / feature:** `same_problem_reports.py`, `analyze_issue()` line 220 (Feature 1: same-problem reports)
- **Associated test case:** `tests/test_team5_same_problem_reports.py` → `AnalyzeIssueTests.test_mixed_naive_and_aware_dates_do_not_crash`
- **Preconditions / test data:**
  - Closed issue with a `closed` event at `2024-01-02T00:00:00+00:00` (timezone-aware)
  - A later `commented` event by `bob` dated `datetime(2024, 2, 1)` with no timezone, text `"Same here."`
- **Steps to reproduce:**
  1. Build the issue above (or, in a JSON data file, give one comment a date without an offset such as `"2024-02-01T00:00:00"`).
  2. Call `same_problem_reports.analyze_issue(issue)`, or run `python run.py --feature 1`.
- **Expected result:** Dates are normalised before comparison, as Features 2 and 3 already do with `as_utc()`, and the comment is analysed normally.
- **Actual result:** `TypeError: can't compare offset-naive and offset-aware datetimes` at `same_problem_reports.py` line 220, `if closure and event.event_date > closure:`. The analysis terminates.
- **Relevant failure output:**
  ```
  FAIL: test_mixed_naive_and_aware_dates_do_not_crash
    File "same_problem_reports.py", line 220, in analyze_issue
      if closure and event.event_date > closure:
  TypeError: can't compare offset-naive and offset-aware datetimes
  ...
  AssertionError: analyze_issue crashed on mixed timezones: can't compare offset-naive and offset-aware datetimes
  ```

---

## D3. `--label` crashes Feature 1 when an issue's labels are `null`

- **Affected module / feature:** `same_problem_reports.py`, `SameProblemReportsAnalysis.run()` line 251 (Feature 1 with the `--label` filter)
- **Associated test case:** `tests/test_team5_same_problem_reports.py` → `RunTests.test_label_filter_with_unlabeled_issue_does_not_crash`
- **Preconditions / test data:**
  - One issue whose `labels` attribute is `None` (`"labels": null` in JSON)
  - Label filter `kind/bug`
  - `DataLoader.get_issues` patched to return that issue
- **Steps to reproduce:**
  1. Set `"labels": null` for an issue in the data file.
  2. Run `python run.py --feature 1 --label kind/bug`.
- **Expected result:** The issue is treated as unlabeled, as Features 2 and 3 do with `(issue.labels or [])`. The analysis prints "No issues found ..." for the filter.
- **Actual result:** `TypeError: argument of type 'NoneType' is not iterable` at line 251, `issues = [issue for issue in issues if self.label in issue.labels]`. The program terminates.
- **Relevant failure output:**
  ```
  FAIL: test_label_filter_with_unlabeled_issue_does_not_crash
    File "same_problem_reports.py", line 251, in run
      issues = [issue for issue in issues if self.label in issue.labels]
  TypeError: argument of type 'NoneType' is not iterable
  ...
  AssertionError: --label crashed on an issue with labels=None: argument of type 'NoneType' is not iterable
  ```

---

## D4. A missing or wrong data path ends in a raw traceback

- **Affected module / feature:** `run.py` → `data_loader.py` `DataLoader._load()` (all features)
- **Associated test case:** `tests/test_team5_run_and_config.py` → `RunPyTests.test_missing_data_file_gives_a_clear_message`
- **Preconditions / test data:** `ENPM611_PROJECT_DATA_PATH` points to a file that does not exist. The same thing happens with the unchanged `config.json`, which ships with the placeholder `"path/to/data/file.json"`.
- **Steps to reproduce:**
  1. Set `ENPM611_PROJECT_DATA_PATH` to a non-existent path, or clone the repository and leave `config.json` unchanged.
  2. Run `python run.py --feature 2`.
- **Expected result:** A short message saying the data file was not found and how to set the path (Milestone 2: "Handle expected user input without terminating unexpectedly").
- **Actual result:** A full Python traceback ending in `FileNotFoundError: [Errno 2] No such file or directory: '<path>'`.
- **Relevant failure output:**
  ```
  FAIL: test_missing_data_file_gives_a_clear_message
  AssertionError: 'Traceback' unexpectedly found in 'Traceback (most recent call last):
    File "run.py", line 66, in <module>
      DeveloperResponseAnalysis().run()
    File "developer_response_time.py", line 229, in run
      all_issues = DataLoader().get_issues()
    File "data_loader.py", line 29, in get_issues
      _ISSUES = self._load()
    File "data_loader.py", line 37, in _load
      with open(self.data_path,'r') as fin:
  FileNotFoundError: [Errno 2] No such file or directory: '.../missing.json'
  ' : missing data file crashed with a traceback
  ```

---

## D5. An invalid `--feature` value exits as if it succeeded

- **Affected module / feature:** `run.py`, argument dispatch (lines 60–70)
- **Associated test case:** `tests/test_team5_run_and_config.py` → `RunPyTests.test_invalid_feature_number_is_reported_as_an_error`
- **Preconditions / test data:** A valid one-issue JSON data file set through `ENPM611_PROJECT_DATA_PATH`.
- **Steps to reproduce:**
  1. Run `python run.py --feature 4`.
  2. Check the exit status: `echo $?` (PowerShell: `$LASTEXITCODE`).
- **Expected result:** An error naming the valid choices (0–3) and a non-zero exit status.
- **Actual result:** Prints `Need to specify which feature to run with --feature flag.` even though a feature was given, then exits with status `0`.
- **Relevant failure output:**
  ```
  FAIL: test_invalid_feature_number_is_reported_as_an_error
    File "tests/test_team5_run_and_config.py", line 70, in test_invalid_feature_number_is_reported_as_an_error
  AssertionError: 0 == 0 : an invalid --feature value exits as if it succeeded
  ```
  Manual run:
  ```
  $ python run.py --feature 4
  Need to specify which feature to run with --feature flag.
  $ echo $?
  0
  ```

---

## D6. The README's name for Feature 3's default mode is rejected

- **Affected module / feature:** `stale_issues_analysis.py` `validated_activity()` and the `--activity` option in `run.py` (Feature 3: stale open issues); `README.md`
- **Associated test case:** `tests/test_team5_stale_issues_analysis.py` → `InputValidationTests.test_mode_named_in_readme_is_accepted`
- **Preconditions / test data:** Activity value `"substantive"`, taken from the README, Feature 3 section: "The default **substantive** clock ...".
- **Steps to reproduce:**
  1. Read the Feature 3 section of `README.md`.
  2. Run `python run.py --feature 3 --activity substantive`.
- **Expected result:** The documented mode name is accepted, or the README uses the real option name (`strict`).
- **Actual result:** `validated_activity("substantive")` returns `None`, and the CLI rejects the value with exit status 2.
- **Relevant failure output:**
  ```
  FAIL: test_mode_named_in_readme_is_accepted
    File "tests/test_team5_stale_issues_analysis.py", line 66, in test_mode_named_in_readme_is_accepted
  AssertionError: unexpectedly None
  ```
  Manual run:
  ```
  $ python run.py --feature 3 --activity substantive
  run.py: error: argument --activity/-a: invalid choice: 'substantive' (choose from 'strict', 'any')
  ```

---

## D7. "+1"-style same-problem comments are not detected

- **Affected module / feature:** `same_problem_reports.py`, `classify_comment()` (Feature 1: same-problem reports)
- **Associated test case:** `tests/test_team5_same_problem_reports.py` → `ClassifyCommentTests.test_plus_one_style_report_is_detected`
- **Preconditions / test data:** Comment text `"+1, same problem on macOS"`.
- **Steps to reproduce:**
  1. Run `python -c "from same_problem_reports import classify_comment; print(classify_comment('+1, same problem on macOS'))"`.
- **Expected result:** The comment is classified as a same-problem report. It states first-hand that the author has the same problem.
- **Actual result:** `None`. The "same problem" patterns only match at the start of the text, so a leading `+1,` prevents a match and Feature 1 under-counts these reports.
- **Relevant failure output:**
  ```
  FAIL: test_plus_one_style_report_is_detected
    File "tests/test_team5_same_problem_reports.py", line 37, in test_plus_one_style_report_is_detected
  AssertionError: unexpectedly None
  ```