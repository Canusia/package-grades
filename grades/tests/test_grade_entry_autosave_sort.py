"""Instructor grade entry: template comments, auto-save, sortable roster.

Auto-save posts the same formset as "Save Grades as 'Draft'", flagged as an
XHR, and gets JSON back instead of the page. The gates (roster confirmation,
grade window) must refuse an auto-save exactly as they refuse a full POST.
"""
import json
import re
from pathlib import Path

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import SimpleTestCase
from .base import GradesTestCase as TestCase
from django.urls import reverse

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import Student
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

User = get_user_model()

GRADES_KEY = getattr(django_settings, 'CAMPUS_CODE_PREFIX') + '_class_grades'
TEMPLATES = Path(__file__).resolve().parent.parent / 'templates'
XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class TemplateCommentTests(SimpleTestCase):
    """`{# #}` is single-line only; a multi-line one renders as page text."""

    def test_no_multiline_hash_comments(self):
        offenders = []
        for path in TEMPLATES.rglob('*.html'):
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                for match in re.finditer(r'\{#', line):
                    if '#}' not in line[match.end():]:
                        offenders.append(f'{path.relative_to(TEMPLATES)}:{lineno}')
        self.assertEqual(offenders, [], 'Use {% comment %} for multi-line comments')


class GradeEntryAutosaveSortTests(TestCase):
    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='instructor')
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})
        Setting.objects.get_or_create(
            key='cis.settings.menu',
            defaults={'value': {'instructor_menu': json.dumps([])}},
        )
        Setting.objects.update_or_create(
            key=GRADES_KEY,
            defaults={'value': {
                'grades': 'A,B,C',
                'registration_status': ['applied'],
                'start_date': '01/01/2020',
                'end_date': '01/01/2040',
            }},
        )

        user = User.objects.create_user(
            username='auto_inst', email='auto_inst@example.com', password='x',
            first_name='Auto', last_name='Instructor')
        user.groups.add(Group.objects.get(name='instructor'))
        cls.user = user
        teacher = Teacher.objects.create(user=user)

        ay = AcademicYear.objects.create(name='AY autosave')
        term = Term.objects.create(academic_year=ay, code='FA34', label='Fall 2034')
        cohort = Cohort.objects.create(name='Cohort Auto', designator='CA')
        course = Course.objects.create(
            catalog_number='402', title='Autosave Course', cohort=cohort,
            credit_hours=3)
        highschool = HighSchool.objects.create(name='HS Autosave')
        cls.section = ClassSection.objects.create(
            class_number='9101', section_number='01',
            term=term, course=course, teacher=teacher)

        cls.registrations = []
        for i, (first, last, psid) in enumerate(
                [('Zoe', 'Adams', '300'), ('Amy', 'Young', '100')]):
            student_user = User.objects.create_user(
                username=f'auto_stu_{i}', email=f'auto_stu_{i}@example.com',
                password='x', first_name=first, last_name=last, psid=psid)
            student = Student.objects.create(user=student_user, account_verified=True)
            cls.registrations.append(StudentRegistration.objects.create(
                student=student, class_section=cls.section,
                highschool=highschool, status='applied',
                verification_status='pending', grade='',
                status_changed_on={'applied_on': '01/01/2024'}))

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse('instructor:class_section_grade', args=[self.section.id])

    def _draft_post(self, grades):
        data = {
            'form-TOTAL_FORMS': str(len(grades)),
            'form-INITIAL_FORMS': str(len(grades)),
            'form-MIN_NUM_FORMS': '1',
            'form-MAX_NUM_FORMS': str(len(grades)),
            'action': 'save_grade',
            'save_grade': "Save Grades as 'Draft'",
        }
        for i, (registration, grade) in enumerate(grades):
            data[f'form-{i}-student'] = 'x'
            data[f'form-{i}-student_id'] = str(registration.id)
            data[f'form-{i}-grade'] = grade
        return data

    # --- comment no longer leaks -------------------------------------------

    def test_period_selector_comment_not_rendered(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, 'Grading period selector')

    # --- auto-save -----------------------------------------------------------

    def test_autosave_saves_draft_and_returns_json(self):
        first, second = self.registrations
        response = self.client.post(
            self.url, self._draft_post([(first, 'B'), (second, '')]), **XHR)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True, 'status': 'saved'})
        first.refresh_from_db()
        self.section.refresh_from_db()
        self.assertEqual(first.grade, 'B')
        self.assertEqual(self.section.grade_status, 'saved')

    def test_autosave_rejects_invalid_grade(self):
        first, second = self.registrations
        response = self.client.post(
            self.url, self._draft_post([(first, 'Q'), (second, '')]), **XHR)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])
        first.refresh_from_db()
        self.assertEqual(first.grade, '')

    def test_autosave_refused_when_window_closed(self):
        Setting.objects.filter(key=GRADES_KEY).update(value={
            'grades': 'A,B,C', 'registration_status': ['applied'],
            'start_date': '01/01/2020', 'end_date': '01/02/2020'})
        first, second = self.registrations
        response = self.client.post(
            self.url, self._draft_post([(first, 'B'), (second, '')]), **XHR)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['ok'])
        first.refresh_from_db()
        self.assertEqual(first.grade, '')

    def test_autosave_refused_after_final_submission(self):
        self.section.grade_status = 'submitted'
        self.section.save()
        first, second = self.registrations
        response = self.client.post(
            self.url, self._draft_post([(first, 'B'), (second, '')]), **XHR)

        self.assertEqual(response.status_code, 409)
        first.refresh_from_db()
        self.section.refresh_from_db()
        self.assertEqual(first.grade, '')
        self.assertEqual(self.section.grade_status, 'submitted')

    def test_page_wires_autosave(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'data-autosave="1"')
        self.assertContains(response, 'grades/js/grade_roster.js')

    # --- sortable roster -----------------------------------------------------

    def test_rows_carry_sort_keys_and_student_id(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'data-last-name="Adams"')
        self.assertContains(response, 'data-first-name="Zoe"')
        self.assertContains(response, 'data-psid="300"')
        self.assertContains(response, 'data-sort-key="psid"')
        self.assertContains(response, '<td class="psid">100</td>', html=False)


class ClassGradesListStatusTests(SimpleTestCase):
    """instructor/grades/ labels grade_status as Draft / Submitted."""

    def test_list_labels_draft_and_submitted(self):
        source = (Path(__file__).resolve().parent.parent
                  / 'static/grades/instructor/js/grades.js').read_text()
        self.assertIn("'saved': '<span class=\"badge badge-secondary\">Draft</span>'", source)
        self.assertIn("'submitted': '<span class=\"badge badge-success\">Submitted</span>'", source)



class SectionsGradesTabTests(SimpleTestCase):
    """The Grades tab on /ce/sections/ shows in the tab bar, not only via #grades."""

    def test_grades_tab_is_not_hidden(self):
        from myce.component_registry.class_section_index import class_section_index_tabs
        self.assertFalse(class_section_index_tabs._tabs['grades']['hidden'])
