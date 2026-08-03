"""Phase B: period-aware grade entry.

The load-bearing test is `test_interim_period_does_not_touch_registration_grade`.
`StudentRegistration.grade` is what the SIS export reads as the final grade, so
a midterm mark landing there would be pushed to the SIS as final. That
assertion is checked against the database, not the response.

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

from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import Student
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from ..models import GradingPeriod, PeriodGrade, SectionPeriodStatus

User = get_user_model()

GRADES_KEY = getattr(django_settings, 'CAMPUS_CODE_PREFIX') + '_class_grades'


class PeriodGradeEntryTests(TestCase):
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
            username='per_inst', email='per_inst@example.com', password='x',
            first_name='Per', last_name='Instructor')
        user.groups.add(Group.objects.get(name='instructor'))
        cls.user = user
        cls.teacher = Teacher.objects.create(user=user)

        ay = AcademicYear.objects.create(name='AY periods entry')
        cls.term = Term.objects.create(
            academic_year=ay, code='FA32', label='Fall 2032')
        cls.other_term = Term.objects.create(
            academic_year=ay, code='SP33', label='Spring 2033')
        cohort = Cohort.objects.create(name='Cohort Per', designator='CP')
        cls.course = Course.objects.create(
            catalog_number='401', title='Periods Course', cohort=cohort,
            credit_hours=3)
        cls.highschool = HighSchool.objects.create(name='HS Periods')

    def setUp(self):
        self.client.force_login(self.user)
        self.counter = getattr(self.__class__, '_counter', 4000) + 1
        self.__class__._counter = self.counter

    def _section(self, term=None):
        section = ClassSection.objects.create(
            class_number=str(self.counter), section_number='01',
            term=term or self.term, course=self.course, teacher=self.teacher)
        student_user = User.objects.create_user(
            username=f'per_stu_{self.counter}',
            email=f'per_stu_{self.counter}@example.com', password='x')
        student = Student.objects.create(
            user=student_user, account_verified=True)
        registration = StudentRegistration.objects.create(
            student=student, class_section=section,
            highschool=self.highschool, status='applied',
            verification_status='pending', grade='A',
            status_changed_on={'applied_on': '01/01/2024'})
        return section, registration

    def _period(self, term=None, name='Midterm', is_final=False, open_now=True):
        today = date.today()
        if open_now:
            opens_on, due_on = today - timedelta(days=7), today + timedelta(days=7)
        else:
            opens_on, due_on = today + timedelta(days=30), today + timedelta(days=60)
        return GradingPeriod.objects.create(
            term=term or self.term, name=name, sequence=1,
            is_final=is_final, opens_on=opens_on, due_on=due_on)

    def _post(self, section, registration, grade='B', period=None):
        url = reverse('instructor:class_section_grade',
                      kwargs={'record_id': section.id})
        if period is not None:
            url += f'?period={period.id}'
        return self.client.post(url, data={
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-student': 'Per, Student',
            'form-0-student_id': str(registration.id),
            'form-0-grade': grade,
            'save_grade': 'Submit',
        })

    # -- no periods configured: unchanged behaviour ------------------------

    def test_no_periods_writes_registration_grade_as_before(self):
        section, registration = self._section()

        self._post(section, registration)

        registration.refresh_from_db()
        section.refresh_from_db()
        self.assertEqual(registration.grade, 'B')
        self.assertEqual(section.grade_status, 'submitted')
        self.assertFalse(PeriodGrade.objects.exists())

    # -- interim period: must not touch the SIS-bound column ---------------

    def test_interim_period_does_not_touch_registration_grade(self):
        section, registration = self._section()
        period = self._period(name='Midterm', is_final=False)

        self._post(section, registration, grade='C', period=period)

        registration.refresh_from_db()
        self.assertEqual(
            registration.grade, 'A',
            'an interim mark must never reach the SIS-bound final grade column')

        mark = PeriodGrade.objects.get(period=period, registration=registration)
        self.assertEqual(mark.grade, 'C')

    def test_interim_period_does_not_mirror_section_grade_status(self):
        section, registration = self._section()
        period = self._period(name='Midterm', is_final=False)

        self._post(section, registration, grade='C', period=period)

        section.refresh_from_db()
        self.assertEqual(section.grade_status, '')
        self.assertEqual(
            SectionPeriodStatus.objects.get(
                period=period, class_section=section).status,
            'submitted')

    # -- final period: writes through and mirrors --------------------------

    def test_final_period_writes_registration_grade_and_mirrors_status(self):
        section, registration = self._section()
        period = self._period(name='Final', is_final=True)

        self._post(section, registration, grade='B', period=period)

        registration.refresh_from_db()
        section.refresh_from_db()
        self.assertEqual(registration.grade, 'B')
        self.assertEqual(section.grade_status, 'submitted')
        self.assertFalse(
            PeriodGrade.objects.filter(period=period).exists(),
            'final grades live on the registration, not duplicated here')

    # -- window and scoping ------------------------------------------------

    def test_closed_period_does_not_write(self):
        section, registration = self._section()
        period = self._period(name='Midterm', open_now=False)

        self._post(section, registration, grade='C', period=period)

        self.assertFalse(PeriodGrade.objects.exists())
        registration.refresh_from_db()
        self.assertEqual(registration.grade, 'A')

    def test_period_from_another_term_is_rejected(self):
        section, registration = self._section()
        self._period(name='Midterm')
        foreign = self._period(term=self.other_term, name='Foreign Midterm')

        resp = self._post(section, registration, grade='C', period=foreign)

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(PeriodGrade.objects.filter(period=foreign).exists())

    def test_marks_are_kept_separate_per_period(self):
        section, registration = self._section()
        midterm = self._period(name='Midterm')
        second = GradingPeriod.objects.create(
            term=self.term, name='Second Check', sequence=2,
            opens_on=date.today() - timedelta(days=3),
            due_on=date.today() + timedelta(days=3))

        self._post(section, registration, grade='B', period=midterm)
        self._post(section, registration, grade='C', period=second)

        self.assertEqual(
            PeriodGrade.objects.get(
                period=midterm, registration=registration).grade, 'B')
        self.assertEqual(
            PeriodGrade.objects.get(
                period=second, registration=registration).grade, 'C')
        registration.refresh_from_db()
        self.assertEqual(registration.grade, 'A')
