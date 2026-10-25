"""The column-per-period grade grid shared by every grade page (spec §3)."""
import datetime

from django.forms.formsets import formset_factory

from .columns import get_columns
from .gating import can_enter_grades
from .periods import (
    is_period_editable, is_period_open, marks_by_period, periods_for_section,
    statuses_for,
)
from .roster import students_for_grades

PERIOD_STATUS_LABELS = {'submitted': 'Submitted', 'saved': 'Draft', '': 'Not started'}


def _last_change(row):
    history = (row.status_changed_on or {}) if row else {}
    return max(history, default='', key=lambda k: datetime.datetime.strptime(k, '%m/%d/%Y %I:%M:%S %p'))


def _header(period, status, row, today):
    if status == 'submitted':
        when = _last_change(row)
        return f'Submitted {when[:10]}' if when else 'Submitted'
    if is_period_open(period, today):
        return f'Open · due {period.due_on:%m/%d/%Y}'
    if today < period.opens_on:
        return f'Opens {period.opens_on:%m/%d/%Y}'
    return 'Closed · not submitted'


def grade_form_classes():
    from ..forms.section import ClassSectionGradeForm, ClassSectionGradeFormSet
    return ClassSectionGradeForm, ClassSectionGradeFormSet


def roster_initial(registrations, marks):
    return [{
        'student_id': reg.id,
        'student': f'{reg.student.user.last_name}, {reg.student.user.first_name}',
        'grade': marks.get(reg.id, '') if marks.get(reg.id, '') not in ('-',) else '',
    } for reg in registrations]


def build_formset(section, period, registrations, marks, user=None, data=None):
    Form, FormSet = grade_form_classes()
    initial = roster_initial(registrations, marks)
    GradeFS = formset_factory(Form, formset=FormSet, extra=0, validate_max=False,
                              min_num=1, max_num=max(len(initial), 1))
    return GradeFS(data, initial=initial, class_section=section, period=period, user=user)


def build_grid(section, *, post_url, next_url, allow_edit=True, force_period=None,
               on_date=None):
    from ..settings.class_section_grades import class_section_grades
    today = on_date or datetime.date.today()
    periods = periods_for_section(section)
    registrations = list(students_for_grades(section).select_related(
        'student__user', 'student__highschool', 'highschool'))
    columns = get_columns()
    statuses = statuses_for(section, periods)
    marks = marks_by_period(section, periods, registrations)
    gate_ok, gate_message = can_enter_grades(section)

    editable = None
    if force_period is not None:
        editable = force_period
    elif allow_edit:
        editable = next((p for p in periods if is_period_editable(section, p, today)), None)

    period_rows = []
    for p in periods:
        row = statuses.get(p.id)
        status = row.status if row else ''
        period_rows.append({
            'period': p, 'status': status, 'label': PERIOD_STATUS_LABELS.get(status, status),
            'header': _header(p, status, row, today), 'editable': p == editable,
            'last_notified_on': row.last_notified_on if row else None,
        })

    formset = (build_formset(section, editable, registrations, marks[editable.id])
               if editable is not None and registrations else None)
    forms = list(formset.forms) if formset else [None] * len(registrations)

    rows = []
    for reg, form in zip(registrations, forms):
        rows.append({
            'registration': reg,
            'cells': [c.value(reg) for c in columns],
            'sort': {c.key: c.value(reg) for c in columns if c.sortable},
            'marks': [marks[p.id].get(reg.id, '') for p in periods],
            'form': form,
        })

    settings = class_section_grades.from_db()
    current = editable or next((p for p in periods if is_period_open(p, today)), None)
    submitted = current is not None and statuses.get(current.id) and statuses[current.id].status == 'submitted'
    message = settings.get('grades_submitted_class_section' if submitted
                           else 'grades_open_class_section') or ''

    return {
        'section': section, 'columns': columns, 'periods': period_rows,
        'editable_period': editable, 'rows': rows, 'formset': formset,
        'management_form': formset.management_form if formset else None,
        'message': message, 'roster_gate_ok': gate_ok, 'roster_gate_message': gate_message,
        'post_url': post_url, 'next_url': next_url, 'has_periods': bool(periods),
    }
