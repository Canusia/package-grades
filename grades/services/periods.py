"""Resolving grading periods for a section, and routing marks to storage.

Storage is routed by finality, and this module is the only place that knows the
rule:

* the **final** period reads and writes `cis.StudentRegistration.grade` -- the
  existing column, which the SIS export treats as the final grade;
* **interim** periods read and write `PeriodGrade` rows.

Keeping the routing here means the entry view, the reminder job and any future
consumer cannot disagree about where a mark belongs. An interim mark reaching
`StudentRegistration.grade` would be exported to the SIS as a final grade.

A term with no grading periods has nothing to grade: `periods_for_section`
returns `[]` and callers render a 'no grading periods' state.
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


def _require(period):
    if period is None:
        raise ValueError('period is required')


def open_period(section, on_date=None):
    """The section's period open on ``on_date`` (periods never overlap)."""
    for period in periods_for_section(section):
        if is_period_open(period, on_date):
            return period
    return None


def resolve_period(section, period_id=None, on_date=None):
    """The period a grade page works on.

    An explicit id wins only when it belongs to this section's term. Otherwise:
    the open period; else the latest period that has started; else the first.
    ``None`` when the term has no periods.
    """
    periods = periods_for_section(section)
    if not periods:
        return None
    if period_id:
        return next((p for p in periods if str(p.id) == str(period_id)), None)
    today = on_date or datetime.date.today()
    current = open_period(section, today)
    if current is not None:
        return current
    started = [p for p in periods if p.opens_on <= today]
    return started[-1] if started else periods[0]


def is_period_open(period, on_date=None):
    if period is None:
        return False
    on_date = on_date or datetime.date.today()
    return period.opens_on <= on_date <= period.due_on


def grades_for(section, period, registrations):
    """Map registration id -> existing mark for this period."""
    _require(period)
    if period.is_final:
        return {reg.id: reg.grade for reg in registrations}

    existing = PeriodGrade.objects.filter(
        period=period, registration__in=registrations
    ).values_list('registration_id', 'grade')
    marks = dict(existing)
    return {reg.id: marks.get(reg.id, '') for reg in registrations}


def save_mark(period, registration, grade, user=None):
    """Write one mark to whichever store the period routes to.

    An unchanged mark is not written, so re-saving a page adds no history row
    and leaves ``entered_by`` with whoever last changed it. A blank grade for
    a student with no mark yet is unchanged too.
    """
    _require(period)
    grade = grade or ''
    if period.is_final:
        # Final grades stay on the registration -- the column the SIS reads.
        if (registration.grade or '') == grade:
            return
        registration.grade = grade
        registration.save(update_fields=['grade'])
        return

    mark = PeriodGrade.objects.filter(period=period, registration=registration).first()
    if mark is None:
        if grade:
            PeriodGrade.objects.create(
                period=period, registration=registration, grade=grade, entered_by=user)
        return
    if (mark.grade or '') == grade:
        return
    mark.grade = grade
    mark.entered_by = user
    mark.save()


def get_status(section, period):
    """Current submission state for a (section, period)."""
    _require(period)
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
    _require(period)
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


def is_period_editable(section, period, on_date=None):
    """Open, not yet submitted, and the roster gate passes."""
    from .gating import can_enter_grades
    if period is None or not is_period_open(period, on_date):
        return False
    if get_status(section, period) == 'submitted':
        return False
    return can_enter_grades(section)[0]


def statuses_for(section, periods):
    """{period_id: SectionPeriodStatus} for the rows that exist."""
    return {
        row.period_id: row for row in SectionPeriodStatus.objects.filter(
            class_section=section, period__in=periods)
    }


def marks_by_period(section, periods, registrations):
    """{period_id: {registration_id: mark}} for every period."""
    return {p.id: grades_for(section, p, registrations) for p in periods}
