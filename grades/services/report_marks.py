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


def _scales_by_term(registrations, period):
    """{term_id: Scale} for the terms in `registrations`.

    With a period chosen, every mark comes from that period, so its scale
    applies; otherwise each term's final scale does.
    """
    from cis.models.term import Term
    from .scales import final_scale_for_term, scale_for_period
    term_ids = set(registrations.order_by().values_list('class_section__term_id', flat=True))
    if period is not None:
        scale = scale_for_period(period)
        return {tid: scale for tid in term_ids}
    terms = Term.objects.filter(pk__in=term_ids).select_related('academic_year').order_by('code')
    cache = {}
    return {t.pk: final_scale_for_term(t, cache=cache) for t in terms}


def report_letters(registrations, period=None):
    """Grade columns for a report: the letters of every scale in play, in order."""
    from .scales import default_scale
    scales = list(_scales_by_term(registrations, period).values()) or [default_scale()]
    letters = []
    for scale in scales:
        for letter in scale.letters():
            if letter not in letters:
                letters.append(letter)
    return letters


def gpa_by_group(registrations, group_fields, period=None):
    """{tuple of group values: average GPA} over `registrations`' period_mark.

    Each mark is worth the points its own term's scale gives it, so two terms
    with different scales are averaged correctly. Marks with no points (P, W,
    a blank, a letter not on the scale) are left out of the average.
    `registrations` must already carry the `period_mark` annotation.
    """
    from django.db.models import Count
    by_term = _scales_by_term(registrations, period)
    points = {tid: scale.points_map() for tid, scale in by_term.items()}
    totals = {}
    rows = (registrations.order_by()
            .values(*group_fields, 'class_section__term_id', 'period_mark')
            .annotate(n=Count('id')))
    for row in rows:
        value = points.get(row['class_section__term_id'], {}).get(row['period_mark'])
        if value is None:
            continue
        key = tuple(row[f] for f in group_fields)
        total, count = totals.get(key, (0.0, 0))
        totals[key] = (total + value * row['n'], count + row['n'])
    return {key: total / count for key, (total, count) in totals.items() if count}
