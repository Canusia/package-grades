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
