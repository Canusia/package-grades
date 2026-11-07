"""The grades-submitted confirmation email (#17).

Sent each time a class's grades are submitted for a grading period, from the
grade POST (``views.grade_entry.handle_grade_post``), which knows the period
and who submitted. It replaces the ClassSection ``grade_status`` signal, which
fired only for the final period and could only email the instructor.

Recipients, deduplicated: whoever submitted, the class's primary instructor,
and the primary school's HS admins holding Can submit grades for the course's
campus. Secondary instructors and secondary-school admins (cis#154) are never
included. The "Send a Confirmation" switch turns all of those off; the Copy To
list always gets one.
"""
from django.template import Context, Template
from django.template.loader import get_template

from .email import parse_addresses, send_grades_mail
from .gating import submit_grades_admins_lookup


def _name(user, attr):
    return getattr(user, attr, '') if user is not None else ''


def submitted_recipients(section, submitter=None):
    """``[user]`` to confirm a submission to, in order, without repeats."""
    people = []
    if submitter is not None and getattr(submitter, 'email', ''):
        people.append(submitter)
    if section.teacher_id and section.teacher.user.email:
        people.append(section.teacher.user)
    lookup = submit_grades_admins_lookup()
    if lookup is not None and section.highschool_id:
        people += lookup(section.highschool_id, getattr(section.course, 'campus_id', None))
    seen, out = set(), []
    for person in people:
        if person.pk not in seen:
            seen.add(person.pk)
            out.append(person)
    return out


def send_grades_submitted(section, period, submitter=None):
    """Queue the confirmation for ``section``'s ``period``. Returns the
    addresses it went to (empty when nothing was sent)."""
    from ..settings.class_section_grades import class_section_grades
    settings = class_section_grades.from_db()

    to = []
    if settings.get('notify_instructor_on_submit', 'Yes') == 'Yes':
        to += [person.email for person in submitted_recipients(section, submitter)]
    to += [address for address in parse_addresses(settings.get('grades_submitted_cc'))
           if address not in to]
    if not to:
        return []

    teacher = section.teacher.user if section.teacher_id else None
    context = Context({
        'instructor_first_name': _name(teacher, 'first_name'),
        'instructor_last_name': _name(teacher, 'last_name'),
        'submitter_first_name': _name(submitter, 'first_name'),
        'submitter_last_name': _name(submitter, 'last_name'),
        'grading_period': period.name if period is not None else '',
        'term': str(section.term) if section.term_id else '',
        'course': section.course,
        'class_number': section.class_number,
    })
    text_body = Template(settings.get('grades_submitted_email') or '').render(context)
    html_body = get_template('cis/email.html').render({'message': text_body})
    send_grades_mail(settings, settings.get('grades_submitted_email_subject'),
                     text_body, html_body, to)
    return to
