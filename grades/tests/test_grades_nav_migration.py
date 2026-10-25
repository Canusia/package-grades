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


class GradesV1NavMigrationTests(SimpleTestCase):
    def setUp(self):
        self.m = importlib.import_module(
            f'{__package__.rsplit(".", 1)[0]}.migrations.0006_grades_v1_nav')

    def _value(self, instructor):
        ce = [{'name': 'classes', 'sub_menu': [{'name': 'sections'}, {'name': 'grades_sis_sync'}, {'name': 'x'}]}]
        return {'ce_menu': json.dumps(ce), 'instructor_menu': json.dumps(instructor)}

    def test_adds_both_items_in_place_and_is_idempotent(self):
        out = self.m.patch_instructor_menu(self.m.patch_ce_menu(
            self._value([{'name': 'students'}, {'name': 'z'}])))
        ce = json.loads(out['ce_menu'])[0]['sub_menu']
        self.assertEqual([s['name'] for s in ce], ['sections', 'grades_sis_sync', 'grades_summary', 'x'])
        self.assertEqual([i['name'] for i in json.loads(out['instructor_menu'])], ['students', 'grades', 'z'])
        again = self.m.patch_instructor_menu(self.m.patch_ce_menu(out))
        self.assertEqual(again, out)

    def test_existing_instructor_grades_item_untouched(self):
        value = self._value([{'name': 'grades', 'url': 'old'}, {'name': 'students'}])
        self.assertEqual(self.m.patch_instructor_menu(value), value)

    def test_reverse_removes_by_name(self):
        out = self.m.patch_instructor_menu(self.m.patch_ce_menu(self._value([{'name': 'students'}])))
        back = self.m.patch_instructor_menu(self.m.patch_ce_menu(out, remove=True), remove=True)
        self.assertEqual([i['name'] for i in json.loads(back['instructor_menu'])], ['students'])
        self.assertNotIn('grades_summary', back['ce_menu'])
