"""Copy each saved `<prefix>_class_grades` grade scale into a "Standard" GradeScale.

Reads cis_setting with raw SQL rather than the historical Setting model: this
migration depends only on cis 0001_initial (tenants are on different cis
migrations), and Setting.campus arrives in a later cis migration. A fresh
database has no setting rows, so nothing is created; services/scales.py falls
back to the setting until a scale exists.
"""
import json
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import migrations

DEFAULT_SCALE = [
    ('A', '4.0'), ('A-', '3.7'), ('B+', '3.3'), ('B', '3.0'), ('B-', '2.7'),
    ('C+', '2.3'), ('C', '2.0'), ('C-', '1.7'), ('D+', '1.3'), ('D', '1.0'),
    ('D-', '0.7'), ('F', '0.0'),
]


def _points(value):
    """Points as a 2-place Decimal, or None (not a number, or too big for
    the 4-digit column)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        points = Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None
    return points if abs(points) < 100 else None


def _as_dict(value):
    while isinstance(value, str):     # saved as (possibly double-encoded) JSON text
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def entries_from_setting(value):
    """[(grade, points)] from a saved setting value.

    Same precedence as services.scales.setting_scale(), which the grade
    picker used: letters from the `grades` list, else `grade_scale`, else
    the shipped default; points from `grade_scale`, else `gpa_points`.
    Letters longer than a final grade can hold (10) are skipped.
    """
    value = _as_dict(value)
    scale = value.get('grade_scale') if isinstance(value.get('grade_scale'), list) else []
    points = {str(i.get('grade') or '').strip(): i.get('points')
              for i in scale if isinstance(i, dict)}
    if not points and isinstance(value.get('gpa_points'), dict):
        points = {str(k).strip(): v for k, v in value['gpa_points'].items()}
    if str(value.get('grades') or '').strip():
        letters = str(value['grades']).split(',')
    elif points:
        letters = list(points)
    else:
        return [(g, Decimal(p)) for g, p in DEFAULT_SCALE]
    out = []
    for grade in letters:
        grade = str(grade).strip()
        if grade and grade != '-' and len(grade) <= 10 and grade not in [g for g, _ in out]:
            out.append((grade, _points(points.get(grade))))
    return out or [(g, Decimal(p)) for g, p in DEFAULT_SCALE]


def _setting_rows(connection, key):
    tables = connection.introspection.table_names()
    if 'cis_setting' not in tables:
        return []
    with connection.cursor() as cursor:
        columns = {c.name for c in connection.introspection.get_table_description(cursor, 'cis_setting')}
        campus_col = 'campus_id' if 'campus_id' in columns else 'NULL'
        cursor.execute(f'SELECT value, {campus_col} FROM cis_setting WHERE key = %s', [key])
        return cursor.fetchall()


def forwards(apps, schema_editor):
    GradeScale = apps.get_model('grades', 'GradeScale')
    GradeScaleEntry = apps.get_model('grades', 'GradeScaleEntry')
    key = getattr(settings, 'CAMPUS_CODE_PREFIX', '') + '_class_grades'
    for value, campus_id in _setting_rows(schema_editor.connection, key):
        if GradeScale.objects.filter(campus_id=campus_id, is_default=True).exists():
            continue
        scale = GradeScale.objects.create(
            name='Standard', campus_id=campus_id, is_default=True,
            description='Copied from the grades settings.')
        GradeScaleEntry.objects.bulk_create([
            GradeScaleEntry(scale=scale, grade=grade, points=points, sequence=i)
            for i, (grade, points) in enumerate(entries_from_setting(value))])


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0001_initial'),
        ('grades', '0009_grade_scales'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
