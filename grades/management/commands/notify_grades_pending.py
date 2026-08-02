from django.core.management.base import BaseCommand
import os, csv, logging, json

from django.utils.safestring import mark_safe

from django.core.mail import EmailMultiAlternatives
from django.template import Context, Template
from django.template.loader import get_template
from django.conf import settings

from cis.models.crontab import CronTab
from cis.signals.crontab import cron_task_done, cron_task_started

logger = logging.getLogger(__name__)

from ...services.reminders import (
    needs_reminder,
    notify_sections_pending_grade
)

class Command(BaseCommand):
    '''
    Notify teachers who have sections marked pending verification
    '''
    help = 'Notify teachers who have sections marked pending verification'

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Time of run')

    def handle(self, *args, **kwargs):
        summary = ''
        detailed_log = {
            'import_students': ''
        }
        
        time = kwargs['time']

        cron_task_started.send(
            sender=self.__class__,
            task=self.__class__,
            scheduled_time=time
        )

        if needs_reminder():
            summary, detailed_log = notify_sections_pending_grade(*args, **kwargs)
        else:
            summary = 'Does not need grades reminder'
            detailed_log = {}

        cron_task_done.send(
            sender=self.__class__,
            task=self.__class__,
            scheduled_time=time,
            summary=summary,
            detailed_log=json.dumps(detailed_log)
        )
