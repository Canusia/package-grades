# Changelog

## 1.0.0

Term grading periods replace the single grade window.

### Breaking

- Removed Class Grades settings fields: `terms`, `start_date`, `end_date`,
  `reminder_dates`, `grades_open`, `grades_closed`, `viewable_from_date`,
  `viewable_end_date`. The Class Grades setting is global-only (no per-campus
  copy). `grades_intro` replaces the Open/Closed messages.
- `notify_grades_pending` is a no-op. Delete its cron job; the command is
  removed in 1.1. `notify_period_grades_pending` is the single reminder job.
- A term without grading periods has no grade entry. Grade terms, open state
  and editability are decided by Grading Periods.
- `period=None` is no longer accepted by `services.periods`.

### Migration

- `0005` creates a Final Grades period for each term that had none, from the
  old grade window. Terms that already have periods are untouched; terms with
  missing dates are skipped and logged. Check the migration log.

### Added

- Grading period fields: remind-before-due, visible-to-students; overlapping
  periods are rejected, one Final Grades period per term, `opens_on <= due_on`.
- Column-per-period grade grid shared by the instructor Class Details Grades
  tab, the standalone grade page and the HS admin grid, with per-period
  submit and a term switcher on the Grades list.
- Grades tab on instructor and CE Class Details (CE: edit on behalf, reopen).
- HS admin grade entry on the shared grid.
- Open-period page messages for instructors and HS admins.
- Per-period student grade visibility.
- CE grade submission summary page with reminders and CSV.
- Reports: grades by period, submission status by period, and a period filter
  on the grade distribution reports.
- Tenant hook `grades_columns` (`columns(builtin, default_keys)`) to choose and
  extend the grid's student columns.

### Upgrade steps

1. Bump the pin to `v1.0.0`; rebuild.
2. `migrate` (creates Final Grades periods; check its log).
3. Review each term's Grading Periods: add interim periods, reminder cadence,
   student visibility.
4. Remove the `notify_grades_pending` cron (no-op in v1.0.0).
5. Optional: configure student columns through the tenant service.
