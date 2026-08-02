"""Grades tabs registered against platform tab registries.

This module is eager-imported from ``GradesConfig.ready()`` so its decorators
run. It must not be imported from ``myce`` — the dependency runs
``grades -> myce`` only, so a tenant without the grades package installed
simply never registers these tabs.

Imports of other apps (``myce``, ``cis``) are absolute; intra-package imports
are relative, because in editable mode this package is ``grades.grades``.
"""
from myce.component_registry.class_section_index import class_section_index_tabs


@class_section_index_tabs.tab(slug='grades', title='Grades', order=20,
                              template='grades/partials/_sections_grades_tab.html',
                              lazy=False, hidden=True)
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

    from .settings.class_section_grades import class_section_grades

    grade_settings = class_section_grades.from_db()
    grade_term_ids = grade_settings.get('terms', [])

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
