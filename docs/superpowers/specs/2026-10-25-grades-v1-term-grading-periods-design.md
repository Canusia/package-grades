# Grades v1.0.0 — grading periods own the dates

**Status:** approved design, 2026-10-25 (brainstormed in the Lamar tenant).
**Release:** `package-grades` v1.0.0 (major: removes settings fields).

## Goal

Make each **term (or subterm)** own its grading schedule through its grading
periods, and reduce the **Class Grades Settings** to configuration that is
global to the tenant. Today the setting holds term-specific data (Class
Term(s), a single submission window, a list of reminder dates) that competes
with grading periods: the class list can say "closed" while a period is open,
a mid-semester submission does not show on the list, and reminders run on two
unrelated schedules.

Success means:

- An administrator schedules grading only on the term's **Grading Periods**
  tab; nothing in Settings is term- or date-specific.
- An instructor sees every period of a class, can edit only the open one, and
  can look back at any term at any time.
- Existing tenants upgrade without losing grade entry: their old window is
  migrated into a period.

## Decisions

| # | Decision |
|---|---|
| 1 | A term is a *grading term* when it has at least one grading period. Pages default to terms with a current or upcoming period. |
| 2 | One-time data migration: each old Class Term(s) term with no periods gets a **Final Grades** period from the old start/end dates, reminders off. Retired keys are then removed. |
| 3 | "Grades open" wording comes from per-user page messages built from periods; Grades Open/Grades Closed merge into one **Grades Intro**. |
| 4 | Reminders: every N days **plus** an optional nudge X days before due. The old reminder-dates list and its job are retired. |
| 5 | Nothing ages off: term switchers on every grades page, defaulting to current and upcoming terms; any past term is selectable. |
| 6 | The grade page shows **one column per period**; only the open period's column is editable. |
| 7 | Periods on one term may not overlap. |
| 8 | The HS admin grade page follows the same layout and rules, from shared code. |
| 9 | Each period has a **visible to students** flag; the dead viewable-date settings go. |
| 10 | Grades is a **tab on the instructor Class Details page** (registered by grades), and the standalone grade page is kept, rebuilt in the same layout. |

## 1. Data model and settings

### `GradingPeriod`

New fields:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `remind_days_before_due` | `PositiveIntegerField` | `0` | One extra reminder this many days before `due_on`; `0` = off. |
| `visible_to_students` | `BooleanField` | `False` | Students see this period's grades once the section submitted it. |

Unchanged: `term`, `name`, `sequence`, `opens_on`, `due_on`, `is_final`,
`reminder_frequency_days`.

Validation (`GradingPeriodForm` and `GradingPeriod.clean()`):

- `opens_on <= due_on`.
- The `[opens_on, due_on]` range does not overlap another period on the same
  term (inclusive at both ends).
- At most one `is_final` period per term.

### Class Grades Settings (`class_section_grades`)

| Kept | Grade scale; registration status(es); require roster confirmation + message; send grades emails + debug list; send grades-due reminders + cron + grades-due subject/email; grades-submitted email subject/body + notify instructor; Grades How To (`grades_open_class_section`); Grades Submitted Message (`grades_submitted_class_section`). |
|---|---|
| Merged | `grades_open` + `grades_closed` → `grades_intro` (Grades Intro, shown above the class list). |
| Removed | `terms`, `start_date`, `end_date`, `reminder_dates`, `viewable_from_date`, `viewable_end_date`. |

The `grades_due_email` template keeps `{{grading_period}}` and `{{due_date}}`
and stops promising `{{term}}` as a list of terms (it is the period's term).

### Migration (`grades` data migration)

Runs once per campus (settings are campus-scoped on multi-campus tenants;
single-campus tenants have one row):

1. Read the stored setting. For each id in `terms` whose term has **no**
   grading period, create `GradingPeriod(name='Final Grades', sequence=1,
   is_final=True, opens_on=start_date, due_on=end_date,
   reminder_frequency_days=0, remind_days_before_due=0,
   visible_to_students=False)`. Skip (and log) a term when either date is
   missing or unparseable.
2. Copy `grades_open` (else `grades_closed`) into `grades_intro`.
3. Remove the retired keys from the stored value.
4. Log one line per created period and per skipped term.

Terms that already have periods are untouched. The migration is reversible
only as a no-op (the removed keys are not restored).

## 2. Rules and jobs

### Period services (`services/periods.py`)

- `periods_for_section(section)` — the section's **own** term's periods (no
  inheritance from a parent term), in `sequence` order. Unchanged.
- `is_period_open(period, on_date=None)` — `opens_on <= date <= due_on`.
- `open_period(section, on_date=None)` — the one open period or `None`
  (non-overlap guarantees at most one).
- `is_period_editable(section, period, on_date=None)` — open, status not
  `submitted`, and the roster gate passes.
- Storage is unchanged: interim marks in `PeriodGrade`; the final period's
  mark in `StudentRegistration.grade`; submitting the final period mirrors
  onto `ClassSection.grade_status`, so CE grade stats, the submitted email and
  the Banner push keep working.

The no-period fallback (`period is None` → old window) is **removed**: a
section whose term has no periods has nothing to grade.

### Window services (`services/window.py`) — same names, period-based

- `grade_terms()` → ids of every term with at least one period.
- `current_grade_terms(on_date=None)` → ids of terms with a period whose
  `due_on >= on_date` (open or upcoming). The default for every term switcher.
- `is_submit_grades_open()` → `True` when any period is open today. Used by
  `cis` helpers and reports (no user available).
- `can_view_grades()` → `True` (viewing is decided per period, see below).
  Kept for `cis.integrations.grades` compatibility.
- `page_header_for_instructor()` → the Grades Intro text.

`cis.integrations.grades` calls these by name; no `cis` change is required.

### Pages that read Class Term(s) today

- CE class-sections **list** page Grades statistics tab (`tabs.py`,
  `sections_grades_tab`; counts become per period of the selected term), CE
  **Grades → SIS** page
  (`views/sis_sync.py`) and the Banner push (`services/sis_push.py`): a term
  switcher defaulting to `current_grade_terms()`; any grade term selectable;
  no age cut-off. The push still sends only sections whose final period is
  submitted.
- **Student grades**: for each period with `visible_to_students`, the
  student sees their mark once that section's status for the period is
  `submitted`. The final period shows `StudentRegistration.grade` as today.

### Reminders (single job: `notify_period_grades_pending`)

A section is reminded for a period on `today` when:

1. `send_grade_reminders` is Yes (global switch), and
2. the period is open (`opens_on <= today <= due_on`), and
3. its `SectionPeriodStatus.status` is not `submitted`, and
4. either `reminder_frequency_days > 0` and that many days have passed since
   `last_notified_on` (or it was never notified), **or**
   `remind_days_before_due > 0` and `today == due_on - remind_days_before_due`,
   and
5. `last_notified_on != today` (no double send).

One email per (teacher, period), as today.

`notify_grades_pending` (reminder-dates job) becomes a no-op that logs
"retired in grades v1.0.0 — use grading-period reminders" for one release,
then is deleted in v1.1. `services/reminders.py`'s date-list functions are
removed.

## 3. Instructor and HS admin pages

### Shared grade fragment

One template (`grades/partials/_grade_grid.html`) and one builder
(`services/grade_grid.py`) used by the instructor tab, the instructor
standalone page and the HS admin tab.

- Rows: eligible registrations (the Registration Status(es) setting).
- Columns: tenant-configurable student columns, then **one column per
  period** in `sequence` order.
  - The editable period's column holds the grade selects (autosave as today).
  - Other periods show the stored mark as text, or "–".
- Column header: period name + status — "Open · due 10/30", "Submitted
  10/25", "Opens 11/16", "Closed · not submitted"; a **Final** badge on the
  final period.
- Save as Draft / Submit act on the editable period only; hidden when no
  period is editable.
- Text above the grid: Grades How To while open and unsubmitted; Grades
  Submitted Message once submitted; roster-gate warning as today.
- Download Roster kept.

#### Tenant-configurable student columns

A column registry in `services/columns.py`, modelled on instructor_portal's
pluggable roster columns:

- A column is `key -> (header, value(registration), sort_key)`.
- Defaults: `last_name`, `first_name`, `psid`.
- The tenant chooses and extends the list through a tenant service
  (`get_tenant_service('grades_columns')` when present), e.g. Lamar adds
  `highschool` (the student's high school).
- Period columns are always appended by the package.
- `grade_roster.js` sorts on any column that declares a `sort_key`.

### Instructor

- **Grades tab** on Class Details: registered from `GradesConfig.ready()` on
  `instructor_class_section_tabs` (resolved through the
  `instructor.instructor.registry` / `instructor.registry` conditional) with
  `slug='grades'`, `title='Grades'`, `order=50`, and a permission that hides
  it when the section's term has no periods. Renders the shared fragment.
- **Standalone page** `/instructor/grades/class_section/<id>`: rebuilt in the
  Class Details layout (breadcrumb, page messages, Details card, fragment on
  the right). It remains the POST and autosave endpoint for both; after a
  submit it redirects to the page the post came from (a `next` field set to
  the standalone URL or `/instructor/class_section/<id>#grades`, validated
  as a same-host path).
- **Class list** `/instructor/grades/`: term switcher (grade terms the
  instructor teaches in; default `current_grade_terms()`), columns Course,
  CRN, High School, Students (counts by registration status), one status per
  period, Manage/Edit (to the standalone page). Page messages on top; Grades
  Intro above the table. Rendered server-side.

### Page messages

Providers registered by grades in `grades/page_messages.py`:

- `('instructor', 'dashboard')`, `('instructor', 'grades')`,
  `('highschool_admin', 'dashboard')`.
- Per open period on the user's sections: warning "*Period* is open through
  *date* — N of M class(es) not submitted", or success when all are
  submitted. The dashboard variant sets `tile_id` so the grades tile is
  highlighted.

### HS admin

The existing HS admin class-page Grades tab (today one link per period to a
separate entry page) renders the shared fragment inline with the same rules, scoped to the admin's administered high schools (unchanged
authorization).

### Lamar

Lamar's overrides `webapp/templates/grades/instructor/*.html`, its
`services/instructor_grades.py`, `templatetags/instructor_grades.py` and
`page_messages.py` are deleted after the upgrade; the High School column is
supplied through the column hook.

## 4. Release, upgrade, testing

### Release

`v1.0.0` from branch `feat/v1-term-grading-periods`. No `cis` or
instructor_portal change is required. CHANGELOG lists removals, the
migration, the retired job and the new fields.

### Tenant upgrade

1. Bump the pin to `v1.0.0`; rebuild.
2. `migrate` (creates Final Grades periods; check its log).
3. Review each term's Grading Periods: add interim periods, reminder cadence,
   student visibility.
4. Remove the `notify_grades_pending` cron (no-op in v1.0.0).
5. Optional: configure student columns through the tenant service.

### Tests (`grades/tests/`)

- Migration: Final Grades created for a period-less term; terms with periods
  untouched; missing dates skipped and logged; retired keys removed;
  `grades_intro` populated; per-campus.
- Period validation: overlap rejected (including touching dates); one final
  per term; `opens_on <= due_on`.
- `is_period_editable`: open/closed, submitted, roster gate.
- Subterm sections use only the subterm's periods.
- Reminders: frequency cadence; days-before-due; no double send; nothing
  outside the window or once submitted; global switch off.
- `grade_terms` / `current_grade_terms` and the term switcher default.
- Grid: one column per period; non-editable columns read-only; POST to a
  closed or submitted period refused (instructor and HS admin); IDOR scoping
  unchanged.
- Tab and standalone page render the same fragment; redirect back to the
  origin; `next` rejects off-host URLs.
- Column registry: defaults, tenant extension, unknown key ignored.
- Student visibility per period.
- Page messages: pending summary and all-submitted success.
- Banner push unchanged (final period submitted only).
- Existing suite updated where it assumed the old window.

## Out of scope

- Copying a term's periods from another term.
- Automatic push of final grades to Banner.
- Any `cis` change. Follow-ups tracked separately: the CE Class Details
  Grades tab (cis), a CE grade-submission summary page, and mid-semester
  grade export reports.
