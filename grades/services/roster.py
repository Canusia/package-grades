"""
Roster service for grade entry.

Lifted from ``ClassSection.get_students_for_grades`` (``cis/models/section.py``).
"""


def roster_statuses():
    """Registration statuses on the grade-entry roster ([] means every status).

    The ``class_section_grades.registration_status`` setting. Shared by
    ``students_for_grades`` and by queryset-level callers (the CE Grades → SIS
    page) that can't go section by section.
    """
    from ..settings.class_section_grades import class_section_grades
    return class_section_grades.from_db().get('registration_status') or []


def students_for_grades(section):
    """Registrations on ``section`` that should appear on the grade-entry roster."""
    students = section.get_students(
        status=roster_statuses()
    )
    return students
