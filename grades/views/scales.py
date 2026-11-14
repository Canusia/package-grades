"""CE Grade Scales pages: list, add/edit, duplicate, delete."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import ProtectedError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from cis.menu import draw_menu

from ..forms.grade_scale import GradeScaleEntryFormSet, GradeScaleForm
from ..models import GradeScale, GradeScaleEntry
from ..services import scales


def _menu():
    return draw_menu(None, 'classes', 'grade_scales', 'ce')


def _note(request, text, ok=True):
    """`text` must already be safe HTML: cis/messages.html renders |safe, so
    build anything holding a scale name with format_html."""
    messages.add_message(request, messages.SUCCESS if ok else messages.ERROR, text,
                         'list-group-item-success' if ok else 'list-group-item-danger')


def _can_change(request, record):
    """On a multi-campus site the deployment-wide scales serve every campus,
    so only a superuser changes them; campus staff change their own."""
    return (record.campus_id is not None or scales.current_campus() is None
            or request.user.is_superuser)


def _get_scale(record_id, request=None, change=False):
    """A scale this campus may see (its own or deployment-wide), else 404;
    with `change`, one this user may also change, else 403."""
    record = scales.scales_for_campus().filter(pk=record_id).first()
    if record is None:
        raise Http404('No such grade scale.')
    if change and request is not None and not _can_change(request, record):
        raise PermissionDenied('Only a superuser can change a scale shared by every campus.')
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
            'can_change': _can_change(request, record),
        })
    return render(request, 'grades/ce/scales/index.html', {
        'menu': _menu(), 'rows': rows, 'heading': 'Grade Scales',
    })


def edit_grade_scale(request, record_id=None):
    record = (_get_scale(record_id, request, change=request.method == 'POST') if record_id
              else GradeScale(campus=scales.current_campus()))
    is_new = record._state.adding   # UUID pk is set before the first save
    in_use = {} if is_new else scales.letters_in_use(record)

    if request.method == 'POST':
        form = GradeScaleForm(request.POST, instance=record, campus=scales.current_campus())
        formset = GradeScaleEntryFormSet(request.POST, instance=record, in_use=in_use,
                                         prefix='entries')
        if form.is_valid() and formset.is_valid():
            others = GradeScale.objects.none()
            if form.cleaned_data.get('is_default'):
                others = GradeScale.objects.filter(campus=record.campus, is_default=True)
                if not is_new:
                    others = others.exclude(pk=record.pk)
                stranded = {}
                for old in others:
                    stranded.update(scales.stranded_by_default_swap(old, formset.kept_letters()))
                if stranded:
                    listed = ', '.join(f'{g} ({n})' for g, n in sorted(stranded.items()))
                    form.add_error('is_default', (
                        'Grading periods that use the default scale already have grades this '
                        f'scale does not offer: {listed}. Add them to this scale, or give those '
                        'periods a scale of their own first.'))
            if form.is_valid():
                with transaction.atomic():
                    for old in others:     # save(), not update(): keeps the history row
                        old.is_default = False
                        old.save()
                    saved = form.save()
                    formset.instance = saved
                    formset.save()
                _note(request, format_html('Saved grade scale "{}".', saved.name))
                return redirect('grades_ce:grade_scales')
    else:
        form = GradeScaleForm(instance=record, campus=scales.current_campus())
        formset = GradeScaleEntryFormSet(instance=record, in_use=in_use, prefix='entries',
                                         queryset=GradeScaleEntry.objects.filter(
                                             scale=record).order_by('sequence', 'grade')
                                         if not is_new else GradeScaleEntry.objects.none())

    return render(request, 'grades/ce/scales/edit.html', {
        'menu': _menu(), 'form': form, 'formset': formset, 'record': record,
        'in_use': in_use, 'periods': 0 if is_new else scales.periods_using(record).count(),
        'can_change': True if is_new else _can_change(request, record),
        'heading': 'Add Grade Scale' if is_new else f'Edit {record.name}',
    })


@require_POST
def duplicate_grade_scale(request, record_id):
    source = _get_scale(record_id)
    # The copy belongs to the campus making it (deployment-wide on a
    # single-campus site), so campus staff can always edit their copy.
    campus = scales.current_campus() if scales.current_campus() is not None else source.campus
    name, n = f'Copy of {source.name}', 2
    while GradeScale.objects.filter(campus=campus, name__iexact=name).exists():
        name, n = f'Copy of {source.name} ({n})', n + 1
    with transaction.atomic():
        copy = GradeScale.objects.create(
            name=name, campus=campus, description=source.description,
            is_default=False, is_active=True)
        for entry in source.entries.all():
            GradeScaleEntry.objects.create(
                scale=copy, grade=entry.grade, points=entry.points, sequence=entry.sequence,
                asks_last_attendance=entry.asks_last_attendance)
    _note(request, format_html('Created "{}". Rename it and change its grades below.', copy.name))
    return redirect(reverse('grades_ce:edit_grade_scale', args=[copy.pk]))


@require_POST
def delete_grade_scale(request, record_id):
    record = _get_scale(record_id, request, change=True)
    if record.is_default:
        _note(request, 'The default scale cannot be deleted. Make another scale the '
                       'default first.', ok=False)
        return redirect('grades_ce:grade_scales')
    try:
        record.delete()
    except ProtectedError:
        _note(request, format_html(
            '"{}" is used by a grading period, so it cannot be deleted. Pick another scale '
            'on those periods, or mark this one inactive.', record.name), ok=False)
        return redirect('grades_ce:grade_scales')
    _note(request, format_html('Deleted grade scale "{}".', record.name))
    return redirect('grades_ce:grade_scales')
