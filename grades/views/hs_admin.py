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

cis#154 widens it to a section's secondary high schools: an admin of a
secondary school (and none of the primary) gets in, but the grid, the CSV, the
roster PDF and any POST cover only students of their own schools, and they
cannot submit the class's period. A primary-school admin keeps the whole class.
See ``admin_scope``.

Every HS admin of a school on the section sees its grades. Entering and
submitting them needs a position at one of those schools holding Can submit
grades for the course's campus (#16, ``hs_admin_can_submit_grades``); a POST
from anyone else 404s, so the URL is not a way round the permission. On a cis
that cannot grant the permission nobody enters grades here.
"""
from django.shortcuts import render, get_object_or_404
from django.http import Http404, HttpResponseNotFound
from django.urls import reverse

from cis.menu import draw_menu, HS_ADMIN_MENU
from cis.models.section import ClassSection
from cis.settings.highschool_admin_portal import (
    highschool_admin_portal as portal_lang,
)

from ..services.gating import hs_admin_can_submit_grades
from ..services.grade_csv import grades_csv_response
from ..compat import section_highschool_ids
from ..services.grade_grid import build_grid
from ..services.roster import roster_pdf_response
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


def admin_scope(request, section):
    """``(on_section, highschool_ids)`` for the requesting HS admin.

    ``on_section``: one of their schools is the section's primary or a
    secondary school. ``highschool_ids`` follows highschool_admin's
    ``roster_school_ids``: only when they reach the section as a SECONDARY
    school (and not the primary) are they narrowed -- to their schools that
    are on the section, so a student from an unrelated school CE-enrolled
    into it stays hidden. Otherwise ``None``, the whole class as before
    cis#154: a primary-school admin, or one who sees the class page through
    another highschool_admin rule (e.g. hosted_or_own_students).
    """
    _, highschools = _hs_admin_context(request)
    admin_ids = set(highschools.values_list('id', flat=True))
    on_section = admin_ids.intersection(section_highschool_ids(section))
    if not on_section:
        return False, None
    if section.highschool_id in admin_ids:
        return True, None
    return True, sorted(on_section, key=str)


def acting_schools(section, scope):
    """The schools an admin acts for on ``section``: their own secondary
    schools when ``admin_scope`` narrowed them, else the primary school.
    Can submit grades must be held at one of these (#16)."""
    if scope is not None:
        return list(scope)
    return [section.highschool_id] if section.highschool_id else []


def hs_admin_grades_intro():
    """The HS admin Grades intro; blank uses the instructor one (#17)."""
    from ..settings.class_section_grades import class_section_grades
    values = class_section_grades.from_db()
    return values.get('hsadmin_grades_intro') or values.get('grades_intro') or ''


def class_section_grade(request, record_id):
    menu_data, _highschools = _hs_admin_context(request)
    menu = draw_menu(menu_data, 'classes', '', 'highschool_admin')

    section = get_object_or_404(ClassSection, pk=record_id)

    # AUTHORIZATION. From highschool_admin/views/classes.py:class_section,
    # widened to secondary schools (cis#154) with the roster scoped to the
    # admin's schools. Placed above every other branch so it gates the POST
    # as well as the GET.
    allowed, scope = admin_scope(request, section)
    if not allowed:
        return HttpResponseNotFound('Class section not found')
    # Everyone here sees the grid (and the roster PDF and CSV); only an admin
    # holding Can submit grades may POST (#16).
    can_edit = hs_admin_can_submit_grades(request.user, section, acting_schools(section, scope))

    here = reverse('grades_highschool_admin:class_section_grade', args=[section.id])
    tab = reverse('highschool_admin:class_section', args=[section.id]) + '#grades'
    if request.GET.get('action') == 'download_roster_pdf':
        return roster_pdf_response(section, scope)
    if request.GET.get('action') == 'download_grades':
        return grades_csv_response(section, scope)
    if request.method == 'POST':
        if not can_edit:
            raise Http404('You do not have permission to enter grades for this class.')
        return handle_grade_post(request, section, redirect_url=tab, highschool_ids=scope)
    return render(request, 'grades/hs_admin/class_section_grade.html', {
        'menu': menu, 'class_section': section,
        'intro': portal_lang(request).from_db().get('class_blurb', ''),
        'grades_intro': hs_admin_grades_intro(),
        'grades_download_url': here + '?action=download_grades',
        'grid': build_grid(section, post_url=here, next_url=here, allow_edit=can_edit,
                           highschool_ids=scope),
    })
