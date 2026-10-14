"""Pieces shared by the instructor and HS admin grade entry views.

Both views authorize differently (teacher vs. administered high school) and
then build the same roster formset. What they share after authorization lives
here so the two pages cannot drift.
"""
from django.http import JsonResponse

from ..services.periods import set_status


def roster_row(registration, grade):
    """Formset initial for one registration.

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
        and 'Draft' in request.POST.get('save_grade', '')
    )


def autosave(request, GradeFS, grade_data, class_section, period,
             roster_gate_ok, roster_gate_message, window_open, period_status):
    """Save the roster as a draft and answer with JSON instead of the page.

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
