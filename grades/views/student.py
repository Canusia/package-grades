"""
Student grade views.

Displays grades and transcripts for authenticated students.
"""
from django.shortcuts import render
from django.template import Context, Template
from django.http import HttpResponse

from cis.menu import draw_menu, STUDENT_MENU
from cis.settings.student_portal import student_portal as portal_lang

from student.views.decorators import verify_account_complete
from student.views.utils import get_current_student


def grades(request):
    """
    View student grades page.

    Displays grades for the authenticated student across all terms.
    """
    student = get_current_student(request)

    template = Template(portal_lang(request).from_db().get('grades_blurb', 'Change me'))
    context = Context({
        'request': request,
        'show_message': True if request.GET.get('show_message', None) else False
    })
    intro = template.render(context)

    return render(
        request,
        'grades/student/grades.html',
        {
            'intro': intro,
            'student': student,
            'request': request,
            'menu': draw_menu(STUDENT_MENU, 'grades', '', 'student')
        })


def transcripts(request):
    """Placeholder view for transcripts functionality."""
    ...


@verify_account_complete
def download_transcript(request):
    """
    Download unofficial transcript as PDF.

    Generates a PDF transcript for the authenticated student
    using configurable templates from settings.

    Supports ?mode=page query parameter to return HTML preview instead of PDF.
    """
    student = get_current_student(request)

    pdf = student.generate_unofficial_transcript(request=request)

    # If mode=page was passed, generate_unofficial_transcript returns HttpResponse
    if request.GET.get('mode') == 'page':
        return pdf

    response = HttpResponse(pdf, content_type='application/pdf')
    filename = f"transcript_{student.user.last_name}_{student.user.first_name}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    return response
