"""Rows of the instructor / HS admin Grades class list (spec §3)."""
from .grade_grid import PERIOD_STATUS_LABELS
from .periods import is_period_open, periods_for_section, statuses_for


def class_rows(sections, on_date=None):
    rows = []
    for section in sections:
        periods = periods_for_section(section)
        statuses = statuses_for(section, periods)
        rows.append({
            'section': section,
            'registrations': section.registration_status_distribution(),
            'periods': [{
                'name': p.name, 'is_final': p.is_final,
                'status': statuses[p.id].status if p.id in statuses else '',
                'label': PERIOD_STATUS_LABELS.get(statuses[p.id].status if p.id in statuses else '', ''),
                'is_open': is_period_open(p, on_date),
            } for p in periods],
        })
    return rows
