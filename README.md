# myce_grades

Django app providing grade submission, unofficial transcripts, grade distribution
reports and the grade settings configurator for the MyCE concurrent enrollment
platform.

This repository is the source of the `myce_grades` distribution
(`Canusia/package-grades`). It is an **optional** package: a tenant can run MyCE
without it, in which case the grades URLs, the grades settings configurator, the
grade reports and the CE sections-list grades tab are simply absent.

## Dependency direction

`grades` depends on `cis` and `myce`. **`cis` never imports `grades`.** The three
`cis` features that genuinely need a grade fact go through one seam,
`cis/integrations/grades.py`, which resolves `grades` with `find_spec` and returns
safe defaults when it is not installed.

There are no models here — grades are stored on `cis.StudentRegistration.grade`
and `cis.ClassSection.grade_status`, so the package ships no migrations.

## Layout

```
package-grades/            # repo root — mounted at webapp/grades in a tenant
├── MANIFEST.in
├── setup.cfg              # name = myce_grades, version = 0.0.1
├── README.md
├── __init__.py            # outer package root (dev/editable mode only)
└── grades/                # the importable package
    ├── __init__.py
    ├── apps.py            # GradesConfig + DevGradesConfig
    ├── signals.py         # grade_status == 'submitted' instructor email
    ├── tabs.py            # CE sections-list grades tab
    ├── urls.py            # placeholder; real routes live in urls/
    ├── urls/              # instructor.py, student.py (included by the host)
    ├── views/             # instructor.py, student.py
    ├── forms/             # section.py — ClassSectionGradeForm(Set)
    ├── settings/          # class_section_grades configurator
    ├── services/          # window, roster, reminders, transcript
    ├── reports/           # grade_by_highschool / _course / _demographics
    ├── management/commands/notify_grades_pending.py
    ├── templates/grades/
    ├── static/grades/
    └── tests/
```

## The dev / pip dual config

The package supports the house editable-submodule pattern, so it can be edited
in-tree in a tenant repo while still being pip-installable everywhere else.

| Mode | Import path | AppConfig |
|---|---|---|
| pip install (`myce_grades`) | `grades` | `grades.apps.GradesConfig` |
| editable submodule at `webapp/grades` | `grades.grades` | `grades.grades.apps.DevGradesConfig` |

Django derives the app label `grades` in both modes, so template paths
(`grades/instructor/grades.html`) and static paths (`grades/js/settings.js`) are
identical either way.

Two consequences for anyone editing this package:

1. **All intra-package imports must be relative** — `from ..settings.class_section_grades
   import class_section_grades`, not `from grades.settings…`. In editable mode an
   absolute `grades.x` resolves to the *repo root*, not the package. Imports of
   other apps (`cis`, `myce`, `mailer`) stay absolute.
2. **`CONFIGURATORS` and `REPORTS` carry an `'app'` key that differs per config**
   (`'grades'` vs `'grades.grades'`). `register_settings` / `register_reports`
   persist that dotted path into `SettingRecord.app` / `Report.app`, and the
   settings-detail and report-run pages `import_string` it. A stale key 500s those
   pages. The entries are declared once in `_CONFIGURATORS_BASE` / `_REPORTS_BASE`
   and each config spreads its own `'app'` over them.

`MANIFEST.in` must keep shipping `templates/` and `static/` explicitly —
`packages = find:` alone will not — and `management/__init__.py` /
`management/commands/__init__.py` must survive, or `setuptools.find_packages()`
drops `notify_grades_pending` from the wheel.

## Install into a tenant

### 1. Pin the package

`webapp/requirements.txt`:

```
git+https://github.com/Canusia/package-grades.git@2026.1.0
```

### 2. INSTALLED_APPS

`myce/settings.py`:

```python
'grades.grades.apps.DevGradesConfig'
if importlib.util.find_spec('grades.grades')
else 'grades.apps.GradesConfig',
```

### 3. Portal URLs

`instructor/urls.py` and `student/urls.py` include the grades routes into the
existing `instructor` / `student` namespaces, conditionally so the include is
skipped entirely when the package is absent:

```python
_grades_urls = (
    'grades.grades.urls.instructor'
    if importlib.util.find_spec('grades.grades')
    else 'grades.urls.instructor' if importlib.util.find_spec('grades')
    else None
)
if _grades_urls:
    urlpatterns += [path('', include(_grades_urls))]
```

### 4. Register settings and reports

```bash
python manage.py register_settings
python manage.py register_reports
python manage.py check
```

`register_settings` / `register_reports` only *create* missing rows; they do not
rewrite the `app` column on rows that already exist. When an existing deployment
switches between pip and editable mode, update the stored dotted path by hand:

```python
SettingRecord.objects.filter(name='class_section_grades').update(app='grades.grades')
Report.objects.filter(name__startswith='grade_by').update(app='grades.grades')
```

## Shipping a release

`setup.cfg` stays at `version = 0.0.1`; releases are tag-driven CalVer
(`YYYY.MAJOR.MINOR`), matching the other Canusia packages.

1. Commit inside `webapp/grades` (it is a separate git repo in a tenant checkout).
2. Push to `Canusia/package-grades`.
3. Tag the new version, e.g. `2026.1.1`.
4. Bump the pin in the tenant's `webapp/requirements.txt` to that tag.
5. `git add webapp/grades` in the tenant to move the gitlink to the new commit.
6. Merge to staging / main.

Skipping steps 3–4 means production silently keeps running the old version — there
is no build failure and no warning.

## URLs

Routes are contributed into the host portals' namespaces, not a `grades` namespace.

| Name | Path |
|---|---|
| `instructor:grades` | `/instructor/grades/` |
| `instructor:class_section_grade` | `/instructor/grades/class_section/<uuid>` |
| `student:grades` | `/student/grades/` |
| `student:download_transcript` | `/student/grades/download/` |
| `student:transcripts` | `/student/transcripts/` |

`grades/urls/instructor.py` and `grades/urls/student.py` are referenced by dotted
string from the host — do not rename them.

## Services

`grades.services` owns all grade behavior, operating on `cis` models it does not own:

| Module | Functions |
|---|---|
| `services/window.py` | `is_submit_grades_open`, `can_view_grades`, `page_header_for_instructor`, `grade_scale`, `grade_terms`, `submitted_grade` |
| `services/roster.py` | `students_for_grades(section)` |
| `services/reminders.py` | `needs_reminder`, `notify_sections_pending_grade` |
| `services/transcript.py` | `render_transcript(student, request=None)` |

## Settings

The `class_section_grades` configurator lives at `/ce/configurator/class_section_grades/`
and controls the grade scale and GPA points, the submission window (`start_date` /
`end_date`), reminder dates and cron, the eligible `registration_status` values, the
grading `terms`, the grades-due / grades-submitted email templates and the unofficial
transcript templates.

## Reports

- Grade Distribution by High School (`grade_by_highschool`)
- Grade Distribution by Course (`grade_by_course`)
- Grade Distribution by Demographics (`grade_by_demographics`)

## Tests

```bash
python manage.py test grades
```
