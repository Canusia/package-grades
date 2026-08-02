"""
Grade window / grade-scale services.

Lifted verbatim from ``cis/utils.py`` (the "Start Grades Module" block) as part of
the grades dependency inversion. Behavior is intentionally unchanged, including the
bare ``except``, the ``'11/01/2035'`` fallback and the ``'-'`` returns.

Imports of ``cis`` models are lazy (inside function bodies) to avoid app-loading
order problems, matching the code these functions were lifted from.
"""
import datetime


def is_submit_grades_open():
    """Is the grade submission window currently open?"""
    try:
        from ..settings.class_section_grades import class_section_grades

        now = datetime.datetime.now()
        settings = class_section_grades.from_db()

        start_date = datetime.datetime.strptime(
            settings.get('start_date'),
            '%m/%d/%Y'
        )
        if now < start_date:
            return False

        end_date = datetime.datetime.strptime(
            settings.get('end_date'),
            '%m/%d/%Y'
        )
        if now > end_date:
            return False
        return True
    except:
        return False


def can_view_grades():
    """Is the grade *viewing* window currently open?"""
    from ..settings.class_section_grades import class_section_grades

    now = datetime.datetime.now()
    settings = class_section_grades.from_db()

    start_date = datetime.datetime.strptime(
        settings.get('viewable_from_date'),
        '%m/%d/%Y'
    )
    if now < start_date:
        return False

    end_date = datetime.datetime.strptime(
        settings.get('viewable_end_date'),
        '%m/%d/%Y'
    )
    if now > end_date:
        return False
    return True


def page_header_for_instructor():
    """Header blurb shown on the instructor grades pages.

    Was ``cis.utils.grades_page_header_for_instructor``.
    """
    from ..settings.class_section_grades import class_section_grades

    settings = class_section_grades.from_db()

    header = settings.get('grades_closed')
    if is_submit_grades_open():
        header = settings.get('grades_open')

    return header


def grade_scale():
    """The configured grade scale as a list of grade strings.

    Parses the comma-separated ``grades`` setting the same way
    ``grades/forms/section.py`` does today.
    """
    from ..settings.class_section_grades import class_section_grades

    settings = class_section_grades.from_db()

    return settings.get('grades', '').split(',')


def grade_terms():
    """Term ids currently open for grading (the ``terms`` setting value)."""
    from ..settings.class_section_grades import class_section_grades

    settings = class_section_grades.from_db()

    return settings.get('terms', [])


def submitted_grade(registration):
    """The grade to show a student for ``registration``, or ``'-'``.

    Was the ``StudentRegistration.submitted_grade`` property.
    """
    if not registration.class_section.grade_submitted:
        return '-'

    from ..settings.class_section_grades import class_section_grades
    configs = class_section_grades.from_db()

    # if today is before configs['end_date'] then return '-'
    if datetime.datetime.now() < datetime.datetime.strptime(configs.get('start_date', '11/01/2035'), '%m/%d/%Y'):
        return '-'

    return registration.grade
