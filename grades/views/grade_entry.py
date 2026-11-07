"""The grade POST shared by every grade page (instructor, HS admin, CE)."""
import logging

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

logger = logging.getLogger(__name__)


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


def _posted_registration_ids(request):
    """Every ``form-N-student_id`` in the POST, as strings."""
    return {value for key, value in request.POST.items()
            if key.startswith('form-') and key.endswith('-student_id')}


def handle_grade_post(request, section, *, redirect_url, force_period=None, on_date=None,
                      on_saved=None, highschool_ids=None):
    """Save (draft/autosave) or submit grades for one period of ``section``.

    The period comes from POST ``period``. Without ``force_period`` (CE) the
    period must be editable on ``on_date`` (today by default): open, not
    submitted, roster gate passing. The caller must already have authorized
    the section.

    ``highschool_ids`` (cis#154, a secondary-school HS admin): only those
    schools' students may be graded -- a POST naming anyone else is refused
    whole, nothing saved -- and the period is never submitted (it is saved as
    a draft), since submitting covers the whole class.
    """
    back = safe_next(request, redirect_url)
    period = force_period or resolve_period(section, request.POST.get('period'), on_date=on_date)
    draft = DRAFT in request.POST.get('save_grade', '') or highschool_ids is not None
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

    registrations = list(students_for_grades(section, highschool_ids))
    if highschool_ids is not None and not _posted_registration_ids(request) <= {
            str(reg.id) for reg in registrations}:
        reason = 'You can only enter grades for students at your school.'
        if autosave:
            return JsonResponse({'ok': False, 'error': reason}, status=403)
        _note(request, reason, ok=False)
        return redirect(back)
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
    was_submitted = get_status(section, period) == 'submitted'
    keep_submitted = force_period is not None and was_submitted
    status = 'submitted' if keep_submitted or not draft else 'saved'
    formset.save()
    set_status(section, period, status)
    if status == 'submitted' and not was_submitted:
        # Every period's submission is confirmed, naming who submitted (#17).
        # The grades are saved by now: a broken template or mailer must not
        # turn the submit into an error page.
        from ..services.submitted_email import send_grades_submitted
        try:
            send_grades_submitted(section, period, request.user)
        except Exception:
            logger.exception('grades: could not send the submitted confirmation '
                             'for section %s, period %s', section.pk, period.pk)
    if on_saved is not None:
        on_saved(period, status == 'saved')
    if autosave:
        return JsonResponse({'ok': True, 'status': status})
    if keep_submitted:
        _note(request, f'{period.name} grades updated; they remain submitted.')
    elif highschool_ids is not None:
        _note(request, 'Your students\' grades have been saved. The instructor or the '
                       'class\'s primary school submits the class\'s grades.')
    else:
        _note(request, 'Your grades have been saved as a draft.' if draft
              else f'Your {period.name} grades have been submitted.')
    return redirect(back)
