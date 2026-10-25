"""Grades reminder switches. The date-list reminder was retired in v1.0.0;
grading-period reminders live in services/period_reminders.py."""

REMINDERS_OFF = 'Grade reminders are turned off'
RETIRED = ('notify_grades_pending retired in grades v1.0.0 -- '
           'use grading-period reminders (notify_period_grades_pending)')


def reminders_enabled():
    """`send_grade_reminders`; absent means Yes."""
    from ..settings.class_section_grades import class_section_grades
    return class_section_grades.from_db().get('send_grade_reminders', 'Yes') == 'Yes'
