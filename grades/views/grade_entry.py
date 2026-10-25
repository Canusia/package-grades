"""The grade POST shared by every grade page (instructor, HS admin, CE)."""
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


def is_autosave(request):
    """An XHR draft save posted by the roster's auto-save, not a form submit."""
    return (
        request.method == 'POST'
        and request.headers.get('x-requested-with') == 'XMLHttpRequest'
        and DRAFT in request.POST.get('save_grade', '')
    )


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


def handle_grade_post(request, section, *, redirect_url, force_period=None, on_date=None,
                      on_saved=None):
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

    # CE (force_period) edits a submitted period in place: it stays submitted.
    # Reopening is the separate reopen action.
    keep_submitted = force_period is not None and get_status(section, period) == 'submitted'
    status = 'submitted' if keep_submitted or not draft else 'saved'
    formset.save()
    set_status(section, period, status)
    if on_saved is not None:
        on_saved(period, status == 'saved')
    if autosave:
        return JsonResponse({'ok': True, 'status': status})
    if keep_submitted:
        _note(request, f'{period.name} grades updated; they remain submitted.')
    else:
        _note(request, 'Your grades have been saved as a draft.' if draft
              else f'Your {period.name} grades have been submitted.')
    return redirect(back)
