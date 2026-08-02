"""
Grades-due reminder services.

Lifted from ``ClassSection.needs_grades_reminder`` and
``ClassSection.notify_sections_pending_grade`` (``cis/models/section.py``), both of
which were only ever called by the grades ``notify_grades_pending`` management
command. The ``(summary, detailed_log)`` return contract that command depends on
is preserved exactly, including the early ``return None`` when no subject is set.
"""
import datetime

from django.conf import settings
from django.core.validators import validate_email
from django.template import Context, Template
from django.template.loader import get_template

from mailer import send_html_mail


def needs_reminder():
    """Is today one of the configured grades-due reminder dates?"""
    from ..settings.class_section_grades import (
        class_section_grades
    )
    notif_settings = class_section_grades.from_db()

    reminder_dates_str = notif_settings.get('reminder_dates', '')
    if not reminder_dates_str:
        return False

    today = datetime.datetime.now().strftime('%m/%d/%Y')
    reminder_dates = [d.strip() for d in reminder_dates_str.split(',') if d.strip()]

    return today in reminder_dates


def notify_sections_pending_grade(*args, **kwargs):
    """Email teachers with sections still pending grades; note each section.

    Returns ``(summary, detailed_log)``, or ``None`` when no email subject is
    configured.
    """
    from django.db.models import Count

    from cis.models.section import ClassSection
    from cis.models.term import Term
    from ..settings.class_section_grades import class_section_grades

    configs = class_section_grades.from_db()
    term_ids = configs.get('terms', [])

    # Get all pending sections for adding notes later
    all_pending_sections = ClassSection.objects.filter(
        grade_status__in=['', 'saved'],
        term__id__in=term_ids
    )

    pending_grades = all_pending_sections.annotate(
        num_sections=Count('teacher__user__email', distinct=True)
    ).order_by('teacher__user__email').values(
        'teacher__user__first_name',
        'teacher__user__last_name',
        'teacher__user__email',
        'num_sections'
    ).distinct()

    grading_terms = Term.objects.filter(id__in=term_ids)
    term_labels = ', '.join([f"{term.label} {term.year}" for term in grading_terms])

    summary = ''
    detailed_log = {
        'teachers_notified': []
    }

    # create and send email
    email_subject = configs.get('grades_due_subject')
    if not email_subject:
        return None

    summary = "Notifying for " + term_labels + "\r\n"
    summary += 'Found ' + str(pending_grades.count()) + ' teachers'
    for pending_grade in pending_grades:

        detailed_log['teachers_notified'].append(
            pending_grade
        )
        email_text = configs.get('grades_due_email')

        teacher_email = pending_grade['teacher__user__email']
        try:
            validate_email(teacher_email)
            send_to = [teacher_email]
        except:
            continue

        if getattr(settings, 'DEBUG', True):
            send_to = ['kadaji@gmail.com']

        message = Template(email_text)
        context = Context({
            'teacher_first_name': pending_grade['teacher__user__first_name'],
            'teacher_last_name': pending_grade['teacher__user__last_name'],
            'number_of_sections_pending_grades': pending_grade['num_sections'],
            'term': term_labels,
        })

        text_body = message.render(context)

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        send_html_mail(
            email_subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            send_to
        )

        # Add note to each of this teacher's pending sections
        teacher_sections = all_pending_sections.filter(
            teacher__user__email=teacher_email
        )
        for section in teacher_sections:
            section.add_note(
                note='Sent grades due reminder email'
            )

    return (summary, detailed_log)
