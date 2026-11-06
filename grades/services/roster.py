"""
Roster service for grade entry.

Lifted from ``ClassSection.get_students_for_grades`` (``cis/models/section.py``).
"""


def roster_statuses():
    """Registration statuses on the grade-entry roster ([] means every status).

    The ``class_section_grades.registration_status`` setting. Shared by
    ``students_for_grades`` and by queryset-level callers (the CE Grades → SIS
    page) that can't go section by section.
    """
    from ..settings.class_section_grades import class_section_grades
    return class_section_grades.from_db().get('registration_status') or []


def students_for_grades(section, highschool_ids=None):
    """Registrations on ``section`` that should appear on the grade-entry roster.

    ``highschool_ids`` (cis#154) narrows it to students of those schools --
    a secondary-school HS admin's view. ``None`` is the whole class; an empty
    list is nobody. Filtered here rather than through get_students'
    ``highschool_ids``, which an older cis lacks and which treats [] as all.
    """
    students = section.get_students(
        status=roster_statuses()
    )
    if highschool_ids is not None:
        students = students.filter(student__highschool_id__in=list(highschool_ids))
    return students


def roster_pdf_response(section, highschool_ids=None):
    """The class roster PDF; with ``highschool_ids``, only those schools'
    students (cis's ``download_roster_pdf`` has no school filter).

    Mirrors ``ClassSection.download_roster_pdf``: same template, the Roster
    Verification statuses (Registered when none are chosen).
    """
    if highschool_ids is None:
        return section.download_roster_pdf()
    import datetime

    import pdfkit
    from django.http import HttpResponse
    from django.template.loader import get_template
    from django.utils.http import content_disposition_header

    from cis.models.section import StudentRegistration
    from cis.settings.roster_verification import roster_registration_statuses

    students = StudentRegistration.objects.filter(
        class_section=section,
        status__in=roster_registration_statuses() or ['registered'],
        student__highschool_id__in=list(highschool_ids),
    ).order_by('student__user__last_name')
    html = get_template('cis/sections/class_roster.html').render({
        'students': students,
        'generated_on': datetime.datetime.now(),
        'class_section': section,
    })
    pdf = pdfkit.from_string(html, False, {'page-size': 'Letter'})
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = content_disposition_header(
        True, f'class_roster_{section.class_number}_{section.term.code}.pdf')
    return response
