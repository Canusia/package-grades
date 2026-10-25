"""Student grades table columns are tenant-configurable (#1).

One list, ``services.student_table.COLUMNS``, drives the ``<th>`` row, the
DataTables column config and the grades-owned feed, so the three cannot drift.
A column switched off is not sent to the browser at all -- hiding Tuition must
not ship the money value in the row JSON.
"""
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.test import RequestFactory

from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import Student

from ..services import student_table
from ..settings.class_section_grades import class_section_grades
from .test_settings_gaps import User, _Fixture, _sfx, legacy_value

ALL = ['term', 'course', 'tuition', 'status', 'grade']


class _Base(_Fixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(  # registration signals log as 'cron'
            username='cron', defaults={'email': 'cron@example.com'})
        cls.hs = HighSchool.objects.create(name=f'HS-{_sfx()}')
        user = User.objects.create_user(
            username=f's_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        cls.student = Student.objects.create(user=user, highschool=cls.hs)
        cls.section = ClassSection.objects.create(
            course=cls.course, term=cls.term, teacher=cls.teacher,
            class_number='7001', section_number='01', tuition=123.4,
            highschool=cls.hs)
        cls.registration = StudentRegistration.objects.create(
            student=cls.student, class_section=cls.section, highschool=cls.hs,
            status='registered', status_changed_on={})

    def _rows(self):
        from ..views import student as views
        request = RequestFactory().get('/student/grades/rows/')
        request.user = self.student.user
        with patch.object(views, 'get_current_student', return_value=self.student):
            response = views.grades_rows(request)
        return json.loads(response.content)['data']


class ColumnSettingTests(_Base):
    def test_default_is_all_five_in_order(self):
        Setting.objects.filter(key=class_section_grades.key).delete()
        self.assertEqual([c['key'] for c in student_table.enabled_columns()], ALL)

    def test_legacy_row_shows_all_five(self):
        self._store()
        self.assertEqual([c['key'] for c in student_table.enabled_columns()], ALL)

    def test_order_follows_columns_not_the_setting(self):
        self._store(student_grade_columns=['grade', 'term'])
        self.assertEqual(
            [c['key'] for c in student_table.enabled_columns()], ['term', 'grade'])

    def test_unknown_keys_are_ignored(self):
        self._store(student_grade_columns=['term', 'bogus'])
        self.assertEqual([c['key'] for c in student_table.enabled_columns()], ['term'])

    def test_form_requires_at_least_one_column(self):
        data = {**legacy_value(self.term.id), 'grade_scale': '',
                'is_active': 'Yes', 'send_grade_reminders': 'Yes',
                'notify_instructor_on_submit': 'Yes', 'student_grades_visible': 'Yes',
                'student_transcript_enabled': 'Yes', 'hs_admin_grade_entry': 'No'}
        form = class_section_grades(HttpRequest(), {**data, 'student_grade_columns': []})
        self.assertFalse(form.is_valid())
        self.assertIn('student_grade_columns', form.errors)
        form = class_section_grades(
            HttpRequest(), {**data, 'student_grade_columns': ['term', 'grade']})
        self.assertTrue(form.is_valid(), form.errors)


class FeedTests(_Base):
    def test_all_columns(self):
        self._store()
        row = self._rows()[0]
        self.assertEqual(set(row), set(ALL))
        self.assertEqual(row['term'], self.term.label)
        self.assertEqual(row['tuition'], '$123.40')
        self.assertIn('7001 - 01', row['course'])

    def test_tuition_off_is_not_sent(self):
        self._store(student_grade_columns=['term', 'course', 'status', 'grade'])
        row = self._rows()[0]
        self.assertNotIn('tuition', row)
        self.assertNotIn('123', json.dumps(row))

    def test_only_registered_registrations(self):
        self._store()
        StudentRegistration.objects.create(
            student=self.student, highschool=self.hs, status='applied', status_changed_on={},
            class_section=ClassSection.objects.create(
                course=self.course, term=self.term, teacher=self.teacher,
                class_number='7002', section_number='01', highschool=self.hs))
        self.assertEqual(len(self._rows()), 1)

    def test_only_the_students_own_registrations(self):
        self._store()
        other = Student.objects.create(
            user=User.objects.create_user(
                username=f'o_{_sfx()}', email=f'oth_{_sfx()}@x.com', password='x'),
            highschool=self.hs)
        StudentRegistration.objects.create(
            student=other, class_section=self.section, highschool=self.hs,
            status='registered', status_changed_on={})
        self.assertEqual(len(self._rows()), 1)

    def test_course_cell_is_escaped(self):
        self._store()
        self.section.highschool_course_name = '<b>x</b>'
        self.section.save()
        self.assertIn('&lt;b&gt;x&lt;/b&gt;', self._rows()[0]['course'])

    def test_hidden_grades_send_nothing(self):
        self._store(student_grades_visible='No')
        self.assertEqual(self._rows(), [])


class TemplateTests(_Base):
    def _html(self):
        return render_to_string('grades/student/_grades_body.html', {
            'grades_visible': True, 'transcript_enabled': False,
            'grade_columns': student_table.enabled_columns()})

    def test_headers_follow_the_setting(self):
        self._store(student_grade_columns=['term', 'course', 'status', 'grade'])
        html = self._html()
        self.assertNotIn('Tuition', html)
        self.assertIn('Grades', html)

    def test_view_passes_columns(self):
        self._store(student_grade_columns=['term', 'grade'])
        from ..views import student as views
        request = RequestFactory().get('/student/grades/')
        request.user = self.student.user
        with patch.object(views, 'get_current_student', return_value=MagicMock()), \
                patch.object(views, 'portal_lang') as lang, \
                patch.object(views, 'draw_menu', return_value=''), \
                patch.object(views, 'render') as render:
            lang.return_value.from_db.return_value = {'grades_blurb': 'x'}
            views.grades(request)
        ctx = render.call_args.args[2]
        self.assertEqual([c['key'] for c in ctx['grade_columns']], ['term', 'grade'])
