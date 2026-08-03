"""Recurring per-period grade reminders.

This is the grading-period counterpart to ``services/reminders.py``. The old
single-window reminder fires on an explicit list of dates configured on the
``class_section_grades`` setting; it is untouched here and keeps driving the
final-grade flow for tenants that define no grading periods.

Cadence -- the roster-verification pattern, not the date-list pattern
--------------------------------------------------------------------
Recurrence is *frequency in days plus per-section last-notified tracking*,
exactly as ``ClassSection.needs_roster_verification_reminder``
(``cis/models/section.py``) does it. Concretely, a section is reminded on a
given day when **all** of the following hold:

1. ``GradingPeriod.reminder_frequency_days > 0``. Zero disables reminders for
   that period entirely -- it is the off switch, checked before anything else.
2. **The reminder window is open**: ``opens_on <= today <= due_on``, inclusive
   at both ends. This is the explicit rule keyed on the period's due date --
   the last reminder a section can receive is on the due date itself. Nothing
   is sent afterwards, because ``services/periods.is_period_open`` closes entry
   at ``due_on``: a reminder past the due date would ask an instructor to do
   something the application no longer lets them do. Nothing is sent before
   ``opens_on`` either, for the same reason.
3. The section's ``SectionPeriodStatus.status`` is not ``submitted``. This is
   what makes the job self-terminating -- an instructor who has acted stops
   being nagged on the next run, with no separate bookkeeping.
4. ``reminder_frequency_days`` have elapsed since
   ``SectionPeriodStatus.last_notified_on``. A section that has never been
   notified (``last_notified_on`` is ``NULL``) is always due.

A section with no ``SectionPeriodStatus`` row at all has never submitted and
has never been notified, so it must be reminded. Rather than treat a missing
row as a special case at every check, the row is created on demand
(``get_or_create``) with the model defaults -- ``status=''`` and
``last_notified_on=None`` -- which land it in exactly the state rules 3 and 4
already describe.

``today`` is threaded through every function so the cadence can be tested
without waiting real days; it defaults to ``date.today()``.

Sections in scope for a period are those whose ``term`` *is* the period's term,
matching ``services/periods.periods_for_section``: a section never inherits a
parent term's periods, which is what lets a subterm keep its own schedule.

See docs/superpowers/specs/2026-08-02-grades-grading-periods-design.md
"""
import datetime

from django.conf import settings
from django.core.validators import validate_email
from django.template import Context, Template
from django.template.loader import get_template

from mailer import send_html_mail

from ..models import GradingPeriod, SectionPeriodStatus


def periods_due_for_reminder(today=None):
    """Grading periods whose reminder window is open on ``today``.

    Rules 1 and 2 of the module docstring, as a queryset.
    """
    today = today or datetime.date.today()

    return GradingPeriod.objects.filter(
        reminder_frequency_days__gt=0,
        opens_on__lte=today,
        due_on__gte=today,
    ).select_related('term').order_by('term', 'sequence')


def needs_reminder(status_row, frequency_days, today=None):
    """Is this (section, period) due for a reminder on ``today``?

    Rules 3 and 4. ``status_row`` may be freshly created and never notified.
    """
    if frequency_days <= 0:
        return False

    if status_row.status == 'submitted':
        return False

    if status_row.last_notified_on is None:
        return True

    today = today or datetime.date.today()
    return (today - status_row.last_notified_on).days >= frequency_days


def sections_pending_for_period(period, today=None):
    """``[(section, status_row)]`` for sections that should be reminded now.

    Only sections on the period's own term, and only those whose teacher has
    an email address to send to.
    """
    from cis.models.section import ClassSection

    today = today or datetime.date.today()

    candidates = ClassSection.objects.filter(
        term_id=period.term_id,
        teacher__isnull=False,
    ).exclude(
        teacher__user__email=''
    ).exclude(
        teacher__user__email__isnull=True
    ).select_related('teacher__user')

    pending = []
    for section in candidates:
        # A missing row means "never submitted, never notified"; creating it
        # with the model defaults puts it in precisely that state.
        status_row, _ = SectionPeriodStatus.objects.get_or_create(
            period=period, class_section=section)

        if needs_reminder(status_row, period.reminder_frequency_days, today):
            pending.append((section, status_row))

    return pending


def _send_period_reminder(period, teacher_user, num_sections, configs, today):
    """Render and queue one teacher's reminder for one period.

    Uses the existing ``grades_due_subject`` / ``grades_due_email`` templates;
    grading periods add ``{{grading_period}}`` and ``{{due_date}}`` to the
    context rather than introducing a second pair of settings fields.
    """
    email_subject = configs.get('grades_due_subject')
    email_text = configs.get('grades_due_email')

    teacher_email = teacher_user.email
    try:
        validate_email(teacher_email)
    except Exception:
        return False

    send_to = [teacher_email]
    if getattr(settings, 'DEBUG', True):
        send_to = ['kadaji@gmail.com']

    message = Template(email_text or '')
    context = Context({
        'teacher_first_name': teacher_user.first_name,
        'teacher_last_name': teacher_user.last_name,
        'number_of_sections_pending_grades': num_sections,
        'term': str(period.term),
        'grading_period': period.name,
        'due_date': period.due_on.strftime('%m/%d/%Y'),
    })

    text_body = message.render(context)

    template = get_template('cis/email.html')
    html_body = template.render({'message': text_body})

    send_html_mail(
        email_subject,
        text_body,
        html_body,
        settings.DEFAULT_FROM_EMAIL,
        send_to
    )
    return True


def notify_sections_pending_period_grade(today=None, *args, **kwargs):
    """Send every reminder due today.

    Returns ``(summary, detailed_log)``, or ``None`` when no email subject is
    configured -- the same contract as
    ``services.reminders.notify_sections_pending_grade``, so the management
    command reports identically.
    """
    from ..settings.class_section_grades import class_section_grades

    today = today or datetime.date.today()
    configs = class_section_grades.from_db()

    email_subject = configs.get('grades_due_subject')
    if not email_subject:
        return None

    periods = list(periods_due_for_reminder(today))

    summary_lines = [
        f'{len(periods)} grading period(s) in reminder window on '
        f'{today.strftime("%m/%d/%Y")}'
    ]
    detailed_log = {'teachers_notified': [], 'periods': []}
    total_notified = 0

    for period in periods:
        pending = sections_pending_for_period(period, today)

        # Group by teacher: one email per (teacher, period), like the
        # single-window reminder sends one email per teacher.
        by_teacher = {}
        for section, status_row in pending:
            by_teacher.setdefault(section.teacher.user, []).append(
                (section, status_row))

        period_log = {
            'period': period.name,
            'term': str(period.term),
            'due_on': period.due_on.strftime('%m/%d/%Y'),
            'sections_pending': len(pending),
            'teachers_notified': 0,
        }

        for teacher_user, rows in by_teacher.items():
            sent = _send_period_reminder(
                period, teacher_user, len(rows), configs, today)
            if not sent:
                continue

            period_log['teachers_notified'] += 1
            total_notified += 1
            detailed_log['teachers_notified'].append({
                'teacher__user__first_name': teacher_user.first_name,
                'teacher__user__last_name': teacher_user.last_name,
                'teacher__user__email': teacher_user.email,
                'num_sections': len(rows),
                'grading_period': period.name,
            })

            for section, status_row in rows:
                status_row.last_notified_on = today
                status_row.save(update_fields=['last_notified_on'])

                section.add_note(
                    note=f'Sent grades due reminder email for {period.name}'
                )

        summary_lines.append(
            f'{period.term} - {period.name}: {len(pending)} section(s) '
            f'pending, {period_log["teachers_notified"]} teacher(s) notified'
        )
        detailed_log['periods'].append(period_log)

    summary_lines.append(f'Notified {total_notified} teacher(s) in total')

    return ('\r\n'.join(summary_lines), detailed_log)
