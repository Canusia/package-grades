"""Grades tabs registered against platform tab registries.

This module is eager-imported from ``GradesConfig.ready()`` so its decorators
run. It must not be imported from ``myce`` — the dependency runs
``grades -> myce`` only, so a tenant without the grades package installed
simply never registers these tabs.

Imports of other apps (``myce``, ``cis``) are absolute; intra-package imports
are relative, because in editable mode this package is ``grades.grades``.
"""
from .compat import register, registry

# Each registry is optional: a host whose myce predates one skips that tab.
class_section_index_tabs = registry(
    'myce.component_registry.class_section_index', 'class_section_index_tabs')
registration_tabs = registry(
    'myce.component_registry.registration', 'registration_tabs')
term_tabs = registry('myce.component_registry.term', 'term_tabs')
ce_class_section_tabs = registry('myce.component_registry.class_section', 'class_section_tabs')
# The HS admin portal's class-section tabs, nested (editable) or flat layout.
hsadmin_class_section_tabs = (
    registry('highschool_admin.highschool_admin.tabs.registry',
             'hsadmin_class_section_tabs')
    or registry('highschool_admin.tabs.registry', 'hsadmin_class_section_tabs'))


@register(class_section_index_tabs, 'tab', slug='grades', title='Grades',
          order=20, template='grades/partials/_sections_grades_tab.html',
          lazy=False)
def sections_grades_tab(request, record):
    """Grade statistics for the CE class-sections list: one row per grading
    period of the selected term(s).

    `record` is always None -- this registry backs a list page, not a detail
    page. Only terms from the campus-scoped ``grade_terms()`` are offered, so
    the period query below never leaves the current campus.
    """
    from django.db.models import Count

    from cis.models.section import ClassSection, StudentRegistration
    from cis.models.term import Term

    from .models import GradingPeriod, SectionPeriodStatus
    from .services.window import chosen_term_id, grade_terms, selected_term_ids

    available = grade_terms()
    selected = selected_term_ids(request, available)
    period_stats = []
    for period in (GradingPeriod.objects.filter(term_id__in=selected)
                   .select_related('term').order_by('term__code', 'sequence')):
        total = ClassSection.objects.filter(term=period.term, status='A').count()
        counts = dict(
            SectionPeriodStatus.objects.filter(
                period=period, class_section__status='A')
            .values_list('status').annotate(n=Count('id')))
        submitted, saved = counts.get('submitted', 0), counts.get('saved', 0)
        period_stats.append({
            'period': period, 'submitted': submitted, 'saved': saved,
            'not_started': total - submitted - saved, 'total': total,
            'completion_pct': round(submitted / total * 100, 1) if total else 0,
        })
    grade_distribution = StudentRegistration.objects.filter(
        class_section__term_id__in=selected,
        class_section__grade_status='submitted',
    ).exclude(grade__in=['-', '']).values('grade').annotate(
        count=Count('grade')).order_by('grade')
    return {
        'terms': Term.objects.filter(pk__in=available).order_by('-code'),
        'selected_term_ids': selected,
        'term_choice': chosen_term_id(request, available),
        'period_stats': period_stats,
        'grade_distribution': list(grade_distribution),
        'grade_total': sum(i['count'] for i in grade_distribution),
    }


@register(term_tabs, 'tab', slug='grading_periods', title='Grading Periods',
          order=100, template='grades/ce/_grading_periods_tab.html')
def grading_periods_tab(request, record):
    """CE staff configuration of a term's grade collections.

    `record` is the Term. Periods belong to exactly one term -- a subterm
    carries its own -- so this lists only the term's own periods, never a
    parent's.
    """
    from .models import GradingPeriod

    return {
        'grading_periods': GradingPeriod.objects.filter(
            term=record).order_by('sequence', 'name'),
    }


def _can_see_grade_sis(user, record):
    from .actions import can_push
    return can_push(user)


@register(registration_tabs, 'tab', slug='grade_sis', title='Grade SIS',
          order=65, template='grades/sis/_registration_tab.html',
          permission=_can_see_grade_sis)
def grade_sis_tab(request, record):
    """SIS push history for one registration's final grade.

    `record` is the StudentRegistration. No sync row means the grade has
    never been sent.
    """
    from .models import GradeSISSync

    sync = GradeSISSync.objects.filter(registration=record).first()
    attempts = list(sync.attempts.select_related('attempted_by')) if sync else []
    return {'sync': sync, 'attempts': attempts, 'registration': record}


def _hs_admin_may_enter_grades(user, record):
    # The class-section view has already 404'd a section outside the admin's
    # schools; this only applies CE's on/off switch (#3).
    from .services.gating import hs_admin_grade_entry_enabled
    return hs_admin_grade_entry_enabled()


@register(hsadmin_class_section_tabs, 'tab', slug='grades', title='Grades',
          order=25, template='grades/hs_admin/_class_section_grades_tab.html',
          lazy=False, permission=_hs_admin_may_enter_grades)
def hs_admin_grades_tab(request, record):
    """The shared grade grid, inline. `record` is the ClassSection."""
    from django.urls import reverse
    from .services.grade_grid import build_grid

    return {'grid': build_grid(
        record,
        post_url=reverse('grades_highschool_admin:class_section_grade', args=[record.id]),
        next_url=reverse('highschool_admin:class_section', args=[record.id]) + '#grades')}


@register(ce_class_section_tabs, 'tab', slug='grades', title='Grades', order=35,
          lazy=True, template='grades/ce/_class_section_grades_tab.html')
def ce_class_section_grades_tab(request, record):
    """Read-only grid for CE; ?edit=<period id> switches one period to edit."""
    from django.urls import reverse
    from .services.grade_grid import build_grid
    from .services.periods import resolve_period
    edit_id = request.GET.get('edit')
    force = resolve_period(record, edit_id) if edit_id else None
    post_url = reverse('grades_ce:class_section_grade', args=[record.id])
    next_url = reverse('cis:section', args=[record.id]) + '#grades'
    return {'grid': build_grid(record, post_url=post_url, next_url=next_url,
                               allow_edit=False, force_period=force, autosave=False),
            'grades_download_url': post_url + '?action=download_grades',
            'record': record}
