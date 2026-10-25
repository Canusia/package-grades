"""
Data migration: v1 menu items.

* CE sidebar: "Grade Summary" under Classes, right below the Grades -> SIS item.
* Instructor sidebar: a "Grades" item right below Students, when the menu has
  no item named ``grades`` yet.

Both live in the cis.settings.menu Setting (one row per campus on a
multi-campus deployment). Idempotent; backwards removes the items by name.
"""
import json

from django.db import migrations


SETTING_KEY = 'cis.settings.menu'
CE_KEY = 'ce_menu'
INSTRUCTOR_KEY = 'instructor_menu'
GROUP_NAME = 'classes'
AFTER_NAME = 'grades_sis_sync'
ENTRY = {
    'label': 'Grade Summary',
    'name': 'grades_summary',
    'url': 'grades_ce:summary',
}
INSTRUCTOR_AFTER = 'students'
INSTRUCTOR_ENTRY = {
    'type': 'nav-item',
    'icon': 'fas fa-fw fa-graduation-cap',
    'name': 'grades',
    'label': 'Grades',
    'url': 'instructor:grades',
}


def _load(value, key):
    try:
        items = json.loads(value.get(key) or '')
    except (TypeError, ValueError):
        return None
    return items if isinstance(items, list) else None


def patch_ce_menu(value, *, remove=False):
    items = _load(value, CE_KEY)
    if items is None:
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
    value[CE_KEY] = json.dumps(items)
    return value


def patch_instructor_menu(value, *, remove=False):
    items = _load(value, INSTRUCTOR_KEY)
    if items is None:
        return value
    names = [i.get('name') for i in items if isinstance(i, dict)]
    if remove:
        items = [i for i in items if not (isinstance(i, dict) and i.get('name') == INSTRUCTOR_ENTRY['name'])]
    elif INSTRUCTOR_ENTRY['name'] in names:
        return value
    else:
        at = names.index(INSTRUCTOR_AFTER) + 1 if INSTRUCTOR_AFTER in names else len(items)
        items.insert(at, dict(INSTRUCTOR_ENTRY))
    value = dict(value)
    value[INSTRUCTOR_KEY] = json.dumps(items)
    return value


def _apply(apps, remove):
    Setting = apps.get_model('cis', 'Setting')
    for setting in Setting.objects.filter(key=SETTING_KEY):
        new = patch_ce_menu(dict(setting.value or {}), remove=remove)
        new = patch_instructor_menu(new, remove=remove)
        if new != setting.value:
            setting.value = new
            setting.save(update_fields=['value'])


def add_nav(apps, schema_editor):
    _apply(apps, remove=False)


def remove_nav(apps, schema_editor):
    _apply(apps, remove=True)


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0001_initial'),
        ('grades', '0005_settings_to_periods'),
    ]

    operations = [
        migrations.RunPython(add_nav, remove_nav),
    ]
