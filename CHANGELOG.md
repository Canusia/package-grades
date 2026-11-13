# Changelog

## 1.5.0

- Grades pages follow renamed menu items (#21): instructor Class Grades (list + class grade page), student My Courses, CE Grades → SIS and Grade Summary.
- Page text from `<menu item>_blurb`; HS admin class grade page reads `class_blurb` then `classes_blurb`. Placeholders hidden on instructor/HS admin pages.
- Uses cis's shared `cis.portal_text` (cis v0.2.10a) when present. No migrations.

## 1.4.1

### Fixed

- **HS admin Grades tab showed the whole class under `hosted_or_own_students`**
  (package-highschool_admin#28, FERPA). An HS admin who sees a class only because
  their own students are in it (their school is neither the primary nor a
  secondary school) now sees only their own students' grades on the class page's
  Grades tab, read-only and without the Download Grades link. Before, the tab
  listed every student in the class. Primary and secondary-school admins are
  unchanged. `views.hs_admin.admin_scope()` now returns the admin's schools
  instead of `None` for this path.

## 1.4.0

### Added

- **#20: run the grading-period reminders from the Django admin.**
  `notify_period_grades_pending` is registered with django-admin-runner under
  the **grades** group (Admin → Admin Runner → Commands). Superusers can
  run it, and so can staff holding `grades.change_gradingperiod`. Runs are
  queued on the django-tasks worker, and their output is kept on the
  execution page. Cron still schedules the regular runs.
- **#20: `--dry-run`** on `notify_period_grades_pending`: lists each teacher
  and HS admin who would be emailed (name, address, sections, grading
  period), renders their emails, and sends, saves and notes nothing.
- The command now prints its summary, so `manage.py` and the admin show what
  it did.

### Fixed

- **#20: `notify_period_grades_pending` without `-t/--time` crashed** before
  sending anything. cis's cron-log receivers parse the scheduled time, and a
  missing time raised `TypeError`. The command now writes to the cron log only
  when cron passes a time, so manual and admin runs work.

### Changed

- **New dependency: `django-admin-runner`**, the Canusia fork
  (`Canusia/package-admin-runner@v0.3.0.post1`), which needs Django 5.2 or
  later and Python 3.12 or later. Installing it is harmless on its own: the
  commands appear in the admin only when the host adds `django_admin_runner`
  to `INSTALLED_APPS` and runs `migrate`. `grades/admin_runner.py` still falls back to a no-op
  decorator if the import fails.
- The runner is pinned to the exact tag. A host that moves its own
  `package-admin-runner` line to another tag or to `git+ssh` gets a pip
  conflict until grades is released with the same pin, so bump them together.
- The retired `notify_grades_pending` is not registered.

## 1.3.0

### Changed (breaking)

- **#16, #17: Can submit grades decides HS admin grade entry.** The High School
  Admin Grade Access setting (none / view / edit, `hs_admin_grade_entry`) is
  removed. Every HS admin of a school on the class sees its grades read-only
  (Grades tab, grade page, CSV, roster PDF, Grades by Grading Period). Entering
  and submitting needs an Active position at the school holding Can submit
  grades for the course's campus at the school they act for: the primary
  school for the whole class, or their own secondary school (cis#154, drafts
  for their own students). A grant at a secondary school never unlocks the
  whole class. On a cis without per-school permissions (before 0.1.15a) no HS
  admin enters grades.
- **#17: HS admin reminders are always on** for admins holding Can submit
  grades. A blank HS admin subject or message no longer turns them off: the
  fields are required and a blank saved value falls back to the default.
- **#17: the grades-submitted confirmation is sent for every grading period**,
  from the grade POST (`services/submitted_email.py`), to whoever submitted,
  the primary instructor and the primary school's HS admins holding Can submit
  grades. Secondary instructors and secondary-school admins are not included.
  The ClassSection `grade_status` signal that sent it (final period, instructor
  only) is removed, so changing `grade_status` outside grade entry sends
  nothing. A class with no instructor no longer errors, and a mail error no
  longer turns a successful submit into an error page.

### Added

- #17: HS Admin Grades Intro (`hsadmin_grades_intro`), shown on the HS admin
  Grades tab and grade page; blank uses Grades Intro.
- #17: the setting page groups its fields under headers, and the High School
  Admins group says who can enter grades and how many active positions hold
  Can submit grades.
- #17: `{{submitter_first_name}}`, `{{submitter_last_name}}`,
  `{{grading_period}}` and `{{term}}` in the grades-submitted email.
- #14: report **Grades: Pending Submission Recipients**: one row per
  instructor and/or HS admin (Recipients choice, default Instructors) who still
  owes grades for the chosen grading periods (blank = every period that has
  opened); also a Bulk Messages data source, one recipient per person.
- `services.gating`: `hs_admin_can_submit_grades(user, section)`,
  `submit_grades_supported()`, `submit_grades_positions()`,
  `submit_grade_grants()`, `submit_grades_admins_lookup()`.

### Wording

- Labels: "Send a Confirmation When Grades Are Submitted", "Grade Entry
  Instructions"; help texts name both instructors and HS admins. The default
  roster-not-confirmed message says "the class section page".

### Deprecated

- `services.gating.hs_admin_grade_access()`, `hs_admin_can_view_grades()`,
  `hs_admin_grade_entry_enabled()`; use `hs_admin_can_submit_grades()`.

## 1.2.0

### Added

- Secondary teachers/high schools (package-cis#154): grade entry stays primary; secondary-school HS admins grade only their own students (drafts; no class submit); reminders reach permitted secondary-school admins.

## 1.1.0

### Added

- #15: grading-period reminders also go to HS admins who hold Can submit
  grades at the section's school (course campus) when HS admin grade access is
  Edit, with their own subject/message settings. One email per person per
  period; sections without a teacher are reminded when they have such admins.

### Changed

- A blank teacher subject no longer stops admin reminders. On a cis without
  per-school HS admin permissions, admin reminders are off (teachers unchanged).

## 1.0.2

### Changed

- Publishes the CE, instructor and student sidebar items to the cis menu registry
  (myce_cis v0.1.43a+). On older cis nothing changes.

## 1.0.1

### Fixed

- #13: Class Grades settings now save "Student Grades Table Columns" and
  "High School Admin Grade Access". Both were validated and then dropped, so
  the page reverted to the defaults after every save. Choices lost to earlier
  saves are not recovered: set them again and save once.
- #12: `submitted_grade()` no longer queries per registration inside a request
  (CE Registrations and Drop/WD request tables): one query per term for its
  final period, one per final period for its statuses. Saving a grading
  period or a section's period status clears the memo; outside a request
  nothing is memoised. `services.cached_final_status()` memoises a block of
  work outside a request (jobs, tests).
- #11: `compat.has_module()` treats a module already in `sys.modules` as
  importable, so package-cis registry stand-ins without `__spec__` no longer
  crash startup.

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
- Report filters: on a multi-campus host every grades report lists and accepts
  only the current campus's terms and grading periods. Grades by Grading
  Period and Grade Submission Status by Period have no Campus field (CE staff
  get the campuses they process), show terms as a parent/sub-term tree (a
  parent includes its sub-terms), and their period list follows the selected
  terms. Grades by Grading Period is also published to HS admins, who get only
  their own schools that are Active at the class's campus. `register_reports`
  does not update an existing report row: add `highschool_admin` to
  `period_grades`' available-for by hand on an upgraded tenant.
  HS admins can run it only while High School Admin Grade Access is View or
  View and enter; with No access the form says access is turned off and a
  submit is rejected.
- Saving a grade page writes only the grades that changed: an unchanged
  grade adds no history row and keeps its `entered_by` (interim) or is not
  re-saved (final).
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
