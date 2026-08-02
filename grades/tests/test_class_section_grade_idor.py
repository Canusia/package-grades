"""PT-32 regression: instructor grade detail view must be ownership-scoped.

The view at /instructor/grades/class_section/<uuid> (grades.views.instructor.
class_section_grade) previously loaded ClassSection by pk with no ownership
filter (IDOR). An instructor must only reach a section they teach
(teacher__user == request.user); any other section must return 404 on both
GET and POST.
"""
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

import json

from cis.models.term import AcademicYear, Term
from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.settings import Setting
from cis.models.student import Student
from cis.models.highschool import HighSchool
from cis.models.section import StudentRegistration
from django.conf import settings as django_settings

User = get_user_model()


class ClassSectionGradeIDORTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler blows up in tests
        # because the request has no usable IP. Disconnect for the test case.
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

        # The grade-detail GET render path instantiates the instructor_portal
        # SettingForm, which json.loads the instructor_menu from the
        # cis.settings.menu Setting. Seed a minimal menu so the owned-section
        # GET render reaches a 200 instead of erroring on a missing setting.
        Setting.objects.get_or_create(
            key='cis.settings.menu',
            defaults={'value': {'instructor_menu': json.dumps([])}},
        )

        # Two instructors, each backed by a Teacher record.
        user_a = User.objects.create_user(
            username='inst_a', email='inst_a@example.com', password='x',
            first_name='Aaa', last_name='Instructor',
        )
        user_a.groups.add(Group.objects.get(name='instructor'))
        user_b = User.objects.create_user(
            username='inst_b', email='inst_b@example.com', password='x',
            first_name='Bbb', last_name='Instructor',
        )
        user_b.groups.add(Group.objects.get(name='instructor'))
        cls.user_a = user_a
        cls.user_b = user_b
        cls.teacher_a = Teacher.objects.create(user=user_a)
        cls.teacher_b = Teacher.objects.create(user=user_b)

        ay = AcademicYear.objects.create(name='AY 2025-2026')
        term = Term.objects.create(
            academic_year=ay, code='FA25', label='Fall 2025',
        )
        cohort = Cohort.objects.create(name='Cohort One', designator='C1')
        course = Course.objects.create(
            catalog_number='101', title='Intro', cohort=cohort, credit_hours=3,
        )

        # One section per instructor.
        cls.section_a = ClassSection.objects.create(
            class_number='1001', section_number='01',
            term=term, course=course, teacher=cls.teacher_a,
        )
        cls.section_b = ClassSection.objects.create(
            class_number='1002', section_number='02',
            term=term, course=course, teacher=cls.teacher_b,
        )

    def setUp(self):
        self.client.force_login(self.user_a)

    def _url(self, section):
        return reverse(
            'instructor:class_section_grade',
            kwargs={'record_id': section.id},
        )

    def test_instructor_can_get_own_section(self):
        resp = self.client.get(self._url(self.section_a))
        self.assertEqual(resp.status_code, 200)

    def test_instructor_cannot_get_foreign_section(self):
        resp = self.client.get(self._url(self.section_b))
        self.assertEqual(resp.status_code, 404)

    def test_instructor_can_post_own_section(self):
        # An empty POST should be handled by the owned section (not 404).
        resp = self.client.post(self._url(self.section_a), data={})
        self.assertNotEqual(resp.status_code, 404)

    def test_instructor_cannot_post_foreign_section(self):
        resp = self.client.post(self._url(self.section_b), data={})
        self.assertEqual(resp.status_code, 404)


class ClassSectionGradeCrossSectionWriteTests(TestCase):
    """An instructor must not grade a registration outside the posted section.

    The view scopes the ClassSection to the requesting instructor (PT-32), but
    `student_id` arrives in POST data. Before the fix, ClassSectionGradeFormSet
    updated StudentRegistration by that bare primary key, so instructor A could
    post instructor B's registration id and write a grade to it.
    """

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
        # Student.save() assigns the 'student' group; it must exist.
        Group.objects.get_or_create(name='student')
        # The registration post_save signal writes a student note attributed
        # to the 'cron' user.
        User.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})
        Setting.objects.get_or_create(
            key='cis.settings.menu',
            defaults={'value': {'instructor_menu': json.dumps([])}},
        )
        # Grade choices come from this setting; without it 'B' is not a valid
        # choice and the formset would fail validation for the wrong reason.
        Setting.objects.update_or_create(
            key=getattr(django_settings, 'CAMPUS_CODE_PREFIX') + '_class_grades',
            defaults={'value': {
                'grades': 'A,B,C',
                'registration_status': ['applied'],
                'start_date': '01/01/2020',
                'end_date': '01/01/2040',
            }},
        )

        user_a = User.objects.create_user(
            username='xsec_a', email='xsec_a@example.com', password='x',
            first_name='Aaa', last_name='Instructor')
        user_a.groups.add(Group.objects.get(name='instructor'))
        user_b = User.objects.create_user(
            username='xsec_b', email='xsec_b@example.com', password='x',
            first_name='Bbb', last_name='Instructor')
        user_b.groups.add(Group.objects.get(name='instructor'))
        cls.user_a = user_a
        cls.teacher_a = Teacher.objects.create(user=user_a)
        cls.teacher_b = Teacher.objects.create(user=user_b)

        ay = AcademicYear.objects.create(name='AY 2026-2027 xsec')
        term = Term.objects.create(academic_year=ay, code='FA26', label='Fall 2026')
        cohort = Cohort.objects.create(name='Cohort XSec', designator='CX')
        course = Course.objects.create(
            catalog_number='201', title='Intro XSec', cohort=cohort, credit_hours=3)

        cls.section_a = ClassSection.objects.create(
            class_number='2001', section_number='01',
            term=term, course=course, teacher=cls.teacher_a)
        cls.section_b = ClassSection.objects.create(
            class_number='2002', section_number='02',
            term=term, course=course, teacher=cls.teacher_b)

        cls.highschool = HighSchool.objects.create(name='HS XSec')
        student_user = User.objects.create_user(
            username='xsec_stu', email='xsec_stu@example.com', password='x')
        cls.student = Student.objects.create(user=student_user, account_verified=True)

        # A registration in the OTHER instructor's section.
        cls.foreign_registration = StudentRegistration.objects.create(
            student=cls.student,
            class_section=cls.section_b,
            highschool=cls.highschool,
            status='applied',
            verification_status='pending',
            grade='A',
            status_changed_on={'applied_on': '01/01/2024'},
        )

    def setUp(self):
        self.client.force_login(self.user_a)

    def test_cannot_grade_registration_from_another_section(self):
        url = reverse('instructor:class_section_grade',
                      kwargs={'record_id': self.section_a.id})
        self.client.post(url, data={
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-student': 'Someone, Else',
            'form-0-student_id': str(self.foreign_registration.id),
            'form-0-grade': 'B',
            'save_grade': 'Submit',
        })

        self.foreign_registration.refresh_from_db()
        self.assertEqual(
            self.foreign_registration.grade, 'A',
            'grade on another section\'s registration must be unchanged')

    def test_malformed_student_id_does_not_error(self):
        url = reverse('instructor:class_section_grade',
                      kwargs={'record_id': self.section_a.id})
        resp = self.client.post(url, data={
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-student': 'Not, AUuid',
            'form-0-student_id': 'not-a-uuid',
            'form-0-grade': 'B',
            'save_grade': 'Submit',
        })
        self.assertNotEqual(resp.status_code, 500)
