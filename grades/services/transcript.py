"""
Unofficial transcript rendering.

Lifted from ``Student.generate_unofficial_transcript`` (``cis/models/student.py``).
"""
from datetime import datetime

import pdfkit

from django.http import HttpResponse
from django.template import Context, Template
from django.template.loader import get_template


def render_transcript(student, request=None):
    """
    Generate an unofficial transcript PDF for the student.

    Uses configurable templates from class_section_grades settings for
    header, table header, row template, and footer.

    Args:
        student: the ``cis.models.student.Student`` to render.
        request: Optional HTTP request. If request.GET.get('mode') == 'page',
                 returns HTML instead of PDF.

    Returns:
        PDF bytes or HttpResponse with HTML if mode=page
    """
    from cis.models.section import StudentRegistration
    from ..settings.class_section_grades import class_section_grades

    base_template = 'student/transcript.html'
    template = get_template(base_template)

    template_settings = class_section_grades.from_db()

    student_name = f"{student.user.first_name} {student.user.last_name}"
    student_id = student.suid or student.user.psid or ''
    highschool_name = student.highschool.name if student.highschool else ''
    generated_date = datetime.now().strftime('%B %d, %Y at %I:%M %p')

    # Context for header and footer templates
    student_context = Context({
        'student_name': student_name,
        'student_id': student_id,
        'highschool': highschool_name,
        'generated_date': generated_date,
    })

    # Render header and footer
    header_template = Template(template_settings.get('transcript_template_header', ''))
    footer_template = Template(template_settings.get('transcript_template_footer', ''))
    table_header_template = Template(template_settings.get('transcript_table_header', ''))
    row_template = Template(template_settings.get('transcript_row_template', ''))

    header_html = header_template.render(student_context)
    footer_html = footer_template.render(student_context)
    table_header_html = table_header_template.render(Context({}))

    # Get registration statuses to include from settings
    transcript_statuses = template_settings.get('transcript_registration_status', ['registered'])

    # Get registrations with matching statuses
    registrations = StudentRegistration.objects.filter(
        student=student,
        status__in=transcript_statuses
    ).select_related(
        'class_section',
        'class_section__term',
        'class_section__course',
        'class_section__teacher',
        'class_section__teacher__user'
    ).order_by('-class_section__term__code', 'class_section__course__name')

    # Render each row
    rows = []
    for reg in registrations:
        teacher_name = ''
        if reg.class_section.teacher and reg.class_section.teacher.user:
            teacher = reg.class_section.teacher.user
            teacher_name = f"{teacher.first_name} {teacher.last_name}"

        row_context = Context({
            'term': str(reg.class_section.term) if reg.class_section.term else '',
            'course_name': reg.class_section.course.name if reg.class_section.course else '',
            'course_title': reg.class_section.course.title if reg.class_section.course else '',
            'teacher': teacher_name,
            'credit_hours': reg.class_section.course.credit_hours if reg.class_section.course else '',
            'grade': reg.submitted_grade or '',
        })
        rows.append(row_template.render(row_context))

    rows_html = '\n'.join(rows)

    # Render main template
    html = template.render({
        'header': header_html,
        'table_header': table_header_html,
        'rows': rows_html,
        'footer': footer_html,
    })

    if request and request.GET.get('mode') == 'page':
        return HttpResponse(html)

    options = {
        'page-size': 'Letter',
        'margin-top': '0.5in',
        'margin-right': '0.5in',
        'margin-bottom': '0.5in',
        'margin-left': '0.5in',
    }
    pdf = pdfkit.from_string(html, False, options)

    return pdf
