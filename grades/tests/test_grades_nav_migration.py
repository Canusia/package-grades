"""0003_add_grades_nav: Grades goes under Classes, right below Sections."""
import importlib
import json

from django.test import SimpleTestCase

migration = importlib.import_module(
    f'{__package__.rsplit(".", 1)[0]}.migrations.0003_add_grades_nav')


def _value(sub_menu, extra=None):
    items = [{'name': 'dashboard', 'url': 'cis:dashboard'},
             {'name': 'classes', 'label': 'Classes', 'sub_menu': sub_menu}]
    value = {'ce_menu': json.dumps(items), 'instructor_menu': '[]'}
    value.update(extra or {})
    return value


def _names(value):
    classes = [i for i in json.loads(value['ce_menu']) if i['name'] == 'classes'][0]
    return [s.get('name') for s in classes['sub_menu']]


class GradesNavMigrationTests(SimpleTestCase):
    def test_inserted_right_after_sections(self):
        value = _value([{'name': 'sections'}, {'name': 'future_sections'}])
        out = migration.patch_ce_menu(value)
        self.assertEqual(_names(out), ['sections', 'grades_sis_sync', 'future_sections'])
        entry = json.loads(out['ce_menu'])[1]['sub_menu'][1]
        self.assertEqual(entry, migration.ENTRY)
        self.assertEqual(out['instructor_menu'], '[]')

    def test_idempotent(self):
        value = _value([{'name': 'sections'}, {'name': 'future_sections'}])
        once = migration.patch_ce_menu(value)
        self.assertEqual(migration.patch_ce_menu(once), once)

    def test_moves_a_misplaced_item_below_sections(self):
        value = _value([{'name': 'grades_sis_sync'}, {'name': 'sections'}])
        self.assertEqual(_names(migration.patch_ce_menu(value)), ['sections', 'grades_sis_sync'])

    def test_appended_when_no_sections(self):
        value = _value([{'name': 'courses'}])
        self.assertEqual(_names(migration.patch_ce_menu(value)), ['courses', 'grades_sis_sync'])

    def test_reverse_removes(self):
        value = migration.patch_ce_menu(_value([{'name': 'sections'}]))
        self.assertEqual(_names(migration.patch_ce_menu(value, remove=True)), ['sections'])

    def test_no_classes_group_or_bad_json_left_alone(self):
        no_classes = {'ce_menu': json.dumps([{'name': 'dashboard'}])}
        self.assertEqual(migration.patch_ce_menu(no_classes), no_classes)
        bad = {'ce_menu': 'not json'}
        self.assertEqual(migration.patch_ce_menu(bad), bad)
        self.assertEqual(migration.patch_ce_menu({}), {})
