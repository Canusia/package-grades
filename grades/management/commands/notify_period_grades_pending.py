"""Recurring grading-period reminders.

Mirrors ``notify_grades_pending`` -- same signal bracketing, same ``-t/--time``
argument, same ``(summary, detailed_log)`` reporting -- but drives the
per-period cadence in ``services/period_reminders.py``. Both commands can run
on the same tenant: this one only ever looks at ``GradingPeriod`` rows, so a
tenant with no periods configured gets nothing from it and keeps being served
by ``notify_grades_pending``.
"""
import json
import logging

from django.core.management.base import BaseCommand

from cis.signals.crontab import cron_task_done, cron_task_started

from ...services.period_reminders import notify_sections_pending_period_grade

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    '''
    Notify teachers who have not submitted grades for an open grading period
    '''
    help = 'Notify teachers who have not submitted grades for a grading period'

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Time of run')

    def handle(self, *args, **kwargs):
        summary = ''
        detailed_log = {}

        time = kwargs['time']

        cron_task_started.send(
            sender=self.__class__,
            task=self.__class__,
            scheduled_time=time
        )

        result = notify_sections_pending_period_grade()

        if result is None:
            # No grades-due subject configured; nothing can be sent.
            summary = 'No grades due email subject configured'
            detailed_log = {}
        else:
            summary, detailed_log = result

        cron_task_done.send(
            sender=self.__class__,
            task=self.__class__,
            scheduled_time=time,
            summary=summary,
            detailed_log=json.dumps(detailed_log)
        )
