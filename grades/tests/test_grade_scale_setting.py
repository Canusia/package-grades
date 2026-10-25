"""Grade Scale on the settings page (#7): the saved scale reaches the table as
JSON, and saving the page never replaces a custom scale with the default."""
import json
import os
import uuid

from django.http import HttpRequest
from .base import GradesTestCase as TestCase

from cis.models.settings import Setting
from cis.models.term import AcademicYear, Term

from ..settings.class_section_grades import class_section_grades
from .test_settings_gaps import legacy_value

CUSTOM = [{'grade': 'A', 'points': 4.0}, {'grade': 'B', 'points': 3.67},
          {'grade': 'W', 'points': 0.0}]


class GradeScaleSettingTests(TestCase):
    def setUp(self):
        ay = AcademicYear.objects.create(name=f'AY-{uuid.uuid4().hex[:6]}')
        self.term = Term.objects.create(academic_year=ay, code=uuid.uuid4().hex[:6], label='Fall')
        Setting.objects.update_or_create(
            key=class_section_grades.key,
            defaults={'value': {**legacy_value(self.term.id), 'grade_scale': CUSTOM}})

    def _form(self, **overrides):
        data = {**legacy_value(self.term.id), 'grade_scale': '',
                'is_active': 'Yes', 'debug_email_list': '',
                'notify_instructor_on_submit': 'Yes', 'grades_submitted_cc': '',
                'send_grade_reminders': 'Yes', 'student_grades_visible': 'Yes',
                'student_transcript_enabled': 'Yes', 'hs_admin_grade_entry': 'No',
                'student_grade_columns': ['term', 'course', 'tuition', 'status', 'grade'],
                **overrides}
        return class_section_grades(HttpRequest(), data)

    def test_saved_scale_renders_as_json(self):
        form = class_section_grades(HttpRequest(), initial=class_section_grades.from_db())
        value = form['grade_scale'].value()
        rendered = form.fields['grade_scale'].prepare_value(value)
        self.assertEqual(json.loads(rendered), CUSTOM)
        self.assertIn('&quot;grade&quot;', str(form['grade_scale']))

    def test_empty_value_keeps_saved_scale(self):
        form = self._form(grade_scale='')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._to_python()['grade_scale'], CUSTOM)
        self.assertEqual(form._to_python()['grades'], 'A,B,W')

    def test_custom_scale_is_saved(self):
        scale = [{'grade': 'P', 'points': 4}, {'grade': 'NP', 'points': 0}]
        form = self._form(grade_scale=json.dumps(scale))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._to_python()['grade_scale'], scale)

    def test_unreadable_scale_is_rejected_not_defaulted(self):
        for bad in ("[{'grade': 'A', 'points': 4.0}]", '{}', '[]',
                    '[{"grade": "", "points": 1}]', '[{"grade": "A", "points": "x"}]'):
            form = self._form(grade_scale=bad)
            self.assertFalse(form.is_valid(), bad)
            self.assertIn('grade_scale', form.errors)

    def test_legacy_text_points_round_trip(self):
        # from_db's legacy gpa_points and hand-edited JSON can store "4.0".
        legacy = [{'grade': 'A', 'points': '4.0'}, {'grade': 'F', 'points': 0}]
        form = self._form(grade_scale=class_section_grades.base_fields['grade_scale']
                          .prepare_value(legacy))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._to_python()['gpa_points'], {'A': 4.0, 'F': 0.0})

    def test_non_finite_or_missing_points_rejected(self):
        for bad in ('[{"grade": "A", "points": NaN}]', '[{"grade": "A", "points": Infinity}]',
                    '[{"grade": "A", "points": null}]', '[{"grade": "A", "points": true}]'):
            form = self._form(grade_scale=bad)
            self.assertFalse(form.is_valid(), bad)

    def test_no_saved_row_falls_back_to_default(self):
        Setting.objects.filter(key=class_section_grades.key).delete()
        form = self._form(grade_scale='')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._to_python()['grade_scale'],
                         class_section_grades.get_default_grade_scale())

    def test_table_does_not_silently_fall_back(self):
        path = os.path.join(os.path.dirname(__file__), '..', 'static', 'grades', 'js', 'settings.js')
        with open(path) as fh:
            src = fh.read()
        self.assertNotIn('} catch (e) {}', src)
        self.assertIn("$hiddenField.val('')", src)
