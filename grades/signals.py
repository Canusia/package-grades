"""
Grades app signals.

Signal handlers for grade-related events.

``grade_status_submitted`` is the instructor notification email that used to
live in ``cis.signals.sections.grades_submitted``. ``cis`` keeps only the
``grade_status_changed_on`` timestamp bookkeeping on its own field; the email is
owned by this (optional) app, so a tenant without ``grades`` installed simply
never sends it.
"""
from django.conf import settings
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.template import Context, Template
from django.template.loader import get_template

from mailer import send_html_mail

from cis.models.section import ClassSection


@receiver(pre_save, sender=ClassSection)
def grade_status_submitted(sender, instance, **kwargs):
    """Email the instructor when a section's grade status becomes 'submitted'."""
    previous_status = instance.tracker.previous('grade_status')
    status = instance.grade_status

    if previous_status == status:
        return

    from .settings.class_section_grades import class_section_grades
    gr_settings = class_section_grades.from_db()
    subject = gr_settings.get('grades_submitted_email_subject')
    message = gr_settings.get('grades_submitted_email')
    if status == 'submitted':
        message = Template(message)
        context = Context({
            'instructor_first_name': instance.teacher.user.first_name,
            'instructor_last_name': instance.teacher.user.last_name,
            'course': instance.course,
            'class_number': instance.class_number
        })
        to = [instance.teacher.user.email]
        text_body = message.render(context)
        template = get_template('cis/email.html')
        html_body = template.render({'message': text_body})
        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']
        send_html_mail(subject, text_body, html_body, settings.DEFAULT_FROM_EMAIL, to)
