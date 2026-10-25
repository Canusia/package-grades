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
# The HS admin portal's class-section tabs, nested (editable) or flat layout.
hsadmin_class_section_tabs = (
    registry('highschool_admin.highschool_admin.tabs.registry',
             'hsadmin_class_section_tabs')
    or registry('highschool_admin.tabs.registry', 'hsadmin_class_section_tabs'))


@register(class_section_index_tabs, 'tab', slug='grades', title='Grades',
          order=20, template='grades/partials/_sections_grades_tab.html',
          lazy=False)
def sections_grades_tab(request, record):
    """Grade statistics for the CE class-sections list page.

    `record` is always None — this registry backs a list page, not a detail
    page. The context computed here was previously inlined in
    ``cis.views.section.index()``; it lives with the template now so ``cis``
    no longer needs to know grades exist.
    """
    from django.db.models import Count

    from cis.models.section import ClassSection, StudentRegistration
    from cis.models.term import Term

    from .services.window import grade_terms
    from .settings.class_section_grades import class_section_grades

    grade_settings = class_section_grades.from_db()
    grade_term_ids = grade_terms()

    submitted_count = ClassSection.objects.filter(
        grade_status='submitted',
        term__id__in=grade_term_ids
    ).count()
    saved_count = ClassSection.objects.filter(
        grade_status='saved',
        term__id__in=grade_term_ids
    ).count()
    not_started_count = ClassSection.objects.filter(
        grade_status='',
        term__id__in=grade_term_ids
    ).count()
    total_count = submitted_count + saved_count + not_started_count

    grade_stats = {
        'submitted': submitted_count,
        'saved': saved_count,
        'not_started': not_started_count,
        'total': total_count,
        'completion_pct': round((submitted_count / total_count * 100), 1) if total_count > 0 else 0,
    }

    grade_distribution = StudentRegistration.objects.filter(
        class_section__term__id__in=grade_term_ids,
        class_section__grade_status='submitted'
    ).exclude(grade='-').exclude(grade='').values('grade').annotate(
        count=Count('grade')
    ).order_by('grade')

    grade_total = sum(item['count'] for item in grade_distribution)

    return {
        'grade_stats': grade_stats,
        'grade_distribution': list(grade_distribution),
        'grade_total': grade_total,
        'grade_terms': Term.objects.filter(pk__in=grade_term_ids),
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
    """Entry point to HS admin grade entry: one link per grading period.

    `record` is the ClassSection. A term with no periods gets a single link,
    matching the pre-periods behaviour of the grade-entry page.
    """
    from .services.periods import get_status, periods_for_section

    periods = [
        {'period': period, 'status': get_status(record, period)}
        for period in periods_for_section(record)
    ]
    return {'periods': periods, 'status': ''}
