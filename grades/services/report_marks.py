"""Which stored mark a report reads for a grading period."""
from django.db.models import F, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from ..models import PeriodGrade


def period_mark_annotation(period):
    if period is None or period.is_final:
        return F('grade')
    return Coalesce(Subquery(PeriodGrade.objects.filter(
        period=period, registration=OuterRef('pk')).values('grade')[:1]), Value(''))


def selected_period(data):
    """The GradingPeriod chosen in a report's ``grading_period`` field, or None."""
    from ..models import GradingPeriod
    value = data.get('grading_period')
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return GradingPeriod.objects.filter(pk=value).first() if value else None
