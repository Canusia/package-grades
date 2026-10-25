"""CE grade submission summary page (spec §5)."""
import csv
import datetime

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from cis.menu import cis_menu, draw_menu
from cis.models.term import Term

from ..compat import picker_queryset
from ..models import GradingPeriod
from ..services.summary import remind, summarize
from ..services.window import grade_terms, selected_term_ids


def _period(request, term_ids):
    periods = list(GradingPeriod.objects.filter(term_id__in=term_ids).select_related('term')
                   .order_by('term__code', 'sequence'))
    chosen = request.GET.get('period') or request.POST.get('period')
    period = next((p for p in periods if str(p.id) == chosen), None)
    if period is None:
        today = datetime.date.today()
        period = (next((p for p in periods if p.opens_on <= today <= p.due_on), None)
                  or next((p for p in reversed(periods) if p.opens_on <= today), None)
                  or (periods[0] if periods else None))
    return periods, period


def summary(request):
    available = grade_terms()
    selected = selected_term_ids(request, available)
    periods, period = _period(request, selected)
    hs_ids = [h for h in request.GET.getlist('highschool') if h]
    data = summarize(period, highschool_ids=hs_ids) if period else None

    if period and request.GET.get('format') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="grade_summary_{period.name}.csv"'
        w = csv.writer(response)
        w.writerow(['Instructor', 'Email', 'High School(s)', 'Classes', 'Submitted', 'Draft',
                    'Not Started', 'Status', 'Last Reminder'])
        for r in data['rows']:
            u = r['teacher_user']
            w.writerow([f'{u.last_name}, {u.first_name}', u.email, '; '.join(r['highschools']),
                        r['classes'], r['submitted'], r['saved'], r['not_started'], r['status'],
                        r['last_notified_on'].strftime('%m/%d/%Y') if r['last_notified_on'] else ''])
        return response

    return render(request, 'grades/ce/summary.html', {
        'menu': draw_menu(cis_menu, 'classes', 'grades_summary'),
        'terms': Term.objects.filter(pk__in=available).order_by('-code'),
        'selected_term_ids': selected, 'periods': periods, 'period': period,
        'highschools': picker_queryset(), 'selected_highschools': hs_ids, 'data': data,
    })


@require_POST
def summary_remind(request):
    # Campus safety: only periods of the current campus's grade terms.
    period = GradingPeriod.objects.filter(
        pk=request.POST.get('period'), term_id__in=grade_terms()).first()
    if period is None:
        raise Http404('No such grading period.')
    ids = [int(i) for i in request.POST.getlist('teacher') if i.isdigit()]
    if request.POST.get('all') == '1':
        ids = [r['teacher_user'].id for r in summarize(period)['rows'] if r['status'] != 'submitted']
    sent = remind(period, ids)
    messages.add_message(request, messages.SUCCESS, f'Sent {sent} reminder(s).', 'list-group-item-success')
    return redirect(reverse('grades_ce:summary') + f'?period={period.id}&term={period.term_id}')
