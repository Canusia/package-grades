from django.shortcuts import render, get_object_or_404, redirect
from django.http import Http404
from django.contrib import messages
from django.forms.formsets import formset_factory

from cis.menu import draw_menu, INSTRUCTOR_MENU
from cis.models.term import Term
from cis.models.section import ClassSection
from ..forms.section import ClassSectionGradeFormSet, ClassSectionGradeForm
from cis.utils import grades_page_header_for_instructor, is_submit_grades_open
from cis.settings.instructor_portal import instructor_portal as portal_lang
from ..services.roster import students_for_grades
from ..services.gating import can_enter_grades
from ..services.periods import (
    periods_for_section,
    resolve_period,
    is_period_open,
    grades_for,
    get_status,
    set_status,
)
from ..settings.class_section_grades import class_section_grades


def class_grades(request):
    menu = draw_menu(INSTRUCTOR_MENU, 'grades', '', 'instructor')
    grade_settings = class_section_grades.from_db()

    grade_term_ids = grade_settings.get('terms', [])
    grade_terms = Term.objects.filter(pk__in=grade_term_ids)

    # Build API URL with all grade-open term IDs
    term_ids_str = ','.join(str(t.id) for t in grade_terms)
    classes_api = f'/instructor/api/v1/class-section/?format=datatables&term={term_ids_str}'

    return render(
        request,
        'grades/instructor/grades.html',
        {
            'menu': menu,
            'intro': portal_lang(request).from_db().get('grades_blurb', 'Change me'),
            'page_header': grades_page_header_for_instructor(),
            'is_open': is_submit_grades_open(),
            'classes_api': classes_api,
            'require_roster_confirmation': grade_settings.get(
                'require_roster_confirmation', False),
            'grades_intro': grade_settings.get('grades_open') if is_submit_grades_open() else grade_settings.get('grades_closed'),
        })


def class_section_grade(request, record_id):
    menu = draw_menu(INSTRUCTOR_MENU, 'grades', '', 'instructor')
    # PT-32: scope to the requesting instructor's own sections (IDOR fix).
    # Teacher.user is a OneToOne to CustomUser, so teacher__user matches the
    # logged-in instructor. Non-owned sections raise 404 (gates GET + POST,
    # since this object is reused by the POST grade-processing branch below).
    class_section_info = get_object_or_404(
        ClassSection, pk=record_id, teacher__user=request.user
    )
    students_in_class = students_for_grades(class_section_info)

    # Roster confirmation gate. Renders the page read-only when the roster is
    # still pending verification; the POST branch below is what actually
    # prevents a write.
    roster_gate_ok, roster_gate_message = can_enter_grades(class_section_info)

    # Grading periods. A term with none configured keeps the old single-window
    # behaviour exactly: period stays None and every downstream call falls back.
    periods = periods_for_section(class_section_info)
    period = resolve_period(class_section_info, request.GET.get('period'))
    if periods and period is None:
        # A period id was supplied that does not belong to this section's term.
        raise Http404('Unknown grading period for this class section.')

    window_open = is_period_open(period) if periods else is_submit_grades_open()
    period_status = get_status(class_section_info, period)

    settings = class_section_grades.from_db()
    existing_marks = grades_for(class_section_info, period, students_in_class)
    grade_data = [
        {
            'student_id': registration.id,
            'grade': existing_marks.get(registration.id, ''),
            'student': registration.student.user.last_name + ', ' + registration.student.user.first_name
        }
        for registration in students_in_class
    ]

    GradeFS = formset_factory(
        ClassSectionGradeForm,
        formset=ClassSectionGradeFormSet,
        extra=0,
        validate_max=False,
        min_num=1,
        max_num=len(grade_data)
    )
    gradeformset = GradeFS(
        initial=grade_data,
        class_section=class_section_info,
        period=period,
        user=request.user
    )

    if request.method == 'POST':
        # The real gate. The read-only rendering above is a courtesy; a POST is
        # refused regardless of what the UI showed.
        if not roster_gate_ok:
            messages.add_message(
                request,
                messages.SUCCESS,
                roster_gate_message,
                'list-group-item-danger'
            )
            return redirect(
                'instructor:class_section_grade', record_id=class_section_info.id)

        if not window_open:
            messages.add_message(
                request,
                messages.SUCCESS,
                f'Grade submission for {period.name} is currently closed.'
                if period else 'Grade submission is currently closed.',
                'list-group-item-success'
            )
            return redirect('instructor:dashboard')

        gradeformset = GradeFS(
            request.POST,
            initial=grade_data,
            class_section=class_section_info,
            period=period,
            user=request.user
        )

        if request.GET.get('action') == 'download_roster_pdf':
            return class_section_info.download_roster_pdf()

        if 'Draft' in request.POST.get('save_grade', ''):
            for form in gradeformset.forms:
                form.fields['grade'].required = False

        if gradeformset.is_valid():
            gradeformset.save()

            if 'Draft' in request.POST.get('save_grade', ''):
                set_status(class_section_info, period, 'saved')
                period_status = 'saved'

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Your grades have been successfully saved.',
                    'list-group-item-success')
            else:
                set_status(class_section_info, period, 'submitted')
                period_status = 'submitted'

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Your grades have been successfully submitted.',
                    'list-group-item-success')
        else:
            messages.add_message(
                request,
                messages.SUCCESS,
                'Please fix the errors below and try again.',
                'list-group-item-danger')

    message = ''
    if period_status == 'submitted':
        message = settings.get('grades_submitted_class_section')
    else:
        message = settings.get('grades_open_class_section')

    return render(
        request,
        'grades/instructor/class_section_grade.html',
        {
            'menu': menu,
            'class_section': class_section_info,
            'grade_formset': gradeformset,
            'students_in_class': students_in_class,
            'is_open': window_open,
            'roster_gate_ok': roster_gate_ok,
            'roster_gate_message': roster_gate_message,
            'periods': periods,
            'period': period,
            'period_status': period_status,
            'intro': portal_lang(request).from_db().get('grades_blurb', 'Change me'),
            'message': message
        })
