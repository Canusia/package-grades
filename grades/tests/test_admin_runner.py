"""grades#20: run grades commands from the Django admin (django-admin-runner).

django-admin-runner is a dependency, but if it can't be imported the
``register_command`` shim does nothing and every command still runs from
``manage.py``.
"""
import importlib
import sys
from datetime import date, timedelta
from io import StringIO
from unittest import mock

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.management import call_command

from mailer.models import Message

from cis.models.course import Cohort, Course
from cis.models.note import ClassSectionNote
from cis.models.section import ClassSection
from cis.models.settings import Setting
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from .base import GradesTestCase as TestCase
from ..models import GradingPeriod, SectionPeriodStatus
from ..services.period_reminders import notify_sections_pending_period_grade

User = get_user_model()

GRADES_KEY = getattr(django_settings, 'CAMPUS_CODE_PREFIX') + '_class_grades'
TODAY = date(2033, 10, 15)
COMMAND_MODULE = 'notify_period_grades_pending'


def _command_module():
    """The command module, whichever layout (editable or installed) is active."""
    pkg = __name__.rsplit('.tests.', 1)[0]
    return importlib.import_module(f'{pkg}.management.commands.{COMMAND_MODULE}')


class ShimTests(TestCase):
    def test_shim_is_a_no_op_without_the_runner(self):
        pkg = __name__.rsplit('.tests.', 1)[0]
        shim_name = f'{pkg}.admin_runner'
        saved = sys.modules.pop(shim_name, None)
        try:
            with mock.patch.dict(sys.modules, {'django_admin_runner': None}):
                shim = importlib.import_module(shim_name)

                class Dummy:
                    pass

                self.assertIs(shim.register_command(group='grades')(Dummy), Dummy)
        finally:
            sys.modules.pop(shim_name, None)
            if saved is not None:
                sys.modules[shim_name] = saved


class RegistrationTests(TestCase):
    def setUp(self):
        try:
            from django_admin_runner.registry import _registry
        except ImportError:
            self.skipTest('django-admin-runner is not installed')
        _command_module()  # registration happens on import
        self.registry = _registry

    def test_period_reminder_command_is_registered(self):
        entry = self.registry[COMMAND_MODULE]
        self.assertEqual(entry['group'], 'grades')
        self.assertEqual(entry['permission'], 'grades.change_gradingperiod')
        # -t/--time is cron bookkeeping, not something to type in the admin.
        self.assertIn('time', entry['exclude_params'])

    def test_retired_command_is_not_registered(self):
        pkg = __name__.rsplit('.tests.', 1)[0]
        importlib.import_module(f'{pkg}.management.commands.notify_grades_pending')
        self.assertNotIn('notify_grades_pending', self.registry)


class PeriodReminderCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})
        Setting.objects.update_or_create(
            key=GRADES_KEY,
            defaults={'value': {
                'grades': 'A,B,C',
                'registration_status': ['applied'],
                'grades_due_subject': 'Grades are due',
                'grades_due_email': 'Hi {{teacher_first_name}}',
            }},
        )
        user = User.objects.create_user(
            username='ar_inst', email='ar_inst@example.com', password='x',
            first_name='Ada', last_name='Runner')
        teacher = Teacher.objects.create(user=user)
        ay = AcademicYear.objects.create(name='AY admin runner')
        term = Term.objects.create(academic_year=ay, code='FA33', label='Fall 2033')
        cohort = Cohort.objects.create(name='Cohort AR', designator='AR')
        course = Course.objects.create(
            catalog_number='502', title='Runner Course', cohort=cohort,
            credit_hours=3)
        cls.section = ClassSection.objects.create(
            class_number='8101', section_number='01', term=term, course=course,
            teacher=teacher)
        cls.period = GradingPeriod.objects.create(
            term=term, name='Midterm', sequence=1,
            opens_on=TODAY - timedelta(days=10),
            due_on=TODAY + timedelta(days=10),
            reminder_frequency_days=3)

    def test_dry_run_sends_and_saves_nothing(self):
        notes_before = ClassSectionNote.objects.count()

        summary, log = notify_sections_pending_period_grade(
            today=TODAY, dry_run=True)

        self.assertEqual(Message.objects.count(), 0)
        self.assertFalse(SectionPeriodStatus.objects.exists())
        self.assertEqual(ClassSectionNote.objects.count(), notes_before)
        # The preview still reports who would get an email.
        self.assertIn('Dry run', summary)
        self.assertIn('1 teacher(s)', summary)
        self.assertEqual(
            log['teachers_notified'][0]['teacher__user__email'],
            'ar_inst@example.com')

    def test_dry_run_leaves_an_existing_status_row_alone(self):
        old = TODAY - timedelta(days=5)
        row = SectionPeriodStatus.objects.create(
            period=self.period, class_section=self.section,
            last_notified_on=old)
        notes_before = ClassSectionNote.objects.count()

        notify_sections_pending_period_grade(today=TODAY, dry_run=True)

        row.refresh_from_db()
        self.assertEqual(row.last_notified_on, old)
        self.assertEqual(ClassSectionNote.objects.count(), notes_before)
        self.assertEqual(Message.objects.count(), 0)

    def test_dry_run_with_email_switched_off_would_notify_nobody(self):
        setting = Setting.objects.get(key=GRADES_KEY)
        setting.value = {**setting.value, 'is_active': 'No'}
        setting.save()

        summary, log = notify_sections_pending_period_grade(
            today=TODAY, dry_run=True)

        self.assertIn('Would notify 0 teacher(s)', summary)
        self.assertEqual(log['teachers_notified'], [])

    def test_command_dry_run_end_to_end_lists_recipients(self):
        # The command uses the real date, so open the period around it.
        today = date.today()
        GradingPeriod.objects.filter(pk=self.period.pk).update(
            opens_on=today - timedelta(days=10),
            due_on=today + timedelta(days=10))
        out = StringIO()
        call_command(COMMAND_MODULE, '--dry-run', stdout=out)

        self.assertEqual(Message.objects.count(), 0)
        self.assertFalse(SectionPeriodStatus.objects.exists())
        self.assertIn('Dry run', out.getvalue())
        self.assertIn('teacher: Ada Runner <ar_inst@example.com>', out.getvalue())

    def test_real_run_still_sends(self):
        notify_sections_pending_period_grade(today=TODAY)
        self.assertEqual(Message.objects.count(), 1)

    def test_command_without_time_runs_and_prints_the_summary(self):
        # The admin runner calls the command without -t; the cron signals
        # need a time, so they must be skipped rather than crash.
        out = StringIO()
        with mock.patch.object(
                _command_module(), 'notify_sections_pending_period_grade',
                return_value=('2 grading period(s) in reminder window', {})) as run:
            call_command(COMMAND_MODULE, stdout=out)
        run.assert_called_once_with(dry_run=False)
        self.assertIn('2 grading period(s) in reminder window', out.getvalue())

    def test_command_passes_dry_run(self):
        out = StringIO()
        with mock.patch.object(
                _command_module(), 'notify_sections_pending_period_grade',
                return_value=('Dry run: nothing sent', {})) as run:
            call_command(COMMAND_MODULE, '--dry-run', stdout=out)
        run.assert_called_once_with(dry_run=True)
        self.assertIn('Dry run', out.getvalue())

    def test_command_with_time_still_sends_cron_signals(self):
        mod = _command_module()
        with mock.patch.object(mod, 'cron_task_started') as started, \
                mock.patch.object(mod, 'cron_task_done') as done, \
                mock.patch.object(mod, 'notify_sections_pending_period_grade',
                                  return_value=('ok', {})):
            call_command(COMMAND_MODULE, time='2033-10-15 08:00:00',
                         stdout=StringIO())
        started.send.assert_called_once()
        done.send.assert_called_once()
