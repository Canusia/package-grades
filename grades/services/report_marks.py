"""Which stored mark a report reads for a grading period."""
from django.db.models import F, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from ..compat import expand_term_ids
from ..models import PeriodGrade


def period_mark_annotation(period):
    if period is None or period.is_final:
        return F('grade')
    return Coalesce(Subquery(PeriodGrade.objects.filter(
        period=period, registration=OuterRef('pk')).values('grade')[:1]), Value(''))


def periods_outside_terms_error(form, field):
    """Add a ``field`` error to a report form when any chosen grading period
    belongs to a term that is not among the chosen ``term``s or their
    sub-terms. Call from clean()."""
    chosen = form.cleaned_data.get(field)
    terms = form.cleaned_data.get('term')
    if not chosen or not terms:
        return
    periods = list(chosen) if hasattr(chosen, '__iter__') else [chosen]
    term_ids = expand_term_ids(terms if hasattr(terms, '__iter__') else [terms])
    outside = [p for p in periods if p.term_id not in term_ids]
    if outside:
        names = ', '.join(f'{p.name} ({p.term})' for p in outside)
        form.add_error(field, f'Choose grading periods of the selected term(s) only; '
                              f'not in them: {names}.')


def selected_period(data):
    """The GradingPeriod chosen in a report's ``grading_period`` field, or None."""
    from ..models import GradingPeriod
    value = data.get('grading_period')
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return GradingPeriod.objects.filter(pk=value).first() if value else None
