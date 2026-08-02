"""
Roster service for grade entry.

Lifted from ``ClassSection.get_students_for_grades`` (``cis/models/section.py``).
"""


def students_for_grades(section):
    """Registrations on ``section`` that should appear on the grade-entry roster."""
    from ..settings.class_section_grades import class_section_grades
    settings = class_section_grades.from_db()

    registration_status = settings.get('registration_status')
    students = section.get_students(
        status=registration_status
    )
    return students
