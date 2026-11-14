"""CE Grade Scales pages: list, add/edit, duplicate, delete."""
from django.contrib import messages
from django.db import transaction
from django.db.models import ProtectedError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from cis.menu import draw_menu

from ..forms.grade_scale import GradeScaleEntryFormSet, GradeScaleForm
from ..models import GradeScale, GradeScaleEntry
from ..services import scales


def _menu():
    return draw_menu(None, 'classes', 'grade_scales', 'ce')


def _note(request, text, ok=True):
    messages.add_message(request, messages.SUCCESS if ok else messages.ERROR, text,
                         'list-group-item-success' if ok else 'list-group-item-danger')


def _get_scale(record_id):
    """A scale this campus may see (its own or deployment-wide), else 404."""
    record = scales.scales_for_campus().filter(pk=record_id).first()
    if record is None:
        raise Http404('No such grade scale.')
    return record


def grade_scales(request):
    scales.ensure_default_record()
    rows = []
    for record in scales.scales_for_campus().prefetch_related('entries'):
        entries = list(record.entries.all())
        rows.append({
            'record': record,
            'letters': ', '.join(e.grade for e in entries),
            'last_attendance': ', '.join(e.grade for e in entries if e.asks_last_attendance),
            'periods': scales.periods_using(record).count(),
        })
    return render(request, 'grades/ce/scales/index.html', {
        'menu': _menu(), 'rows': rows, 'heading': 'Grade Scales',
    })


def edit_grade_scale(request, record_id=None):
    record = _get_scale(record_id) if record_id else GradeScale(campus=scales.current_campus())
    in_use = scales.letters_in_use(record) if record.pk else {}

    if request.method == 'POST':
        form = GradeScaleForm(request.POST, instance=record, campus=scales.current_campus())
        formset = GradeScaleEntryFormSet(request.POST, instance=record, in_use=in_use,
                                         prefix='entries')
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                if form.cleaned_data.get('is_default'):
                    others = GradeScale.objects.filter(
                        campus=record.campus, is_default=True)
                    if record.pk:
                        others = others.exclude(pk=record.pk)
                    others.update(is_default=False)
                saved = form.save()
                formset.instance = saved
                formset.save()
            _note(request, f'Saved grade scale "{saved.name}".')
            return redirect('grades_ce:grade_scales')
    else:
        form = GradeScaleForm(instance=record, campus=scales.current_campus())
        formset = GradeScaleEntryFormSet(instance=record, in_use=in_use, prefix='entries',
                                         queryset=GradeScaleEntry.objects.filter(
                                             scale=record).order_by('sequence', 'grade')
                                         if record.pk else GradeScaleEntry.objects.none())

    return render(request, 'grades/ce/scales/edit.html', {
        'menu': _menu(), 'form': form, 'formset': formset, 'record': record,
        'in_use': in_use, 'periods': scales.periods_using(record).count() if record.pk else 0,
        'heading': f'Edit {record.name}' if record.pk else 'Add Grade Scale',
    })


@require_POST
def duplicate_grade_scale(request, record_id):
    source = _get_scale(record_id)
    name, n = f'Copy of {source.name}', 2
    while GradeScale.objects.filter(campus=source.campus, name__iexact=name).exists():
        name, n = f'Copy of {source.name} ({n})', n + 1
    with transaction.atomic():
        copy = GradeScale.objects.create(
            name=name, campus=source.campus, description=source.description,
            is_default=False, is_active=True)
        for entry in source.entries.all():
            GradeScaleEntry.objects.create(
                scale=copy, grade=entry.grade, points=entry.points, sequence=entry.sequence,
                asks_last_attendance=entry.asks_last_attendance)
    _note(request, f'Created "{copy.name}". Rename it and change its grades below.')
    return redirect(reverse('grades_ce:edit_grade_scale', args=[copy.pk]))


@require_POST
def delete_grade_scale(request, record_id):
    record = _get_scale(record_id)
    if record.is_default:
        _note(request, 'The default scale cannot be deleted. Make another scale the '
                       'default first.', ok=False)
        return redirect('grades_ce:grade_scales')
    try:
        record.delete()
    except ProtectedError:
        _note(request, f'"{record.name}" is used by a grading period, so it cannot be '
                       'deleted. Pick another scale on those periods, or mark this one '
                       'inactive.', ok=False)
        return redirect('grades_ce:grade_scales')
    _note(request, f'Deleted grade scale "{record.name}".')
    return redirect('grades_ce:grade_scales')
