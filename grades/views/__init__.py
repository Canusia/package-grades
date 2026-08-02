# Note: To avoid circular imports, imports are done directly from submodules
# Use: from ..views.instructor import class_grades, class_section_grade
# Use: from ..views.student import grades, download_transcript, transcripts

__all__ = [
    'class_grades',
    'class_section_grade',
    'grades',
    'download_transcript',
    'transcripts',
]


def __getattr__(name):
    """Lazy import to avoid circular imports."""
    if name in ('class_grades', 'class_section_grade'):
        from .instructor import class_grades, class_section_grade
        return {'class_grades': class_grades, 'class_section_grade': class_section_grade}[name]
    if name in ('grades', 'download_transcript', 'transcripts'):
        from .student import grades, download_transcript, transcripts
        return {'grades': grades, 'download_transcript': download_transcript, 'transcripts': transcripts}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
