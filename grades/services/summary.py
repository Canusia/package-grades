"""Grade submission summary for CE staff (spec §5)."""
import datetime
from collections import OrderedDict

from ..models import SectionPeriodStatus


def _rank(statuses):
    if statuses and all(s == 'submitted' for s in statuses):
        return 'submitted'
    if any(s in ('saved', 'submitted') for s in statuses):
        return 'saved'
    return 'not_started'


def summarize(period, highschool_ids=None, campus_ids=None):
    from cis.models.section import ClassSection
    sections = ClassSection.objects.filter(term_id=period.term_id, status='A', teacher__isnull=False)
    if highschool_ids:
        sections = sections.filter(highschool_id__in=highschool_ids)
    if campus_ids:
        sections = sections.filter(course__campus_id__in=campus_ids)
    sections = list(sections.select_related('teacher__user', 'highschool', 'course__cohort'))
    rows_by_status = {r.class_section_id: r for r in SectionPeriodStatus.objects.filter(
        period=period, class_section__in=sections)}

    classes = {'submitted': 0, 'saved': 0, 'not_started': 0, 'total': len(sections)}
    by_teacher = OrderedDict()
    for s in sorted(sections, key=lambda s: (s.teacher.user.last_name, s.teacher.user.first_name)):
        row = rows_by_status.get(s.id)
        status = (row.status if row else '') or 'not_started'
        classes[status] += 1
        t = by_teacher.setdefault(s.teacher.user, {
            'teacher_user': s.teacher.user, 'sections': [], 'statuses': [], 'highschools': set(),
            'last_notified_on': None})
        t['sections'].append(s)
        t['statuses'].append(status)
        if s.highschool_id:
            t['highschools'].add(str(s.highschool))
        if row and row.last_notified_on and (t['last_notified_on'] is None or row.last_notified_on > t['last_notified_on']):
            t['last_notified_on'] = row.last_notified_on

    instructors = {'submitted': 0, 'saved': 0, 'not_started': 0, 'total': len(by_teacher)}
    rows = []
    for t in by_teacher.values():
        status = _rank(t['statuses'])
        instructors[status] += 1
        rows.append({
            'teacher_user': t['teacher_user'], 'sections': t['sections'],
            'highschools': sorted(t['highschools']), 'classes': len(t['sections']),
            'submitted': t['statuses'].count('submitted'), 'saved': t['statuses'].count('saved'),
            'not_started': t['statuses'].count('not_started'), 'status': status,
            'last_notified_on': t['last_notified_on'],
        })
    return {'classes': classes, 'instructors': instructors, 'rows': rows}


def remind(period, teacher_user_ids, today=None):
    """Email each listed instructor with unsubmitted classes in ``period``,
    skipping classes already reminded today. Returns emails sent."""
    from ..settings.class_section_grades import class_section_grades
    from .period_reminders import _send_period_reminder
    today = today or datetime.date.today()
    configs = class_section_grades.from_db()
    wanted = set(teacher_user_ids)
    sent = 0
    for row in summarize(period)['rows']:
        if row['teacher_user'].id not in wanted:
            continue
        pending = []
        for section in row['sections']:
            status_row, _ = SectionPeriodStatus.objects.get_or_create(period=period, class_section=section)
            if status_row.status != 'submitted' and status_row.last_notified_on != today:
                pending.append((section, status_row))
        if not pending:
            continue
        if _send_period_reminder(period, row['teacher_user'], len(pending), configs, today):
            sent += 1
            for section, status_row in pending:
                status_row.last_notified_on = today
                status_row.save(update_fields=['last_notified_on'])
                section.add_note(note=f'Sent grades due reminder email for {period.name} (CE summary)')
    return sent
