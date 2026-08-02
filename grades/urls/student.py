"""
Student portal grade URLs.

Included in student/urls.py under /student/ path.
"""
from django.urls import path
from django.contrib.auth.decorators import user_passes_test

from ..views.student import grades, transcripts, download_transcript


def user_has_student_role(user):
    """Check if user has student role."""
    if not user:
        return False
    try:
        roles = user.get_roles()
        return 'student' in roles
    except Exception:
        return False


urlpatterns = [
    path('grades/', grades, name='grades'),
    path(
        'grades/download/',
        user_passes_test(user_has_student_role, login_url='/')(download_transcript),
        name='download_transcript'
    ),
    path('transcripts/', transcripts, name='transcripts'),
]
