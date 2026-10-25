"""Open grading periods over a set of sections, for page messages and the CE summary."""
import datetime

from ..models import GradingPeriod, SectionPeriodStatus


def open_period_summary(sections, on_date=None):
    """[(period, submitted, total)] for each period open on ``on_date``."""
    on_date = on_date or datetime.date.today()
    by_term = {}
    for section in sections:
        by_term.setdefault(section.term_id, []).append(section)
    out = []
    for period in GradingPeriod.objects.filter(
            term_id__in=by_term, opens_on__lte=on_date, due_on__gte=on_date
    ).order_by('due_on', 'sequence'):
        term_sections = by_term[period.term_id]
        submitted = SectionPeriodStatus.objects.filter(
            period=period, class_section__in=term_sections, status='submitted').count()
        out.append((period, submitted, len(term_sections)))
    return out
