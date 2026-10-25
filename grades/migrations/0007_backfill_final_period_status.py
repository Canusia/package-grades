"""Grades v1.0.0: carry pre-v1 grade status onto the final grading period.

Before v1 a section's submission state lived only on
``ClassSection.grade_status``. v1 reads per-period ``SectionPeriodStatus``
rows, so an upgraded section that was saved or submitted under 0.0.x would
show its final period as "Not started" and be editable again.

For every final grading period, each section on that period's term whose
``grade_status`` is 'saved' or 'submitted' and that has no status row for the
period gets one with the same status (and the section's
``grade_status_changed_on`` history, when it is a dict). Sections that already
have a row are left alone, so the migration is idempotent.

Reverse is a no-op: the rows it creates are indistinguishable from rows v1
writes, and removing them would hide submitted grades again.
"""
from django.db import migrations


def backfill(GradingPeriod, ClassSection, SectionPeriodStatus):
    created = 0
    for period in GradingPeriod.objects.filter(is_final=True):
        have = set(SectionPeriodStatus.objects.filter(period=period)
                   .values_list('class_section_id', flat=True))
        sections = ClassSection.objects.filter(
            term_id=period.term_id, grade_status__in=('saved', 'submitted'))
        for section in sections.exclude(pk__in=have):
            history = section.grade_status_changed_on
            SectionPeriodStatus.objects.create(
                period=period, class_section=section, status=section.grade_status,
                status_changed_on=dict(history) if isinstance(history, dict) else {})
            created += 1
    return created


def forwards(apps, schema_editor):
    backfill(
        apps.get_model('grades', 'GradingPeriod'),
        apps.get_model('cis', 'ClassSection'),
        apps.get_model('grades', 'SectionPeriodStatus'),
    )


class Migration(migrations.Migration):
    dependencies = [
        ('grades', '0006_grades_v1_nav'),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
