"""
Data migration: add a "Grades" item under Classes, right below Sections, in
the CE sidebar.

The sidebar is rendered from the cis.settings.menu Setting (draw_menu reloads
it from the DB), not from cis/menu.py, so the item has to be written into the
saved menu. It links to the Grades → SIS page, whose view already marks
classes / grades_sis_sync as active.

Every cis.settings.menu row is patched (one per campus on a multi-campus
deployment). Forwards no-ops when there is no row, no ce_menu or no Classes
group, and is idempotent; backwards removes the item by name.
"""
import json

from django.db import migrations


SETTING_KEY = 'cis.settings.menu'
ROLE_KEY = 'ce_menu'
GROUP_NAME = 'classes'
AFTER_NAME = 'sections'
ENTRY = {
    'label': 'Grades',
    'name': 'grades_sis_sync',
    'url': 'grades_ce:sis_sync',
}


def patch_ce_menu(value, *, remove=False):
    """``value`` (the Setting's value dict) with the Grades item added or removed."""
    try:
        items = json.loads(value.get(ROLE_KEY) or '')
    except (TypeError, ValueError):
        return value
    if not isinstance(items, list):
        return value

    group = next((i for i in items if isinstance(i, dict) and i.get('name') == GROUP_NAME), None)
    if group is None or not isinstance(group.get('sub_menu'), list):
        return value

    sub_menu = [s for s in group['sub_menu'] if s.get('name') != ENTRY['name']]
    if not remove:
        names = [s.get('name') for s in sub_menu]
        at = names.index(AFTER_NAME) + 1 if AFTER_NAME in names else len(sub_menu)
        sub_menu.insert(at, dict(ENTRY))
    group['sub_menu'] = sub_menu

    value = dict(value)
    value[ROLE_KEY] = json.dumps(items)
    return value


def _apply(apps, remove):
    Setting = apps.get_model('cis', 'Setting')
    for setting in Setting.objects.filter(key=SETTING_KEY):
        new = patch_ce_menu(dict(setting.value or {}), remove=remove)
        if new != setting.value:
            setting.value = new
            setting.save(update_fields=['value'])


def add_grades_nav(apps, schema_editor):
    _apply(apps, remove=False)


def remove_grades_nav(apps, schema_editor):
    _apply(apps, remove=True)


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0001_initial'),
        ('grades', '0002_gradesissync'),
    ]

    operations = [
        migrations.RunPython(add_grades_nav, remove_grades_nav),
    ]
