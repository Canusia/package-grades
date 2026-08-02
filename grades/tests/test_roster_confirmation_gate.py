"""Roster confirmation gate: grades must not be writable while a section's
roster is pending verification, when the tenant has enabled the setting.

The load-bearing assertions POST a grade and then check the database, not the
response code -- the read-only rendering is a courtesy, the write refusal is
the actual gate.

The '' (never asked) and 'inaccurate' cases are pinned deliberately: both pass
the gate by design, and a future change that starts blocking them would be an
outage rather than a tightening. See
docs/superpowers/specs/2026-08-02-grades-roster-confirmation-gate-design.md
"""
import json

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

User = get_user_model()

GRADES_KEY = getattr(django_settings, 'CAMPUS_CODE_PREFIX') + '_class_grades'


class RosterConfirmationGateTests(TestCase):
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

        user = User.objects.create_user(
            username='gate_inst', email='gate_inst@example.com', password='x',
            first_name='Gate', last_name='Instructor')
        user.groups.add(Group.objects.get(name='instructor'))
        cls.user = user
        cls.teacher = Teacher.objects.create(user=user)

        ay = AcademicYear.objects.create(name='AY gate')
        cls.term = Term.objects.create(
            academic_year=ay, code='FA27', label='Fall 2027')
        cohort = Cohort.objects.create(name='Cohort Gate', designator='CG')
        cls.course = Course.objects.create(
            catalog_number='301', title='Gate Course', cohort=cohort,
            credit_hours=3)
        cls.highschool = HighSchool.objects.create(name='HS Gate')

    def _grade_settings(self, **overrides):
        value = {
            'grades': 'A,B,C',
            'registration_status': ['applied'],
            'start_date': '01/01/2020',
            'end_date': '01/01/2040',
        }
        value.update(overrides)
        Setting.objects.update_or_create(
            key=GRADES_KEY, defaults={'value': value})

    def _section(self, roster_status, class_number):
        section = ClassSection.objects.create(
            class_number=class_number, section_number='01',
            term=self.term, course=self.course, teacher=self.teacher,
            roster_status=roster_status,
        )
        student_user = User.objects.create_user(
            username=f'gate_stu_{class_number}',
            email=f'gate_stu_{class_number}@example.com', password='x')
        student = Student.objects.create(
            user=student_user, account_verified=True)
        registration = StudentRegistration.objects.create(
            student=student,
            class_section=section,
            highschool=self.highschool,
            status='applied',
            verification_status='pending',
            grade='A',
            status_changed_on={'applied_on': '01/01/2024'},
        )
        return section, registration

    def _post_grade(self, section, registration, grade='B'):
        self.client.force_login(self.user)
        url = reverse('instructor:class_section_grade',
                      kwargs={'record_id': section.id})
        return self.client.post(url, data={
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'form-0-student': 'Gate, Student',
            'form-0-student_id': str(registration.id),
            'form-0-grade': grade,
            'save_grade': 'Submit',
        })

    def _grade_after_post(self, roster_status, class_number, **setting_overrides):
        self._grade_settings(**setting_overrides)
        section, registration = self._section(roster_status, class_number)
        self._post_grade(section, registration)
        registration.refresh_from_db()
        return registration.grade

    # -- setting off ------------------------------------------------------

    def test_setting_off_pending_roster_still_writes(self):
        """Default behaviour is unchanged; no tenant regresses on upgrade."""
        self.assertEqual(
            self._grade_after_post('pending verification', '3001'), 'B')

    # -- setting on -------------------------------------------------------

    def test_pending_verification_blocks_write(self):
        self.assertEqual(
            self._grade_after_post(
                'pending verification', '3002',
                require_roster_confirmation=True),
            'A', 'grade must not be written while the roster is pending')

    def test_accurate_allows_write(self):
        self.assertEqual(
            self._grade_after_post(
                'accurate', '3003', require_roster_confirmation=True), 'B')

    def test_inaccurate_allows_write(self):
        """Reporting the roster inaccurate is still a response; do not punish it."""
        self.assertEqual(
            self._grade_after_post(
                'inaccurate', '3004', require_roster_confirmation=True), 'B')

    def test_never_asked_allows_write(self):
        """'' is the default state -- blocking it would strand every section."""
        self.assertEqual(
            self._grade_after_post(
                '', '3005', require_roster_confirmation=True), 'B')

    # -- rendering --------------------------------------------------------

    def test_blocked_section_renders_read_only_with_message(self):
        self._grade_settings(
            require_roster_confirmation=True,
            roster_not_confirmed_message='Confirm the roster first.')
        section, _ = self._section('pending verification', '3006')

        self.client.force_login(self.user)
        resp = self.client.get(reverse(
            'instructor:class_section_grade',
            kwargs={'record_id': section.id}))

        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('Confirm the roster first.', body)
        self.assertNotIn('Submit Final Grades', body,
                         'grade entry form must not render when gated')
