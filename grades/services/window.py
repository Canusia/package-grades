"""
Grade-window / grade-scale services, driven by grading periods.

Imports of ``cis`` models are lazy (inside function bodies) to avoid app-loading
order problems.
"""
import contextvars
import datetime
from contextlib import contextmanager

# Per-request memo for submitted_grade() (#12). None outside a request, so
# commands and tasks read the database on every call as before.
_final_status_memo = contextvars.ContextVar('grades_final_status_memo', default=None)


def start_request_memo(**kwargs):
    """request_started: begin an empty memo for this request."""
    _final_status_memo.set({})


def end_request_memo(**kwargs):
    """request_finished: drop the memo."""
    _final_status_memo.set(None)


@contextmanager
def cached_final_status():
    """Memoise submitted_grade()'s lookups inside the block, as a request
    does -- for jobs and tests that show many registrations outside one."""
    if _final_status_memo.get() is not None:  # already memoising: share it
        yield
        return
    token = _final_status_memo.set({})
    try:
        yield
    finally:
        _final_status_memo.reset(token)


def clear_request_memo(**kwargs):
    """A GradingPeriod or SectionPeriodStatus was saved, or a GradingPeriod
    deleted: forget what this request has looked up, so the change shows
    straight away.

    Not seen until the next request: QuerySet.update()/bulk_create() (no
    signals; nothing in grades or cis writes these models that way) and a
    save inside a transaction that is then rolled back."""
    memo = _final_status_memo.get()
    if memo:
        memo.clear()


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


def chosen_term_id(request, available_ids):
    """The one term picked in a term switcher (``?term=<id>``), or ``''`` for
    its default "All current terms" option (no ``term``, or ``term=``), which
    ``selected_term_ids`` serves as the current terms."""
    available = {str(t) for t in available_ids}
    return next((t for t in request.GET.getlist('term') if t in available), '')


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
    section = registration.class_section
    status = _final_period_status(section)
    if status is None:
        status = section.grade_status
    if status != 'submitted':
        return '-'
    return registration.grade


def _final_period_status(section):
    """The section's status for its term's final period, or None when the term
    has no final period or the section has no status row for it.

    Inside a request this costs one query per term and one per final period,
    however many registrations are shown (#12); outside it, up to two per call.
    """
    from ..models import GradingPeriod, SectionPeriodStatus
    memo = _final_status_memo.get()
    if memo is None:
        final = GradingPeriod.objects.filter(term_id=section.term_id, is_final=True).first()
        row = (SectionPeriodStatus.objects.filter(period=final, class_section=section).first()
               if final is not None else None)
        return row.status if row is not None else None

    term_key = ('final', section.term_id)
    if term_key not in memo:
        memo[term_key] = (GradingPeriod.objects.filter(term_id=section.term_id, is_final=True)
                          .values_list('id', flat=True).first())
    final_id = memo[term_key]
    if final_id is None:
        return None

    status_key = ('statuses', final_id)
    if status_key not in memo:
        memo[status_key] = dict(SectionPeriodStatus.objects.filter(period_id=final_id)
                                .values_list('class_section_id', 'status'))
    return memo[status_key].get(section.id)
