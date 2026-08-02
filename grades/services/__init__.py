"""
Grade service layer.

Owns the grade logic that used to live in ``cis`` (``cis/utils.py``,
``ClassSection``, ``StudentRegistration`` and ``Student``). ``cis`` reaches
back into these through a single shim module; everything else should import
from here.
"""
from ..services.reminders import (
    needs_reminder,
    notify_sections_pending_grade,
)
from ..services.roster import students_for_grades
from ..services.transcript import render_transcript
from ..services.window import (
    can_view_grades,
    grade_scale,
    grade_terms,
    is_submit_grades_open,
    page_header_for_instructor,
    submitted_grade,
)

__all__ = [
    'can_view_grades',
    'grade_scale',
    'grade_terms',
    'is_submit_grades_open',
    'needs_reminder',
    'notify_sections_pending_grade',
    'page_header_for_instructor',
    'render_transcript',
    'students_for_grades',
    'submitted_grade',
]
