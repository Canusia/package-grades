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

from ...admin_runner import register_command
from ...services.reminders import REMINDERS_OFF, reminders_enabled
from ...services.period_reminders import notify_sections_pending_period_grade

logger = logging.getLogger(__name__)


@register_command(
    group='grades',
    # CE staff with this permission may run it; superusers always can.
    permission='grades.change_gradingperiod',
    # -t/--time is cron bookkeeping, not something to type in the admin.
    exclude_params=['time'],
)
class Command(BaseCommand):
    '''
    Notify teachers who have not submitted grades for an open grading period
    '''
    help = ('Email teachers and HS admins whose sections still have grades '
            'pending for an open grading period. Use --dry-run to preview.')

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Time of run')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='List who would be emailed; send and save nothing')

    def handle(self, *args, **kwargs):
        summary = ''
        detailed_log = {}

        time = kwargs.get('time')
        dry_run = kwargs.get('dry_run', False)

        # cis's cron receivers parse the scheduled time and crash on None,
        # so only report to the cron log when cron started the run.
        if time:
            cron_task_started.send(
                sender=self.__class__,
                task=self.__class__,
                scheduled_time=time
            )

        result = (notify_sections_pending_period_grade(dry_run=dry_run)
                  if reminders_enabled() else (REMINDERS_OFF, {}))

        if result is None:
            # No grades-due subject configured; nothing can be sent.
            summary = 'No grades due email subject configured'
            detailed_log = {}
        else:
            summary, detailed_log = result

        self.stdout.write(summary)
        if dry_run:
            for row in detailed_log.get('teachers_notified', []):
                self.stdout.write(
                    f"  teacher: {row['teacher__user__first_name']} "
                    f"{row['teacher__user__last_name']} "
                    f"<{row['teacher__user__email']}> - {row['num_sections']} "
                    f"section(s), {row['grading_period']}")
            for row in detailed_log.get('hs_admins_notified', []):
                self.stdout.write(
                    f"  HS admin: {row['first_name']} {row['last_name']} "
                    f"<{row['email']}> - {row['num_sections']} section(s), "
                    f"{row['grading_period']}")

        if time:
            cron_task_done.send(
                sender=self.__class__,
                task=self.__class__,
                scheduled_time=time,
                summary=summary,
                detailed_log=json.dumps(detailed_log)
            )
