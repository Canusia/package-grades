# Changelog

## 1.0.0

Term grading periods replace the single grade window.

### Breaking

- Removed Class Grades settings fields: `terms`, `start_date`, `end_date`,
  `reminder_dates`, `grades_open`, `grades_closed`, `viewable_from_date`,
  `viewable_end_date`. The Class Grades setting now holds only global
  (non-term, non-date) configuration; it is still one setting per campus.
  `grades_intro` replaces the Open/Closed messages.
- `notify_grades_pending` is a no-op. Delete its cron job; the command is
  removed in 1.1. `notify_period_grades_pending` is the single reminder job.
- A term without grading periods has no grade entry. Grade terms, open state
  and editability are decided by Grading Periods.
- `period=None` is no longer accepted by `services.periods`.

### Migration

- `0005` creates a Final Grades period for each term that had none, from the
  old grade window. Terms that already have periods are untouched; terms with
  missing dates are skipped and logged. Check the migration log.
  Migrated Final Grades periods have reminders off and the old reminder dates
  are dropped. Dates in m/d/Y or YYYY-MM-DD are read; a setting row that fails
  is logged and skipped without stopping the migration.
- `0007` carries pre-v1 grade status onto the final period: each section saved
  or submitted under 0.0.x gets a status row for its term's Final Grades
  period, so it stays submitted (not editable, final grade visible to
  students). Idempotent; reverse is a no-op.
- `0008` adds change history for interim (mid-semester) marks
  (`HistoricalPeriodGrade`, django-simple-history; now a declared dependency).
  Final grades already have history on `StudentRegistration`.

### Added

- Grading period fields: remind-before-due, visible-to-students; overlapping
  periods are rejected, one Final Grades period per term, `opens_on <= due_on`.
- Column-per-period grade grid shared by the instructor Class Details Grades
  tab, the standalone grade page and the HS admin grid, with per-period
  submit and a term switcher on the Grades list.
- Grades tab on instructor and CE Class Details (CE: edit on behalf, reopen).
  The CE edit page has no auto-save; every CE save adds a class note that
  lists each changed grade (`Last, First: old → new`), and saving a submitted
  period keeps it submitted (use Reopen to un-submit).
- Download Grades (CSV: student columns plus a column per period) on the
  instructor grade page and Grades tab, the CE Grades tab and edit page, and
  the HS admin Grades tab and grade page (view access is enough).
  The instructor grade page uses the Class Details layout with only the
  Grades and Notes tabs.
- HS admin grades on the shared grid. The Class Grades setting "High School
  Admin Grade Access" (key `hs_admin_grade_entry`) is now No access / View
  grades only / View and enter grades; stored Yes maps to edit, No to none.
  View shows a read-only Grades tab; only edit accepts a save.
- Open-period page messages for instructors and HS admins.
- Per-period student grade visibility.
- CE grade submission summary page with reminders and CSV.
  It lists and reminds only classes on the CE user's campuses.
- Term switchers open on "All current terms"; picking a term filters to it.
- Reports: grades by period, submission status by period, and a period filter
  on the grade distribution reports.
  A grading period outside the selected terms is rejected.
- Tenant hook `grades_columns` (`columns(builtin, default_keys)`) to choose and
  extend the grid's student columns.

### Upgrade steps

1. Bump the pin to `v1.0.0`; rebuild.
2. `migrate` (creates Final Grades periods and carries pre-v1 grade status
   onto them; check its log).
3. Review each term's Grading Periods: add interim periods, reminder cadence,
   student visibility.
   Migrated Final Grades periods have reminders off and the old reminder
   dates are dropped: set a reminder cadence on each period.
4. Remove the `notify_grades_pending` cron (no-op in v1.0.0).
5. Optional: configure student columns through the tenant service.
