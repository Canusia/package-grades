"""Grades v1.0.0: move the Class Grades window into grading periods.

For each stored Class Grades setting (one per campus on multi-campus hosts):
each term in the old ``terms`` list that has no grading period gets a
"Final Grades" period over the old start/end dates (final, reminders off,
not visible to students); ``grades_open`` (else ``grades_closed``) becomes
``grades_intro``; the retired keys are removed. Terms that already have
periods are left alone. Reverse is a no-op.

Dates may be m/d/Y or ISO YYYY-MM-DD. Messy values never abort the
migration: a non-dict setting value is left as is, a non-list ``terms`` is
treated as empty, and any error on one setting row is logged and that row
skipped (inside a savepoint) while the other rows still migrate.
"""
import datetime

from django.conf import settings
from django.db import migrations, transaction

RETIRED_KEYS = (
    'terms', 'start_date', 'end_date', 'reminder_dates', 'grades_open',
    'grades_closed', 'viewable_from_date', 'viewable_end_date',
)


DATE_FORMATS = ('%m/%d/%Y', '%Y-%m-%d')


def _date(value):
    text = str(value or '').strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _term_ids(value):
    if isinstance(value, str):
        value = [v for v in value.split(',') if v.strip()]
    if not isinstance(value, (list, tuple, set)):
        return []  # None, a number, a dict...: nothing usable
    return [str(v).strip() for v in value]


def _is_uuid(value):
    import uuid
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def migrate_settings(Setting, Term, GradingPeriod, key, log=print):
    """Migrate every setting row; a row that fails is logged and skipped so
    one bad campus never aborts the migration for the others."""
    for setting in Setting.objects.filter(key=key):
        try:
            with transaction.atomic():  # a savepoint: a failed row leaves no partial writes
                _migrate_one(setting, Term, GradingPeriod, log)
        except Exception as exc:  # noqa: BLE001 -- log and keep going
            log(f'grades 0005: skipped setting {setting.pk}: {exc!r}')


def _migrate_one(setting, Term, GradingPeriod, log):
    if not isinstance(setting.value, dict):
        log(f'grades 0005: setting {setting.pk} value is not a dict; left as is')
        return
    value = dict(setting.value)
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
    if not value.get('grades_intro'):
        value['grades_intro'] = '' if intro == '-' else intro
    for retired in RETIRED_KEYS:
        value.pop(retired, None)
    setting.value = value
    setting.save(update_fields=['value'])


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
        ('cis', '0001_initial'),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
