"""CE staff views for managing a term's grading periods.

Surfaced as the "Grading Periods" tab on the term detail page (see
``grades/tabs.py``). Access is gated at the URLconf with
``user_passes_test(user_has_cis_role, ...)`` -- the same gate every other
``/ce/`` route uses -- and every view here is additionally scoped to the term
in the URL, so a period is only reachable through its own term.

Imports of other apps (``cis``) are absolute; intra-package imports are
relative, because in editable mode this package is ``grades.grades``.
"""
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from cis.models.term import Term

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
