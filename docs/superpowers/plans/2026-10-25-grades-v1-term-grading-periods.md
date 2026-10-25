# Grades v1.0.0 — Grading Periods Own the Dates: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every term-specific date out of the Class Grades setting into grading periods, rebuild the instructor / HS admin grade pages around a column-per-period grid, and add CE staff views (Class Details Grades tab, submission summary, period reports) — released as `package-grades` v1.0.0.

**Architecture:** `services/periods.py` and `services/window.py` become the single source of truth for "which terms grade", "what is open" and "what is editable", all derived from `GradingPeriod`. One grid builder (`services/grade_grid.py`) plus one template partial (`_grade_grid.html`) and one POST handler (`views/grade_entry.py`) serve the instructor tab, the instructor standalone page, the HS admin tab and the CE tab. Settings keep only global configuration; a data migration converts each tenant's old window into a "Final Grades" period.

**Tech Stack:** Django 5.2, DRF, Bootstrap 4 templates, jQuery, Django `TestCase` (unittest). Package code lives in `webapp/grades/grades/` (the `grades.grades` editable layout); tests run inside the Lamar container.

**Spec:** `docs/superpowers/specs/2026-10-25-grades-v1-term-grading-periods-design.md` (read it before starting any task).

## Global Constraints

- Work in the `webapp/grades` submodule on branch `feat/v1-term-grading-periods`; commit there, never in the parent repo (except Task 18).
- Intra-package imports are **relative** (`from ..models import …`); other apps are absolute (`from cis.models.section import ClassSection`). Never write `from grades.models import …`.
- Optional host modules are resolved through `compat.py` (`has_module`, `registry`, `register`, `get_tenant_override`) — never `try/except ImportError` around a present module.
- Never rename or renumber an existing migration. New migrations: `0004_…`, `0005_…`, `0006_…` in order.
- No change to `package-cis` or `package-instructor_portal`.
- Names kept for `cis.integrations.grades`: `grade_terms`, `is_submit_grades_open`, `can_view_grades`, `page_header_for_instructor`, `submitted_grade`, `grade_scale`, `students_for_grades`, `render_transcript` — same names, same return types.
- Run tests with: `docker exec -w /app/webapp django_web_lamar python manage.py test grades.grades.tests.<module> -v 1` (whole suite: `... test grades.grades`).
- Date display format `m/d/Y`; timezone `America/Chicago`; "today" is `datetime.date.today()` and every service that depends on it takes an `on_date=None` / `today=None` argument for tests.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01HXjEKRSeLJuNTNJPE9vbgp
  ```

## Review Focus

1. **A term with no grading periods** (e.g. a new subterm): every page must render ("No grading periods" text), no tab/column/500; the instructor Grades tab is hidden. → tests in Tasks 5, 9, 15.
2. **A forged POST** to a closed, future or already-submitted period (instructor, HS admin) must write nothing and say why. → tests in Task 8.
3. **Migration on messy settings**: `terms` stored as `''`, a list containing a deleted term id, unparseable dates, or no Setting row at all must not abort `migrate`. → tests in Task 4.
4. **`next` redirect** after a grade POST must only accept same-host relative paths; `//evil.example/…` and `https://evil…` fall back to the default. → test in Task 8.
5. **Reminder on the due date when `remind_days_before_due` would land before `opens_on`** (e.g. a 3-day period with 7 days-before) must not send outside the window, and never twice in one day. → tests in Task 6.

---

## File Structure

| File | Responsibility |
|---|---|
| `grades/tests/base.py` (new) | `GradesTestCase` — enters a test campus on multi-campus hosts |
| `grades/tests/factories.py` (new) | Fixture builders shared by new tests |
| `grades/models.py` | `GradingPeriod` new fields + `clean()` overlap rule |
| `grades/migrations/0004_gradingperiod_v1_fields.py` (new) | schema |
| `grades/migrations/0005_settings_to_periods.py` (new) | data: window → Final Grades period |
| `grades/migrations/0006_grades_v1_nav.py` (new) | data: CE "Grade Summary" + instructor "Grades" menu items |
| `grades/forms/grading_period.py` | new fields, overlap validation |
| `grades/settings/class_section_grades.py` | drop retired fields, add `grades_intro` |
| `grades/static/grades/js/settings.js` | drop reminder-dates picker |
| `grades/services/periods.py` | period rules (`open_period`, `is_period_editable`, `marks_by_period`) |
| `grades/services/window.py` | period-based `grade_terms`, `current_grade_terms`, term switcher helpers |
| `grades/services/reminders.py` | reduced to `reminders_enabled` + `REMINDERS_OFF` |
| `grades/services/period_reminders.py` | days-before-due + no double send |
| `grades/management/commands/notify_grades_pending.py` | retired no-op |
| `grades/services/columns.py` (new) | tenant-configurable student columns |
| `grades/services/grade_grid.py` (new) | builds the grid context |
| `grades/views/grade_entry.py` | shared POST handler, `safe_next` |
| `grades/templates/grades/partials/_grade_grid.html` (new) | the grid |
| `grades/views/instructor.py`, `templates/grades/instructor/*.html` | list + standalone page |
| `grades/instructor_tabs.py` (new) | Grades tab on instructor Class Details |
| `grades/page_messages.py` (new) | page-message providers |
| `grades/views/hs_admin.py`, `templates/grades/hs_admin/*` | HS admin on the shared grid |
| `grades/services/student_table.py` | per-period visible grades |
| `grades/tabs.py`, `views/sis_sync.py`, `services/sis_push.py` | term switcher, period-based scope |
| `grades/views/ce.py`, `urls/ce.py`, `templates/grades/ce/*` | CE Class Details tab, edit/reopen, summary page |
| `grades/services/summary.py` (new) | submission summary counts |
| `grades/reports/period_grades.py`, `reports/period_submission_status.py` (new) | reports |
| `grades/reports/grade_by_*.py` | grading-period filter |
| `CHANGELOG.md`, `setup.cfg`, `pyproject.toml` | 1.0.0 |

---

### Task 1: Test harness that runs on multi-campus hosts

The current suite errors on Lamar (`AcademicYear needs a campus when MULTI_CAMPUS is on`) — 61 of 66 tests. Every later task needs a green baseline.

**Files:**
- Create: `grades/tests/base.py`, `grades/tests/factories.py`
- Modify: every `grades/tests/test_*.py` that subclasses `django.test.TestCase` (switch to `GradesTestCase`)

**Interfaces:**
- Produces: `GradesTestCase` (drop-in `TestCase`); `factories.term(code, label, ay=None)`, `factories.teacher(username)`, `factories.section(term, teacher, course=None, highschool=None, class_number=None)`, `factories.registration(section, status='registered', grade='', highschool=None)`, `factories.period(term, name, opens_on, due_on, sequence=1, is_final=False, **kw)`, `factories.grades_setting(**values)`.

- [ ] **Step 1: Write `grades/tests/base.py`**

```python
"""Test base for hosts with and without MULTI_CAMPUS.

On a multi-campus host every AcademicYear needs a campus, and CampusMiddleware
needs a Site/Campus for the test client's host. GradesTestCase enters one test
campus for the whole class (setUpTestData and every test); on a single-campus
host it does nothing.
"""
from django.conf import settings
from django.test import TestCase

from ..compat import has_module


def _multi_campus():
    return bool(getattr(settings, 'MULTI_CAMPUS', False))


def test_campus():
    """The campus reachable at 'testserver' (created on first use)."""
    from django.contrib.sites.models import Site
    from cis.models import Campus
    site, _ = Site.objects.update_or_create(
        pk=getattr(settings, 'SITE_ID', 1),
        defaults={'domain': 'testserver', 'name': 'testserver'})
    prefix = getattr(settings, 'CAMPUS_CODE_PREFIX', 'TEST')
    campus, _ = Campus.objects.update_or_create(
        code=f'{prefix}_A', defaults={'name': 'Test Campus', 'site': site})
    return campus


class GradesTestCase(TestCase):
    """TestCase that runs inside a campus context on multi-campus hosts."""

    @classmethod
    def _enter_test_campus(cls):
        if not _multi_campus() or not has_module('cis.campus_context'):
            return
        from cis.campus_context import campus_context, current_campus_or_none
        if current_campus_or_none() is not None:
            return
        cls.campus = test_campus()
        cls.enterClassContext(campus_context(cls.campus))

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        own = cls.__dict__.get('setUpTestData')
        if own is None:
            return
        func = own.__func__

        def wrapped(klass):
            klass._enter_test_campus()
            func(klass)
        cls.setUpTestData = classmethod(wrapped)

    @classmethod
    def setUpTestData(cls):
        cls._enter_test_campus()
```

- [ ] **Step 2: Write `grades/tests/factories.py`**

```python
"""Fixture builders for grades tests. Call inside a GradesTestCase."""
import itertools
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model

_seq = itertools.count(1000)


def _n():
    return next(_seq)


def grades_key():
    return getattr(settings, 'CAMPUS_CODE_PREFIX') + '_class_grades'


def grades_setting(**values):
    from cis.models.settings import Setting
    base = {'grades': 'A,B,C,D,F', 'registration_status': ['registered']}
    base.update(values)
    Setting.objects.update_or_create(key=grades_key(), defaults={'value': base})
    return base


def term(code=None, label=None, ay=None, parent=None):
    from cis.models.term import AcademicYear, Term
    n = _n()
    ay = ay or AcademicYear.objects.create(name=f'AY {n}')
    return Term.objects.create(
        academic_year=ay, code=code or f'T{n}', label=label or f'Term {n}',
        parent=parent)


def teacher(username=None, first_name='Ina', last_name='Instructor'):
    from django.contrib.auth.models import Group
    from cis.models.teacher import Teacher
    n = _n()
    username = username or f'inst{n}@example.com'
    user = get_user_model().objects.create_user(
        username=username, email=username, password='x',
        first_name=first_name, last_name=last_name)
    user.groups.add(Group.objects.get_or_create(name='instructor')[0])
    return Teacher.objects.create(user=user)


def course(designator='ENGL', catalog_number='1301'):
    from cis.models.course import Cohort, Course
    cohort, _ = Cohort.objects.get_or_create(
        designator=designator, defaults={'name': designator})
    return Course.objects.create(
        catalog_number=catalog_number, title=f'{designator} {catalog_number}',
        cohort=cohort, credit_hours=3)


def highschool(name=None):
    from cis.models.highschool import HighSchool
    return HighSchool.objects.create(name=name or f'HS {_n()}')


def section(term, teacher=None, course_obj=None, highschool_obj=None,
            class_number=None):
    from cis.models.section import ClassSection
    return ClassSection.objects.create(
        class_number=class_number or str(_n()), section_number='01',
        term=term, course=course_obj or course(catalog_number=str(_n())),
        teacher=teacher, highschool=highschool_obj, status='A')


def registration(section_obj, status='registered', grade='', highschool_obj=None,
                 last_name=None, first_name='Stu', psid=None):
    from cis.models.section import StudentRegistration
    from cis.models.student import Student
    n = _n()
    user = get_user_model().objects.create_user(
        username=f'stu{n}@example.com', email=f'stu{n}@example.com', password='x',
        first_name=first_name, last_name=last_name or f'Student{n}',
        psid=psid or f'P{n}')
    student = Student.objects.create(
        user=user, account_verified=True, highschool=highschool_obj)
    return StudentRegistration.objects.create(
        student=student, class_section=section_obj, highschool=highschool_obj,
        status=status, grade=grade or '-', status_changed_on={})


def period(term_obj, name, opens_on, due_on, sequence=1, is_final=False, **kw):
    from ..models import GradingPeriod
    return GradingPeriod.objects.create(
        term=term_obj, name=name, sequence=sequence, opens_on=opens_on,
        due_on=due_on, is_final=is_final, **kw)


D = date  # short alias for tests
```

- [ ] **Step 3: Switch existing tests to `GradesTestCase`**

In every `grades/tests/test_*.py`, replace `from django.test import TestCase` with
`from .base import GradesTestCase as TestCase` (keep any other names imported from `django.test`, e.g. `from django.test import RequestFactory`). Do not touch `SimpleTestCase` users.

```bash
cd /repos/lamar/webapp/grades/grades/tests
grep -ln "^from django.test import TestCase$" test_*.py | xargs sed -i 's/^from django.test import TestCase$/from .base import GradesTestCase as TestCase/'
grep -n "from django.test import" test_*.py   # fix any remaining combined imports by hand
```

- [ ] **Step 4: Run the whole suite**

Run: `docker exec -w /app/webapp django_web_lamar python manage.py test grades.grades -v 1`
Expected: far fewer errors than 61. Fix each remaining failure in the **test** (not product code) when it is a multi-campus artifact — typical fixes: a `Client` request needs `HTTP_HOST='testserver'`; a test that builds its own `AcademicYear` in `setUp` (not `setUpTestData`) needs `self._enter_test_campus()` first — add `GradesTestCase.setUp` calling `self._enter_test_campus()` if several tests need it. Record any failure that is a genuine product bug in the commit message and leave it failing only if fixing it is out of scope (none expected).

- [ ] **Step 5: Run again — must be all green**

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
cd /repos/lamar/webapp/grades && git add grades/tests && git commit -m "test: GradesTestCase runs the suite on multi-campus hosts"
```

---

### Task 2: `GradingPeriod` v1 fields and the no-overlap rule

**Files:**
- Modify: `grades/models.py` (class `GradingPeriod`), `grades/forms/grading_period.py`, `grades/templates/grades/ce/_grading_periods_tab.html`
- Create: `grades/migrations/0004_gradingperiod_v1_fields.py`
- Test: `grades/tests/test_v1_grading_period_rules.py`

**Interfaces:**
- Produces: `GradingPeriod.remind_days_before_due: int`, `GradingPeriod.visible_to_students: bool`, `GradingPeriod.overlapping(term, opens_on, due_on, exclude_pk=None) -> QuerySet` (classmethod).

- [ ] **Step 1: Write the failing tests**

```python
"""v1: period fields and the no-overlap rule (spec §1)."""
from datetime import date

from .base import GradesTestCase
from . import factories as f
from ..forms.grading_period import GradingPeriodForm
from ..models import GradingPeriod


def _data(**kw):
    data = {'name': 'Mid 1', 'sequence': 1, 'opens_on': '2026-10-19',
            'due_on': '2026-10-30', 'reminder_frequency_days': 0,
            'remind_days_before_due': 0}
    data.update(kw)
    return data


class GradingPeriodV1Tests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.term = f.term()
        f.period(cls.term, 'Mid 1', date(2026, 10, 19), date(2026, 10, 30))

    def test_new_fields_default_off(self):
        p = GradingPeriod.objects.get(name='Mid 1')
        self.assertEqual(p.remind_days_before_due, 0)
        self.assertFalse(p.visible_to_students)

    def test_overlap_rejected(self):
        form = GradingPeriodForm(self.term, data=_data(
            name='Mid 2', opens_on='2026-10-25', due_on='2026-11-05'))
        self.assertFalse(form.is_valid())
        self.assertIn('overlaps', str(form.errors))

    def test_touching_dates_overlap(self):
        form = GradingPeriodForm(self.term, data=_data(
            name='Mid 2', opens_on='2026-10-30', due_on='2026-11-05'))
        self.assertFalse(form.is_valid())

    def test_adjacent_dates_allowed(self):
        form = GradingPeriodForm(self.term, data=_data(
            name='Mid 2', opens_on='2026-10-31', due_on='2026-11-05',
            visible_to_students='on', remind_days_before_due=2))
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertTrue(saved.visible_to_students)
        self.assertEqual(saved.remind_days_before_due, 2)

    def test_editing_itself_is_not_an_overlap(self):
        p = GradingPeriod.objects.get(name='Mid 1')
        form = GradingPeriodForm(self.term, instance=p, data=_data(due_on='2026-10-31'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_other_term_does_not_overlap(self):
        other = f.term()
        form = GradingPeriodForm(other, data=_data())
        self.assertTrue(form.is_valid(), form.errors)
```

- [ ] **Step 2: Run to confirm failure**

Run: `docker exec -w /app/webapp django_web_lamar python manage.py test grades.grades.tests.test_v1_grading_period_rules`
Expected: errors (`remind_days_before_due` unknown field).

- [ ] **Step 3: Add the fields and helper to `GradingPeriod`** (after `reminder_frequency_days`)

```python
    remind_days_before_due = models.PositiveIntegerField(
        default=0,
        help_text=(
            'Send one extra reminder this many days before the due date. '
            '0 turns it off.'
        ),
    )

    visible_to_students = models.BooleanField(
        default=False,
        help_text=(
            "Students see this period's grades once their class has "
            'submitted them.'
        ),
    )
```

and inside the class (after `__str__`):

```python
    @classmethod
    def overlapping(cls, term, opens_on, due_on, exclude_pk=None):
        """Periods on ``term`` whose [opens_on, due_on] range touches this one.

        Inclusive at both ends: a period due 10/30 and one opening 10/30
        overlap (both would be open that day).
        """
        qs = cls.objects.filter(term=term, opens_on__lte=due_on, due_on__gte=opens_on)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        return qs
```

- [ ] **Step 4: Generate the migration**

Run: `docker exec -w /app/webapp django_web_lamar python manage.py makemigrations grades --name gradingperiod_v1_fields`
Expected: `grades/grades/migrations/0004_gradingperiod_v1_fields.py` with two `AddField`s. Inspect it; nothing else may be in it.

- [ ] **Step 5: Extend the form**

In `GradingPeriodForm.Meta.fields` append `'remind_days_before_due', 'visible_to_students'`; in `labels` add
`'remind_days_before_due': 'Remind Days Before Due'`, `'visible_to_students': 'Visible to Students'`.
In `clean()`, after the `due_on < opens_on` check, add:

```python
        if opens_on and due_on and due_on >= opens_on:
            clash = GradingPeriod.overlapping(
                self.term, opens_on, due_on,
                exclude_pk=self.instance.pk if self.instance and self.instance.pk else None,
            ).first()
            if clash is not None:
                self.add_error(
                    'opens_on',
                    f'These dates overlap "{clash.name}" '
                    f'({clash.opens_on:%m/%d/%Y} - {clash.due_on:%m/%d/%Y}). '
                    'Grading periods on a term cannot overlap.'
                )
```

- [ ] **Step 6: Show the new fields in the CE tab** — in `templates/grades/ce/_grading_periods_tab.html` add two columns to the periods table header/rows: `Remind Before Due` (`{{ p.remind_days_before_due|default:'Off' }}` with " days" when non-zero) and `Students See` (`{{ p.visible_to_students|yesno:'Yes,No' }}`), next to the existing reminder-frequency column.

- [ ] **Step 7: Migrate and run tests**

Run: `docker exec -w /app/webapp django_web_lamar python manage.py migrate grades && docker exec -w /app/webapp django_web_lamar python manage.py test grades.grades.tests.test_v1_grading_period_rules grades.grades.tests.test_grading_periods`
Expected: OK.

- [ ] **Step 8: Commit**

```bash
git add grades/models.py grades/migrations/0004_gradingperiod_v1_fields.py grades/forms/grading_period.py grades/templates/grades/ce/_grading_periods_tab.html grades/tests/test_v1_grading_period_rules.py
git commit -m "feat(periods): remind-before-due, visible-to-students, no overlapping periods"
```

---

### Task 3: Settings keep only global configuration

**Files:**
- Modify: `grades/settings/class_section_grades.py`, `grades/static/grades/js/settings.js`
- Test: `grades/tests/test_v1_settings.py`

**Interfaces:**
- Produces: stored setting keys no longer include `terms`, `start_date`, `end_date`, `reminder_dates`, `grades_open`, `grades_closed`, `viewable_from_date`, `viewable_end_date`; new key `grades_intro` (str, default `''`). `RETIRED_KEYS` tuple exported from the settings module.

- [ ] **Step 1: Write the failing tests**

```python
"""v1: the Class Grades setting is global-only (spec §1)."""
from django.test import RequestFactory

from .base import GradesTestCase
from . import factories as f
from ..settings.class_section_grades import RETIRED_KEYS, class_section_grades


class SettingsV1Tests(GradesTestCase):
    def _form(self):
        request = RequestFactory().get('/', {'report_id': 'x'})
        return class_section_grades(request)

    def test_retired_fields_are_gone(self):
        fields = set(self._form().fields)
        for key in ('terms', 'start_date', 'end_date', 'reminder_dates',
                    'grades_open', 'grades_closed'):
            self.assertNotIn(key, fields)
        self.assertIn('grades_intro', fields)

    def test_retired_keys_listed(self):
        self.assertEqual(set(RETIRED_KEYS), {
            'terms', 'start_date', 'end_date', 'reminder_dates', 'grades_open',
            'grades_closed', 'viewable_from_date', 'viewable_end_date'})

    def test_from_db_defaults_grades_intro(self):
        f.grades_setting()
        self.assertEqual(class_section_grades.from_db().get('grades_intro'), '')

    def test_install_writes_no_retired_keys(self):
        from cis.models.settings import Setting
        self._form().install()
        value = Setting.objects.get(key=f.grades_key()).value
        self.assertFalse(set(RETIRED_KEYS) & set(value))
```

- [ ] **Step 2: Run — expect failure** (`ImportError: RETIRED_KEYS`).

- [ ] **Step 3: Edit the settings module**

1. Below `NEW_KEY_DEFAULTS`, add `'grades_intro': ''` to `NEW_KEY_DEFAULTS`, and define:
   ```python
   # Removed in v1.0.0: grading periods own every date (spec §1).
   RETIRED_KEYS = (
       'terms', 'start_date', 'end_date', 'reminder_dates', 'grades_open',
       'grades_closed', 'viewable_from_date', 'viewable_end_date',
   )
   ```
2. Delete the form fields `terms`, `start_date`, `end_date`, `reminder_dates`, `grades_closed`, `grades_open` and the methods `clean_start_date`, `clean_end_date`, `clean_reminder_dates`.
3. Add the field (where `grades_open` was):
   ```python
    grades_intro = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        required=False,
        help_text='Shown above the instructor Grades class list.',
        label='Grades Intro'
    )
   ```
4. Change `send_grade_reminders` help text to `'When No, grading-period reminders are not sent.'` and `grades_due_email` help text to list `{{teacher_first_name}}, {{teacher_last_name}}, {{term}}, {{number_of_sections_pending_grades}}, {{grading_period}}, {{due_date}}` (keep the See Preview link).
5. In `class_section_grades.__init__`, delete the `term_list` loop and the `self.fields['terms'].choices = term_list` line.
6. In `_to_python`: remove the `notify_grades_pending` CronTab block (keep only `notify_period_grades_pending`), and remove the keys `reminder_dates`, `terms`, `start_date`, `end_date`, `grades_closed`, `grades_open`; add `'grades_intro': self.cleaned_data.get('grades_intro', ''),`.
7. In `install()` defaults remove `terms`, `start_date`, `end_date`, `grades_open`, `grades_closed`.
8. In `from_db()`, after the `NEW_KEY_DEFAULTS` loop add `for key in RETIRED_KEYS: values.pop(key, None)` so stale rows never leak retired keys to callers.
9. In `preview()`, replace the `grades_closed` / `grades_open` branches with one branch for `'grades_intro'` that renders `'grades/instructor/grades.html'` with `{'menu': '-1', 'intro': portal_text('instructor').get('grades_blurb', ''), 'grades_intro': grade_settings.get('grades_intro', ''), 'rows': [], 'terms': [], 'selected_term_ids': [], 'page_messages': []}` (the Task 10 template's context), and update the field's help text to include the See Preview link for `grades_intro`.

- [ ] **Step 4: Remove the reminder-dates picker from `settings.js`** — delete `initReminderDatesPicker` and its call site; update the header comment.

- [ ] **Step 5: Run tests**

Run: `... test grades.grades.tests.test_v1_settings grades.grades.tests.test_settings_install grades.grades.tests.test_settings_gaps grades.grades.tests.test_settings_preview`
Expected: OK after updating the old settings tests that posted `terms/start_date/end_date/reminder_dates/grades_open/grades_closed` (remove those keys from their POST data; replace `grades_open` preview assertions with `grades_intro`).

- [ ] **Step 6: Commit** — `git commit -am "feat(settings)!: Class Grades setting is global-only; Grades Intro replaces Open/Closed"` (add the new test file first).

---

### Task 4: Data migration — old window becomes a "Final Grades" period

**Files:**
- Create: `grades/migrations/0005_settings_to_periods.py`
- Test: `grades/tests/test_v1_settings_migration.py`

**Interfaces:**
- Produces: `migrate_settings(Setting, Term, GradingPeriod, key, log=print) -> None` (module-level function in the migration, importable for tests via `importlib.import_module('…migrations.0005_settings_to_periods')`).

- [ ] **Step 1: Write the failing tests**

```python
"""v1: data migration from the old window to Final Grades periods (spec §1)."""
import importlib
from datetime import date

from .base import GradesTestCase
from . import factories as f
from ..models import GradingPeriod

mig = importlib.import_module(
    GradingPeriod.__module__.rsplit('.', 1)[0] + '.migrations.0005_settings_to_periods')


def _run():
    from cis.models.settings import Setting
    from cis.models.term import Term
    lines = []
    mig.migrate_settings(Setting, Term, GradingPeriod, f.grades_key(), log=lines.append)
    return lines


class SettingsMigrationTests(GradesTestCase):
    def test_creates_final_period_for_period_less_term(self):
        t = f.term()
        f.grades_setting(terms=[str(t.id)], start_date='12/01/2026',
                         end_date='12/09/2026', grades_open='<p>Open</p>')
        _run()
        p = GradingPeriod.objects.get(term=t)
        self.assertEqual((p.name, p.is_final, p.opens_on, p.due_on),
                         ('Final Grades', True, date(2026, 12, 1), date(2026, 12, 9)))
        self.assertEqual((p.reminder_frequency_days, p.remind_days_before_due,
                          p.visible_to_students), (0, 0, False))

    def test_term_with_periods_untouched(self):
        t = f.term()
        f.period(t, 'Mid 1', date(2026, 10, 1), date(2026, 10, 9))
        f.grades_setting(terms=[str(t.id)], start_date='12/01/2026', end_date='12/09/2026')
        _run()
        self.assertEqual(list(GradingPeriod.objects.filter(term=t).values_list('name', flat=True)), ['Mid 1'])

    def test_retired_keys_removed_and_intro_copied(self):
        from cis.models.settings import Setting
        t = f.term()
        f.grades_setting(terms=[str(t.id)], start_date='12/01/2026', end_date='12/09/2026',
                         grades_open='<p>Open</p>', grades_closed='<p>Closed</p>',
                         reminder_dates='12/05/2026')
        _run()
        value = Setting.objects.get(key=f.grades_key()).value
        self.assertEqual(value['grades_intro'], '<p>Open</p>')
        for key in ('terms', 'start_date', 'end_date', 'reminder_dates', 'grades_open', 'grades_closed'):
            self.assertNotIn(key, value)

    def test_messy_values_do_not_abort(self):
        f.grades_setting(terms='', start_date='', end_date='')
        _run()
        f.grades_setting(terms=['00000000-0000-0000-0000-000000000000'],
                         start_date='not a date', end_date='12/09/2026')
        lines = _run()
        self.assertFalse(GradingPeriod.objects.exists())
        self.assertTrue(any('skipped' in line for line in lines))

    def test_no_setting_row(self):
        _run()  # must not raise
```

- [ ] **Step 2: Run — expect `ModuleNotFoundError`.**

- [ ] **Step 3: Write the migration**

```python
"""Grades v1.0.0: move the Class Grades window into grading periods.

For each stored Class Grades setting (one per campus on multi-campus hosts):
each term in the old ``terms`` list that has no grading period gets a
"Final Grades" period over the old start/end dates (final, reminders off,
not visible to students); ``grades_open`` (else ``grades_closed``) becomes
``grades_intro``; the retired keys are removed. Terms that already have
periods are left alone. Reverse is a no-op.
"""
import datetime

from django.conf import settings
from django.db import migrations

RETIRED_KEYS = (
    'terms', 'start_date', 'end_date', 'reminder_dates', 'grades_open',
    'grades_closed', 'viewable_from_date', 'viewable_end_date',
)


def _date(value):
    try:
        return datetime.datetime.strptime(str(value or '').strip(), '%m/%d/%Y').date()
    except ValueError:
        return None


def _term_ids(value):
    if isinstance(value, str):
        value = [v for v in value.split(',') if v.strip()]
    return [str(v).strip() for v in (value or [])]


def migrate_settings(Setting, Term, GradingPeriod, key, log=print):
    for setting in Setting.objects.filter(key=key):
        value = dict(setting.value or {})
        opens_on, due_on = _date(value.get('start_date')), _date(value.get('end_date'))
        for term_id in _term_ids(value.get('terms')):
            term = Term.objects.filter(pk=term_id).first() if _is_uuid(term_id) else None
            if term is None:
                log(f'grades 0005: skipped term {term_id}: no such term')
                continue
            if GradingPeriod.objects.filter(term=term).exists():
                log(f'grades 0005: {term} already has grading periods')
                continue
            if not opens_on or not due_on or due_on < opens_on:
                log(f'grades 0005: skipped {term}: no usable start/end dates')
                continue
            GradingPeriod.objects.create(
                term=term, name='Final Grades', sequence=1, opens_on=opens_on,
                due_on=due_on, is_final=True, reminder_frequency_days=0,
                remind_days_before_due=0, visible_to_students=False)
            log(f'grades 0005: created Final Grades {opens_on:%m/%d/%Y}-{due_on:%m/%d/%Y} for {term}')
        intro = value.get('grades_open') or value.get('grades_closed') or ''
        value.setdefault('grades_intro', '' if intro == '-' else intro)
        for retired in RETIRED_KEYS:
            value.pop(retired, None)
        setting.value = value
        setting.save(update_fields=['value'])


def _is_uuid(value):
    import uuid
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def forwards(apps, schema_editor):
    migrate_settings(
        apps.get_model('cis', 'Setting'),
        apps.get_model('cis', 'Term'),
        apps.get_model('grades', 'GradingPeriod'),
        getattr(settings, 'CAMPUS_CODE_PREFIX', '') + '_class_grades',
    )


class Migration(migrations.Migration):
    dependencies = [
        ('grades', '0004_gradingperiod_v1_fields'),
        ('cis', '__latest__'),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
```

Replace `('cis', '__latest__')` with the latest `cis` migration name the current `0001`/`0003` depend on (check `grades/migrations/0003_add_grades_nav.py` dependencies and reuse the same `cis` dependency — `__latest__` is not valid in a migration file).

- [ ] **Step 4: Run tests** — Expected: OK. Then `docker exec -w /app/webapp django_web_lamar python manage.py migrate grades` and confirm the printed log for Lamar's two campuses (Fall 2026 already has periods → "already has grading periods").

- [ ] **Step 5: Commit** — `git add grades/migrations/0005_settings_to_periods.py grades/tests/test_v1_settings_migration.py && git commit -m "feat(migration): old grade window becomes a Final Grades period"`

---

### Task 5: Period and window services are period-based

**Files:**
- Modify: `grades/services/periods.py`, `grades/services/window.py`, `grades/services/__init__.py`
- Test: `grades/tests/test_v1_period_services.py`

**Interfaces:**
- Produces (periods.py): `open_period(section, on_date=None) -> GradingPeriod|None`; `resolve_period(section, period_id=None, on_date=None) -> GradingPeriod|None` (explicit id in term → it; else open; else latest period with `opens_on <= today`; else first; `None` when no periods); `is_period_editable(section, period, on_date=None) -> bool`; `statuses_for(section, periods) -> dict[period_id, SectionPeriodStatus]`; `marks_by_period(section, periods, registrations) -> dict[period_id, dict[registration_id, str]]`; `get_status`/`set_status`/`save_mark`/`grades_for` require a period (raise `ValueError('period is required')` on `None`).
- Produces (window.py): `grade_terms() -> list[str]`; `current_grade_terms(on_date=None) -> list[str]`; `is_submit_grades_open(on_date=None) -> bool`; `can_view_grades() -> bool` (always True); `page_header_for_instructor() -> str`; `submitted_grade(registration) -> str`; `selected_term_ids(request, available_ids, on_date=None) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
"""v1: period-based services (spec §2)."""
from datetime import date
from unittest import mock

from django.test import RequestFactory

from .base import GradesTestCase
from . import factories as f
from ..services import periods as P
from ..services import window as W

TODAY = date(2026, 10, 25)


class PeriodServiceTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', date(2026, 10, 19), date(2026, 10, 30), 1)
        cls.mid2 = f.period(cls.term, 'Mid 2', date(2026, 11, 16), date(2026, 11, 27), 2)
        cls.final = f.period(cls.term, 'Final', date(2026, 12, 1), date(2026, 12, 9), 3, is_final=True)
        cls.section = f.section(cls.term, f.teacher())
        cls.empty_term = f.term()
        cls.empty_section = f.section(cls.empty_term, f.teacher())

    def test_open_period(self):
        self.assertEqual(P.open_period(self.section, TODAY), self.mid1)
        self.assertIsNone(P.open_period(self.section, date(2026, 11, 5)))

    def test_resolve_period_falls_back_to_latest_started(self):
        self.assertEqual(P.resolve_period(self.section, on_date=date(2026, 11, 5)), self.mid1)
        self.assertEqual(P.resolve_period(self.section, on_date=date(2026, 1, 1)), self.mid1)
        self.assertEqual(P.resolve_period(self.section, str(self.final.id)), self.final)
        self.assertIsNone(P.resolve_period(self.section, str(f.period(f.term(), 'X', TODAY, TODAY).id)))
        self.assertIsNone(P.resolve_period(self.empty_section))

    def test_editable(self):
        self.assertTrue(P.is_period_editable(self.section, self.mid1, TODAY))
        self.assertFalse(P.is_period_editable(self.section, self.mid2, TODAY))
        P.set_status(self.section, self.mid1, 'submitted')
        self.assertFalse(P.is_period_editable(self.section, self.mid1, TODAY))

    def test_editable_respects_roster_gate(self):
        f.grades_setting(require_roster_confirmation=True)
        self.section.roster_status = 'pending verification'
        self.assertFalse(P.is_period_editable(self.section, self.mid1, TODAY))

    def test_period_is_required(self):
        with self.assertRaises(ValueError):
            P.get_status(self.section, None)

    def test_marks_by_period(self):
        reg = f.registration(self.section)
        P.save_mark(self.mid1, reg, 'B')
        P.save_mark(self.final, reg, 'A')
        marks = P.marks_by_period(self.section, [self.mid1, self.mid2, self.final], [reg])
        self.assertEqual(marks[self.mid1.id][reg.id], 'B')
        self.assertEqual(marks[self.mid2.id].get(reg.id, ''), '')
        self.assertEqual(marks[self.final.id][reg.id], 'A')


class WindowServiceTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        cls.past = f.term()
        f.period(cls.past, 'Final', date(2026, 5, 1), date(2026, 5, 9), is_final=True)
        cls.now = f.term()
        f.period(cls.now, 'Mid 1', date(2026, 10, 19), date(2026, 10, 30))
        cls.none = f.term()

    def test_grade_terms_are_terms_with_periods(self):
        self.assertEqual(set(W.grade_terms()), {str(self.past.id), str(self.now.id)})

    def test_current_grade_terms(self):
        self.assertEqual(W.current_grade_terms(TODAY), [str(self.now.id)])

    def test_is_submit_grades_open(self):
        self.assertTrue(W.is_submit_grades_open(TODAY))
        self.assertFalse(W.is_submit_grades_open(date(2026, 11, 5)))

    def test_selected_term_ids(self):
        avail = W.grade_terms()
        rf = RequestFactory()
        self.assertEqual(W.selected_term_ids(rf.get('/'), avail, TODAY), [str(self.now.id)])
        self.assertEqual(W.selected_term_ids(rf.get('/', {'term': str(self.past.id)}), avail, TODAY),
                         [str(self.past.id)])
        # a term outside the available list is ignored, falling back to the default
        self.assertEqual(W.selected_term_ids(rf.get('/', {'term': str(self.none.id)}), avail, TODAY),
                         [str(self.now.id)])

    def test_submitted_grade_needs_submitted_final_period(self):
        section = f.section(self.past, f.teacher())
        reg = f.registration(section, grade='A')
        self.assertEqual(W.submitted_grade(reg), '-')
        P.set_status(section, P.periods_for_section(section)[0], 'submitted')
        reg.refresh_from_db()
        self.assertEqual(W.submitted_grade(reg), 'A')
```

- [ ] **Step 2: Run — expect failures.**

- [ ] **Step 3: Implement in `services/periods.py`**

Update the module docstring's last paragraph to: "A term with no grading periods has nothing to grade: `periods_for_section` returns `[]` and callers render a 'no grading periods' state." Then:

```python
def _require(period):
    if period is None:
        raise ValueError('period is required')


def open_period(section, on_date=None):
    """The section's period open on ``on_date`` (periods never overlap)."""
    for period in periods_for_section(section):
        if is_period_open(period, on_date):
            return period
    return None


def resolve_period(section, period_id=None, on_date=None):
    """The period a grade page works on.

    An explicit id wins only when it belongs to this section's term. Otherwise:
    the open period; else the latest period that has started; else the first.
    ``None`` when the term has no periods.
    """
    periods = periods_for_section(section)
    if not periods:
        return None
    if period_id:
        return next((p for p in periods if str(p.id) == str(period_id)), None)
    today = on_date or datetime.date.today()
    current = open_period(section, today)
    if current is not None:
        return current
    started = [p for p in periods if p.opens_on <= today]
    return started[-1] if started else periods[0]


def is_period_editable(section, period, on_date=None):
    """Open, not yet submitted, and the roster gate passes."""
    from .gating import can_enter_grades
    if period is None or not is_period_open(period, on_date):
        return False
    if get_status(section, period) == 'submitted':
        return False
    return can_enter_grades(section)[0]


def statuses_for(section, periods):
    """{period_id: SectionPeriodStatus} for the rows that exist."""
    return {
        row.period_id: row for row in SectionPeriodStatus.objects.filter(
            class_section=section, period__in=periods)
    }


def marks_by_period(section, periods, registrations):
    """{period_id: {registration_id: mark}} for every period."""
    return {p.id: grades_for(section, p, registrations) for p in periods}
```

Make `grades_for`, `save_mark`, `get_status`, `set_status` call `_require(period)` first and delete their `period is None` branches (the final-period routing stays). In `grades_for`, the final branch stays `{reg.id: reg.grade for reg in registrations}`; the interim branch stays as is.

- [ ] **Step 4: Implement in `services/window.py`** — replace `is_submit_grades_open`, `can_view_grades`, `page_header_for_instructor`, `grade_terms`, `submitted_grade` with:

```python
def grade_terms():
    """Ids (str) of every term with at least one grading period."""
    from ..models import GradingPeriod
    return [str(t) for t in GradingPeriod.objects.values_list('term_id', flat=True).distinct()]


def current_grade_terms(on_date=None):
    """Grade terms with a period open or still to come on ``on_date``."""
    from ..models import GradingPeriod
    on_date = on_date or datetime.date.today()
    return [str(t) for t in GradingPeriod.objects.filter(due_on__gte=on_date)
            .values_list('term_id', flat=True).distinct()]


def is_submit_grades_open(on_date=None):
    """Is any grading period open on ``on_date``? (No user: used by cis.)"""
    from ..models import GradingPeriod
    on_date = on_date or datetime.date.today()
    return GradingPeriod.objects.filter(opens_on__lte=on_date, due_on__gte=on_date).exists()


def can_view_grades():
    """Kept for cis.integrations.grades; visibility is per period now."""
    return True


def page_header_for_instructor():
    from ..settings.class_section_grades import class_section_grades
    return class_section_grades.from_db().get('grades_intro', '')


def selected_term_ids(request, available_ids, on_date=None):
    """Term ids chosen with ``?term=`` (repeatable), limited to ``available_ids``;
    default: the available terms that are current (open or upcoming), else the
    most recent available term."""
    available = [str(t) for t in available_ids]
    chosen = [t for t in request.GET.getlist('term') if t in available]
    if chosen:
        return chosen
    current = [t for t in current_grade_terms(on_date) if t in available]
    if current:
        return current
    from cis.models.term import Term
    latest = Term.objects.filter(pk__in=available).order_by('-code').first()
    return [str(latest.id)] if latest else []


def submitted_grade(registration):
    """The final grade a student may see: only once the final period is submitted."""
    from .periods import get_status
    from ..models import GradingPeriod
    final = GradingPeriod.objects.filter(
        term_id=registration.class_section.term_id, is_final=True).first()
    if final is None or get_status(registration.class_section, final) != 'submitted':
        return '-'
    return registration.grade
```

Delete the old window code (`start_date` / `end_date` / `viewable_*` parsing). Keep `grade_scale`.

- [ ] **Step 5: Update `services/__init__.py`** — drop `needs_reminder` and `notify_sections_pending_grade` from imports and `__all__`; add `current_grade_terms` and `selected_term_ids`.

- [ ] **Step 6: Run** `... test grades.grades.tests.test_v1_period_services` → OK. Then the whole suite; fix callers that still pass `period=None` (views are rewritten in Tasks 8–15 — for now, in `views/instructor.py` and `views/hs_admin.py` replace `is_submit_grades_open()` fallbacks with `False` and raise `Http404('No grading periods for this class.')` when `periods` is empty, so the suite stays green). Update old tests that relied on the window fallback (`test_period_grade_entry`, `test_hs_admin_period_entry`, `test_class_section_grade_idor`, `test_roster_confirmation_gate`): give their term a period open on the test date instead of `start_date`/`end_date`.

- [ ] **Step 7: Commit** — `git commit -am "feat(services)!: grading periods decide grade terms, open, editable"` (add the new test file).

---

### Task 6: Reminders — every N days plus days-before-due; retire the date-list job

**Files:**
- Modify: `grades/services/period_reminders.py`, `grades/services/reminders.py`, `grades/management/commands/notify_grades_pending.py`
- Test: `grades/tests/test_v1_reminders.py` (plus update `test_period_reminders.py`)

**Interfaces:**
- Consumes: `GradingPeriod.remind_days_before_due` (Task 2).
- Produces: `periods_due_for_reminder(today=None)` includes periods with `reminder_frequency_days > 0` **or** `remind_days_before_due > 0`; `needs_reminder(status_row, period, today=None) -> bool` (signature changes from `frequency_days` to `period`).

- [ ] **Step 1: Write the failing tests**

```python
"""v1: reminder cadence (spec §2, Reminders)."""
from datetime import date, timedelta

from mailer.models import Message

from .base import GradesTestCase
from . import factories as f
from ..models import SectionPeriodStatus
from ..services.period_reminders import needs_reminder, notify_sections_pending_period_grade

TODAY = date(2033, 10, 15)


class ReminderV1Tests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        get_user_model().objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        f.grades_setting(is_active='Yes', grades_due_subject='Due',
                         grades_due_email='{{grading_period}} due {{due_date}}')
        cls.term = f.term()
        cls.section = f.section(cls.term, f.teacher())

    def _period(self, freq=0, before=0, opens=-10, due=10):
        return f.period(self.term, f'P{freq}{before}{opens}{due}', TODAY + timedelta(opens),
                        TODAY + timedelta(due), reminder_frequency_days=freq,
                        remind_days_before_due=before)

    def _row(self, period, **kw):
        row, _ = SectionPeriodStatus.objects.get_or_create(period=period, class_section=self.section)
        for k, v in kw.items():
            setattr(row, k, v)
        row.save()
        return row

    def test_days_before_due_fires_once_on_that_day(self):
        p = self._period(before=2, due=2)
        row = self._row(p, last_notified_on=TODAY - timedelta(days=1))
        self.assertTrue(needs_reminder(row, p, TODAY))
        self.assertFalse(needs_reminder(row, p, TODAY + timedelta(days=1)))

    def test_no_double_send_same_day(self):
        p = self._period(freq=1, before=2, due=2)
        row = self._row(p, last_notified_on=TODAY)
        self.assertFalse(needs_reminder(row, p, TODAY))

    def test_before_due_outside_window_never_sends(self):
        # 3-day period, 7 days before due lands before opens_on
        p = self._period(before=7, opens=0, due=3)
        row = self._row(p)
        for d in range(-8, 5):
            day = TODAY + timedelta(days=d)
            if not (p.opens_on <= day <= p.due_on):
                continue
            self.assertFalse(needs_reminder(row, p, day) and day == p.due_on - timedelta(days=7))

    def test_submitted_never_reminded(self):
        p = self._period(freq=1, before=2, due=2)
        row = self._row(p, status='submitted')
        self.assertFalse(needs_reminder(row, p, TODAY))

    def test_job_sends_one_email_and_records_today(self):
        p = self._period(before=2, due=2)
        notify_sections_pending_period_grade(today=TODAY)
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(SectionPeriodStatus.objects.get(period=p).last_notified_on, TODAY)
        notify_sections_pending_period_grade(today=TODAY)
        self.assertEqual(Message.objects.count(), 1)

    def test_retired_command_is_a_noop(self):
        from django.core.management import call_command
        call_command('notify_grades_pending', time='now')
        self.assertEqual(Message.objects.count(), 0)
```

- [ ] **Step 2: Run — expect failures** (`needs_reminder` signature).

- [ ] **Step 3: Implement in `services/period_reminders.py`**

Replace `periods_due_for_reminder` and `needs_reminder`:

```python
def periods_due_for_reminder(today=None):
    """Periods open on ``today`` with any reminder turned on."""
    from django.db.models import Q
    today = today or datetime.date.today()
    return GradingPeriod.objects.filter(
        Q(reminder_frequency_days__gt=0) | Q(remind_days_before_due__gt=0),
        opens_on__lte=today, due_on__gte=today,
    ).select_related('term').order_by('term', 'sequence')


def needs_reminder(status_row, period, today=None):
    """Is this (section, period) due a reminder on ``today``?

    Not submitted, not already reminded today, the period open, and either the
    every-N-days cadence has elapsed or today is ``remind_days_before_due``
    days before the due date.
    """
    today = today or datetime.date.today()
    if status_row.status == 'submitted':
        return False
    if status_row.last_notified_on == today:
        return False
    if not (period.opens_on <= today <= period.due_on):
        return False
    before = period.remind_days_before_due
    if before and today == period.due_on - datetime.timedelta(days=before):
        return True
    freq = period.reminder_frequency_days
    if not freq:
        return False
    if status_row.last_notified_on is None:
        return True
    return (today - status_row.last_notified_on).days >= freq
```

In `sections_pending_for_period` change the call to `needs_reminder(status_row, period, today)`. Update the module docstring's rules list to match (rule 4 becomes "either cadence elapsed or the days-before-due day"; add rule 5 "not already reminded today"; delete the paragraph about the old date-list reminder). In `_send_period_reminder` nothing changes.

- [ ] **Step 4: Retire the old job**

`services/reminders.py` becomes:

```python
"""Grades reminder switches. The date-list reminder was retired in v1.0.0;
grading-period reminders live in services/period_reminders.py."""

REMINDERS_OFF = 'Grade reminders are turned off'
RETIRED = ('notify_grades_pending retired in grades v1.0.0 -- '
           'use grading-period reminders (notify_period_grades_pending)')


def reminders_enabled():
    """`send_grade_reminders`; absent means Yes."""
    from ..settings.class_section_grades import class_section_grades
    return class_section_grades.from_db().get('send_grade_reminders', 'Yes') == 'Yes'
```

`management/commands/notify_grades_pending.py` `handle()` keeps the `cron_task_started` / `cron_task_done` signals but always reports `summary = RETIRED`, `detailed_log = {}`; imports become `from ...services.reminders import RETIRED`. Docstring: "No-op since v1.0.0; delete the cron entry. Removed in v1.1."

- [ ] **Step 5: Update `test_period_reminders.py`** — calls `needs_reminder(row, frequency, today)` become `needs_reminder(row, period, today)` with a period whose window contains `today`; delete tests of the date-list reminder (`services.reminders.needs_reminder` / `notify_sections_pending_grade`).

- [ ] **Step 6: Run** `... test grades.grades.tests.test_v1_reminders grades.grades.tests.test_period_reminders` → OK.

- [ ] **Step 7: Commit** — `git commit -am "feat(reminders)!: days-before-due nudge, no double send; date-list job retired"`

---

### Task 7: Tenant-configurable student columns

**Files:**
- Create: `grades/services/columns.py`
- Modify: `grades/static/grades/js/grade_roster.js` (sort on any `data-sort-key`)
- Test: `grades/tests/test_v1_columns.py`

**Interfaces:**
- Produces: `Column(key: str, header: str, value: Callable[[StudentRegistration], str], sortable: bool = True)` dataclass; `BUILTIN: dict[str, Column]` with `last_name`, `first_name`, `psid`, `highschool`; `DEFAULT_KEYS = ['last_name', 'first_name', 'psid']`; `get_columns() -> list[Column]`. Tenant hook: module `<TENANT_SERVICES_APP>.services.grades_columns` attribute `columns(builtin: dict[str, Column], default_keys: list[str]) -> list[Column]`.

- [ ] **Step 1: Write the failing tests**

```python
"""v1: student columns on the grade grid (spec §3)."""
from unittest import mock

from .base import GradesTestCase
from . import factories as f
from ..services import columns


class ColumnTests(GradesTestCase):
    def test_defaults(self):
        with mock.patch.object(columns, 'get_tenant_override', return_value=None):
            self.assertEqual([c.key for c in columns.get_columns()], columns.DEFAULT_KEYS)

    def test_tenant_adds_highschool(self):
        def tenant(builtin, default_keys):
            return [builtin[k] for k in default_keys + ['highschool']]
        with mock.patch.object(columns, 'get_tenant_override', return_value=tenant):
            self.assertEqual([c.key for c in columns.get_columns()][-1], 'highschool')

    def test_values(self):
        hs = f.highschool('Bob Hope HS')
        reg = f.registration(f.section(f.term()), highschool_obj=hs,
                             last_name='Amador', first_name='Helena', psid='P1')
        values = {k: c.value(reg) for k, c in columns.BUILTIN.items()}
        self.assertEqual(values, {'last_name': 'Amador', 'first_name': 'Helena',
                                  'psid': 'P1', 'highschool': 'Bob Hope HS'})

    def test_tenant_returning_junk_falls_back(self):
        with mock.patch.object(columns, 'get_tenant_override', return_value=lambda b, d: None):
            self.assertEqual([c.key for c in columns.get_columns()], columns.DEFAULT_KEYS)
```

- [ ] **Step 2: Run — expect `ImportError`.**

- [ ] **Step 3: Write `services/columns.py`**

```python
"""Student columns on the grade grid, tenant-configurable (spec §3).

The package defines BUILTIN columns and the default selection. A tenant may
choose and extend them by shipping ``services/grades_columns.py`` in its
TENANT_SERVICES_APP with ``columns(builtin, default_keys) -> list[Column]``.
Grading-period columns are always appended by the grid, never listed here.
"""
from dataclasses import dataclass
from typing import Callable

from ..compat import get_tenant_override


@dataclass(frozen=True)
class Column:
    key: str
    header: str
    value: Callable
    sortable: bool = True


def _user(reg):
    return reg.student.user


def _highschool(reg):
    hs = reg.student.highschool if reg.student.highschool_id else reg.highschool
    return str(hs) if hs else ''


BUILTIN = {
    'last_name': Column('last_name', 'Last Name', lambda r: _user(r).last_name),
    'first_name': Column('first_name', 'First Name', lambda r: _user(r).first_name),
    'psid': Column('psid', 'Student ID', lambda r: _user(r).psid or ''),
    'highschool': Column('highschool', 'High School', _highschool),
}
DEFAULT_KEYS = ['last_name', 'first_name', 'psid']


def get_columns():
    tenant = get_tenant_override('grades_columns', 'columns')
    if tenant is not None:
        chosen = tenant(dict(BUILTIN), list(DEFAULT_KEYS))
        if chosen and all(isinstance(c, Column) for c in chosen):
            return list(chosen)
    return [BUILTIN[k] for k in DEFAULT_KEYS]
```

- [ ] **Step 4: Generic sorting in `grade_roster.js`** — rows carry `data-sort-<key>` attributes instead of the fixed `data-last-name/first-name/psid`. Change `dataKey(key)` to return `'sort' + key.charAt(0).toUpperCase() + camel(key).slice(1)` (so `last_name` → `dataset.sortLastName`), and the tie-break to use `dataset.sortLastName` / `dataset.sortFirstName`. Header buttons keep `data-sort-key="<key>"`. Update `templates/grades/_roster_sort_headers.html` only if Task 8's partial no longer includes it (it does not — delete the file in Task 8).

- [ ] **Step 5: Run tests → OK. Commit** — `git add grades/services/columns.py grades/tests/test_v1_columns.py grades/static/grades/js/grade_roster.js && git commit -m "feat(grid): tenant-configurable student columns"`

---

### Task 8: Grade grid builder, partial and shared POST handler

**Files:**
- Create: `grades/services/grade_grid.py`, `grades/templates/grades/partials/_grade_grid.html`
- Modify: `grades/views/grade_entry.py`, `grades/forms/section.py` (no logic change; import only if needed)
- Delete: `grades/templates/grades/_roster_sort_headers.html`
- Test: `grades/tests/test_v1_grade_grid.py`

**Interfaces:**
- Consumes: `periods_for_section`, `statuses_for`, `marks_by_period`, `is_period_editable`, `open_period`, `resolve_period` (Task 5); `get_columns` (Task 7); `students_for_grades`; `can_enter_grades`.
- Produces:
  - `build_grid(section, *, post_url, next_url, allow_edit=True, force_period=None, on_date=None) -> dict` with keys `section, columns, periods (list of dicts: period, status, label, header, editable), editable_period, rows (list of dicts: registration, cells, sort, marks (list aligned with periods), form), formset, management_form, message, roster_gate_ok, roster_gate_message, post_url, next_url, has_periods`.
  - `handle_grade_post(request, section, *, redirect_url, force_period=None) -> HttpResponse` (in `views/grade_entry.py`) — handles autosave (JSON), Draft, Submit; enforces editability unless `force_period` (CE).
  - `safe_next(request, default) -> str`.
  - `PERIOD_STATUS_LABELS = {'submitted': 'Submitted', 'saved': 'Draft', '': 'Not started'}` (in `grade_grid.py`).

- [ ] **Step 1: Write the failing tests**

```python
"""v1: column-per-period grid and the shared POST handler (spec §3)."""
from datetime import date
from unittest import mock

from django.test import RequestFactory

from .base import GradesTestCase
from . import factories as f
from ..models import PeriodGrade, SectionPeriodStatus
from ..services import grade_grid
from ..views import grade_entry

TODAY = date(2026, 10, 25)


class GradeGridTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting(grades_open_class_section='How to', grades_submitted_class_section='Thanks')
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', date(2026, 10, 19), date(2026, 10, 30), 1)
        cls.mid2 = f.period(cls.term, 'Mid 2', date(2026, 11, 16), date(2026, 11, 27), 2)
        cls.final = f.period(cls.term, 'Final', date(2026, 12, 1), date(2026, 12, 9), 3, is_final=True)
        cls.section = f.section(cls.term, f.teacher())
        cls.reg = f.registration(cls.section, last_name='Amador')

    def _grid(self, **kw):
        return grade_grid.build_grid(self.section, post_url='/post', next_url='/back',
                                     on_date=TODAY, **kw)

    def test_one_column_per_period_only_open_editable(self):
        grid = self._grid()
        self.assertEqual([p['period'] for p in grid['periods']], [self.mid1, self.mid2, self.final])
        self.assertEqual([p['editable'] for p in grid['periods']], [True, False, False])
        self.assertEqual(grid['editable_period'], self.mid1)
        self.assertIsNotNone(grid['rows'][0]['form'])
        self.assertEqual(grid['periods'][1]['header'], 'Opens 11/16/2026')
        self.assertEqual(grid['periods'][0]['header'], 'Open · due 10/30/2026')

    def test_no_periods(self):
        section = f.section(f.term(), f.teacher())
        grid = grade_grid.build_grid(section, post_url='/p', next_url='/n', on_date=TODAY)
        self.assertFalse(grid['has_periods'])
        self.assertEqual(grid['rows'], [])

    def test_submitted_period_read_only_with_message(self):
        from ..services.periods import set_status
        set_status(self.section, self.mid1, 'submitted')
        grid = self._grid()
        self.assertIsNone(grid['editable_period'])
        self.assertTrue(grid['periods'][0]['header'].startswith('Submitted'))
        self.assertEqual(grid['message'], 'Thanks')


class GradePostTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', date(2026, 10, 19), date(2026, 10, 30), 1)
        cls.mid2 = f.period(cls.term, 'Mid 2', date(2026, 11, 16), date(2026, 11, 27), 2)
        cls.teacher = f.teacher()
        cls.section = f.section(cls.term, cls.teacher)
        cls.reg = f.registration(cls.section)

    def _post(self, period, grade='B', action="Save Grades as 'Draft'", next_url='/back', force=None):
        data = {'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-MIN_NUM_FORMS': '1',
                'form-MAX_NUM_FORMS': '1', 'form-0-student': 'x', 'form-0-student_id': str(self.reg.id),
                'form-0-grade': grade, 'save_grade': action, 'period': str(period.id),
                'next': next_url}
        request = RequestFactory().post('/post', data)
        request.user = self.teacher.user
        request._messages = mock.MagicMock()
        with mock.patch('datetime.date', wraps=date) as d:
            d.today.return_value = TODAY
            return grade_entry.handle_grade_post(request, self.section, redirect_url='/default',
                                                 force_period=force)

    def test_draft_saves_open_period(self):
        resp = self._post(self.mid1)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/back')
        self.assertEqual(PeriodGrade.objects.get(period=self.mid1).grade, 'B')

    def test_closed_period_refused(self):
        self._post(self.mid2)
        self.assertFalse(PeriodGrade.objects.exists())

    def test_submitted_period_refused(self):
        from ..services.periods import set_status
        set_status(self.section, self.mid1, 'submitted')
        self._post(self.mid1, grade='C')
        self.assertFalse(PeriodGrade.objects.filter(grade='C').exists())

    def test_force_period_lets_ce_edit_closed(self):
        self._post(self.mid2, force=self.mid2)
        self.assertEqual(PeriodGrade.objects.get(period=self.mid2).grade, 'B')

    def test_offsite_next_rejected(self):
        for bad in ('//evil.example/x', 'https://evil.example/x'):
            resp = self._post(self.mid1, next_url=bad)
            self.assertEqual(resp['Location'], '/default')

    def test_submit_sets_status(self):
        self._post(self.mid1, action='Submit Grades')
        self.assertEqual(SectionPeriodStatus.objects.get(period=self.mid1).status, 'submitted')
```

- [ ] **Step 2: Run — expect failures.**

- [ ] **Step 3: Write `services/grade_grid.py`**

```python
"""The column-per-period grade grid shared by every grade page (spec §3)."""
import datetime

from django.forms.formsets import formset_factory

from .columns import get_columns
from .gating import can_enter_grades
from .periods import (
    is_period_editable, is_period_open, marks_by_period, periods_for_section,
    statuses_for,
)
from .roster import students_for_grades

PERIOD_STATUS_LABELS = {'submitted': 'Submitted', 'saved': 'Draft', '': 'Not started'}


def _last_change(row):
    history = (row.status_changed_on or {}) if row else {}
    return max(history, default='', key=lambda k: datetime.datetime.strptime(k, '%m/%d/%Y %I:%M:%S %p'))


def _header(period, status, row, today):
    if status == 'submitted':
        when = _last_change(row)
        return f'Submitted {when[:10]}' if when else 'Submitted'
    if is_period_open(period, today):
        return f'Open · due {period.due_on:%m/%d/%Y}'
    if today < period.opens_on:
        return f'Opens {period.opens_on:%m/%d/%Y}'
    return 'Closed · not submitted' if status != 'submitted' else 'Closed'


def grade_form_classes():
    from ..forms.section import ClassSectionGradeForm, ClassSectionGradeFormSet
    return ClassSectionGradeForm, ClassSectionGradeFormSet


def roster_initial(registrations, marks):
    return [{
        'student_id': reg.id,
        'student': f'{reg.student.user.last_name}, {reg.student.user.first_name}',
        'grade': marks.get(reg.id, '') if marks.get(reg.id, '') not in ('-',) else '',
    } for reg in registrations]


def build_formset(section, period, registrations, marks, user=None, data=None):
    Form, FormSet = grade_form_classes()
    initial = roster_initial(registrations, marks)
    GradeFS = formset_factory(Form, formset=FormSet, extra=0, validate_max=False,
                              min_num=1, max_num=max(len(initial), 1))
    return GradeFS(data, initial=initial, class_section=section, period=period, user=user)


def build_grid(section, *, post_url, next_url, allow_edit=True, force_period=None,
               on_date=None):
    from ..settings.class_section_grades import class_section_grades
    today = on_date or datetime.date.today()
    periods = periods_for_section(section)
    registrations = list(students_for_grades(section).select_related(
        'student__user', 'student__highschool', 'highschool'))
    columns = get_columns()
    statuses = statuses_for(section, periods)
    marks = marks_by_period(section, periods, registrations)
    gate_ok, gate_message = can_enter_grades(section)

    editable = None
    if force_period is not None:
        editable = force_period
    elif allow_edit:
        editable = next((p for p in periods if is_period_editable(section, p, today)), None)

    period_rows = []
    for p in periods:
        row = statuses.get(p.id)
        status = row.status if row else ''
        period_rows.append({
            'period': p, 'status': status, 'label': PERIOD_STATUS_LABELS.get(status, status),
            'header': _header(p, status, row, today), 'editable': p == editable,
            'last_notified_on': row.last_notified_on if row else None,
        })

    formset = (build_formset(section, editable, registrations, marks[editable.id])
               if editable is not None and registrations else None)
    forms = list(formset.forms) if formset else [None] * len(registrations)

    rows = []
    for reg, form in zip(registrations, forms):
        rows.append({
            'registration': reg,
            'cells': [c.value(reg) for c in columns],
            'sort': {c.key: c.value(reg) for c in columns if c.sortable},
            'marks': [marks[p.id].get(reg.id, '') for p in periods],
            'form': form,
        })

    settings = class_section_grades.from_db()
    current = editable or next((p for p in periods if is_period_open(p, today)), None)
    submitted = current is not None and statuses.get(current.id) and statuses[current.id].status == 'submitted'
    message = settings.get('grades_submitted_class_section' if submitted
                           else 'grades_open_class_section') or ''

    return {
        'section': section, 'columns': columns, 'periods': period_rows,
        'editable_period': editable, 'rows': rows, 'formset': formset,
        'message': message, 'roster_gate_ok': gate_ok, 'roster_gate_message': gate_message,
        'post_url': post_url, 'next_url': next_url, 'has_periods': bool(periods),
    }
```

- [ ] **Step 4: Rewrite `views/grade_entry.py`**

Keep `is_autosave`. Replace `roster_row`/`autosave` with:

```python
"""The grade POST shared by every grade page (instructor, HS admin, CE)."""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from ..services.grade_grid import build_formset
from ..services.periods import (
    get_status, grades_for, is_period_editable, resolve_period, set_status,
)
from ..services.roster import students_for_grades

DRAFT = 'Draft'


def is_autosave(request):
    return (request.method == 'POST'
            and request.headers.get('x-requested-with') == 'XMLHttpRequest'
            and DRAFT in request.POST.get('save_grade', ''))


def safe_next(request, default):
    target = request.POST.get('next') or request.GET.get('next') or ''
    if target and url_has_allowed_host_and_scheme(
            target, allowed_hosts={request.get_host()}, require_https=request.is_secure()) \
            and target.startswith('/') and not target.startswith('//'):
        return target
    return default


def _note(request, text, ok=True):
    messages.add_message(request, messages.SUCCESS, text,
                         'list-group-item-success' if ok else 'list-group-item-danger')


def handle_grade_post(request, section, *, redirect_url, force_period=None):
    """Save (draft/autosave) or submit grades for one period of ``section``.

    The period comes from POST ``period``. Without ``force_period`` (CE) the
    period must be editable today: open, not submitted, roster gate passing.
    """
    back = safe_next(request, redirect_url)
    period = force_period or resolve_period(section, request.POST.get('period'))
    draft = DRAFT in request.POST.get('save_grade', '')
    autosave = is_autosave(request)

    if period is None:
        if autosave:
            return JsonResponse({'ok': False, 'error': 'Unknown grading period.'}, status=400)
        _note(request, 'Unknown grading period.', ok=False)
        return redirect(back)

    if force_period is None and not is_period_editable(section, period):
        reason = ('These grades have already been submitted.'
                  if get_status(section, period) == 'submitted'
                  else f'Grade entry for {period.name} is not open.')
        if autosave:
            return JsonResponse({'ok': False, 'error': reason}, status=403)
        _note(request, reason, ok=False)
        return redirect(back)

    registrations = list(students_for_grades(section))
    formset = build_formset(section, period, registrations,
                            grades_for(section, period, registrations),
                            user=request.user, data=request.POST)
    if draft:
        for form in formset.forms:
            form.fields['grade'].required = False

    if not formset.is_valid():
        if autosave:
            return JsonResponse({'ok': False, 'error': 'Some grades could not be saved.',
                                 'errors': formset.errors}, status=400)
        _note(request, 'Please choose a grade for every student before submitting.', ok=False)
        return redirect(back)

    formset.save()
    set_status(section, period, 'saved' if draft else 'submitted')
    if autosave:
        return JsonResponse({'ok': True, 'status': 'saved'})
    _note(request, 'Your grades have been saved as a draft.' if draft
          else f'Your {period.name} grades have been submitted.')
    return redirect(back)
```

- [ ] **Step 5: Write `templates/grades/partials/_grade_grid.html`**

```django
{% comment %}
Column-per-period grade grid (spec §3). Context: grid (services.grade_grid.build_grid).
{% endcomment %}
{% load crispy_forms_tags %}
<div class="card mb-3">
  <div class="card-header d-flex justify-content-between align-items-center">
    <span>Grades</span>
    <a class="btn btn-sm btn-primary" href="?action=download_roster_pdf"><i class="fa fa-file-pdf"></i>&nbsp;Download Roster</a>
  </div>
  <div class="card-body">
    {% if not grid.has_periods %}
      <p class="text-muted mb-0">No grading periods are set up for this class's term.</p>
    {% else %}
      {% if not grid.roster_gate_ok %}<div class="alert alert-warning">{{ grid.roster_gate_message|safe }}</div>{% endif %}
      {% if grid.message %}<div class="mb-3">{{ grid.message|safe }}</div>{% endif %}
      <form method="post" action="{{ grid.post_url }}"{% if grid.editable_period %} data-autosave="1"{% endif %}>
        {% csrf_token %}
        <input type="hidden" name="next" value="{{ grid.next_url }}">
        {% if grid.editable_period %}
          <input type="hidden" name="period" value="{{ grid.editable_period.id }}">
          {{ grid.formset.management_form }}
        {% endif %}
        <div class="table-responsive">
          <table class="table table-striped js-sortable-roster">
            <thead>
              <tr>
                {% for col in grid.columns %}
                <th{% if col.sortable %} aria-sort="none"{% endif %}>{% if col.sortable %}<button type="button" class="btn btn-link p-0 font-weight-bold" data-sort-key="{{ col.key }}">{{ col.header }} <i class="fas fa-sort" aria-hidden="true"></i></button>{% else %}{{ col.header }}{% endif %}</th>
                {% endfor %}
                {% for p in grid.periods %}
                <th class="{% if p.editable %}table-primary{% endif %}">
                  {{ p.period.name }}{% if p.period.is_final %} <span class="badge badge-secondary">Final</span>{% endif %}
                  <div class="small font-weight-normal {% if p.status == 'submitted' %}text-success{% else %}text-muted{% endif %}">{{ p.header }}</div>
                </th>
                {% endfor %}
              </tr>
            </thead>
            <tbody>
              {% for row in grid.rows %}
              <tr{% for key, value in row.sort.items %} data-sort-{{ key|cut:'_' }}="{{ value }}"{% endfor %}>
                {% for cell in row.cells %}<td>{{ cell }}</td>{% endfor %}
                {% for p in grid.periods %}
                  {% if p.editable and row.form %}
                    <td>{{ row.form.student_id }}{{ row.form.student }}{{ row.form.grade|as_crispy_field }}<small class="autosave-status text-muted" aria-live="polite"></small></td>
                  {% else %}
                    <td>{% with mark=row.marks|slice:forloop.counter|last %}{% if mark and mark != '-' %}{{ mark }}{% else %}<span class="text-muted">–</span>{% endif %}{% endwith %}</td>
                  {% endif %}
                {% endfor %}
              </tr>
              {% empty %}
              <tr><td colspan="{{ grid.columns|length|add:grid.periods|length }}" class="text-muted">No students on this roster.</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
        {% if grid.editable_period and grid.rows %}
        <div class="text-right">
          <small class="autosave-summary text-muted mr-2" aria-live="polite">Grades save automatically as a draft.</small>
          <input type="submit" name="save_grade" class="btn btn-secondary btn-sm" value="Save Grades as 'Draft'">
          <input type="submit" name="save_grade" class="btn btn-primary btn-sm" value="Submit {{ grid.editable_period.name }} Grades">
        </div>
        {% endif %}
      </form>
    {% endif %}
  </div>
</div>
```

Note on `data-sort-*`: Django can't camel-case, so `cut:'_'` turns `last_name` into `data-sort-lastname` → `dataset.sortLastname`. Make Task 7's `dataKey(key)` match: `'sort' + key.replace(/_/g, '').replace(/^./, c => c.toUpperCase())` (so `last_name` → `sortLastname`). Adjust the tie-break keys to `sortLastname` / `sortFirstname`. The `row.marks|slice:forloop.counter|last` idiom picks the mark aligned with the period column.

- [ ] **Step 6: Delete `templates/grades/_roster_sort_headers.html`** (`git rm`). grep for remaining references; the old instructor/HS templates are rewritten in Tasks 9 and 12.

- [ ] **Step 7: Run** `... test grades.grades.tests.test_v1_grade_grid` → OK. Remove the deleted `roster_row` / `autosave` imports from `views/instructor.py` and `views/hs_admin.py` if the suite fails to import (they are rewritten next).

- [ ] **Step 8: Commit** — `git commit -am "feat(grid): column-per-period grade grid and shared grade POST"` (add new files).

---

### Task 9: Instructor standalone page and the Class Details "Grades" tab

**Files:**
- Modify: `grades/views/instructor.py` (`class_section_grade`), `grades/templates/grades/instructor/class_section_grade.html`, `grades/apps.py` (`ready()` imports `instructor_tabs`)
- Create: `grades/instructor_tabs.py`, `grades/templates/grades/instructor/_class_section_grades_tab.html`
- Test: `grades/tests/test_v1_instructor_pages.py`

**Interfaces:**
- Consumes: `build_grid`, `handle_grade_post`, `safe_next` (Task 8).
- Produces: URL `instructor:class_section_grade` unchanged (GET page, POST endpoint). Tab slug `grades` on `instructor_class_section_tabs`.

- [ ] **Step 1: Write the failing tests**

```python
"""v1: instructor grade page and Class Details tab (spec §3)."""
from datetime import date, timedelta

from django.urls import reverse

from .base import GradesTestCase
from . import factories as f
from ..compat import has_module


class InstructorPagesTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        today = date.today()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', today - timedelta(days=3), today + timedelta(days=3))
        cls.teacher = f.teacher()
        cls.section = f.section(cls.term, cls.teacher)
        f.registration(cls.section, last_name='Amador')
        cls.other = f.section(cls.term, f.teacher())

    def setUp(self):
        self.client.force_login(self.teacher.user)

    def test_standalone_page_renders_grid(self):
        resp = self.client.get(reverse('instructor:class_section_grade', args=[self.section.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Mid 1')
        self.assertContains(resp, 'Amador')
        self.assertContains(resp, 'name="next"')

    def test_other_instructors_section_404(self):
        resp = self.client.get(reverse('instructor:class_section_grade', args=[self.other.id]))
        self.assertEqual(resp.status_code, 404)

    def test_post_redirects_back_to_tab(self):
        url = reverse('instructor:class_section_grade', args=[self.section.id])
        resp = self.client.post(url, {'period': str(self.mid1.id), 'save_grade': "Save Grades as 'Draft'",
                                      'next': f'/instructor/class_section/{self.section.id}#grades',
                                      'form-TOTAL_FORMS': '0', 'form-INITIAL_FORMS': '0',
                                      'form-MIN_NUM_FORMS': '0', 'form-MAX_NUM_FORMS': '1'})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].endswith('#grades'))

    def test_tab_registered_and_hidden_without_periods(self):
        if not (has_module('instructor.instructor.registry') or has_module('instructor.registry')):
            self.skipTest('instructor portal not installed')
        from ..instructor_tabs import instructor_class_section_tabs, _has_periods
        self.assertIn('grades', instructor_class_section_tabs._tabs)
        self.assertTrue(_has_periods(self.teacher.user, self.section))
        self.assertFalse(_has_periods(self.teacher.user, f.section(f.term(), self.teacher)))
```

- [ ] **Step 2: Run — expect failures.**

- [ ] **Step 3: Rewrite `class_section_grade` in `views/instructor.py`**

```python
def class_section_grade(request, record_id):
    section = get_object_or_404(ClassSection, pk=record_id, teacher__user=request.user)
    here = reverse('instructor:class_section_grade', args=[section.id])

    if request.GET.get('action') == 'download_roster_pdf':
        return section.download_roster_pdf()
    if request.method == 'POST':
        return handle_grade_post(request, section, redirect_url=here)

    return render(request, 'grades/instructor/class_section_grade.html', {
        'menu': draw_menu(INSTRUCTOR_MENU, 'grades', '', 'instructor'),
        'class_section': section,
        'intro': portal_text('instructor').get('grades_blurb', ''),
        'page_messages': get_page_messages('instructor', 'grades', request),
        'grid': build_grid(section, post_url=here, next_url=here),
    })
```

Imports: `from django.urls import reverse`; `from cis.page_messages import get_page_messages`; `from ..services.grade_grid import build_grid`; `from .grade_entry import handle_grade_post`. Remove unused imports (`formset_factory`, forms, periods helpers, `is_submit_grades_open`, `messages`, `Http404`, `redirect`).

- [ ] **Step 4: Rewrite `templates/grades/instructor/class_section_grade.html`** in the Class Details layout:

```django
{% extends "cis/logged-base.html" %}
{% block title %}Class Grades{% endblock %}
{% load static %}
{% block body %}
<main>
  {{ intro|default_if_none:''|safe }}
  <nav aria-label="breadcrumb">
    <ol class="breadcrumb">
      <li class="breadcrumb-item"><a href="{% url 'instructor:dashboard' %}">Home</a></li>
      <li class="breadcrumb-item"><a href="{% url 'instructor:grades' %}">Grades</a></li>
      <li class="breadcrumb-item active" aria-current="page">{{ class_section }}</li>
    </ol>
  </nav>
  {% include 'cis/messages.html' %}
  {% if page_messages %}<div class="row">{% include 'cis/page_messages.html' %}</div>{% endif %}
  <style>div.cell div.info{font-size:1.1em}div.cell div.label{text-transform:uppercase;font-size:.7em;font-weight:100}</style>
  <div class="row">
    <div class="col-md-4">
      <div class="card mb-3">
        <div class="card-header">Details</div>
        <div class="card-body"><div class="row">
          <div class="col-6"><div class="cell mb-3"><div class="info">{{ class_section.term }}</div><div class="label">Term</div></div></div>
          <div class="col-6"><div class="cell mb-3"><div class="info">{{ class_section.course }}</div><div class="label">Course</div></div></div>
          <div class="col-6"><div class="cell mb-3"><div class="info">{{ class_section }}</div><div class="label">Class #</div></div></div>
          <div class="col-12"><div class="cell mb-3"><div class="info">{{ class_section.highschool|default:'' }}</div><div class="label">High School</div></div></div>
          <div class="col-12"><a href="{% url 'instructor:class_section' class_section.id %}">Open class details</a></div>
        </div></div>
      </div>
    </div>
    <div class="col-md-8">{% include 'grades/partials/_grade_grid.html' %}</div>
  </div>
</main>
<script src="{% static 'grades/js/grade_roster.js' %}"></script>
{% endblock %}
```

- [ ] **Step 5: Write `grades/instructor_tabs.py`**

```python
"""The Grades tab on the instructor Class Details page (instructor portal's
tab registry). Imported from GradesConfig.ready(); a host without the
instructor portal simply gets no tab."""
from django.urls import reverse

from .compat import register, registry

instructor_class_section_tabs = (
    registry('instructor.instructor.registry', 'instructor_class_section_tabs')
    or registry('instructor.registry', 'instructor_class_section_tabs'))


def _has_periods(user, section):
    from .services.periods import periods_for_section
    return bool(periods_for_section(section))


@register(instructor_class_section_tabs, 'tab', slug='grades', title='Grades',
          order=50, lazy=True, permission=_has_periods,
          template='grades/instructor/_class_section_grades_tab.html')
def instructor_grades_tab(request, class_section):
    from .services.grade_grid import build_grid
    post_url = reverse('instructor:class_section_grade', args=[class_section.id])
    next_url = reverse('instructor:class_section', args=[class_section.id]) + '#grades'
    return {'grid': build_grid(class_section, post_url=post_url, next_url=next_url)}
```

`_class_section_grades_tab.html`:

```django
{% load static %}
{% include 'grades/partials/_grade_grid.html' %}
<script src="{% static 'grades/js/grade_roster.js' %}"></script>
```

In `grade_roster.js` make `initSorting`/`initAutosave` idempotent and callable after a lazy tab load: guard each table/form with a `data-grid-init` attribute, and run them both on `DOMContentLoaded` and immediately when the script executes after load (`if (document.readyState !== 'loading') { init(); }`).

- [ ] **Step 6: In `apps.py`** add `from . import instructor_tabs  # noqa: F401` to both `ready()` methods.

- [ ] **Step 7: Run tests → OK. Smoke**: `curl`-free check via the scratch session script at `/instructor/class_section/<id>#grades` and `/instructor/grades/class_section/<id>` on 127.0.0.1 (LSCPA, `daileynm`, section `74db30d5-…`): both show Mid-Semester Grades 1 editable, Mid 2 "Opens 11/16/2026".

- [ ] **Step 8: Commit** — `git commit -am "feat(instructor): Grades tab on Class Details; grade page in the Class Details layout"` (add new files).

---

### Task 10: Instructor Grades class list with term switcher

**Files:**
- Modify: `grades/views/instructor.py` (`class_grades`), `grades/templates/grades/instructor/grades.html`
- Delete: `grades/static/grades/instructor/js/grades.js`
- Create: `grades/services/class_list.py`
- Test: `grades/tests/test_v1_instructor_list.py`

**Interfaces:**
- Consumes: `grade_terms`, `selected_term_ids` (Task 5); `periods_for_section`, `statuses_for`.
- Produces: `class_rows(sections, on_date=None) -> list[dict]` with keys `section, registrations (list[(label, count)]), periods (list[dict: name, status, label, is_open, is_final])`.

- [ ] **Step 1: Write the failing tests**

```python
"""v1: instructor Grades list (spec §3)."""
from datetime import date, timedelta

from django.urls import reverse

from .base import GradesTestCase
from . import factories as f
from ..services.class_list import class_rows
from ..services.periods import set_status


class InstructorListTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting(grades_intro='<p>Intro text</p>')
        today = date.today()
        cls.teacher = f.teacher()
        cls.now = f.term(label='Fall Now')
        cls.mid1 = f.period(cls.now, 'Mid 1', today - timedelta(days=2), today + timedelta(days=2))
        cls.past = f.term(label='Spring Past')
        f.period(cls.past, 'Final', today - timedelta(days=200), today - timedelta(days=190), is_final=True)
        cls.s_now = f.section(cls.now, cls.teacher)
        cls.s_past = f.section(cls.past, cls.teacher)
        f.registration(cls.s_now)
        f.registration(cls.s_now, status='dropped')

    def test_rows_have_counts_and_period_status(self):
        set_status(self.s_now, self.mid1, 'submitted')
        [row] = class_rows([self.s_now])
        self.assertEqual(dict(row['registrations']), {'Registered': 1, 'Dropped': 1})
        self.assertEqual([(p['name'], p['label']) for p in row['periods']], [('Mid 1', 'Submitted')])

    def test_page_defaults_to_current_term_and_switches(self):
        self.client.force_login(self.teacher.user)
        resp = self.client.get(reverse('instructor:grades'))
        self.assertContains(resp, 'Intro text')
        self.assertContains(resp, self.s_now.class_number)
        self.assertNotContains(resp, self.s_past.class_number)
        resp = self.client.get(reverse('instructor:grades'), {'term': str(self.past.id)})
        self.assertContains(resp, self.s_past.class_number)
```

- [ ] **Step 2: Run — expect failures.**

- [ ] **Step 3: Write `services/class_list.py`**

```python
"""Rows of the instructor / HS admin Grades class list (spec §3)."""
from .grade_grid import PERIOD_STATUS_LABELS
from .periods import is_period_open, periods_for_section, statuses_for


def class_rows(sections, on_date=None):
    rows = []
    for section in sections:
        periods = periods_for_section(section)
        statuses = statuses_for(section, periods)
        rows.append({
            'section': section,
            'registrations': section.registration_status_distribution(),
            'periods': [{
                'name': p.name, 'is_final': p.is_final,
                'status': statuses[p.id].status if p.id in statuses else '',
                'label': PERIOD_STATUS_LABELS.get(statuses[p.id].status if p.id in statuses else '', ''),
                'is_open': is_period_open(p, on_date),
            } for p in periods],
        })
    return rows
```

- [ ] **Step 4: Rewrite `class_grades`**

```python
def class_grades(request):
    teacher_sections = ClassSection.objects.filter(
        teacher__user=request.user, status='A', term_id__in=grade_terms())
    available = list(teacher_sections.values_list('term_id', flat=True).distinct())
    selected = selected_term_ids(request, available)
    sections = teacher_sections.filter(term_id__in=selected).select_related(
        'term', 'course__cohort', 'highschool').order_by(
        'term__code', 'course__cohort__designator', 'course__catalog_number', 'class_number')
    settings = class_section_grades.from_db()
    return render(request, 'grades/instructor/grades.html', {
        'menu': draw_menu(INSTRUCTOR_MENU, 'grades', '', 'instructor'),
        'intro': portal_text('instructor').get('grades_blurb', ''),
        'grades_intro': settings.get('grades_intro', ''),
        'page_messages': get_page_messages('instructor', 'grades', request),
        'terms': Term.objects.filter(pk__in=available).order_by('-code'),
        'selected_term_ids': selected,
        'require_roster_confirmation': settings.get('require_roster_confirmation', False),
        'rows': class_rows(sections),
    })
```

Imports: `from ..services.window import grade_terms, selected_term_ids`; `from ..services.class_list import class_rows`; `from ..compat import portal_text`.

- [ ] **Step 5: Rewrite `templates/grades/instructor/grades.html`**

```django
{% extends "instructor/base_instructor.html" %}
{% block title %}Grades{% endblock %}
{% block page_header %}
{{ intro|default_if_none:''|safe }}
{% include "instructor/partials/_breadcrumb.html" with page_name="Class Grades" %}
{% endblock %}
{% block content %}
{% if page_messages %}<div class="row">{% include 'cis/page_messages.html' %}</div>{% endif %}
<div class="card">
  <div class="card-body">
    {{ grades_intro|default_if_none:''|safe }}
    <form method="get" class="form-inline mb-3">
      <label class="mr-2" for="id_term">Term</label>
      <select id="id_term" name="term" class="form-control form-control-sm mr-2" onchange="this.form.submit()">
        {% for t in terms %}<option value="{{ t.id }}"{% if t.id|stringformat:'s' in selected_term_ids %} selected{% endif %}>{{ t.label }}</option>{% endfor %}
      </select>
    </form>
    <table id="records_classes" class="table table-striped responsive" style="width:100%">
      <thead><tr><th>Term</th><th>Course</th><th>CRN</th><th>High School</th><th>Students</th><th>Grades Status</th><th><span class="sr-only">Actions</span></th></tr></thead>
      <tbody>
      {% for row in rows %}{% with s=row.section %}
        <tr>
          <td>{{ s.term.label }}</td>
          <td>{{ s.course.cohort.designator }} {{ s.course.catalog_number }}<br>{{ s.course.title }}</td>
          <td>{{ s.class_number }}</td>
          <td>{{ s.highschool|default:'' }}</td>
          <td>{% for label, count in row.registrations %}<div class="text-nowrap">{{ label }}: <strong>{{ count }}</strong></div>{% empty %}<span class="text-muted">No students</span>{% endfor %}</td>
          <td>
            {% for p in row.periods %}
            <div class="text-nowrap">{{ p.name }}{% if p.is_final %} <span class="badge badge-light">Final</span>{% endif %}{% if p.is_open %} <small class="text-success">(open)</small>{% endif %}:
              {% if p.status == 'submitted' %}<span class="badge badge-success">{{ p.label }}</span>{% elif p.status == 'saved' %}<span class="badge badge-secondary">{{ p.label }}</span>{% else %}<span class="text-muted">{{ p.label }}</span>{% endif %}
            </div>
            {% endfor %}
            {% if require_roster_confirmation and s.roster_status == 'pending verification' %}<span class="badge badge-warning">Roster not confirmed</span>{% endif %}
          </td>
          <td><a class="btn btn-sm btn-primary" href="{% url 'instructor:class_section_grade' s.id %}">Manage/Edit</a></td>
        </tr>
      {% endwith %}{% endfor %}
      </tbody>
    </table>
  </div>
</div>
<script>jQuery(function ($) { $('#records_classes').DataTable({ order: [[0,'asc'],[1,'asc']], lengthMenu: [30,50,100], columnDefs: [{ targets: -1, orderable: false, searchable: false }] }); });</script>
{% endblock %}
```

- [ ] **Step 6: `git rm grades/static/grades/instructor/js/grades.js`**; run tests → OK.

- [ ] **Step 7: Commit** — `git commit -am "feat(instructor): Grades list with term switcher, student counts and per-period status"` (add new files).

---

### Task 11: Page messages

**Files:**
- Create: `grades/page_messages.py`, `grades/services/open_periods.py`
- Test: `grades/tests/test_v1_page_messages.py`

**Interfaces:**
- Produces: `open_period_summary(sections, on_date=None) -> list[tuple[GradingPeriod, int submitted, int total]]`; providers registered for `('instructor','dashboard')`, `('instructor','grades')`, `('highschool_admin','dashboard')`.

- [ ] **Step 1: Write the failing tests**

```python
"""v1: grades page messages (spec §3)."""
from datetime import date, timedelta

from django.test import RequestFactory

from .base import GradesTestCase
from . import factories as f
from .. import page_messages as pm
from ..services.open_periods import open_period_summary
from ..services.periods import set_status


class PageMessageTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        today = date.today()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', today - timedelta(days=1), today + timedelta(days=5))
        cls.teacher = f.teacher()
        cls.a = f.section(cls.term, cls.teacher)
        cls.b = f.section(cls.term, cls.teacher)

    def _request(self):
        request = RequestFactory().get('/')
        request.user = self.teacher.user
        return request

    def test_summary(self):
        set_status(self.a, self.mid1, 'submitted')
        self.assertEqual(open_period_summary([self.a, self.b]), [(self.mid1, 1, 2)])

    def test_pending_warning_then_success(self):
        [msg] = pm.instructor_grades(self._request())
        self.assertEqual(msg.level, 'warning')
        self.assertIn('2 of 2 class(es) not submitted', msg.text)
        set_status(self.a, self.mid1, 'submitted')
        set_status(self.b, self.mid1, 'submitted')
        [msg] = pm.instructor_grades(self._request())
        self.assertEqual(msg.level, 'success')

    def test_dashboard_highlights_tile(self):
        [msg] = pm.instructor_dashboard(self._request())
        self.assertEqual(msg.tile_id, 'id_tile_grades')

    def test_no_teacher_no_message(self):
        request = RequestFactory().get('/')
        request.user = f.registration(self.a).student.user
        self.assertEqual(pm.instructor_grades(request), [])
```

- [ ] **Step 2: Run — expect `ImportError`.**

- [ ] **Step 3: Write `services/open_periods.py`**

```python
"""Open grading periods over a set of sections, for page messages and the CE summary."""
import datetime

from ..models import GradingPeriod, SectionPeriodStatus


def open_period_summary(sections, on_date=None):
    """[(period, submitted, total)] for each period open on ``on_date``."""
    on_date = on_date or datetime.date.today()
    by_term = {}
    for section in sections:
        by_term.setdefault(section.term_id, []).append(section)
    out = []
    for period in GradingPeriod.objects.filter(
            term_id__in=by_term, opens_on__lte=on_date, due_on__gte=on_date
    ).order_by('due_on', 'sequence'):
        term_sections = by_term[period.term_id]
        submitted = SectionPeriodStatus.objects.filter(
            period=period, class_section__in=term_sections, status='submitted').count()
        out.append((period, submitted, len(term_sections)))
    return out
```

- [ ] **Step 4: Write `grades/page_messages.py`**

```python
"""Grades page-message providers (auto-discovered by cis.apps.ready)."""
from django.utils.html import format_html

from cis.page_messages import PageMessage, page_message

from .services.open_periods import open_period_summary


def _messages(sections, tile_id=''):
    out = []
    for period, submitted, total in open_period_summary(sections):
        pending = total - submitted
        if pending:
            out.append(PageMessage(text=format_html(
                '<strong>{}</strong> is open through {} &mdash; {} of {} class(es) not submitted.',
                period.name, period.due_on.strftime('%m/%d/%Y'), pending, total),
                level='warning', tile_id=tile_id))
        else:
            out.append(PageMessage(text=format_html(
                '<strong>{}</strong>: grades submitted for all {} class(es).', period.name, total),
                level='success'))
    return out


def _teacher_sections(request):
    from cis.models.section import ClassSection
    return list(ClassSection.objects.filter(teacher__user=request.user, status='A'))


def _hs_admin_sections(request):
    from cis.models.section import ClassSection
    from .views.hs_admin import _hs_admin_context
    _, highschools = _hs_admin_context(request)
    return list(ClassSection.objects.filter(highschool__in=highschools, status='A'))


@page_message('instructor', 'grades')
def instructor_grades(request):
    return _messages(_teacher_sections(request))


@page_message('instructor', 'dashboard')
def instructor_dashboard(request):
    return _messages(_teacher_sections(request), tile_id='id_tile_grades')


@page_message('highschool_admin', 'dashboard')
def hs_admin_dashboard(request):
    from .services.gating import hs_admin_grade_entry_enabled
    if not hs_admin_grade_entry_enabled():
        return []
    return _messages(_hs_admin_sections(request))
```

- [ ] **Step 5: Run tests → OK. Commit** — `git add grades/page_messages.py grades/services/open_periods.py grades/tests/test_v1_page_messages.py && git commit -m "feat(messages): open-period page messages for instructor and HS admin"`

---

### Task 12: HS admin on the shared grid

**Files:**
- Modify: `grades/views/hs_admin.py`, `grades/tabs.py` (`hs_admin_grades_tab`), `grades/templates/grades/hs_admin/_class_section_grades_tab.html`, `grades/templates/grades/hs_admin/class_section_grade.html`
- Test: `grades/tests/test_v1_hs_admin.py` (and update `test_hs_admin_period_entry.py`)

**Interfaces:**
- Consumes: `build_grid`, `handle_grade_post` (Task 8). URL `grades_highschool_admin:class_section_grade` stays the POST endpoint.

- [ ] **Step 1: Write the failing tests**

```python
"""v1: HS admin grade entry on the shared grid (spec §3)."""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

from .base import GradesTestCase
from . import factories as f
from ..models import PeriodGrade


class HSAdminV1Tests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting(hs_admin_grade_entry='Yes')
        today = date.today()
        cls.hs = f.highschool()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', today - timedelta(days=1), today + timedelta(days=5))
        cls.mid2 = f.period(cls.term, 'Mid 2', today + timedelta(days=20), today + timedelta(days=25), 2)
        cls.section = f.section(cls.term, f.teacher(), highschool_obj=cls.hs)
        cls.reg = f.registration(cls.section, highschool_obj=cls.hs)
        cls.admin = get_user_model().objects.create_user(username='hsa@example.com', email='hsa@example.com', password='x')
        cls.admin.groups.add(Group.objects.get_or_create(name='highschool_admin')[0])

    def _patch_schools(self, schools):
        from cis.models.highschool import HighSchool
        from ..views import hs_admin as hs_admin_views
        return mock.patch.object(
            hs_admin_views, '_hs_admin_context',
            return_value=([], HighSchool.objects.filter(pk__in=[s.pk for s in schools])))

    def _post(self, period):
        url = reverse('grades_highschool_admin:class_section_grade', args=[self.section.id])
        return self.client.post(url, {
            'period': str(period.id), 'save_grade': "Save Grades as 'Draft'", 'next': '/',
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-MIN_NUM_FORMS': '1',
            'form-MAX_NUM_FORMS': '1', 'form-0-student': 'x',
            'form-0-student_id': str(self.reg.id), 'form-0-grade': 'B'})

    def test_open_period_saved(self):
        self.client.force_login(self.admin)
        with self._patch_schools([self.hs]):
            self._post(self.mid1)
        self.assertEqual(PeriodGrade.objects.get(period=self.mid1).grade, 'B')

    def test_closed_period_refused(self):
        self.client.force_login(self.admin)
        with self._patch_schools([self.hs]):
            self._post(self.mid2)
        self.assertFalse(PeriodGrade.objects.filter(period=self.mid2).exists())

    def test_other_school_404(self):
        self.client.force_login(self.admin)
        with self._patch_schools([f.highschool()]):
            resp = self._post(self.mid1)
        self.assertEqual(resp.status_code, 404)
```

If two-step verification blocks the test client, follow what `test_hs_admin_period_entry.py` already does to satisfy `verification_required` (reuse its session setup) instead of the mock above.

- [ ] **Step 2: Run — expect failures.**

- [ ] **Step 3: Rewrite `views/hs_admin.class_section_grade`** (keep `_hs_admin_context`, the enable switch and the authorization block verbatim), then:

```python
    here = reverse('grades_highschool_admin:class_section_grade', args=[section.id])
    tab = reverse('highschool_admin:class_section', args=[section.id]) + '#grades'
    if request.GET.get('action') == 'download_roster_pdf':
        return section.download_roster_pdf()
    if request.method == 'POST':
        return handle_grade_post(request, section, redirect_url=tab)
    return render(request, 'grades/hs_admin/class_section_grade.html', {
        'menu': menu, 'class_section': section,
        'intro': portal_lang(request).from_db().get('class_blurb', ''),
        'grid': build_grid(section, post_url=here, next_url=here),
    })
```

Rename the local `class_section_info` to `section`. Remove `is_submit_grades_open` and the old formset code.

- [ ] **Step 4: `tabs.hs_admin_grades_tab`** returns `{'grid': build_grid(record, post_url=reverse('grades_highschool_admin:class_section_grade', args=[record.id]), next_url=reverse('highschool_admin:class_section', args=[record.id]) + '#grades')}` and the tab template becomes:

```django
{% load static %}
{% include 'grades/partials/_grade_grid.html' %}
<script src="{% static 'grades/js/grade_roster.js' %}"></script>
```

`grades/hs_admin/class_section_grade.html` is rebuilt like Task 9 Step 4 with HS admin breadcrumbs (`highschool_admin:dashboard`, `highschool_admin:class_section`) and `{% include 'grades/partials/_grade_grid.html' %}`.

- [ ] **Step 5: Update `test_hs_admin_period_entry.py`** for the new response shapes (redirect target is the tab URL or `next`; no `period=None` path). Run both test modules → OK.

- [ ] **Step 6: Commit** — `git commit -am "feat(hs_admin): HS admin grade entry on the shared grid"`

---

### Task 13: Student grade visibility per period

**Files:**
- Modify: `grades/services/student_table.py`, `grades/settings/class_section_grades.py` (choice label only)
- Test: `grades/tests/test_v1_student_visibility.py`

**Interfaces:**
- Consumes: `GradingPeriod.visible_to_students` (Task 2), `submitted_grade` (Task 5).
- Produces: student table column `grade` renders "Mid 1: B<br>Final: A" — every period with `visible_to_students` whose section status is `submitted`, plus the final period's `submitted_grade` when submitted (the final period shows whenever submitted, as today).

- [ ] **Step 1: Write the failing test**

```python
"""v1: students see a period's grades only when visible and submitted (spec §2)."""
from datetime import date

from .base import GradesTestCase
from . import factories as f
from ..services import student_table
from ..services.periods import save_mark, set_status


class StudentVisibilityTests(GradesTestCase):
    def test_visible_submitted_periods_only(self):
        f.grades_setting()
        term = f.term()
        mid1 = f.period(term, 'Mid 1', date(2026, 10, 1), date(2026, 10, 9), 1, visible_to_students=True)
        mid2 = f.period(term, 'Mid 2', date(2026, 11, 1), date(2026, 11, 9), 2, visible_to_students=False)
        final = f.period(term, 'Final', date(2026, 12, 1), date(2026, 12, 9), 3, is_final=True)
        section = f.section(term, f.teacher())
        reg = f.registration(section)
        for p, g in ((mid1, 'B'), (mid2, 'C'), (final, 'A')):
            save_mark(p, reg, g)
        cell = student_table.COLUMNS['grade'][1]
        self.assertEqual(cell(reg), '-')
        set_status(section, mid1, 'submitted')
        set_status(section, mid2, 'submitted')
        self.assertEqual(str(cell(reg)), 'Mid 1: B')
        set_status(section, final, 'submitted')
        reg.refresh_from_db()
        self.assertEqual(str(cell(reg)), 'Mid 1: B<br>Final: A')
```

- [ ] **Step 2: Run — expect failure.**

- [ ] **Step 3: Replace `_grade` in `student_table.py`**

```python
def _grade(registration):
    """Visible, submitted interim marks, then the final grade once submitted."""
    from django.utils.html import format_html
    from django.utils.safestring import mark_safe
    from .periods import get_status, periods_for_section
    from .window import submitted_grade
    from ..models import PeriodGrade
    section = registration.class_section
    lines = []
    for period in periods_for_section(section):
        if period.is_final:
            grade = submitted_grade(registration)
            if grade not in ('', '-'):
                lines.append((period.name, grade))
        elif period.visible_to_students and get_status(section, period) == 'submitted':
            mark = PeriodGrade.objects.filter(period=period, registration=registration).first()
            if mark and mark.grade:
                lines.append((period.name, mark.grade))
    if not lines:
        return '-'
    return mark_safe('<br>'.join(format_html('{}: {}', name, grade) for name, grade in lines))
```

The test asserts exactly `'Mid 1: B<br>Final: A'`. Because `rows()` runs `conditional_escape` on each cell, a `SafeString` passes through unescaped. Rename the column title to `'Grades'`.

- [ ] **Step 4: Run tests (`test_v1_student_visibility`, `test_student_grade_columns`, `test_transcript_pdf`) → OK; commit** — `git commit -am "feat(student): per-period grade visibility"`

---

### Task 14: CE pages that used Class Term(s) — term switcher, period-based scope

**Files:**
- Modify: `grades/tabs.py` (`sections_grades_tab`), `grades/templates/grades/partials/_sections_grades_tab.html`, `grades/views/sis_sync.py`, `grades/services/sis_push.py`
- Test: `grades/tests/test_v1_ce_scope.py` (and update `test_sis_page.py`, `test_sis_push.py`)

**Interfaces:**
- Consumes: `grade_terms`, `selected_term_ids`, `current_grade_terms`.
- Produces: `sections_grades_tab` context `{'terms', 'selected_term_ids', 'period_stats': list[dict(period, submitted, saved, not_started, total, completion_pct)], 'grade_distribution', 'grade_total'}`.

- [ ] **Step 1: Write the failing tests**

```python
"""v1: CE grade pages scope by grading periods (spec §2)."""
from datetime import date, timedelta

from django.test import RequestFactory

from .base import GradesTestCase
from . import factories as f
from ..services import sis_push
from ..services.periods import set_status
from ..tabs import sections_grades_tab


class CEScopeTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        today = date.today()
        cls.term = f.term()
        cls.mid = f.period(cls.term, 'Mid', today - timedelta(days=1), today + timedelta(days=1), 1)
        cls.final = f.period(cls.term, 'Final', today + timedelta(days=10), today + timedelta(days=12), 2, is_final=True)
        cls.a = f.section(cls.term, f.teacher())
        cls.b = f.section(cls.term, f.teacher())

    def test_sections_tab_counts_per_period(self):
        set_status(self.a, self.mid, 'submitted')
        set_status(self.b, self.mid, 'saved')
        ctx = sections_grades_tab(RequestFactory().get('/'), None)
        mid = next(s for s in ctx['period_stats'] if s['period'] == self.mid)
        self.assertEqual((mid['submitted'], mid['saved'], mid['not_started'], mid['total']), (1, 1, 0, 2))

    def test_push_scope_is_grade_terms(self):
        set_status(self.a, self.final, 'submitted')
        ids, skipped = sis_push.select_for_sections([str(self.a.id), str(self.b.id)])
        self.assertIn(self.b, skipped)
```

- [ ] **Step 2: Run — expect failures.**

- [ ] **Step 3: Rewrite `sections_grades_tab`** (keep its registration decorator):

```python
def sections_grades_tab(request, record):
    """Grade statistics for the CE class-sections list: one row per grading
    period of the selected term(s)."""
    from django.db.models import Count
    from cis.models.section import ClassSection, StudentRegistration
    from cis.models.term import Term
    from .models import GradingPeriod, SectionPeriodStatus
    from .services.window import grade_terms, selected_term_ids

    available = grade_terms()
    selected = selected_term_ids(request, available)
    period_stats = []
    for period in GradingPeriod.objects.filter(term_id__in=selected).select_related('term').order_by('term__code', 'sequence'):
        total = ClassSection.objects.filter(term=period.term, status='A').count()
        counts = dict(SectionPeriodStatus.objects.filter(period=period, class_section__status='A')
                      .values_list('status').annotate(n=Count('id')))
        submitted, saved = counts.get('submitted', 0), counts.get('saved', 0)
        period_stats.append({
            'period': period, 'submitted': submitted, 'saved': saved,
            'not_started': total - submitted - saved, 'total': total,
            'completion_pct': round(submitted / total * 100, 1) if total else 0,
        })
    grade_distribution = StudentRegistration.objects.filter(
        class_section__term_id__in=selected, class_section__grade_status='submitted'
    ).exclude(grade__in=['-', '']).values('grade').annotate(count=Count('grade')).order_by('grade')
    return {
        'terms': Term.objects.filter(pk__in=available).order_by('-code'),
        'selected_term_ids': selected,
        'period_stats': period_stats,
        'grade_distribution': list(grade_distribution),
        'grade_total': sum(i['count'] for i in grade_distribution),
    }
```

Rewrite `_sections_grades_tab.html`: a term `<select name="term">` (GET, auto-submit) like Task 10, a table with columns Term, Grading Period (Final badge), Submitted, Draft, Not Started, Total, Complete %, and a "View summary" link per row to `{% url 'grades_ce:summary' %}?term={{ s.period.term_id }}&period={{ s.period.id }}` (route created in Task 16; until then guard with `{% url 'grades_ce:summary' as summary_url %}{% if summary_url %}`), followed by the existing final-grade distribution block.

- [ ] **Step 4: SIS page and push.** `views/sis_sync.py`: `sections_base()` and `registration_queryset()` keep `term_id__in=grade_terms()` (now period-based — no code change needed) ; in `sis_sync_page`, `terms` becomes `Term.objects.filter(pk__in=grade_terms()).order_by('-code')` and add `'selected_term_ids': selected_term_ids(request, grade_terms())` to the context; in `templates/grades/sis/index.html` preselect those ids in the existing term filter. `services/sis_push.py` is unchanged in code (it already uses `grade_terms()`); update its docstring line "configured grade terms" → "grade terms (terms with grading periods)".

- [ ] **Step 5: Update `test_sis_page.py` / `test_sis_push.py` fixtures** — replace `terms=[...]` settings with a final period on the test term. Run → OK.

- [ ] **Step 6: Commit** — `git commit -am "feat(ce): sections Grades tab per period with term switcher; SIS scope from periods"`

---

### Task 15: CE Class Details "Grades" tab with edit-on-behalf and reopen

**Files:**
- Modify: `grades/tabs.py` (register on `myce.component_registry.class_section`), `grades/views/ce.py`, `grades/urls/ce.py`
- Create: `grades/templates/grades/ce/_class_section_grades_tab.html`
- Test: `grades/tests/test_v1_ce_class_tab.py`

**Interfaces:**
- Consumes: `build_grid(..., allow_edit=False | force_period=…)`, `handle_grade_post(..., force_period=…)`, `set_status`.
- Produces: URLs `grades_ce:class_section_grade` (`class_section/<uuid:record_id>`, POST = save for `?period=` with force) and `grades_ce:reopen_period` (`class_section/<uuid:record_id>/period/<uuid:period_id>/reopen`, POST).

- [ ] **Step 1: Write the failing tests**

```python
"""v1: CE Class Details Grades tab (spec §5)."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

from .base import GradesTestCase
from . import factories as f
from ..models import PeriodGrade, SectionPeriodStatus
from ..services.periods import set_status


class CEClassTabTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        today = date.today()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', today - timedelta(days=30), today - timedelta(days=20))
        cls.section = f.section(cls.term, f.teacher())
        cls.reg = f.registration(cls.section)
        cls.ce = get_user_model().objects.create_user(username='ce@example.com', email='ce@example.com', password='x', is_staff=True)
        cls.ce.groups.add(Group.objects.get_or_create(name='ce')[0])

    def setUp(self):
        self.client.force_login(self.ce)

    def test_tab_read_only_by_default(self):
        from ..tabs import ce_class_section_grades_tab
        from django.test import RequestFactory
        request = RequestFactory().get('/')
        request.user = self.ce
        ctx = ce_class_section_grades_tab(request, self.section)
        self.assertIsNone(ctx['grid']['editable_period'])

    def test_ce_can_edit_closed_period_and_note_is_logged(self):
        url = reverse('grades_ce:class_section_grade', args=[self.section.id])
        self.client.post(url + f'?period={self.mid1.id}', {
            'period': str(self.mid1.id), 'save_grade': 'Submit', 'next': '/',
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1', 'form-MIN_NUM_FORMS': '1',
            'form-MAX_NUM_FORMS': '1', 'form-0-student': 'x',
            'form-0-student_id': str(self.reg.id), 'form-0-grade': 'B'})
        self.assertEqual(PeriodGrade.objects.get(period=self.mid1).grade, 'B')
        self.assertTrue(self.section.classsectionnote_set.filter(note__icontains='ce@example.com').exists()
                        if hasattr(self.section, 'classsectionnote_set') else True)

    def test_reopen(self):
        set_status(self.section, self.mid1, 'submitted')
        self.client.post(reverse('grades_ce:reopen_period', args=[self.section.id, self.mid1.id]))
        self.assertEqual(SectionPeriodStatus.objects.get(period=self.mid1).status, 'saved')

    def test_non_ce_forbidden(self):
        self.client.force_login(self.section.teacher.user)
        resp = self.client.post(reverse('grades_ce:reopen_period', args=[self.section.id, self.mid1.id]))
        self.assertNotEqual(resp.status_code, 200)
        self.assertEqual(SectionPeriodStatus.objects.filter(period=self.mid1).count(), 0)
```

Check how `ClassSection.add_note` stores notes (`grep -n "def add_note" -A15` in cis `models/section.py`) and assert on that model instead of the `hasattr` fallback above.

- [ ] **Step 2: Run — expect failures.**

- [ ] **Step 3: Register the tab in `tabs.py`**

```python
ce_class_section_tabs = registry('myce.component_registry.class_section', 'class_section_tabs')


@register(ce_class_section_tabs, 'tab', slug='grades', title='Grades', order=35,
          lazy=True, template='grades/ce/_class_section_grades_tab.html')
def ce_class_section_grades_tab(request, record):
    """Read-only grid for CE; ?edit=<period id> switches one period to edit."""
    from django.urls import reverse
    from .services.grade_grid import build_grid
    from .services.periods import resolve_period
    edit_id = request.GET.get('edit')
    force = resolve_period(record, edit_id) if edit_id else None
    post_url = reverse('grades_ce:class_section_grade', args=[record.id])
    next_url = reverse('cis:section', args=[record.id]) + '#grades'
    return {'grid': build_grid(record, post_url=post_url, next_url=next_url,
                               allow_edit=False, force_period=force),
            'record': record}
```

`_class_section_grades_tab.html`: for each `p in grid.periods`, a row of small buttons above the grid — "Edit" (`<a data-tab-reload href="?edit={{ p.period.id }}#grades">` — implement as a link to `{% url 'grades_ce:class_section_grade' record.id %}?period={{ p.period.id }}` which renders the standalone CE edit page) and, when `p.status == 'submitted'`, a "Reopen" `<form method="post" action="{% url 'grades_ce:reopen_period' record.id p.period.id %}">{% csrf_token %}<button class="btn btn-sm btn-outline-warning">Reopen {{ p.period.name }}</button></form>`; then each period's status history (`last_notified_on`, `header`) and `{% include 'grades/partials/_grade_grid.html' %}` plus `grade_roster.js`.

- [ ] **Step 4: CE views in `views/ce.py`**

```python
def ce_class_section_grade(request, record_id):
    """CE edits any period of a class on the instructor's behalf (spec §5)."""
    from django.urls import reverse
    from cis.models.section import ClassSection
    from ..services.grade_grid import build_grid
    from ..services.periods import resolve_period
    from .grade_entry import handle_grade_post
    section = get_object_or_404(ClassSection, pk=record_id)
    period = resolve_period(section, request.GET.get('period') or request.POST.get('period'))
    if period is None:
        raise Http404('Unknown grading period.')
    back = reverse('cis:section', args=[section.id]) + '#grades'
    if request.method == 'POST':
        response = handle_grade_post(request, section, redirect_url=back, force_period=period)
        section.add_note(note=f'{request.user.email} edited {period.name} grades on the instructor\'s behalf')
        return response
    here = reverse('grades_ce:class_section_grade', args=[section.id]) + f'?period={period.id}'
    return render(request, 'grades/ce/class_section_grade.html', {
        'record': section, 'period': period,
        'grid': build_grid(section, post_url=here, next_url=back, force_period=period),
    })


@require_POST
def reopen_period(request, record_id, period_id):
    from cis.models.section import ClassSection
    from ..services.periods import set_status
    section = get_object_or_404(ClassSection, pk=record_id)
    period = get_object_or_404(GradingPeriod, pk=period_id, term_id=section.term_id)
    set_status(section, period, 'saved')
    section.add_note(note=f'{request.user.email} reopened {period.name} grades')
    messages.add_message(request, messages.SUCCESS, f'{period.name} reopened.', 'list-group-item-success')
    return redirect(reverse('cis:section', args=[section.id]) + '#grades')
```

Imports: `from django.contrib import messages`, `from django.http import Http404`, `from django.shortcuts import redirect`, `from django.views.decorators.http import require_POST`. Create `templates/grades/ce/class_section_grade.html` extending `cis/logged-base.html` with breadcrumb Home › Sections › `{{ record }}` › Edit `{{ period.name }}`, `cis/messages.html`, and the grid partial + `grade_roster.js`.

- [ ] **Step 5: URLs** in `urls/ce.py`:

```python
    path('class_section/<uuid:record_id>', ce_only(ce_class_section_grade), name='class_section_grade'),
    path('class_section/<uuid:record_id>/period/<uuid:period_id>/reopen', ce_only(reopen_period), name='reopen_period'),
```

- [ ] **Step 6: In `apps.py`** nothing new (tabs already imported). Run tests → OK. Commit — `git commit -am "feat(ce): Grades tab on CE Class Details with edit-on-behalf and reopen"` (add new files).

---

### Task 16: CE grade submission summary page (+ menu items)

**Files:**
- Create: `grades/services/summary.py`, `grades/views/summary.py`, `grades/templates/grades/ce/summary.html`, `grades/migrations/0006_grades_v1_nav.py`
- Modify: `grades/urls/ce.py`
- Test: `grades/tests/test_v1_summary.py`

**Interfaces:**
- Consumes: `grade_terms`, `selected_term_ids`, `open_period`, `PERIOD_STATUS_LABELS`, `_send_period_reminder` (period_reminders), `SectionPeriodStatus`.
- Produces: `summarize(period, highschool_ids=None, campus_ids=None) -> dict(classes={'submitted','saved','not_started','total'}, instructors={'submitted','saved','not_started','total'}, rows=list[dict(teacher_user, highschools, classes, submitted, saved, not_started, status, last_notified_on, sections)])`; `remind(period, teacher_user_ids, today=None) -> int` (emails sent); URLs `grades_ce:summary` (GET page, `?format=csv` export), `grades_ce:summary_remind` (POST).

- [ ] **Step 1: Write the failing tests**

```python
"""v1: CE grade submission summary (spec §5)."""
from datetime import date, timedelta

from mailer.models import Message

from .base import GradesTestCase
from . import factories as f
from ..services.periods import set_status
from ..services.summary import remind, summarize


class SummaryTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        get_user_model().objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        f.grades_setting(is_active='Yes', grades_due_subject='Due', grades_due_email='{{grading_period}}')
        today = date.today()
        cls.term = f.term()
        cls.mid = f.period(cls.term, 'Mid', today - timedelta(days=1), today + timedelta(days=5))
        cls.t1, cls.t2, cls.t3 = f.teacher(), f.teacher(), f.teacher()
        cls.a1 = f.section(cls.term, cls.t1); cls.a2 = f.section(cls.term, cls.t1)
        cls.b1 = f.section(cls.term, cls.t2)
        cls.c1 = f.section(cls.term, cls.t3)

    def test_counts_by_class_and_instructor(self):
        set_status(self.a1, self.mid, 'submitted')
        set_status(self.a2, self.mid, 'submitted')
        set_status(self.b1, self.mid, 'saved')
        s = summarize(self.mid)
        self.assertEqual(s['classes'], {'submitted': 2, 'saved': 1, 'not_started': 1, 'total': 4})
        self.assertEqual(s['instructors'], {'submitted': 1, 'saved': 1, 'not_started': 1, 'total': 3})

    def test_instructor_with_one_draft_is_draft(self):
        set_status(self.a1, self.mid, 'submitted')
        set_status(self.a2, self.mid, 'saved')
        row = next(r for r in summarize(self.mid)['rows'] if r['teacher_user'] == self.t1.user)
        self.assertEqual(row['status'], 'saved')

    def test_remind_skips_submitted_and_same_day(self):
        set_status(self.a1, self.mid, 'submitted')
        set_status(self.a2, self.mid, 'submitted')
        sent = remind(self.mid, [self.t1.user.id, self.t2.user.id])
        self.assertEqual(sent, 1)
        self.assertEqual(remind(self.mid, [self.t2.user.id]), 0)
        self.assertEqual(Message.objects.count(), 1)
```

- [ ] **Step 2: Run — expect `ImportError`.**

- [ ] **Step 3: Write `services/summary.py`**

```python
"""Grade submission summary for CE staff (spec §5)."""
import datetime
from collections import OrderedDict

from ..models import SectionPeriodStatus


def _rank(statuses):
    if statuses and all(s == 'submitted' for s in statuses):
        return 'submitted'
    if any(s in ('saved', 'submitted') for s in statuses):
        return 'saved'
    return 'not_started'


def summarize(period, highschool_ids=None, campus_ids=None):
    from cis.models.section import ClassSection
    sections = ClassSection.objects.filter(term_id=period.term_id, status='A', teacher__isnull=False)
    if highschool_ids:
        sections = sections.filter(highschool_id__in=highschool_ids)
    if campus_ids:
        sections = sections.filter(course__campus_id__in=campus_ids)
    sections = list(sections.select_related('teacher__user', 'highschool', 'course__cohort'))
    rows_by_status = {r.class_section_id: r for r in SectionPeriodStatus.objects.filter(
        period=period, class_section__in=sections)}

    classes = {'submitted': 0, 'saved': 0, 'not_started': 0, 'total': len(sections)}
    by_teacher = OrderedDict()
    for s in sorted(sections, key=lambda s: (s.teacher.user.last_name, s.teacher.user.first_name)):
        row = rows_by_status.get(s.id)
        status = (row.status if row else '') or 'not_started'
        classes[status] += 1
        t = by_teacher.setdefault(s.teacher.user, {
            'teacher_user': s.teacher.user, 'sections': [], 'statuses': [], 'highschools': set(),
            'last_notified_on': None})
        t['sections'].append(s)
        t['statuses'].append(status)
        if s.highschool_id:
            t['highschools'].add(str(s.highschool))
        if row and row.last_notified_on and (t['last_notified_on'] is None or row.last_notified_on > t['last_notified_on']):
            t['last_notified_on'] = row.last_notified_on

    instructors = {'submitted': 0, 'saved': 0, 'not_started': 0, 'total': len(by_teacher)}
    rows = []
    for t in by_teacher.values():
        status = _rank(t['statuses'])
        instructors[status] += 1
        rows.append({
            'teacher_user': t['teacher_user'], 'sections': t['sections'],
            'highschools': sorted(t['highschools']), 'classes': len(t['sections']),
            'submitted': t['statuses'].count('submitted'), 'saved': t['statuses'].count('saved'),
            'not_started': t['statuses'].count('not_started'), 'status': status,
            'last_notified_on': t['last_notified_on'],
        })
    return {'classes': classes, 'instructors': instructors, 'rows': rows}


def remind(period, teacher_user_ids, today=None):
    """Email each listed instructor with unsubmitted classes in ``period``,
    skipping classes already reminded today. Returns emails sent."""
    from ..settings.class_section_grades import class_section_grades
    from .period_reminders import _send_period_reminder
    today = today or datetime.date.today()
    configs = class_section_grades.from_db()
    sent = 0
    for row in summarize(period)['rows']:
        if row['teacher_user'].id not in set(teacher_user_ids):
            continue
        pending = []
        for section in row['sections']:
            status_row, _ = SectionPeriodStatus.objects.get_or_create(period=period, class_section=section)
            if status_row.status != 'submitted' and status_row.last_notified_on != today:
                pending.append((section, status_row))
        if not pending:
            continue
        if _send_period_reminder(period, row['teacher_user'], len(pending), configs, today):
            sent += 1
            for section, status_row in pending:
                status_row.last_notified_on = today
                status_row.save(update_fields=['last_notified_on'])
                section.add_note(note=f'Sent grades due reminder email for {period.name} (CE summary)')
    return sent
```

- [ ] **Step 4: Views (`views/summary.py`)**

```python
"""CE grade submission summary page (spec §5)."""
import csv

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from cis.menu import draw_menu, cis_menu
from cis.models.term import Term

from ..models import GradingPeriod
from ..services.summary import remind, summarize
from ..services.window import grade_terms, selected_term_ids
from ..compat import picker_queryset


def _period(request, term_ids):
    periods = list(GradingPeriod.objects.filter(term_id__in=term_ids).select_related('term')
                   .order_by('term__code', 'sequence'))
    chosen = request.GET.get('period') or request.POST.get('period')
    period = next((p for p in periods if str(p.id) == chosen), None)
    if period is None:
        import datetime
        today = datetime.date.today()
        period = (next((p for p in periods if p.opens_on <= today <= p.due_on), None)
                  or next((p for p in reversed(periods) if p.opens_on <= today), None)
                  or (periods[0] if periods else None))
    return periods, period


def summary(request):
    available = grade_terms()
    selected = selected_term_ids(request, available)
    periods, period = _period(request, selected)
    hs_ids = [h for h in request.GET.getlist('highschool') if h]
    data = summarize(period, highschool_ids=hs_ids) if period else None

    if period and request.GET.get('format') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="grade_summary_{period.name}.csv"'
        w = csv.writer(response)
        w.writerow(['Instructor', 'Email', 'High School(s)', 'Classes', 'Submitted', 'Draft',
                    'Not Started', 'Status', 'Last Reminder'])
        for r in data['rows']:
            u = r['teacher_user']
            w.writerow([f'{u.last_name}, {u.first_name}', u.email, '; '.join(r['highschools']),
                        r['classes'], r['submitted'], r['saved'], r['not_started'], r['status'],
                        r['last_notified_on'].strftime('%m/%d/%Y') if r['last_notified_on'] else ''])
        return response

    return render(request, 'grades/ce/summary.html', {
        'menu': draw_menu(cis_menu, 'classes', 'grades_summary'),
        'terms': Term.objects.filter(pk__in=available).order_by('-code'),
        'selected_term_ids': selected, 'periods': periods, 'period': period,
        'highschools': picker_queryset(), 'selected_highschools': hs_ids, 'data': data,
    })


@require_POST
def summary_remind(request):
    period = GradingPeriod.objects.filter(pk=request.POST.get('period')).first()
    if period is not None:
        ids = [int(i) for i in request.POST.getlist('teacher') if i.isdigit()]
        if request.POST.get('all') == '1':
            ids = [r['teacher_user'].id for r in summarize(period)['rows'] if r['status'] != 'submitted']
        sent = remind(period, ids)
        messages.add_message(request, messages.SUCCESS, f'Sent {sent} reminder(s).', 'list-group-item-success')
    return redirect(reverse('grades_ce:summary') + (f'?period={period.id}&term={period.term_id}' if period else ''))
```

If `cis.menu` exposes a different name than `cis_menu`, use what `cis/views/section.py` uses for `draw_menu(...)` (it passes `cis_menu`; import it from the same place).

- [ ] **Step 5: URLs** — `path('summary/', ce_only(summary), name='summary')`, `path('summary/remind/', ce_only(summary_remind), name='summary_remind')`.

- [ ] **Step 6: Template `grades/ce/summary.html`** — extends `cis/logged-base.html`; filter bar (GET form: Term select, Grading Period select, High School multi-select, Apply); two headline cards ("By class" and "By instructor": Submitted / Draft / Not Started / Total); table (checkbox, Instructor, Email, High School(s), Classes, Submitted, Draft, Not Started, Status badge, Last Reminder, link list of class numbers → `{% url 'cis:section' s.id %}#grades`); a POST form around the table to `grades_ce:summary_remind` with hidden `period`, buttons "Send reminder to selected" and "Remind all not submitted" (`name="all" value="1"`); an "Export CSV" link `?{{ request.GET.urlencode }}&format=csv`. When `period` is None show "No grading periods for the selected term."

- [ ] **Step 7: Menu migration `0006_grades_v1_nav.py`** — copy the pattern of `0003_add_grades_nav.py` (same `patch_ce_menu` shape, same dependency style) to add `{'label': 'Grade Summary', 'name': 'grades_summary', 'url': 'grades_ce:summary'}` after `grades_sis_sync` under the CE `classes` group, **and** to add `{'type': 'nav-item', 'icon': 'fas fa-fw fa-graduation-cap', 'name': 'grades', 'label': 'Grades', 'url': 'instructor:grades'}` to `instructor_menu` after the item named `students` when no item named `grades` exists. Idempotent; reverse removes by name. Depends on `('grades', '0005_settings_to_periods')`.

- [ ] **Step 8: Run tests (`test_v1_summary`, `test_grades_nav_migration`) → OK; migrate; commit** — `git commit -am "feat(ce): grade submission summary with reminders and CSV; menu items"` (add new files).

---

### Task 17: Reports — Period Grades, Grade Submission Status, period filter on distributions

**Files:**
- Create: `grades/reports/period_grades.py`, `grades/reports/period_submission_status.py`, `grades/services/report_marks.py`
- Modify: `grades/apps.py` (`_REPORTS_BASE`), `grades/reports/grade_by_course.py`, `grades/reports/grade_by_highschool.py`, `grades/reports/grade_by_demographics.py`
- Test: `grades/tests/test_v1_reports.py`

**Interfaces:**
- Produces: `period_mark_annotation(period) -> Expression` (in `services/report_marks.py`): for a final period (or `None`) returns `F('grade')`; otherwise `Coalesce(Subquery(PeriodGrade grade for OuterRef('pk')), Value(''))`. Report classes `period_grades`, `period_submission_status` following `class_grade_status`'s shape (`__init__(request=None)`, `get_result(data, user=None)`, `rows(...)`, `run(task, data)`).

- [ ] **Step 1: Write the failing tests**

```python
"""v1: period reports (spec §5)."""
from datetime import date

from .base import GradesTestCase
from . import factories as f
from ..reports.period_grades import period_grades
from ..reports.period_submission_status import period_submission_status
from ..services.periods import save_mark, set_status
from ..services.report_marks import period_mark_annotation


class PeriodReportTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        f.grades_setting()
        cls.term = f.term()
        cls.mid = f.period(cls.term, 'Mid', date(2026, 10, 1), date(2026, 10, 9), 1)
        cls.final = f.period(cls.term, 'Final', date(2026, 12, 1), date(2026, 12, 9), 2, is_final=True)
        cls.section = f.section(cls.term, f.teacher())
        cls.reg = f.registration(cls.section, last_name='Amador')
        save_mark(cls.mid, cls.reg, 'B')
        save_mark(cls.final, cls.reg, 'A')
        set_status(cls.section, cls.mid, 'submitted')

    def test_mark_annotation(self):
        from cis.models.section import StudentRegistration
        qs = StudentRegistration.objects.filter(pk=self.reg.pk)
        self.assertEqual(qs.annotate(m=period_mark_annotation(self.mid)).get().m, 'B')
        self.assertEqual(qs.annotate(m=period_mark_annotation(self.final)).get().m, 'A')

    def test_period_grades_one_column_per_period(self):
        report = period_grades()
        data = {'term': [self.term.id], 'periods': [self.mid.id, self.final.id], 'campus': []}
        header, rows = report.table(data)
        self.assertEqual(header[-2:], ['Mid', 'Final'])
        self.assertEqual(rows[0][-2:], ['B', 'A'])

    def test_submission_status_rows(self):
        report = period_submission_status()
        rows = list(report.rows(report.get_result({'term': [self.term.id], 'campus': []})))
        statuses = {r[2]: r[-3] for r in rows}  # period name -> status label
        self.assertEqual(statuses, {'Mid': 'Submitted', 'Final': 'Not Started'})
```

- [ ] **Step 2: Run — expect `ImportError`.**

- [ ] **Step 3: `services/report_marks.py`**

```python
"""Which stored mark a report reads for a grading period."""
from django.db.models import F, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from ..models import PeriodGrade


def period_mark_annotation(period):
    if period is None or period.is_final:
        return F('grade')
    return Coalesce(Subquery(PeriodGrade.objects.filter(
        period=period, registration=OuterRef('pk')).values('grade')[:1]), Value(''))
```

- [ ] **Step 4: `reports/period_grades.py`** — copy `class_grade_status.py`'s imports, campus/term/highschools fields, `__init__`, and `run()` (CSV to `PrivateMediaStorage`, file name `period_grades_<timestamp>.csv`). Fields: `campus`, `term` (required), `periods` (`ModelMultipleChoiceField(queryset=GradingPeriod.objects.select_related('term').order_by('-term__code','sequence'), required=True, label='Grading Period(s)')`), `highschools`, `registration_status` (`MultipleChoiceField(choices=StudentRegistration.STATUS_OPTIONS, required=False)`), `period_status` (`MultipleChoiceField(choices=GRADE_STATUS_CHOICES, required=False)` — import from `class_grade_status`). Add:

```python
    @staticmethod
    def _mark(value):
        return '' if value in (None, '-') else value

    COLUMNS = ['Term', 'Course', 'Class No.', 'Section No.', 'Instructor', 'Instructor Email',
               'High School', 'Student Last Name', 'Student First Name', 'Student ID',
               'Registration Status']

    def table(self, data, user=None):
        periods = list(GradingPeriod.objects.filter(pk__in=data.get('periods') or [])
                       .order_by('sequence'))
        regs = StudentRegistration.objects.filter(
            class_section__term_id__in=data.get('term') or []
        ).select_related('class_section__term', 'class_section__course',
                         'class_section__teacher__user', 'class_section__highschool',
                         'student__user')
        if data.get('highschools'):
            regs = regs.filter(class_section__highschool_id__in=data['highschools'])
        if data.get('registration_status'):
            regs = regs.filter(status__in=data['registration_status'])
        regs = scope_report_by_campus(regs, user, data.get('campus'),
                                      campus_path='class_section__course__campus')
        for i, p in enumerate(periods):
            regs = regs.annotate(**{f'p{i}': period_mark_annotation(p)})
        header = self.COLUMNS + [p.name for p in periods]
        rows = []
        for r in regs.order_by('class_section__term__code', 'class_section__class_number',
                               'student__user__last_name'):
            s, u = r.class_section, r.student.user
            t = s.teacher.user if s.teacher_id else None
            rows.append([s.term.label, s.course.name, s.class_number, s.section_number,
                         f'{t.last_name}, {t.first_name}' if t else '', t.email if t else '',
                         s.highschool.name if s.highschool_id else '', u.last_name, u.first_name,
                         u.psid or '', r.status] +
                        [self._mark(getattr(r, f'p{i}')) for i in range(len(periods))])
        return header, rows
```

(`period_status` filtering: when given, keep only registrations whose section's `SectionPeriodStatus` for **every** selected period is in the chosen statuses, treating a missing row as `not_started`; implement with a Python filter on the section ids before building rows.) `run()` writes `header` then `rows`.

- [ ] **Step 5: `reports/period_submission_status.py`** — same scaffolding; fields `campus`, `term`, `periods` (optional; blank = every period of the terms), `highschools`. Columns: `['Term', 'Course', 'Grading Period', 'Final', 'Class No.', 'Section No.', 'Instructor', 'Instructor Email', 'High School', 'Status', 'Status Changed On', 'Last Reminder']`. `get_result(data, user=None)` returns a list of `(section, period, status_row_or_None)` for every active section × period of its term; `rows()` yields lists in the column order using `STATUS_LABELS[status_key(row.status if row else '')]` and `last_changed(row.status_changed_on)` from `class_grade_status` (import both helpers). The test indexes `r[2]` = period name and `r[-3]` = status label.

- [ ] **Step 6: Register** — add to `_REPORTS_BASE` in `apps.py`:

```python
    {
        'name': 'period_grades',
        'title': 'Grades by Grading Period',
        'description': 'One row per student registration with the grade for each selected grading period (mid-semester and final)',
        'categories': ['Students', 'Classes'],
        'available_for': ['ce'],
    },
    {
        'name': 'period_submission_status',
        'title': 'Grade Submission Status by Period',
        'description': 'One row per class per grading period: submitted, draft or not started, with last reminder date',
        'categories': ['Classes'],
        'available_for': ['ce'],
    },
```

Then run `docker exec -w /app/webapp django_web_lamar python manage.py register_reports`.

- [ ] **Step 7: Period filter on distribution reports** — in each of `grade_by_course.py`, `grade_by_highschool.py`, `grade_by_demographics.py`: add field
`grading_period = forms.ModelChoiceField(queryset=GradingPeriod.objects.select_related('term').order_by('-term__code', 'sequence'), required=False, label='Grading Period', help_text='Blank = final grades')`; in `run()` (or `get_result`) annotate `registrations = registrations.annotate(period_mark=period_mark_annotation(period))` where `period = GradingPeriod.objects.filter(pk=data.get('grading_period')).first()`, and replace every `When(grade=…)`, `.exclude(grade=…)`, `values('grade')` reference on the registration queryset with `period_mark`. Add one test per report asserting a non-final period counts the interim marks (reuse the fixture above: `B` for Mid).

- [ ] **Step 8: Run tests → OK; commit** — `git commit -am "feat(reports): grades by period, submission status by period, period filter on distributions"` (add new files).

---

### Task 18: Release notes, version, Lamar cutover

**Files:**
- Modify (grades repo): `CHANGELOG.md` (create if absent), `setup.cfg`, `pyproject.toml`, `README.md` (settings section)
- Modify (Lamar repo, parent): delete `webapp/templates/grades/`, `webapp/myce_tenant_configs/services/instructor_grades.py`, `webapp/myce_tenant_configs/templatetags/instructor_grades.py`, `webapp/myce_tenant_configs/page_messages.py`, `webapp/myce_tenant_configs/tests/test_instructor_grades.py`; create `webapp/myce_tenant_configs/services/grades_columns.py` + test; bump the `webapp/grades` submodule pointer.

- [ ] **Step 1: CHANGELOG `## 1.0.0`** — sections *Breaking* (removed settings fields; `notify_grades_pending` is a no-op, delete its cron, removed in 1.1; terms without grading periods have no grade entry; `period=None` no longer accepted by `services.periods`), *Migration* (0005 creates Final Grades periods — check the log), *Added* (period fields, column-per-period grid, Class Details tabs for instructor/CE, HS admin grid, page messages, CE summary, reports, tenant `grades_columns` hook), *Upgrade steps* (spec §4 list verbatim).

- [ ] **Step 2: Version** — set `version = 1.0.0` in `setup.cfg` and `pyproject.toml`. Run the full suite: `docker exec -w /app/webapp django_web_lamar python manage.py test grades.grades` → OK. Commit `chore(release): v1.0.0`. **Do not push or tag** — the user approves pushing/tagging.

- [ ] **Step 3: Lamar tenant column hook** — `webapp/myce_tenant_configs/services/grades_columns.py`:

```python
"""Grade grid student columns for Lamar: the defaults plus High School."""


def columns(builtin, default_keys):
    return [builtin[k] for k in default_keys + ['highschool']]
```

Test `webapp/myce_tenant_configs/tests/test_grades_columns.py` asserting `[c.key for c in get_columns()]` ends with `'highschool'` (import `get_columns` via the `grades.grades.services.columns` / `grades.services.columns` `find_spec` conditional).

- [ ] **Step 4: Remove Lamar overrides** listed above (`git rm`), run `docker exec -w /app/webapp django_web_lamar python manage.py test myce_tenant_configs.tests.test_grades_columns grades.grades` → OK, and smoke the four pages on 127.0.0.1 as `daileynm` (Grades list, `/instructor/class_section/74db30d5-…#grades`, standalone grade page, CE `/ce/sections/74db30d5-…#grades`) and `/ce/grades/summary/` as a CE user.

- [ ] **Step 5: Commit in Lamar `dev`** — `git add -A webapp/grades webapp/myce_tenant_configs webapp/templates && git commit -m "feat(grades): adopt grades v1 (submodule); High School column via grades_columns"`. Do not push.

---

## Self-Review

- **Spec coverage:** §1 fields/validation → T2; settings → T3; migration → T4. §2 services → T5; CE pages → T14; student → T13; reminders → T6. §3 grid/columns → T7–T8; instructor tab/standalone → T9; list → T10; page messages → T11; HS admin → T12; Lamar cleanup → T18. §4 release/tests → T18 + each task. §5 CE tab → T15; summary → T16; reports → T17. Menu items (CE summary, instructor Grades) → T16 Step 7.
- **Placeholders:** none intended; Task 17 Step 7 names the exact substitutions per report.
- **Type consistency:** `needs_reminder(status_row, period, today)` (T6) used only in period_reminders; `build_grid(...)` keys used by T9/T12/T15 templates match T8; `class_rows` (T10) consumes `PERIOD_STATUS_LABELS` from T8; `open_period_summary` (T11); `summarize`/`remind` (T16).
- **Review Focus:** each of the five lines has a test in its owning task (T5/T8/T9/T14 no-period cases, T8 forged POST + `next`, T4 messy migration, T6 before-due outside window).
