"""Resolving grading periods for a section, and routing marks to storage.

Storage is routed by finality, and this module is the only place that knows the
rule:

* the **final** period reads and writes `cis.StudentRegistration.grade` -- the
  existing column, which the SIS export treats as the final grade;
* **interim** periods read and write `PeriodGrade` rows.

Keeping the routing here means the entry view, the reminder job and any future
consumer cannot disagree about where a mark belongs. An interim mark reaching
`StudentRegistration.grade` would be exported to the SIS as a final grade.

A term with no grading periods defined behaves exactly as it did before periods
existed: `periods_for_section` returns an empty list and callers fall back to
the single global grade window.
"""
import datetime

from ..models import GradingPeriod, PeriodGrade, SectionPeriodStatus


def periods_for_section(section):
    """Grading periods that apply to a section, in sequence order.

    A section follows its **own** term's periods and never a parent term's --
    that is what lets a short section on a subterm keep a different schedule.
    """
    if section is None or section.term_id is None:
        return []
    return list(GradingPeriod.objects.filter(term_id=section.term_id))


def resolve_period(section, period_id=None):
    """Pick which period the entry page is working on.

    An explicit id wins, but only if it belongs to this section's term --
    otherwise an instructor could grade against another term's period by
    editing the querystring. Falls back to the period whose window is open
    today, then to the first period.
    """
    periods = periods_for_section(section)
    if not periods:
        return None

    if period_id:
        for period in periods:
            if str(period.id) == str(period_id):
                return period
        return None

    today = datetime.date.today()
    for period in periods:
        if period.opens_on <= today <= period.due_on:
            return period

    return periods[0]


def is_period_open(period, on_date=None):
    if period is None:
        return False
    on_date = on_date or datetime.date.today()
    return period.opens_on <= on_date <= period.due_on


def grades_for(section, period, registrations):
    """Map registration id -> existing mark for this period."""
    if period is None or period.is_final:
        return {reg.id: reg.grade for reg in registrations}

    existing = PeriodGrade.objects.filter(
        period=period, registration__in=registrations
    ).values_list('registration_id', 'grade')
    marks = dict(existing)
    return {reg.id: marks.get(reg.id, '') for reg in registrations}


def save_mark(period, registration, grade, user=None):
    """Write one mark to whichever store the period routes to."""
    if period is None or period.is_final:
        # Final grades stay on the registration -- the column the SIS reads.
        registration.grade = grade
        registration.save(update_fields=['grade'])
        return

    PeriodGrade.objects.update_or_create(
        period=period,
        registration=registration,
        defaults={'grade': grade, 'entered_by': user},
    )


def get_status(section, period):
    """Current submission state for a (section, period)."""
    if period is None:
        return section.grade_status or ''
    row = SectionPeriodStatus.objects.filter(
        period=period, class_section=section).first()
    return row.status if row else ''


def set_status(section, period, status):
    """Record submission state, mirroring the final period onto the section.

    `ClassSection.grade_status` is a single column and cannot hold per-period
    state, so per-period state lives in `SectionPeriodStatus`. The final
    period is mirrored back onto the section so everything already reading
    `grade_status` keeps working: the CE sections-list grade stats, the
    grade-submitted instructor email, and `StudentRegistration.submitted_grade`.
    """
    if period is None:
        section.grade_status = status
        section.save()
        return

    row, _ = SectionPeriodStatus.objects.get_or_create(
        period=period, class_section=section)

    if row.status != status:
        history = row.status_changed_on or {}
        history[datetime.datetime.now().strftime('%m/%d/%Y %I:%M:%S %p')] = status
        row.status_changed_on = history

    row.status = status
    row.save()

    if period.is_final:
        section.grade_status = status
        section.save()
