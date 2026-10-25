from django.shortcuts import render, get_object_or_404
from django.urls import reverse

from cis.menu import draw_menu, INSTRUCTOR_MENU
from cis.models.term import Term
from cis.models.section import ClassSection
from cis.page_messages import get_page_messages
from cis.utils import grades_page_header_for_instructor, is_submit_grades_open
from ..compat import portal_text
from ..services.window import grade_terms as grade_terms_service
from ..services.grade_grid import build_grid
from ..settings.class_section_grades import class_section_grades
from .grade_entry import handle_grade_post


def class_grades(request):
    menu = draw_menu(INSTRUCTOR_MENU, 'grades', '', 'instructor')
    grade_settings = class_section_grades.from_db()

    grade_term_ids = grade_terms_service()
    grade_terms = Term.objects.filter(pk__in=grade_term_ids)

    # Build API URL with all grade-open term IDs
    term_ids_str = ','.join(str(t.id) for t in grade_terms)
    classes_api = f'/instructor/api/v1/class-section/?format=datatables&term={term_ids_str}'

    return render(
        request,
        'grades/instructor/grades.html',
        {
            'menu': menu,
            'intro': portal_text('instructor').get('grades_blurb', 'Change me'),
            'page_header': grades_page_header_for_instructor(),
            'is_open': is_submit_grades_open(),
            'classes_api': classes_api,
            'require_roster_confirmation': grade_settings.get(
                'require_roster_confirmation', False),
            'grades_intro': grade_settings.get('grades_intro', ''),
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
