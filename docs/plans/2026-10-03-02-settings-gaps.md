# #2 — Settings gaps from the Grades Configuration Workbook

> Implemented inline (native execution). Written against `v0.0.8` / `57736d4`.

**Goal:** Every workbook answer listed in #2 maps to a `class_section_grades` setting. The
hard-coded DEBUG recipient is gone. Existing tenants see **no behaviour change** until they
change a setting.

**Architecture:** Add new keys to `SettingForm`. `from_db()` fills them with
backward-compatible defaults *only when absent*, so the settings API, which builds form data from
`from_db()`, validates old rows unchanged. All three email paths (submitted confirmation,
grades-due reminders, grading-period reminders) go through one helper,
`services/email.py::send_grades_mail()`, which applies the master switch and the debug list.

## Global Constraints

- Defaults for absent keys reproduce today's behaviour: `is_active='Yes'`,
  `notify_instructor_on_submit='Yes'`, `grades_submitted_cc=''`, `send_grade_reminders='Yes'`,
  `student_grades_visible='Yes'`, `student_transcript_enabled='Yes'`, `debug_email_list=''`.
- `install()` stays seed-only (package-cis #51).
- Never hardcode the `grades.` / `grades.grades.` import prefix.

## Decisions per gap

| # | Gap | Decision |
|---|---|---|
| 1 | Turn off the "grades submitted" email | `notify_instructor_on_submit` (Yes/No). |
| 2 | CC the CE office | `grades_submitted_cc`, comma-separated, each address validated. Sent with the confirmation, even if the instructor copy is off (the office copy is separate). |
| 3 | Turn off reminders | `send_grade_reminders` (Yes/No). `cron` is required only when Yes. When No, the CronTab rows are **left alone** (deleting them would cascade-delete their run history), and both reminder commands no-op with "Grade reminders are turned off". |
| 4 | Student portal switches | `student_grades_visible`: when No, the grades page shows a notice instead of the table. `student_transcript_enabled`: when No, the download button is hidden and the download URL returns 404. **Limit:** the table's data comes from the student app's `/student/api/registrations/`, which is outside this package, so it is not gated here. |
| 5 | Email master switch | `is_active` = Yes / Debug / No plus `debug_email_list`, the same shape as package-class_visit. No = send nothing. Debug = send only to the debug list. |
| 6 | Hard-coded `kadaji@gmail.com` | Removed from all three paths (`signals.py`, `services/reminders.py`, `services/period_reminders.py`). With `settings.DEBUG` on, a `Yes` switch is treated as **Debug** (debug list only; nothing is sent if the list is empty), so a dev/misconfigured tenant can never mail real instructors. |
| 7 | Terms by name | No change. A test pins that the schema's `terms` choices are `(term.id, str(term))`. |
| — | `dry_run` side effect | Already safe: the API writes inside `transaction.atomic()` and rolls back on `dry_run`, and a CronTab save only writes DB rows (`CronLog`). A test pins that a dry run leaves `CronTab` unchanged. |

## Review Focus

1. A legacy setting row (no new keys) still validates through the form and the API, and emails still go to the instructor.
2. `settings.DEBUG=True` with no debug list → **nothing** sent (previously sent to a personal address).
3. `send_grade_reminders=No` with a blank `cron` → valid; with `Yes` and a blank cron → a field error.
4. An invalid address in `grades_submitted_cc` → a field error naming it.
5. `student_transcript_enabled=No` → a direct GET of `/student/grades/download/` returns 404, not a PDF.

## Tasks

1. **Email helper + switch** — `services/email.py`, rewire the three senders. Tests: Yes/No/Debug, DEBUG override, cc + instructor toggle.
2. **Settings fields** — the new fields, `clean()` for cron and cc, `_to_python`, `from_db` defaults, `install` defaults. Tests: legacy row via the API, cron conditional, cc validation, dry run leaves CronTab unchanged, terms choices.
3. **Reminder off switch** — both commands no-op. Tests.
4. **Student switches** — views + template. Tests.
5. README settings docs, full suite, commit.
