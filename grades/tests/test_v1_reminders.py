"""v1: reminder cadence (spec §2, Reminders)."""
from datetime import date, timedelta

from mailer.models import Message

from .base import GradesTestCase
from . import factories as f
from ..models import SectionPeriodStatus
from ..services.period_reminders import needs_reminder, notify_sections_pending_period_grade

TODAY = date(2033, 10, 15)


class ReminderV1Tests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        get_user_model().objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        f.grades_setting(is_active='Yes', grades_due_subject='Due',
                         grades_due_email='{{grading_period}} due {{due_date}}')
        cls.term = f.term()
        cls.section = f.section(cls.term, f.teacher())

    def _period(self, freq=0, before=0, opens=-10, due=10):
        return f.period(self.term, f'P{freq}{before}{opens}{due}', TODAY + timedelta(opens),
                        TODAY + timedelta(due), reminder_frequency_days=freq,
                        remind_days_before_due=before)

    def _row(self, period, **kw):
        row, _ = SectionPeriodStatus.objects.get_or_create(period=period, class_section=self.section)
        for k, v in kw.items():
            setattr(row, k, v)
        row.save()
        return row

    def test_days_before_due_fires_once_on_that_day(self):
        p = self._period(before=2, due=2)
        row = self._row(p, last_notified_on=TODAY - timedelta(days=1))
        self.assertTrue(needs_reminder(row, p, TODAY))
        self.assertFalse(needs_reminder(row, p, TODAY + timedelta(days=1)))

    def test_no_double_send_same_day(self):
        p = self._period(freq=1, before=2, due=2)
        row = self._row(p, last_notified_on=TODAY)
        self.assertFalse(needs_reminder(row, p, TODAY))

    def test_before_due_outside_window_never_sends(self):
        # 3-day period, 7 days before due lands before opens_on: never fires.
        p = f.period(self.term, 'Short', TODAY, TODAY + timedelta(days=3),
                     reminder_frequency_days=0, remind_days_before_due=7)
        row = self._row(p)
        day = p.opens_on
        while day <= p.due_on:
            self.assertFalse(needs_reminder(row, p, day), day)
            day += timedelta(days=1)

    def test_submitted_never_reminded(self):
        p = self._period(freq=1, before=2, due=2)
        row = self._row(p, status='submitted')
        self.assertFalse(needs_reminder(row, p, TODAY))

    def test_job_sends_one_email_and_records_today(self):
        p = self._period(before=2, due=2)
        notify_sections_pending_period_grade(today=TODAY)
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(SectionPeriodStatus.objects.get(period=p).last_notified_on, TODAY)
        notify_sections_pending_period_grade(today=TODAY)
        self.assertEqual(Message.objects.count(), 1)

    def test_retired_command_is_a_noop(self):
        from django.core.management import call_command
        call_command('notify_grades_pending', time='2033-10-15 08:00:00')
        self.assertEqual(Message.objects.count(), 0)

    def test_inactive_sections_not_reminded(self):
        p = self._period(before=2, due=2)
        self.section.status = 'C'
        self.section.save()
        notify_sections_pending_period_grade(today=TODAY)
        self.assertEqual(Message.objects.count(), 0)
        self.assertFalse(SectionPeriodStatus.objects.filter(period=p).exists())
