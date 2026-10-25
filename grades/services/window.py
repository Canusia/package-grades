"""
Grade-window / grade-scale services, driven by grading periods.

Imports of ``cis`` models are lazy (inside function bodies) to avoid app-loading
order problems.
"""
import datetime


def _periods():
    """GradingPeriod queryset, scoped to the current campus on multi-campus hosts.

    Single-campus hosts may have AcademicYears with no campus, so they stay
    unscoped.
    """
    from ..compat import has_module
    from ..models import GradingPeriod
    qs = GradingPeriod.objects.all()
    if has_module('cis.campus_context'):
        from cis.campus_context import current_campus_or_none, is_multi_campus
        if is_multi_campus():
            campus = current_campus_or_none()
            if campus is not None:
                qs = qs.filter(term__academic_year__campus=campus)
    return qs


def grade_terms():
    """Ids (str) of every term with at least one grading period."""
    return [str(t) for t in _periods().order_by().values_list('term_id', flat=True).distinct()]


def current_grade_terms(on_date=None):
    """Grade terms with a period open or still to come on ``on_date``."""
    on_date = on_date or datetime.date.today()
    return [str(t) for t in _periods().filter(due_on__gte=on_date)
            .order_by().values_list('term_id', flat=True).distinct()]


def is_submit_grades_open(on_date=None):
    """Is any grading period open on ``on_date``? (No user: used by cis.)"""
    on_date = on_date or datetime.date.today()
    return _periods().filter(opens_on__lte=on_date, due_on__gte=on_date).exists()


def can_view_grades():
    """Kept for cis.integrations.grades; visibility is per period now."""
    return True


def page_header_for_instructor():
    from ..settings.class_section_grades import class_section_grades
    return class_section_grades.from_db().get('grades_intro', '')


def selected_term_ids(request, available_ids, on_date=None):
    """Term ids chosen with ``?term=`` (repeatable), limited to ``available_ids``;
    default: the available terms that are current (open or upcoming), else the
    most recent available term."""
    available = [str(t) for t in available_ids]
    chosen = [t for t in request.GET.getlist('term') if t in available]
    if chosen:
        return chosen
    current = [t for t in current_grade_terms(on_date) if t in available]
    if current:
        return current
    from cis.models.term import Term
    latest = Term.objects.filter(pk__in=available).order_by('-code').first()
    return [str(latest.id)] if latest else []


def grade_scale():
    """The configured grade scale as a list of grade strings.

    Parses the comma-separated ``grades`` setting the same way
    ``grades/forms/section.py`` does today.
    """
    from ..settings.class_section_grades import class_section_grades

    settings = class_section_grades.from_db()

    return settings.get('grades', '').split(',')


def submitted_grade(registration):
    """The final grade a student may see: only once final grades are submitted.

    The final period's ``SectionPeriodStatus`` decides when it exists.
    Without one -- a term with no periods, or a section submitted before v1
    (0.0.x) -- ``ClassSection.grade_status`` decides; ``set_status`` mirrors
    the final period onto that column, so the two never disagree for v1 data.
    """
    from ..models import GradingPeriod, SectionPeriodStatus
    section = registration.class_section
    final = GradingPeriod.objects.filter(term_id=section.term_id, is_final=True).first()
    row = (SectionPeriodStatus.objects.filter(period=final, class_section=section).first()
           if final is not None else None)
    status = row.status if row is not None else section.grade_status
    if status != 'submitted':
        return '-'
    return registration.grade
