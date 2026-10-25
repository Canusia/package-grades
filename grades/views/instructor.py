from django.shortcuts import render, get_object_or_404
from django.urls import reverse

from cis.menu import draw_menu, INSTRUCTOR_MENU
from cis.models.term import Term
from cis.models.section import ClassSection
from cis.page_messages import get_page_messages
from ..compat import portal_text
from ..services.window import grade_terms as grade_terms_service, selected_term_ids
from ..services.class_list import class_rows
from ..services.grade_grid import build_grid
from ..settings.class_section_grades import class_section_grades
from .grade_entry import handle_grade_post


def class_grades(request):
    teacher_sections = ClassSection.objects.filter(
        teacher__user=request.user, status='A', term_id__in=grade_terms_service())
    available = list(teacher_sections.values_list('term_id', flat=True).distinct())
    selected = selected_term_ids(request, available)
    sections = teacher_sections.filter(term_id__in=selected).select_related(
        'term', 'course__cohort', 'highschool').order_by(
        'term__code', 'course__cohort__designator', 'course__catalog_number', 'class_number')
    settings = class_section_grades.from_db()
    return render(request, 'grades/instructor/grades.html', {
        'menu': draw_menu(INSTRUCTOR_MENU, 'grades', '', 'instructor'),
        'intro': portal_text('instructor').get('grades_blurb', ''),
        'grades_intro': settings.get('grades_intro', ''),
        'page_messages': get_page_messages('instructor', 'grades', request),
        'terms': Term.objects.filter(pk__in=available).order_by('-code'),
        'selected_term_ids': selected,
        'require_roster_confirmation': settings.get('require_roster_confirmation', False),
        'rows': class_rows(sections),
    })


def class_section_grade(request, record_id):
    # PT-32: scope to the requesting instructor's own sections (IDOR fix);
    # non-owned sections 404 on GET and POST.
    section = get_object_or_404(ClassSection, pk=record_id, teacher__user=request.user)
    here = reverse('instructor:class_section_grade', args=[section.id])

    if request.GET.get('action') == 'download_roster_pdf':
        return section.download_roster_pdf()
    if request.method == 'POST':
        return handle_grade_post(request, section, redirect_url=here)

    return render(request, 'grades/instructor/class_section_grade.html', {
        'menu': draw_menu(INSTRUCTOR_MENU, 'grades', '', 'instructor'),
        'class_section': section,
        'intro': portal_text('instructor').get('grades_blurb', ''),
        'page_messages': get_page_messages('instructor', 'grades', request),
        'grid': build_grid(section, post_url=here, next_url=here),
    })
