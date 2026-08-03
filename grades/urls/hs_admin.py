"""
High school admin portal grade URLs.

Included in myce/urls.py under the /highschool_admin/ prefix behind a find_spec
guard, so the highschool_admin package's own urls.py needs no change and a
tenant without grades installed is unaffected.

Access control matches the highschool_admin portal's own pages (PT-19): the
role check first, then two-step verification, so an authenticated
highschool_admin who has not completed the second factor is redirected to
two_step:verify rather than reaching the page. The per-section authorization
(which high schools this admin actually administers) lives in the view, because
it depends on the record.
"""
from django.contrib.auth.decorators import user_passes_test
from django.urls import path

from cis.utils import user_has_highschool_admin_role
from two_step.decorators import verification_required

from ..views.hs_admin import class_section_grade


app_name = 'grades_highschool_admin'


def hsadmin_view(view):
    role_gated = user_passes_test(
        user_has_highschool_admin_role, login_url='/'
    )(view)
    return verification_required(role_gated)


urlpatterns = [
    path(
        'class_section/<uuid:record_id>',
        hsadmin_view(class_section_grade),
        name='class_section_grade'
    ),
]
