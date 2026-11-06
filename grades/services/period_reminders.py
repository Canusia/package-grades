"""Recurring per-period grade reminders.

Grading-period reminders. The old date-list reminder (``services/reminders.py``)
was retired in v1.0.0; this is the only reminder job.

Cadence -- the roster-verification pattern, not the date-list pattern
--------------------------------------------------------------------
Recurrence is *frequency in days plus per-section last-notified tracking*,
exactly as ``ClassSection.needs_roster_verification_reminder``
(``cis/models/section.py``) does it. Concretely, a section is reminded on a
given day when **all** of the following hold:

1. The period has a reminder on: ``reminder_frequency_days > 0`` or
   ``remind_days_before_due > 0``. Both zero disables reminders for the period.
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
4. Either ``reminder_frequency_days`` have elapsed since
   ``SectionPeriodStatus.last_notified_on`` (never notified is always due), or
   today is exactly ``remind_days_before_due`` days before ``due_on``.
5. The section was not already reminded today (``last_notified_on != today``).

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

from django.core.validators import validate_email
from django.template import Context, Template
from django.template.loader import get_template

from .email import send_grades_mail

from ..models import GradingPeriod, SectionPeriodStatus


def periods_due_for_reminder(today=None):
    """Periods open on ``today`` with any reminder turned on."""
    from django.db.models import Q
    today = today or datetime.date.today()
    return GradingPeriod.objects.filter(
        Q(reminder_frequency_days__gt=0) | Q(remind_days_before_due__gt=0),
        opens_on__lte=today, due_on__gte=today,
    ).select_related('term').order_by('term', 'sequence')


def needs_reminder(status_row, period, today=None):
    """Is this (section, period) due a reminder on ``today``?

    Not submitted, not already reminded today, the period open, and either the
    every-N-days cadence has elapsed or today is ``remind_days_before_due``
    days before the due date.
    """
    today = today or datetime.date.today()
    if status_row.status == 'submitted':
        return False
    if status_row.last_notified_on == today:
        return False
    if not (period.opens_on <= today <= period.due_on):
        return False
    before = period.remind_days_before_due
    if before and today == period.due_on - datetime.timedelta(days=before):
        return True
    freq = period.reminder_frequency_days
    if not freq:
        return False
    if status_row.last_notified_on is None:
        return True
    return (today - status_row.last_notified_on).days >= freq


def _hs_admin_lookup(configs):
    """``(highschool_id, campus) -> [users]`` of HS admins who can submit
    grades, or ``None`` when admins are not reminded at all.

    Admins are reminded when HS admin grade entry is Edit and an admin
    subject is configured. Their position at the school must be Active and
    hold Can submit grades for the course's campus (#15). On a cis without
    per-school permissions nothing is looked up.
    """
    from ..settings.class_section_grades import hs_admin_grade_access_value
    if hs_admin_grade_access_value(configs.get('hs_admin_grade_entry')) != 'edit':
        return None
    if not configs.get('hsadmin_grades_due_subject'):
        return None
    try:
        from cis.models.highschool_administrator import (
            HSAdminPerm, HSAdministratorPosition)
    except ImportError:  # cis before per-school HS admin permissions
        return None

    cache = {}

    def lookup(highschool_id, campus):
        key = (highschool_id, getattr(campus, 'pk', campus))
        if key not in cache:
            positions = HSAdministratorPosition.objects.filter(
                highschool_id=highschool_id,
            ).with_perm(HSAdminPerm.SUBMIT_GRADES, campus).select_related(
                'hsadmin__user').distinct()
            users = []
            for position in positions:
                user = position.hsadmin.user
                if _valid_email(user.email) and user not in users:
                    users.append(user)
            cache[key] = users
        return cache[key]
    return lookup


def _valid_email(address):
    try:
        validate_email(address)
    except Exception:
        return False
    return True


def _section_recipients(section, admin_lookup):
    """``[(user, kind)]`` for one section: its teacher ('teacher') when they
    have an email address, then the permitted HS admins ('hsadmin')."""
    recipients = []
    if section.teacher_id and _valid_email(section.teacher.user.email):
        recipients.append((section.teacher.user, 'teacher'))
    if admin_lookup is not None and section.highschool_id:
        campus = getattr(section.course, 'campus', None)
        for user in admin_lookup(section.highschool_id, campus):
            recipients.append((user, 'hsadmin'))
    return recipients


def sections_pending_for_period(period, today=None, admin_lookup=None):
    """``[(section, status_row)]`` for sections that should be reminded now.

    Only active sections (status 'A', as the CE summary counts them) on the
    period's own term, and only those with someone to remind: a teacher with
    an email address, or (with ``admin_lookup``) a permitted HS admin.
    """
    from django.db.models import Q
    from cis.models.section import ClassSection

    today = today or datetime.date.today()

    has_teacher = Q(teacher__isnull=False) & ~Q(teacher__user__email='') & Q(
        teacher__user__email__isnull=False)
    who = has_teacher
    if admin_lookup is not None:
        who = has_teacher | Q(highschool__isnull=False)

    candidates = ClassSection.objects.filter(
        who, term_id=period.term_id, status='A',
    ).select_related('teacher__user', 'course')

    pending = []
    for section in candidates:
        if admin_lookup is not None and not _section_recipients(section, admin_lookup):
            continue
        # A missing row means "never submitted, never notified"; creating it
        # with the model defaults puts it in precisely that state.
        status_row, _ = SectionPeriodStatus.objects.get_or_create(
            period=period, class_section=section)

        if needs_reminder(status_row, period, today):
            pending.append((section, status_row))

    return pending


def _send_period_reminder(period, user, num_sections, configs, today,
                          kind='teacher'):
    """Render and queue one reminder for one period.

    Teachers get ``grades_due_subject`` / ``grades_due_email``; HS admins
    (#15) get ``hsadmin_grades_due_subject`` / ``hsadmin_grades_due_email``.
    """
    prefix = 'hsadmin_' if kind == 'hsadmin' else ''
    email_subject = configs.get(f'{prefix}grades_due_subject')
    email_text = configs.get(f'{prefix}grades_due_email')

    if not _valid_email(user.email):
        return False

    send_to = [user.email]

    message = Template(email_text or '')
    context = Context({
        'teacher_first_name': user.first_name,
        'teacher_last_name': user.last_name,
        'admin_first_name': user.first_name,
        'admin_last_name': user.last_name,
        'number_of_sections_pending_grades': num_sections,
        'term': str(period.term),
        'grading_period': period.name,
        'due_date': period.due_on.strftime('%m/%d/%Y'),
    })

    text_body = message.render(context)

    template = get_template('cis/email.html')
    html_body = template.render({'message': text_body})

    return bool(send_grades_mail(configs, email_subject, text_body, html_body, send_to))


def notify_sections_pending_period_grade(today=None, *args, **kwargs):
    """Send every reminder due today.

    Returns ``(summary, detailed_log)``, or ``None`` when no email subject is
    configured.
    """
    from ..settings.class_section_grades import class_section_grades

    today = today or datetime.date.today()
    configs = class_section_grades.from_db()

    email_subject = configs.get('grades_due_subject')
    if not email_subject:
        return None

    admin_lookup = _hs_admin_lookup(configs)
    periods = list(periods_due_for_reminder(today))

    summary_lines = [
        f'{len(periods)} grading period(s) in reminder window on '
        f'{today.strftime("%m/%d/%Y")}'
    ]
    detailed_log = {'teachers_notified': [], 'hs_admins_notified': [],
                    'periods': []}
    total_teachers = total_admins = 0

    for period in periods:
        pending = sections_pending_for_period(period, today, admin_lookup)

        # One email per (person, period) covering all their sections. A
        # person who teaches any of them gets the teacher email, even when
        # they are also an admin at the school.
        by_user = {}
        for section, status_row in pending:
            for user, kind in _section_recipients(section, admin_lookup):
                entry = by_user.setdefault(user.pk, {'user': user, 'kind': kind, 'rows': []})
                if kind == 'teacher':
                    entry['kind'] = 'teacher'
                if (section, status_row) not in entry['rows']:
                    entry['rows'].append((section, status_row))

        period_log = {
            'period': period.name,
            'term': str(period.term),
            'due_on': period.due_on.strftime('%m/%d/%Y'),
            'sections_pending': len(pending),
            'teachers_notified': 0,
            'hs_admins_notified': 0,
        }

        notified_sections = {}
        for entry in by_user.values():
            user, kind, rows = entry['user'], entry['kind'], entry['rows']
            sent = _send_period_reminder(
                period, user, len(rows), configs, today, kind=kind)
            if not sent:
                continue

            if kind == 'teacher':
                period_log['teachers_notified'] += 1
                total_teachers += 1
                detailed_log['teachers_notified'].append({
                    'teacher__user__first_name': user.first_name,
                    'teacher__user__last_name': user.last_name,
                    'teacher__user__email': user.email,
                    'num_sections': len(rows),
                    'grading_period': period.name,
                })
            else:
                period_log['hs_admins_notified'] += 1
                total_admins += 1
                detailed_log['hs_admins_notified'].append({
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'email': user.email,
                    'num_sections': len(rows),
                    'grading_period': period.name,
                })
            for section, status_row in rows:
                notified_sections[section.pk] = (section, status_row)

        for section, status_row in notified_sections.values():
            status_row.last_notified_on = today
            status_row.save(update_fields=['last_notified_on'])

            section.add_note(
                note=f'Sent grades due reminder email for {period.name}'
            )

        summary_lines.append(
            f'{period.term} - {period.name}: {len(pending)} section(s) '
            f'pending, {period_log["teachers_notified"]} teacher(s), '
            f'{period_log["hs_admins_notified"]} HS admin(s) notified'
        )
        detailed_log['periods'].append(period_log)

    summary_lines.append(
        f'Notified {total_teachers} teacher(s) and {total_admins} HS admin(s) in total')

    return ('\r\n'.join(summary_lines), detailed_log)
