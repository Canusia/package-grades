"""Phase C: period-aware grade entry on the high school admin side.

Two things are load-bearing here.

1. **Authorization.** A high school admin is scoped by the high schools they
   administer, not by a teacher record. `test_cross_school_post_does_not_write`
   asserts against the *database* that a POST for a section at another school
   changes nothing -- a 404 response with a completed write would still be a
   breach.
2. **Storage routing.** An interim period must never touch
   `StudentRegistration.grade`, which the SIS export reads as the final grade.

See docs/superpowers/specs/2026-08-02-grades-grading-periods-design.md
"""
import json
from datetime import date, timedelta

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from two_step.models import TwoStep

from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition, HSPosition,
)
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import Student
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from ..models import GradingPeriod, PeriodGrade, SectionPeriodStatus

User = get_user_model()

GRADES_KEY = getattr(django_settings, 'CAMPUS_CODE_PREFIX') + '_class_grades'


class HSAdminPeriodGradeEntryTests(TestCase):
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
        Group.objects.get_or_create(name='highschool_admin')
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})
        Setting.objects.get_or_create(
            key='cis.settings.menu',
            defaults={'value': {'highschool_admin_menu': json.dumps([])}},
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

        # Two schools. The admin administers `hs_own` only.
        cls.hs_own = HighSchool.objects.create(name='HS Own')
        cls.hs_other = HighSchool.objects.create(name='HS Other')

        user = User.objects.create_user(
            username='hs_grade_admin', email='hs_grade_admin@example.com',
            password='x', first_name='Hs', last_name='Admin')
        user.groups.add(Group.objects.get(name='highschool_admin'))
        cls.user = user
        hsadmin = HSAdministrator.objects.create(user=user)
        position = HSPosition.objects.create(name='Counselor')
        HSAdministratorPosition.objects.create(
            hsadmin=hsadmin, highschool=cls.hs_own, position=position,
            status='Active')

        teacher_user = User.objects.create_user(
            username='hs_grade_teacher', email='hs_grade_teacher@example.com',
            password='x', first_name='Tea', last_name='Cher')
        cls.teacher = Teacher.objects.create(user=teacher_user)

        ay = AcademicYear.objects.create(name='AY hs periods')
        cls.term = Term.objects.create(
            academic_year=ay, code='FA34', label='Fall 2034')
        cohort = Cohort.objects.create(name='Cohort HS', designator='CH')
        cls.course = Course.objects.create(
            catalog_number='402', title='HS Periods Course', cohort=cohort,
            credit_hours=3)

    def setUp(self):
        self.client.force_login(self.user)
        TwoStep.objects.update_or_create(
            session_id=self.client.session.session_key,
            user=self.user,
            defaults={'verification_code': '123456', 'verified': True},
        )
        self.counter = getattr(self.__class__, '_counter', 6000) + 1
        self.__class__._counter = self.counter

    def _section(self, highschool=None, term=None):
        highschool = highschool or self.hs_own
        section = ClassSection.objects.create(
            class_number=str(self.counter), section_number='01',
            term=term or self.term, course=self.course, teacher=self.teacher,
            highschool=highschool)
        student_user = User.objects.create_user(
            username=f'hs_stu_{self.counter}',
            email=f'hs_stu_{self.counter}@example.com', password='x')
        student = Student.objects.create(
            user=student_user, account_verified=True, highschool=highschool)
        registration = StudentRegistration.objects.create(
            student=student, class_section=section, highschool=highschool,
            status='applied', verification_status='pending', grade='A',
            status_changed_on={'applied_on': '01/01/2024'})
        self.counter += 1
        self.__class__._counter = self.counter
        return section, registration

    def _period(self, name='Midterm', is_final=False, open_now=True):
        today = date.today()
        if open_now:
            opens_on, due_on = today - timedelta(days=7), today + timedelta(days=7)
        else:
            opens_on, due_on = today + timedelta(days=30), today + timedelta(days=60)
        return GradingPeriod.objects.create(
            term=self.term, name=name, sequence=1, is_final=is_final,
            opens_on=opens_on, due_on=due_on)

    def _url(self, section, period=None):
        url = reverse('grades_highschool_admin:class_section_grade',
                      kwargs={'record_id': section.id})
        if period is not None:
            url += f'?period={period.id}'
        return url

    def _post(self, section, registration, grade='B', period=None):
        return self.client.post(self._url(section, period), data={
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-student': 'Hs, Student',
            'form-0-student_id': str(registration.id),
            'form-0-grade': grade,
            'save_grade': 'Submit',
        })

    # -- own school: the page works -----------------------------------------

    def test_own_school_get_renders(self):
        section, _registration = self._section()

        resp = self.client.get(self._url(section))

        self.assertEqual(resp.status_code, 200)

    def test_own_school_post_writes_grade(self):
        section, registration = self._section()

        self._post(section, registration, grade='B')

        registration.refresh_from_db()
        section.refresh_from_db()
        self.assertEqual(registration.grade, 'B')
        self.assertEqual(section.grade_status, 'submitted')

    # -- other school: nothing renders and nothing writes --------------------

    def test_cross_school_get_is_not_found(self):
        section, _registration = self._section(highschool=self.hs_other)

        resp = self.client.get(self._url(section))

        self.assertEqual(resp.status_code, 404)

    def test_cross_school_post_does_not_write(self):
        """The gate must cover the POST, not only the render.

        Asserted against the database: a 404 with a completed write would
        still be a breach.
        """
        section, registration = self._section(highschool=self.hs_other)

        resp = self._post(section, registration, grade='C')

        # Database first: the write is what matters. A 404 that still wrote
        # would be a breach, so the response code is checked last.
        registration.refresh_from_db()
        section.refresh_from_db()
        self.assertEqual(
            registration.grade, 'A',
            'a HS admin must not grade a section at a school they do not '
            'administer')
        self.assertEqual(section.grade_status, '')
        self.assertFalse(PeriodGrade.objects.exists())
        self.assertFalse(SectionPeriodStatus.objects.exists())
        self.assertEqual(resp.status_code, 404)

    def test_cross_school_post_to_interim_period_does_not_write(self):
        section, registration = self._section(highschool=self.hs_other)
        period = self._period(name='Midterm', is_final=False)

        resp = self._post(section, registration, grade='C', period=period)

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(
            PeriodGrade.objects.filter(registration=registration).exists())

    # -- storage routing is the same as the instructor side ------------------

    def test_interim_period_writes_period_grade_only(self):
        section, registration = self._section()
        period = self._period(name='Midterm', is_final=False)

        self._post(section, registration, grade='C', period=period)

        registration.refresh_from_db()
        self.assertEqual(
            registration.grade, 'A',
            'an interim mark must never reach the SIS-bound final grade column')
        self.assertEqual(
            PeriodGrade.objects.get(
                period=period, registration=registration).grade, 'C')

        section.refresh_from_db()
        self.assertEqual(section.grade_status, '')
        self.assertEqual(
            SectionPeriodStatus.objects.get(
                period=period, class_section=section).status, 'submitted')

    def test_final_period_writes_registration_grade_and_mirrors_status(self):
        section, registration = self._section()
        period = self._period(name='Final', is_final=True)

        self._post(section, registration, grade='B', period=period)

        registration.refresh_from_db()
        section.refresh_from_db()
        self.assertEqual(registration.grade, 'B')
        self.assertEqual(section.grade_status, 'submitted')
        self.assertFalse(PeriodGrade.objects.filter(period=period).exists())

    def test_closed_period_does_not_write(self):
        section, registration = self._section()
        period = self._period(name='Midterm', open_now=False)

        self._post(section, registration, grade='C', period=period)

        self.assertFalse(PeriodGrade.objects.exists())
        registration.refresh_from_db()
        self.assertEqual(registration.grade, 'A')
