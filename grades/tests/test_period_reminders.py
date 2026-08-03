"""Phase C: recurring per-period grade reminders.

The cadence is frequency-in-days plus per-section last-notified tracking (the
roster-verification pattern), so every test here controls "today" explicitly
rather than waiting real days -- ``notify_sections_pending_period_grade``
takes the date as an argument for exactly that reason.

Assertions are against the database: ``mailer.Message`` rows (``send_html_mail``
queues, it does not use ``django.core.mail.outbox``) and
``SectionPeriodStatus.last_notified_on``.

The load-bearing property is self-termination -- a section whose status is
``submitted`` must never be reminded again, no matter how long ago it was
notified.

See docs/superpowers/specs/2026-08-02-grades-grading-periods-design.md
"""
from datetime import date, timedelta

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from mailer.models import Message

from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection
from cis.models.settings import Setting
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from ..models import GradingPeriod, SectionPeriodStatus
from ..services.period_reminders import (
    needs_reminder,
    notify_sections_pending_period_grade,
    periods_due_for_reminder,
    sections_pending_for_period,
)

User = get_user_model()

GRADES_KEY = getattr(django_settings, 'CAMPUS_CODE_PREFIX') + '_class_grades'

TODAY = date(2033, 10, 15)


class PeriodReminderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})

        Setting.objects.update_or_create(
            key=GRADES_KEY,
            defaults={'value': {
                'grades': 'A,B,C',
                'registration_status': ['applied'],
                'start_date': '01/01/2020',
                'end_date': '01/01/2040',
                'grades_due_subject': 'Grades are due',
                'grades_due_email': (
                    'Hello {{teacher_first_name}} {{teacher_last_name}}, '
                    '{{number_of_sections_pending_grades}} section(s) pending '
                    'for {{grading_period}} ({{term}}), due {{due_date}}.'
                ),
            }},
        )

        user = User.objects.create_user(
            username='rem_inst', email='rem_inst@example.com', password='x',
            first_name='Rem', last_name='Instructor')
        cls.teacher = Teacher.objects.create(user=user)
        cls.teacher_user = user

        ay = AcademicYear.objects.create(name='AY period reminders')
        cls.term = Term.objects.create(
            academic_year=ay, code='FA33', label='Fall 2033')
        cohort = Cohort.objects.create(name='Cohort Rem', designator='CR')
        cls.course = Course.objects.create(
            catalog_number='501', title='Reminder Course', cohort=cohort,
            credit_hours=3)
        cls.highschool = HighSchool.objects.create(name='HS Reminders')

    def setUp(self):
        self.counter = getattr(self.__class__, '_counter', 7000) + 1
        self.__class__._counter = self.counter

    # -- fixtures ---------------------------------------------------------

    _UNSET = object()

    def _section(self, term=None, teacher=_UNSET):
        return ClassSection.objects.create(
            class_number=str(self.counter), section_number='01',
            term=term or self.term, course=self.course,
            teacher=self.teacher if teacher is self._UNSET else teacher)

    def _period(self, name='Midterm', frequency=3, opens_offset=-10,
                due_offset=10, term=None):
        return GradingPeriod.objects.create(
            term=term or self.term, name=name, sequence=1,
            opens_on=TODAY + timedelta(days=opens_offset),
            due_on=TODAY + timedelta(days=due_offset),
            reminder_frequency_days=frequency)

    def _run(self, today=TODAY):
        return notify_sections_pending_period_grade(today=today)

    # -- a section with no status row is reminded -------------------------

    def test_section_with_no_status_row_is_reminded(self):
        section = self._section()
        period = self._period()

        self.assertFalse(SectionPeriodStatus.objects.exists())

        self._run()

        self.assertEqual(Message.objects.count(), 1)

        row = SectionPeriodStatus.objects.get(
            period=period, class_section=section)
        self.assertEqual(row.last_notified_on, TODAY)
        self.assertEqual(row.status, '')

    def test_reminder_email_renders_the_grading_period_variable(self):
        self._section()
        self._period(name='Midterm 1')

        self._run()

        message = Message.objects.first()
        body = message.email.body
        self.assertIn('Midterm 1', body)
        self.assertIn('1 section(s) pending', body)
        self.assertIn(
            (TODAY + timedelta(days=10)).strftime('%m/%d/%Y'), body)

    # -- self-terminating: submitted sections are never reminded ----------

    def test_submitted_section_is_not_reminded(self):
        section = self._section()
        period = self._period()
        SectionPeriodStatus.objects.create(
            period=period, class_section=section, status='submitted')

        self._run()

        self.assertEqual(Message.objects.count(), 0)
        row = SectionPeriodStatus.objects.get(
            period=period, class_section=section)
        self.assertIsNone(row.last_notified_on)

    def test_submitted_section_is_not_reminded_even_long_after_last_notice(self):
        section = self._section()
        period = self._period(frequency=3)
        SectionPeriodStatus.objects.create(
            period=period, class_section=section, status='submitted',
            last_notified_on=TODAY - timedelta(days=90))

        self._run()

        self.assertEqual(Message.objects.count(), 0)

    def test_saved_but_not_submitted_section_is_still_reminded(self):
        section = self._section()
        period = self._period()
        SectionPeriodStatus.objects.create(
            period=period, class_section=section, status='saved')

        self._run()

        self.assertEqual(Message.objects.count(), 1)
        row = SectionPeriodStatus.objects.get(
            period=period, class_section=section)
        self.assertEqual(row.last_notified_on, TODAY)
        self.assertEqual(row.status, 'saved')

    # -- cadence ----------------------------------------------------------

    def test_recently_notified_section_is_not_re_notified(self):
        section = self._section()
        period = self._period(frequency=7)
        last = TODAY - timedelta(days=3)
        SectionPeriodStatus.objects.create(
            period=period, class_section=section, last_notified_on=last)

        self._run()

        self.assertEqual(Message.objects.count(), 0)
        row = SectionPeriodStatus.objects.get(
            period=period, class_section=section)
        self.assertEqual(
            row.last_notified_on, last,
            'last_notified_on must not move when nothing was sent')

    def test_section_notified_longer_ago_is_re_notified_and_stamped(self):
        section = self._section()
        period = self._period(frequency=7)
        SectionPeriodStatus.objects.create(
            period=period, class_section=section,
            last_notified_on=TODAY - timedelta(days=8))

        self._run()

        self.assertEqual(Message.objects.count(), 1)
        row = SectionPeriodStatus.objects.get(
            period=period, class_section=section)
        self.assertEqual(row.last_notified_on, TODAY)

    def test_frequency_boundary_is_inclusive(self):
        section = self._section()
        period = self._period(frequency=7)
        SectionPeriodStatus.objects.create(
            period=period, class_section=section,
            last_notified_on=TODAY - timedelta(days=7))

        self._run()

        self.assertEqual(Message.objects.count(), 1)

    def test_reminder_recurs_across_runs_on_cadence(self):
        section = self._section()
        period = self._period(frequency=5, opens_offset=-10, due_offset=20)

        self._run(TODAY)
        self.assertEqual(Message.objects.count(), 1)

        # Too soon.
        self._run(TODAY + timedelta(days=3))
        self.assertEqual(Message.objects.count(), 1)

        # Cadence elapsed.
        self._run(TODAY + timedelta(days=5))
        self.assertEqual(Message.objects.count(), 2)

        row = SectionPeriodStatus.objects.get(
            period=period, class_section=section)
        self.assertEqual(row.last_notified_on, TODAY + timedelta(days=5))

    # -- frequency 0 disables ---------------------------------------------

    def test_zero_frequency_disables_reminders_entirely(self):
        section = self._section()
        period = self._period(frequency=0)

        self._run()

        self.assertEqual(Message.objects.count(), 0)
        self.assertFalse(
            SectionPeriodStatus.objects.filter(
                period=period, class_section=section,
                last_notified_on__isnull=False).exists())
        self.assertFalse(list(periods_due_for_reminder(TODAY)))

    def test_zero_frequency_is_off_even_with_an_existing_status_row(self):
        section = self._section()
        period = self._period(frequency=0)
        SectionPeriodStatus.objects.create(
            period=period, class_section=section,
            last_notified_on=TODAY - timedelta(days=365))

        self._run()

        self.assertEqual(Message.objects.count(), 0)
        self.assertFalse(
            needs_reminder(
                SectionPeriodStatus.objects.get(
                    period=period, class_section=section),
                period.reminder_frequency_days,
                TODAY))

    # -- window ------------------------------------------------------------

    def test_period_not_yet_open_sends_nothing(self):
        self._section()
        self._period(opens_offset=5, due_offset=25)

        self._run()

        self.assertEqual(Message.objects.count(), 0)

    def test_period_past_due_sends_nothing(self):
        self._section()
        self._period(opens_offset=-30, due_offset=-1)

        self._run()

        self.assertEqual(Message.objects.count(), 0)

    def test_due_date_itself_is_the_last_reminder_day(self):
        self._section()
        self._period(opens_offset=-30, due_offset=0)

        self._run()

        self.assertEqual(Message.objects.count(), 1)

    # -- scope --------------------------------------------------------------

    def test_only_sections_on_the_periods_own_term_are_in_scope(self):
        other_term = Term.objects.create(
            academic_year=self.term.academic_year, code='SP34',
            label='Spring 2034')
        self._section(term=other_term)
        period = self._period()

        self._run()

        self.assertEqual(Message.objects.count(), 0)
        self.assertFalse(
            SectionPeriodStatus.objects.filter(period=period).exists())

    def test_section_without_a_teacher_is_skipped(self):
        self._section(teacher=None)
        period = self._period()

        self.assertEqual(sections_pending_for_period(period, TODAY), [])
        self._run()
        self.assertEqual(Message.objects.count(), 0)

    def test_teacher_without_an_email_is_skipped(self):
        user = User.objects.create_user(
            username='no_email_inst', email='', password='x')
        teacher = Teacher.objects.create(user=user)
        self._section(teacher=teacher)
        period = self._period()

        self.assertEqual(sections_pending_for_period(period, TODAY), [])
        self._run()
        self.assertEqual(Message.objects.count(), 0)

    def test_one_email_per_teacher_per_period_covering_all_their_sections(self):
        first = self._section()
        self.counter += 1
        second = ClassSection.objects.create(
            class_number=str(self.counter), section_number='02',
            term=self.term, course=self.course, teacher=self.teacher)
        period = self._period()

        self._run()

        self.assertEqual(Message.objects.count(), 1)
        self.assertIn('2 section(s) pending', Message.objects.first().email.body)

        for section in (first, second):
            row = SectionPeriodStatus.objects.get(
                period=period, class_section=section)
            self.assertEqual(row.last_notified_on, TODAY)

    def test_no_subject_configured_returns_none_and_sends_nothing(self):
        setting = Setting.objects.get(key=GRADES_KEY)
        value = dict(setting.value)
        value['grades_due_subject'] = ''
        setting.value = value
        setting.save()

        self._section()
        self._period()

        self.assertIsNone(self._run())
        self.assertEqual(Message.objects.count(), 0)
