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
"""
from django.shortcuts import render, get_object_or_404, redirect
from django.http import Http404, HttpResponseNotFound
from django.contrib import messages
from django.forms.formsets import formset_factory

from cis.menu import draw_menu, HS_ADMIN_MENU
from cis.models.section import ClassSection
from cis.utils import is_submit_grades_open
from cis.settings.highschool_admin_portal import (
    highschool_admin_portal as portal_lang,
)

from ..forms.section import ClassSectionGradeFormSet, ClassSectionGradeForm
from ..services.roster import students_for_grades
from ..services.gating import can_enter_grades
from ..services.periods import (
    periods_for_section,
    resolve_period,
    is_period_open,
    grades_for,
    get_status,
    set_status,
)
from ..settings.class_section_grades import class_section_grades


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
    menu_data, highschools = _hs_admin_context(request)
    menu = draw_menu(menu_data, 'classes', '', 'highschool_admin')

    class_section_info = get_object_or_404(ClassSection, pk=record_id)

    # AUTHORIZATION. Copied from highschool_admin/views/classes.py:class_section.
    # Placed above every other branch so it gates the POST as well as the GET.
    if class_section_info.highschool is None or (
        class_section_info.highschool.id
        not in highschools.values_list('id', flat=True)
    ):
        return HttpResponseNotFound('Class section not found')

    students_in_class = students_for_grades(class_section_info)

    # Roster confirmation gate. Renders read-only while the roster is pending
    # verification; the POST branch below is what actually prevents a write.
    roster_gate_ok, roster_gate_message = can_enter_grades(class_section_info)

    # Grading periods. A term with none configured keeps the old single-window
    # behaviour exactly: period stays None and every downstream call falls back.
    periods = periods_for_section(class_section_info)
    period = resolve_period(class_section_info, request.GET.get('period'))
    if periods and period is None:
        raise Http404('Unknown grading period for this class section.')

    window_open = is_period_open(period) if periods else is_submit_grades_open()
    period_status = get_status(class_section_info, period)

    settings = class_section_grades.from_db()
    existing_marks = grades_for(class_section_info, period, students_in_class)
    grade_data = [
        {
            'student_id': registration.id,
            'grade': existing_marks.get(registration.id, ''),
            'student': registration.student.user.last_name + ', ' + registration.student.user.first_name
        }
        for registration in students_in_class
    ]

    GradeFS = formset_factory(
        ClassSectionGradeForm,
        formset=ClassSectionGradeFormSet,
        extra=0,
        validate_max=False,
        min_num=1,
        max_num=len(grade_data)
    )
    gradeformset = GradeFS(
        initial=grade_data,
        class_section=class_section_info,
        period=period,
        user=request.user
    )

    if request.method == 'POST':
        if not roster_gate_ok:
            messages.add_message(
                request,
                messages.SUCCESS,
                roster_gate_message,
                'list-group-item-danger'
            )
            return redirect(
                'grades_highschool_admin:class_section_grade',
                record_id=class_section_info.id)

        if not window_open:
            messages.add_message(
                request,
                messages.SUCCESS,
                f'Grade submission for {period.name} is currently closed.'
                if period else 'Grade submission is currently closed.',
                'list-group-item-success'
            )
            return redirect(
                'highschool_admin:class_section',
                record_id=class_section_info.id)

        gradeformset = GradeFS(
            request.POST,
            initial=grade_data,
            class_section=class_section_info,
            period=period,
            user=request.user
        )

        if request.GET.get('action') == 'download_roster_pdf':
            return class_section_info.download_roster_pdf()

        if 'Draft' in request.POST.get('save_grade', ''):
            for form in gradeformset.forms:
                form.fields['grade'].required = False

        if gradeformset.is_valid():
            gradeformset.save()

            if 'Draft' in request.POST.get('save_grade', ''):
                set_status(class_section_info, period, 'saved')
                period_status = 'saved'

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Your grades have been successfully saved.',
                    'list-group-item-success')
            else:
                set_status(class_section_info, period, 'submitted')
                period_status = 'submitted'

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Your grades have been successfully submitted.',
                    'list-group-item-success')
        else:
            messages.add_message(
                request,
                messages.SUCCESS,
                'Please fix the errors below and try again.',
                'list-group-item-danger')

    if period_status == 'submitted':
        message = settings.get('grades_submitted_class_section')
    else:
        message = settings.get('grades_open_class_section')

    return render(
        request,
        'grades/hs_admin/class_section_grade.html',
        {
            'menu': menu,
            'class_section': class_section_info,
            'grade_formset': gradeformset,
            'students_in_class': students_in_class,
            'is_open': window_open,
            'roster_gate_ok': roster_gate_ok,
            'roster_gate_message': roster_gate_message,
            'periods': periods,
            'period': period,
            'period_status': period_status,
            'intro': portal_lang(request).from_db().get('class_blurb', 'Change me'),
            'message': message
        })
