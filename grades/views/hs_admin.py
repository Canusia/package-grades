"""Phase C: period-aware grade entry on the high school admin side.

This mirrors ``grades/views/instructor.py:class_section_grade`` -- same period
selector, same per-period window, same roster gate, same routing through
``services.periods``. The routing rules are *not* duplicated here; every
decision about where a mark lands stays in ``services.periods``.

The one thing that is genuinely different is authorization, and it is the
reason this is a separate view rather than a parameterised one. The instructor
view scopes a section by ``teacher__user=request.user``; a high school admin has
no teacher record and is instead scoped by the high schools they administer.
The check is copied verbatim from
``highschool_admin/highschool_admin/views/classes.py:class_section``::

    highschools = get_user_highschools(request)
    if class_section_info.highschool.id not in highschools.values_list('id', flat=True):
        return HttpResponseNotFound('Class section not found')

It runs before anything else in this view, so it gates the POST exactly as it
gates the render -- a HS admin cannot enter grades for a section at a school
they do not administer.

Ahead of even that, the whole view 404s unless CE has set
``hs_admin_grade_entry`` to view or edit (default none), and a POST 404s
unless it is edit, so the URL is not a way round the setting.
"""
from django.shortcuts import render, get_object_or_404
from django.http import Http404, HttpResponseNotFound
from django.urls import reverse

from cis.menu import draw_menu, HS_ADMIN_MENU
from cis.models.section import ClassSection
from cis.settings.highschool_admin_portal import (
    highschool_admin_portal as portal_lang,
)

from ..services.gating import hs_admin_can_view_grades, hs_admin_grade_entry_enabled
from ..services.grade_grid import build_grid
from .grade_entry import handle_grade_post


def _hs_admin_context(request):
    """(menu, highschools) for the requesting high school admin.

    ``highschool_admin`` ships in either the nested (in-tree submodule) or the
    flat (pip-installed) layout, and grades must not hard-depend on either.
    """
    try:
        from highschool_admin.highschool_admin.views.utils import (
            get_user_highschools, get_hsadmin_menu,
        )
    except ImportError:  # pragma: no cover - flat layout
        from highschool_admin.views.utils import (
            get_user_highschools, get_hsadmin_menu,
        )

    try:
        menu_data = get_hsadmin_menu()
    except Exception:  # pragma: no cover - menu Setting missing
        menu_data = HS_ADMIN_MENU

    return menu_data, get_user_highschools(request)


def class_section_grade(request, record_id):
    # CE's access setting: view lets the admin see the grid (and the roster
    # PDF); only edit lets a POST through.
    if not hs_admin_can_view_grades():
        raise Http404('High school admin grade access is not enabled.')
    can_edit = hs_admin_grade_entry_enabled()

    menu_data, highschools = _hs_admin_context(request)
    menu = draw_menu(menu_data, 'classes', '', 'highschool_admin')

    section = get_object_or_404(ClassSection, pk=record_id)

    # AUTHORIZATION. Copied from highschool_admin/views/classes.py:class_section.
    # Placed above every other branch so it gates the POST as well as the GET.
    if section.highschool is None or (
        section.highschool.id not in highschools.values_list('id', flat=True)
    ):
        return HttpResponseNotFound('Class section not found')

    here = reverse('grades_highschool_admin:class_section_grade', args=[section.id])
    tab = reverse('highschool_admin:class_section', args=[section.id]) + '#grades'
    if request.GET.get('action') == 'download_roster_pdf':
        return section.download_roster_pdf()
    if request.method == 'POST':
        if not can_edit:
            raise Http404('High school admin grade entry is not enabled.')
        return handle_grade_post(request, section, redirect_url=tab)
    return render(request, 'grades/hs_admin/class_section_grade.html', {
        'menu': menu, 'class_section': section,
        'intro': portal_lang(request).from_db().get('class_blurb', ''),
        'grid': build_grid(section, post_url=here, next_url=here, allow_edit=can_edit),
    })
