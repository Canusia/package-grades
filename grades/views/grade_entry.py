"""The grade POST shared by every grade page (instructor, HS admin, CE).

``roster_row`` and ``autosave`` are the pre-v1 helpers still used by the
instructor and HS admin views; they go when Tasks 9 and 12 move those views
onto ``handle_grade_post``.
"""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from ..services.grade_grid import build_formset
from ..services.periods import (
    get_status, grades_for, is_period_editable, resolve_period, set_status,
)
from ..services.roster import students_for_grades

DRAFT = 'Draft'


def roster_row(registration, grade):
    """Formset initial for one registration. Pre-v1; removed in Tasks 9/12.

    `first_name`, `last_name` and `psid` are not form fields: the form ignores
    unknown initial keys, and the template reads them off ``form.initial`` as
    the roster's sort keys.
    """
    user = registration.student.user
    return {
        'student_id': registration.id,
        'grade': grade,
        'student': user.last_name + ', ' + user.first_name,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'psid': user.psid or '',
    }


def is_autosave(request):
    """An XHR draft save posted by the roster's auto-save, not a form submit."""
    return (
        request.method == 'POST'
        and request.headers.get('x-requested-with') == 'XMLHttpRequest'
        and DRAFT in request.POST.get('save_grade', '')
    )


def autosave(request, GradeFS, grade_data, class_section, period,
             roster_gate_ok, roster_gate_message, window_open, period_status):
    """Save the roster as a draft and answer with JSON instead of the page.

    Pre-v1; superseded by ``handle_grade_post`` and removed in Tasks 9/12.

    Same gates and the same write as "Save Grades as 'Draft'", plus one the
    page only enforces by disabling the selects: nothing is saved once the
    grades are submitted. The caller must already have authorized the section.
    """
    if not roster_gate_ok:
        return JsonResponse(
            {'ok': False, 'error': roster_gate_message}, status=403)
    if not window_open:
        return JsonResponse(
            {'ok': False, 'error': 'Grade submission is currently closed.'},
            status=403)
    if period_status == 'submitted':
        return JsonResponse(
            {'ok': False, 'error': 'These grades have already been submitted.'},
            status=409)

    gradeformset = GradeFS(
        request.POST,
        initial=grade_data,
        class_section=class_section,
        period=period,
        user=request.user
    )
    for form in gradeformset.forms:
        form.fields['grade'].required = False

    if not gradeformset.is_valid():
        return JsonResponse(
            {'ok': False, 'error': 'Some grades could not be saved.',
             'errors': gradeformset.errors}, status=400)

    gradeformset.save()
    set_status(class_section, period, 'saved')
    return JsonResponse({'ok': True, 'status': 'saved'})


def safe_next(request, default):
    """POST/GET ``next`` when it is a same-site path, else ``default``."""
    target = request.POST.get('next') or request.GET.get('next') or ''
    if target and url_has_allowed_host_and_scheme(
            target, allowed_hosts={request.get_host()}, require_https=request.is_secure()) \
            and target.startswith('/') and not target.startswith('//'):
        return target
    return default


def _note(request, text, ok=True):
    messages.add_message(request, messages.SUCCESS, text,
                         'list-group-item-success' if ok else 'list-group-item-danger')


def handle_grade_post(request, section, *, redirect_url, force_period=None, on_date=None):
    """Save (draft/autosave) or submit grades for one period of ``section``.

    The period comes from POST ``period``. Without ``force_period`` (CE) the
    period must be editable on ``on_date`` (today by default): open, not
    submitted, roster gate passing. The caller must already have authorized
    the section.
    """
    back = safe_next(request, redirect_url)
    period = force_period or resolve_period(section, request.POST.get('period'), on_date=on_date)
    draft = DRAFT in request.POST.get('save_grade', '')
    autosave = is_autosave(request)

    if period is None:
        if autosave:
            return JsonResponse({'ok': False, 'error': 'Unknown grading period.'}, status=400)
        _note(request, 'Unknown grading period.', ok=False)
        return redirect(back)

    if force_period is None and not is_period_editable(section, period, on_date):
        reason = ('These grades have already been submitted.'
                  if get_status(section, period) == 'submitted'
                  else f'Grade entry for {period.name} is not open.')
        if autosave:
            return JsonResponse({'ok': False, 'error': reason}, status=403)
        _note(request, reason, ok=False)
        return redirect(back)

    registrations = list(students_for_grades(section))
    formset = build_formset(section, period, registrations,
                            grades_for(section, period, registrations),
                            user=request.user, data=request.POST)
    if draft:
        for form in formset.forms:
            form.fields['grade'].required = False

    if not formset.is_valid():
        if autosave:
            return JsonResponse({'ok': False, 'error': 'Some grades could not be saved.',
                                 'errors': formset.errors}, status=400)
        _note(request, 'Please choose a grade for every student before submitting.', ok=False)
        return redirect(back)

    formset.save()
    set_status(section, period, 'saved' if draft else 'submitted')
    if autosave:
        return JsonResponse({'ok': True, 'status': 'saved'})
    _note(request, 'Your grades have been saved as a draft.' if draft
          else f'Your {period.name} grades have been submitted.')
    return redirect(back)
