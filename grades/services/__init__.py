"""
Grade service layer.

Owns the grade logic that used to live in ``cis`` (``cis/utils.py``,
``ClassSection``, ``StudentRegistration`` and ``Student``). ``cis`` reaches
back into these through a single shim module; everything else should import
from here.
"""
from ..services.roster import students_for_grades
from ..services.transcript import render_transcript
from ..services.window import (
    cached_final_status,
    can_view_grades,
    current_grade_terms,
    grade_scale,
    grade_terms,
    is_submit_grades_open,
    page_header_for_instructor,
    selected_term_ids,
    submitted_grade,
)

__all__ = [
    'cached_final_status',
    'can_view_grades',
    'current_grade_terms',
    'grade_scale',
    'grade_terms',
    'is_submit_grades_open',
    'page_header_for_instructor',
    'render_transcript',
    'selected_term_ids',
    'students_for_grades',
    'submitted_grade',
]
