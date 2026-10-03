"""
Grades app signals.

Signal handlers for grade-related events.

``grade_status_submitted`` is the instructor notification email that used to
live in ``cis.signals.sections.grades_submitted``. ``cis`` keeps only the
``grade_status_changed_on`` timestamp bookkeeping on its own field; the email is
owned by this (optional) app, so a tenant without ``grades`` installed simply
never sends it.
"""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.template import Context, Template
from django.template.loader import get_template


from cis.models.section import ClassSection, StudentRegistration


@receiver(pre_save, sender=ClassSection)
def grade_status_submitted(sender, instance, **kwargs):
    """Email the instructor when a section's grade status becomes 'submitted'."""
    previous_status = instance.tracker.previous('grade_status')
    status = instance.grade_status

    if previous_status == status:
        return

    if status != 'submitted':
        return

    from .services.email import parse_addresses, send_grades_mail
    from .settings.class_section_grades import class_section_grades
    gr_settings = class_section_grades.from_db()
    subject = gr_settings.get('grades_submitted_email_subject')
    message = gr_settings.get('grades_submitted_email')

    # The instructor copy and the office copy (#2) are switched separately.
    to = []
    if gr_settings.get('notify_instructor_on_submit', 'Yes') == 'Yes':
        to.append(instance.teacher.user.email)
    to += parse_addresses(gr_settings.get('grades_submitted_cc'))
    if not to:
        return

    message = Template(message or '')
    context = Context({
        'instructor_first_name': instance.teacher.user.first_name,
        'instructor_last_name': instance.teacher.user.last_name,
        'course': instance.course,
        'class_number': instance.class_number
    })
    text_body = message.render(context)
    template = get_template('cis/email.html')
    html_body = template.render({'message': text_body})
    send_grades_mail(gr_settings, subject, text_body, html_body, to)


@receiver(post_save, sender=StudentRegistration)
def flag_grade_change(sender, instance, created, update_fields=None, **kwargs):
    """Flag a sent grade that has since changed as needing to be re-sent.

    Compares against the grade the SIS last accepted (`sent_grade`), so no
    FieldTracker on cis is needed. Queued/failed rows are left alone: the next
    send reads the current grade anyway.
    """
    if created:
        return
    if update_fields is not None and 'grade' not in update_fields:
        return

    from django.utils import timezone

    from .models import GradeSISSync
    from .services.sis_push import normalize_grade

    sync = GradeSISSync.objects.filter(
        registration_id=instance.pk,
        status__in=[GradeSISSync.SENT, GradeSISSync.NEEDS_MIRRORING],
    ).first()
    if sync is None:
        return

    changed = normalize_grade(instance.grade) != sync.sent_grade
    if changed and sync.status == GradeSISSync.SENT:
        sync.status = GradeSISSync.NEEDS_MIRRORING
        sync.grade_changed_at = timezone.now()
        sync.save(update_fields=['status', 'grade_changed_at'])
    elif not changed and sync.status == GradeSISSync.NEEDS_MIRRORING:
        sync.status = GradeSISSync.SENT
        sync.grade_changed_at = None
        sync.save(update_fields=['status', 'grade_changed_at'])
