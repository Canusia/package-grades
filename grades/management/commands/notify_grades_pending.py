import json
import logging

from django.core.management.base import BaseCommand

from cis.signals.crontab import cron_task_done, cron_task_started

from ...services.reminders import RETIRED

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """No-op since v1.0.0; delete the cron entry. Removed in v1.1."""
    help = RETIRED

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Time of run')

    def handle(self, *args, **kwargs):
        time = kwargs['time']

        cron_task_started.send(
            sender=self.__class__,
            task=self.__class__,
            scheduled_time=time
        )

        cron_task_done.send(
            sender=self.__class__,
            task=self.__class__,
            scheduled_time=time,
            summary=RETIRED,
            detailed_log=json.dumps({})
        )
