"""#17: the grades-submitted confirmation.

Sent each time a class's grades are submitted for any grading period, to
whoever submitted, the primary instructor and the primary school's HS admins
holding Can submit grades. Never to a secondary instructor or a
secondary-school admin (cis#154). The Copy To list always gets one.
"""
import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.urls import reverse

from mailer.models import Message

from cis.models.settings import Setting

from .base import GradesTestCase
from . import factories as f
from ..services.periods import set_status
from ..services.submitted_email import send_grades_submitted, submitted_recipients

User = get_user_model()

SETTINGS = {
    'grades_submitted_email_subject': 'Grades submitted',
    'grades_submitted_email': (
        '{{submitter_first_name}} {{submitter_last_name}} submitted {{grading_period}} '
        'for {{class_number}}; instructor {{instructor_first_name}} {{instructor_last_name}}.'),
}


class SubmittedEmailTests(GradesTestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved = list(user_logged_in.receivers)
        user_logged_in.receivers = []
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        user_logged_in.receivers = cls._saved

    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='instructor')
        Setting.objects.get_or_create(
            key='cis.settings.menu',
            defaults={'value': {'instructor_menu': json.dumps([])}})
        f.grades_setting(**SETTINGS)
        today = date.today()
        cls.term = f.term()
        cls.mid1 = f.period(cls.term, 'Mid 1', today - timedelta(days=3), today + timedelta(days=3))
        cls.primary_hs = f.highschool()
        cls.secondary_hs = f.highschool()
        cls.teacher = f.teacher(first_name='Ina', last_name='Instructor')
        cls.teacher.user.groups.add(Group.objects.get(name='instructor'))
        cls.section = f.section(cls.term, cls.teacher, highschool_obj=cls.primary_hs)
        cls.reg = f.registration(cls.section, highschool_obj=cls.primary_hs)

        def admin(name, *schools, perm=True):
            user = User.objects.create_user(
                username=name, email=f'{name}@example.com', password='x',
                first_name=name.title(), last_name='Admin')
            if perm:
                f.grant_submit_grades(user, *schools)
            return user
        cls.admin_with = admin('withperm', cls.primary_hs)
        cls.admin_secondary = admin('secondaryadmin', cls.secondary_hs)
        if hasattr(cls.section, 'add_secondary_highschool'):
            cls.section.add_secondary_highschool(cls.secondary_hs)
        cls.secondary_teacher = f.teacher()
        if hasattr(cls.section, 'add_secondary_teacher'):
            cls.section.add_secondary_teacher(cls.secondary_teacher)

    def setUp(self):
        Message.objects.all().delete()

    def _to(self):
        return sorted(a for m in Message.objects.all() for a in m.email.to)

    def _submit(self, period, draft=False):
        self.client.force_login(self.teacher.user)
        return self.client.post(
            reverse('instructor:class_section_grade', args=[self.section.id]), {
                'period': str(period.id),
                'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1',
                'form-MIN_NUM_FORMS': '0', 'form-MAX_NUM_FORMS': '1000',
                'form-0-student': 'x', 'form-0-student_id': str(self.reg.id),
                'form-0-grade': 'B',
                'save_grade': "Save Grades as 'Draft'" if draft else 'Submit',
            })

    def test_recipients_are_submitter_instructor_and_permitted_primary_admins(self):
        people = submitted_recipients(self.section, submitter=self.admin_with)
        self.assertEqual([p.email for p in people],
                         ['withperm@example.com', self.teacher.user.email])

    def test_no_secondary_teacher_or_secondary_school_admin(self):
        emails = [p.email for p in submitted_recipients(self.section)]
        self.assertNotIn(self.secondary_teacher.user.email, emails)
        self.assertNotIn('secondaryadmin@example.com', emails)

    def test_interim_period_submission_is_confirmed(self):
        self._submit(self.mid1)
        self.assertEqual(self._to(), sorted([self.teacher.user.email, 'withperm@example.com']))
        body = Message.objects.first().email.body
        self.assertIn('Ina Instructor submitted Mid 1', body)
        self.assertIn(self.section.class_number, body)

    def test_a_draft_sends_nothing(self):
        self._submit(self.mid1, draft=True)
        self.assertEqual(self._to(), [])

    def test_already_submitted_sends_nothing(self):
        set_status(self.section, self.mid1, 'submitted')
        self.assertEqual(self._submit(self.mid1).status_code, 302)
        self.assertEqual(self._to(), [])

    def test_section_without_instructor_does_not_fail(self):
        section = f.section(self.term, None, highschool_obj=self.primary_hs)
        self.assertEqual(send_grades_submitted(section, self.mid1, self.admin_with),
                         ['withperm@example.com'])

    def test_switch_off_leaves_only_copy_to(self):
        f.grades_setting(**SETTINGS, notify_instructor_on_submit='No',
                         grades_submitted_cc='ce@example.com')
        send_grades_submitted(self.section, self.mid1, self.admin_with)
        self.assertEqual(self._to(), ['ce@example.com'])

    def test_saving_grade_status_alone_sends_nothing(self):
        # The old ClassSection signal is gone; only the grade POST confirms.
        self.section.grade_status = 'submitted'
        self.section.save()
        self.assertEqual(self._to(), [])


class SubmittedEmailCEAndDebugTests(SubmittedEmailTests):
    """Review follow-ups: CE edit on behalf, Debug mode, mail failures."""

    def _ce_post(self, draft=False):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        from ..views.grade_entry import handle_grade_post
        request = RequestFactory().post('/', {
            'period': str(self.mid1.id),
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '1',
            'form-MIN_NUM_FORMS': '0', 'form-MAX_NUM_FORMS': '1000',
            'form-0-student': 'x', 'form-0-student_id': str(self.reg.id),
            'form-0-grade': 'A',
            'save_grade': "Save Grades as 'Draft'" if draft else 'Submit'})
        request.user = self.ce_user
        request.session = {}
        request._messages = FallbackStorage(request)
        return handle_grade_post(request, self.section, redirect_url='/', force_period=self.mid1)

    def setUp(self):
        super().setUp()
        self.ce_user = User.objects.create_user(
            username=f'ce{User.objects.count()}', email='ce_staff@example.com', password='x',
            first_name='Cee', last_name='Staff')

    def test_ce_submitting_on_behalf_sends_once_naming_ce(self):
        self._ce_post()
        self.assertEqual(self._to(), sorted(
            ['ce_staff@example.com', self.teacher.user.email, 'withperm@example.com']))
        self.assertIn('Cee Staff submitted Mid 1', Message.objects.first().email.body)

    def test_ce_editing_a_submitted_period_sends_nothing(self):
        set_status(self.section, self.mid1, 'submitted')
        self._ce_post()
        self.assertEqual(self._to(), [])

    def test_debug_mode_goes_to_the_debug_list_only(self):
        f.grades_setting(**SETTINGS, is_active='Debug', debug_email_list='qa@example.com')
        send_grades_submitted(self.section, self.mid1, self.admin_with)
        self.assertEqual(self._to(), ['qa@example.com'])

    def test_a_mail_error_does_not_fail_the_submit(self):
        from unittest import mock
        from ..services import submitted_email
        with mock.patch.object(submitted_email, 'send_grades_mail', side_effect=RuntimeError):
            response = self._submit(self.mid1)
        self.assertEqual(response.status_code, 302)
        from ..services.periods import get_status
        self.assertEqual(get_status(self.section, self.mid1), 'submitted')

    # The parent's tests are not re-run here.
    test_recipients_are_submitter_instructor_and_permitted_primary_admins = None
    test_no_secondary_teacher_or_secondary_school_admin = None
    test_interim_period_submission_is_confirmed = None
    test_a_draft_sends_nothing = None
    test_already_submitted_sends_nothing = None
    test_section_without_instructor_does_not_fail = None
    test_switch_off_leaves_only_copy_to = None
    test_saving_grade_status_alone_sends_nothing = None
