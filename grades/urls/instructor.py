"""
Instructor portal grade URLs.

Included in myce/urls.py under /instructor/ path.
"""
from django.urls import path
from django.contrib.auth.decorators import user_passes_test

from cis.utils import user_has_instructor_role
from ..views.instructor import class_grades, class_section_grade


urlpatterns = [
    path(
        'grades/',
        user_passes_test(user_has_instructor_role, login_url='/')(class_grades),
        name='grades'
    ),
    path(
        'grades/class_section/<uuid:record_id>',
        user_passes_test(user_has_instructor_role, login_url='/')(class_section_grade),
        name='class_section_grade'
    ),
]
