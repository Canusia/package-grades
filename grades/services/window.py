"""
Grade-window / grade-scale services, driven by grading periods.

Imports of ``cis`` models are lazy (inside function bodies) to avoid app-loading
order problems.
"""
import datetime


def grade_terms():
    """Ids (str) of every term with at least one grading period."""
    from ..models import GradingPeriod
    return [str(t) for t in GradingPeriod.objects.values_list('term_id', flat=True).distinct()]


def current_grade_terms(on_date=None):
    """Grade terms with a period open or still to come on ``on_date``."""
    from ..models import GradingPeriod
    on_date = on_date or datetime.date.today()
    return [str(t) for t in GradingPeriod.objects.filter(due_on__gte=on_date)
            .values_list('term_id', flat=True).distinct()]


def is_submit_grades_open(on_date=None):
    """Is any grading period open on ``on_date``? (No user: used by cis.)"""
    from ..models import GradingPeriod
    on_date = on_date or datetime.date.today()
    return GradingPeriod.objects.filter(opens_on__lte=on_date, due_on__gte=on_date).exists()


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
    """The final grade a student may see: only once the final period is submitted."""
    from .periods import get_status
    from ..models import GradingPeriod
    final = GradingPeriod.objects.filter(
        term_id=registration.class_section.term_id, is_final=True).first()
    if final is None or get_status(registration.class_section, final) != 'submitted':
        return '-'
    return registration.grade
