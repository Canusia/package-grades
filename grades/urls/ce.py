"""
CE portal grading-period URLs.

Included in myce/urls.py under the /ce/ prefix, behind a find_spec guard so a
tenant without the grades package installed is unaffected.

Access control matches every other /ce/ route (see cis/urls.py, e.g.
``path('term/<uuid:record_id>', user_passes_test(user_has_cis_role,
login_url='/')(term), name='term')``).
"""
from django.contrib.auth.decorators import user_passes_test
from django.urls import path

from cis.utils import user_has_cis_role

from ..views.ce import delete_grading_period, manage_grading_period


app_name = 'grades_ce'

ce_only = user_passes_test(user_has_cis_role, login_url='/')


urlpatterns = [
    path(
        'term/<uuid:term_id>/grading_period/add',
        ce_only(manage_grading_period),
        name='add_grading_period'
    ),
    path(
        'term/<uuid:term_id>/grading_period/<uuid:record_id>',
        ce_only(manage_grading_period),
        name='edit_grading_period'
    ),
    path(
        'term/<uuid:term_id>/grading_period/<uuid:record_id>/delete',
        ce_only(delete_grading_period),
        name='delete_grading_period'
    ),
]
