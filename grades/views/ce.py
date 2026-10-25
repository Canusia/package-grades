"""CE staff views for managing a term's grading periods.

Surfaced as the "Grading Periods" tab on the term detail page (see
``grades/tabs.py``). Access is gated at the URLconf with
``user_passes_test(user_has_cis_role, ...)`` -- the same gate every other
``/ce/`` route uses -- and every view here is additionally scoped to the term
in the URL, so a period is only reachable through its own term.

Imports of other apps (``cis``) are absolute; intra-package imports are
relative, because in editable mode this package is ``grades.grades``.
"""
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from cis.models.term import Term

from ..compat import has_module
from ..forms.grading_period import GradingPeriodForm
from ..models import GradingPeriod


def _get_period(term, record_id):
    """Fetch a period *within this term*, 404 otherwise.

    Filtering on `term` as well as the pk is what stops a period being edited
    or deleted through some other term's page.
    """
    return get_object_or_404(GradingPeriod, pk=record_id, term=term)


def manage_grading_period(request, term_id, record_id=None):
    """Add (no ``record_id``) or edit one grading period on a term.

    GET renders the modal form fragment; POST saves and answers with the
    ``{'status': 'success', 'action': 'reload'}`` envelope the CE modal forms
    use elsewhere.
    """
    term = get_object_or_404(Term, pk=term_id)
    record = _get_period(term, record_id) if record_id else None

    if request.method == 'POST':
        form = GradingPeriodForm(
            term=term, instance=record, data=request.POST)

        if form.is_valid():
            saved = form.save()
            # save() returns None when a database constraint was violated
            # between validation and the write; the errors it recorded are
            # reported below exactly like ordinary validation errors.
            if saved is not None:
                return JsonResponse({
                    'status': 'success',
                    'message': 'Successfully saved grading period.',
                    'new_record_id': str(saved.id),
                    'new_record_name': saved.name,
                    'action': 'reload',
                })

        return JsonResponse({
            'status': 'error',
            'message': 'Please correct the errors and try again',
            'errors': form.errors.get_json_data(),
        })

    form = GradingPeriodForm(term=term, instance=record)

    return render(
        request,
        'grades/ce/manage_grading_period.html', {
            'form': form,
            'record': record,
            'term': term,
        })


def delete_grading_period(request, term_id, record_id):
    term = get_object_or_404(Term, pk=term_id)
    record = _get_period(term, record_id)

    try:
        record.delete()
        data = {
            'status': 'success',
            'message': 'Successfully deleted grading period.',
            'action': 'reload',
        }
    except Exception as e:
        data = {
            'status': 'error',
            'message': 'Unable to complete request. ' + str(e),
        }

    return JsonResponse(data)


def _get_section_or_404(request, record_id):
    """The section, or 404 when the CE user may not process its campus."""
    from cis.models.section import ClassSection
    section = get_object_or_404(ClassSection, pk=record_id)
    if has_module('cis.campus_gate'):
        from cis.utils import can_edit_campus_section
        if not can_edit_campus_section(request.user, section):
            raise Http404('Class section not found.')
    return section


def ce_class_section_grade(request, record_id):
    """CE edits any period of a class on the instructor's behalf (spec 5)."""
    from ..services.grade_grid import build_grid
    from ..services.periods import resolve_period
    from .grade_entry import handle_grade_post
    section = _get_section_or_404(request, record_id)
    if request.method == 'GET' and request.GET.get('action') == 'download_roster_pdf':
        return section.download_roster_pdf()
    period = resolve_period(section, request.GET.get('period') or request.POST.get('period'))
    if period is None:
        raise Http404('Unknown grading period.')
    back = reverse('cis:section', args=[section.id]) + '#grades'
    if request.method == 'POST':
        def log(saved_period, draft):
            verb = f'saved {saved_period.name} grades as draft' if draft else f'submitted {saved_period.name} grades'
            section.add_note(createdby=request.user,
                             note=f"{request.user.email} {verb} on the instructor's behalf")
        return handle_grade_post(request, section, redirect_url=back,
                                 force_period=period, on_saved=log)
    here = reverse('grades_ce:class_section_grade', args=[section.id]) + f'?period={period.id}'
    return render(request, 'grades/ce/class_section_grade.html', {
        'record': section, 'period': period,
        'grid': build_grid(section, post_url=here, next_url=back, force_period=period),
    })


@require_POST
def reopen_period(request, record_id, period_id):
    from ..services.periods import get_status, set_status
    section = _get_section_or_404(request, record_id)
    period = get_object_or_404(GradingPeriod, pk=period_id, term_id=section.term_id)
    back = reverse('cis:section', args=[section.id]) + '#grades'
    if get_status(section, period) != 'submitted':
        messages.add_message(request, messages.WARNING, f'{period.name} is not submitted.',
                             'list-group-item-warning')
        return redirect(back)
    set_status(section, period, 'saved')
    section.add_note(createdby=request.user, note=f'{request.user.email} reopened {period.name} grades')
    messages.add_message(request, messages.SUCCESS, f'{period.name} reopened.', 'list-group-item-success')
    return redirect(back)
