# Defect Report: Poetry Issue Analyzer (tested by Team 5)

Repository tested: https://github.com/mertkanalacahan/poetry-issue-analyzer

All defects below are reproduced by a failing test in `tests/`. Run the full suite with:

```bash
python -m unittest discover -v
```

Unless stated otherwise, steps use `poetry_issues_all.json` and `ENPM611_PROJECT_DATA_PATH` set as described in the README.

---

## D1. Replies posted after an issue was closed count as the "first developer reply" (Feature 2)

**Severity:** High. Wrong values appear in the normal output.

**Steps to reproduce**
1. `python run.py --feature 2`
2. Look at "Slowest first replies".

**Expected:** An issue that was closed before any developer commented is not reported as "answered" after a long wait.

**Actual:** Issue #263 was closed by its own author on 2018-06-28, one day after it was opened. A developer comment posted in December 2022 is counted as its first reply, so it is listed as waiting **1635.4 days by clintonroy**. These post-closure replies also raise the reported mean and 90th percentile.

**Test:** `tests/test_team5_developer_response_time.py::AnalyzeIssueTests::test_reply_after_issue_was_closed_is_not_a_first_response`

**Cause:** `first_developer_reply()` considers every developer comment and ignores the issue's closing date.

---

## D2. Feature 1 crashes when timestamps mix timezone-aware and naive dates

**Severity:** Medium. The program terminates.

**Steps to reproduce**
1. In a data file, give one comment a date without a timezone (for example `"2024-02-01T00:00:00"`) on an issue whose closing date has one (`"2024-01-02T00:00:00+00:00"`).
2. `python run.py --feature 1`

**Expected:** Dates are normalised, as Features 2 and 3 already do with `as_utc()`.

**Actual:** `TypeError: can't compare offset-naive and offset-aware datetimes` at `same_problem_reports.py`, line 220 (and in `latest_closure`).

**Test:** `tests/test_team5_same_problem_reports.py::AnalyzeIssueTests::test_mixed_naive_and_aware_dates_do_not_crash`

---

## D3. `--label` crashes Feature 1 when an issue has no labels list

**Severity:** Medium. The program terminates.

**Steps to reproduce**
1. In a data file, set `"labels": null` for one issue.
2. `python run.py --feature 1 --label kind/bug`

**Expected:** The issue is treated as unlabeled, as Features 2 and 3 do with `(issue.labels or [])`.

**Actual:** `TypeError: argument of type 'NoneType' is not iterable` at `same_problem_reports.py`, line 251.

**Test:** `tests/test_team5_same_problem_reports.py::RunTests::test_label_filter_with_unlabeled_issue_does_not_crash`

---

## D4. A missing or wrong data path ends in a traceback

**Severity:** Medium. No helpful error message.

**Steps to reproduce**
1. Clone the repository and do not change `config.json` (it ships with `"path/to/data/file.json"`), or set `ENPM611_PROJECT_DATA_PATH` to a file that does not exist.
2. `python run.py --feature 2`

**Expected:** A short message explaining that the data file was not found and how to set the path.

**Actual:** A full Python traceback ending in `FileNotFoundError: [Errno 2] No such file or directory: 'path/to/data/file.json'`.

**Test:** `tests/test_team5_run_and_config.py::RunPyTests::test_missing_data_file_gives_a_clear_message`

---

## D5. An invalid `--feature` number exits as if it succeeded

**Severity:** Low.

**Steps to reproduce**
1. `python run.py --feature 4`
2. `echo $?` (PowerShell: `$LASTEXITCODE`)

**Expected:** An error naming the valid choices (0–3) and a non-zero exit status.

**Actual:** Prints "Need to specify which feature to run with --feature flag." even though a feature *was* specified, then exits with status 0.

**Test:** `tests/test_team5_run_and_config.py::RunPyTests::test_invalid_feature_number_is_reported_as_an_error`

---

## D6. The README's name for Feature 3's default mode is rejected by the program

**Severity:** Low (documentation).

**Steps to reproduce**
1. Read the Feature 3 README section: "The default **substantive** clock ...".
2. `python run.py --feature 3 --activity substantive`

**Expected:** The documented name is accepted, or the README uses the real option name.

**Actual:** `run.py: error: argument --activity/-a: invalid choice: 'substantive' (choose from 'strict', 'any')`

**Test:** `tests/test_team5_stale_issues_analysis.py::InputValidationTests::test_mode_named_in_readme_is_accepted`

---

## D7. Feature 1 misses "+1"-style same-problem reports

**Severity:** Low (accuracy).

**Steps to reproduce**
1. `python -c "from same_problem_reports import classify_comment; print(classify_comment('+1, same problem on macOS'))"`

**Expected:** The comment is detected as a same-problem report.

**Actual:** `None`. The "same problem" patterns only match at the start of the text, so a leading "+1," prevents a match.

**Test:** `tests/test_team5_same_problem_reports.py::ClassifyCommentTests::test_plus_one_style_report_is_detected`
