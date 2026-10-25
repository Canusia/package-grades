"""Columns of the student portal grades table (#1).

``COLUMNS`` is the only definition: the template's ``<th>`` row, the DataTables
column config and the ``grades_rows`` feed are all built from it, and CE picks
which ones show with the ``student_grade_columns`` setting. A column that is
off is left out of the feed too, so its value never reaches the browser.
"""
from django.utils.html import conditional_escape, format_html


def _term(registration):
    return registration.class_section.term.label


def _course(registration):
    section = registration.class_section
    return format_html(
        '{} ({} credits)<br><span class="text-muted">{}</span><br>{} - {}<br>{}',
        section.course.name, section.course.credit_hours, section.course.title,
        section.class_number, section.section_number,
        section.highschool_course_name)


def _tuition(registration):
    return f'${float(registration.class_section.tuition or 0):.2f}'


def _status(registration):
    return registration.get_status


def _grade(registration):
    """Visible, submitted interim marks, then the final grade once submitted."""
    from django.utils.html import format_html
    from django.utils.safestring import mark_safe
    from .periods import get_status, periods_for_section
    from .window import submitted_grade
    from ..models import PeriodGrade
    section = registration.class_section
    periods = periods_for_section(section)
    if not periods:
        # A term graded before v1 has no periods: show its submitted final grade.
        return submitted_grade(registration)
    lines = []
    for period in periods:
        if period.is_final:
            grade = submitted_grade(registration)
            if grade not in ('', '-'):
                lines.append((period.name, grade))
        elif period.visible_to_students and get_status(section, period) == 'submitted':
            mark = PeriodGrade.objects.filter(period=period, registration=registration).first()
            if mark and mark.grade:
                lines.append((period.name, mark.grade))
    if not lines:
        return '-'
    return mark_safe('<br>'.join(format_html('{}: {}', name, grade) for name, grade in lines))


# key -> title, cell. Display order is this order.
COLUMNS = {
    'term': ('Term', _term),
    'course': ('Course / Section No.', _course),
    'tuition': ('Tuition', _tuition),
    'status': ('Status', _status),
    'grade': ('Grades', _grade),
}

CHOICES = [(key, title) for key, (title, _) in COLUMNS.items()]
DEFAULT = list(COLUMNS)


def enabled_columns(config=None):
    """[{'key', 'title'}] for the columns CE has switched on, in display order."""
    if config is None:
        from ..settings.class_section_grades import class_section_grades
        config = class_section_grades.from_db()
    chosen = config.get('student_grade_columns') or DEFAULT
    return [{'key': key, 'title': title}
            for key, (title, _) in COLUMNS.items() if key in chosen]


def rows(registrations, columns):
    """One dict per registration; every cell is HTML-escaped (DataTables
    renders cells as HTML)."""
    keys = [column['key'] for column in columns]
    return [{key: str(conditional_escape(COLUMNS[key][1](registration)))
             for key in keys}
            for registration in registrations]
