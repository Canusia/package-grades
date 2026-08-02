import json, datetime
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, HTML

from cis.models.crontab import CronTab
from cis.models.term import Term
from cis.models.section import StudentRegistration
from cis.models.settings import Setting
from cis.validators import validate_html_short_code, validate_cron


class SettingForm(forms.Form):

    class Media:
        js = ('grades/js/settings.js',)

    grade_scale = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'id_grade_scale'}),
        label="Grade Scale"
    )

    registration_status = forms.MultipleChoiceField(
        help_text='Registration status(es) that are eligible to receive grade',
        label='Registration Status(es)',
        choices=StudentRegistration.STATUS_OPTIONS
    )

    terms = forms.MultipleChoiceField(
        choices=(),
        label='Class Term(s)',
        help_text='Class Section Term(s) for which grades can be submitted'
    )

    start_date = forms.DateField(
        label='Grade Submission Window Starting Date',
        help_text='Available to post grades on and after'
    )

    end_date = forms.DateField(
        label='Grade Submission Due Date',
        help_text='Available to post grades until'
    )

    require_roster_confirmation = forms.BooleanField(
        required=False,
        label='Require roster confirmation before grades are entered',
        help_text=(
            'When checked, an instructor cannot enter grades for a class '
            'section whose roster is still marked Pending Verification. '
            'Sections the instructor has already responded to (Accurate or '
            'Inaccurate), and sections never sent for verification, are not '
            'affected.'
        )
    )

    roster_not_confirmed_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        required=False,
        help_text=(
            'Shown on the class section page when grade entry is blocked '
            'because the roster is pending verification.'
        ),
        label="Roster Not Confirmed Message"
    )

    reminder_dates = forms.CharField(
        required=False,
        help_text='Select specific dates to send grade reminders',
        label="Reminder Dates",
        widget=forms.TextInput(attrs={
            'class': 'form-control reminder-dates-picker',
            'placeholder': 'Click to select dates',
            'readonly': 'readonly'
        })
    )

    cron = forms.CharField(
        max_length=20,
        help_text='Min Hr Day Month WeekDay',
        label="When should the notification be sent?",
        validators=[validate_cron]
    )

    grades_due_subject = forms.CharField(
        max_length=None,
        help_text='',
        label="Grades Due Email Subject")

    grades_due_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Customize with {{teacher_first_name}}, {{teacher_last_name}}, {{term}}, {{number_of_sections_pending_grades}}. <a href="#" class="float-right" onClick="do_bulk_action(\'class_section_grades\', \'grades_due\')" >See Preview</a>',
        label="Grades Due Email Message")
   
    grades_closed = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Message displayed when grades are closed. <a href="#" class="float-right" onClick="do_bulk_action(\'class_section_grades\', \'grades_closed\')" >See Preview</a>',
        label="Grades Closed"
    )

    grades_open = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Message displayed when grades are open. This is in the all classes page. <a href="#" class="float-right" onClick="do_bulk_action(\'class_section_grades\', \'grades_open\')" >See Preview</a>',
        label="Grades Open"
    )

    grades_open_class_section = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Message displayed when grades are not yet submitted - this is in the class section page. <a href="#" class="float-right" onClick="do_bulk_action(\'class_section_grades\', \'grades_open_class_section\')" >See Preview</a>',
        label="Grades How To"
    )

    grades_submitted_class_section = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Message displayed when grades have been submitted - this is in the class section page. <a href="#" class="float-right" onClick="do_bulk_action(\'class_section_grades\', \'grades_submitted\')" >See Preview</a>',
        label="Grades Submitted Message"
    )

    grades_submitted_email_subject = forms.CharField(
        max_length=100,
        help_text='',
        label="Grades Submitted - Email Subject"
    )

    grades_submitted_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent to instructor after final grades are submitted. Customize with {{instructor_first_name}}, {{instructor_last_name}}, {{course}}, {{class_number}}. <a href="#" class="float-right" onClick="do_bulk_action(\'class_section_grades\', \'grades_submitted_email\')" >See Preview</a>',
        label="Grades Submitted - Email"
    )

    transcript_template_header = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        required=False,
        help_text='Header HTML for unofficial transcript PDF. Customize with {{student_name}}, {{student_id}}, {{highschool}}, {{generated_date}}',
        label="Transcript Header"
    )

    transcript_table_header = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        required=False,
        help_text='Table header row HTML (thead tr) for transcript. Example: &lt;tr&gt;&lt;th&gt;Term&lt;/th&gt;&lt;th&gt;Course&lt;/th&gt;...&lt;/tr&gt;',
        label="Transcript Table Header"
    )

    transcript_row_template = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        required=False,
        help_text='Template for each course row. Customize with {{term}}, {{course_name}}, {{course_title}}, {{teacher}}, {{credit_hours}}, {{grade}}',
        label="Transcript Row Template"
    )

    transcript_template_footer = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        required=False,
        help_text='Footer HTML for unofficial transcript PDF. Customize with {{student_name}}, {{student_id}}, {{highschool}}, {{generated_date}}',
        label="Transcript Footer"
    )

    transcript_registration_status = forms.MultipleChoiceField(
        choices=StudentRegistration.STATUS_OPTIONS,
        required=False,
        help_text='Registration status(es) to include in the unofficial transcript',
        label='Transcript Registration Status(es)'
    )


    def clean_start_date(self):
        return self.data.get('start_date')

    def clean_end_date(self):
        start_date = datetime.datetime.strptime(
            self.data.get('start_date'), '%m/%d/%Y'
        )

        end_date = datetime.datetime.strptime(
            self.data.get('end_date'), '%m/%d/%Y'
        )

        if start_date > end_date:
            raise ValidationError(
                _(f'Open Until date has to be after Starting date.')
            )

        return self.data.get('end_date')

    def clean_reminder_dates(self):
        """Validate that reminder dates fall within the start/end date range."""
        reminder_dates_str = self.data.get('reminder_dates', '')
        if not reminder_dates_str:
            return ''

        start_date_str = self.data.get('start_date')
        end_date_str = self.data.get('end_date')

        if not start_date_str or not end_date_str:
            return reminder_dates_str

        try:
            start_date = datetime.datetime.strptime(start_date_str, '%m/%d/%Y').date()
            end_date = datetime.datetime.strptime(end_date_str, '%m/%d/%Y').date()

            dates = [d.strip() for d in reminder_dates_str.split(',') if d.strip()]
            for date_str in dates:
                try:
                    date = datetime.datetime.strptime(date_str, '%m/%d/%Y').date()
                    if date < start_date or date > end_date:
                        raise ValidationError(
                            _(f'Reminder date {date_str} must be between {start_date_str} and {end_date_str}.')
                        )
                except ValueError:
                    raise ValidationError(_(f'Invalid date format: {date_str}. Use MM/DD/YYYY.'))
        except ValueError:
            pass  # start_date or end_date parsing failed, skip validation

        return reminder_dates_str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


    def preview(self, request, field_name):
        from django.shortcuts import (
            render
        )
        from django.utils.safestring import mark_safe

        from django.template.loader import get_template, render_to_string
        from django.template import Context, Template
        from django.shortcuts import render, get_object_or_404

        from cis.models.student import Student
        from cis.settings.student_regis_pending import student_regis_pending
        from cis.settings.instructor_portal import instructor_portal as portal_lang
        from cis.utils import (
            active_term, grades_page_header_for_instructor,
            is_submit_grades_open
        )

        if field_name in ['grades_closed']:
            grade_settings = self.from_db()
            return render(
                request,
                'grades/instructor/grades.html',
                {
                    'menu': '-1',
                    'intro': portal_lang(request).from_db().get('grades_blurb', 'Change me'),
                    'page_header': grades_page_header_for_instructor(),
                    'is_open': False,
                    'classes_api': '',
                    'terms': None,
                    'grades_intro': grade_settings.get('grades_closed') ,
                    'intro': portal_lang(request).from_db().get('grades_blurb', 'Change me'),
                    'active_term': None
                })
        elif field_name in ['grades_open']:
            grade_settings = self.from_db()
            return render(
                request,
                'grades/instructor/grades.html',
                {
                    'menu': '-1',
                    'intro': portal_lang(request).from_db().get('grades_blurb', 'Change me'),
                    'page_header': grades_page_header_for_instructor(),
                    'is_open': True,
                    'classes_api': '',
                    'terms': None,
                    'grades_intro': grade_settings.get('grades_open') ,
                    'intro': portal_lang(request).from_db().get('grades_blurb', 'Change me'),
                    'active_term': None
                })
        elif field_name in ['grades_open_class_section']:
            grade_settings = self.from_db()
            
            return render(
                request,
                'instructor/class_section_grade.html',
                {
                    'menu': None,
                    'class_section': None,
                    'grade_formset': None,
                    'students_in_class': None,
                    'is_open': True,
                    'intro': portal_lang(request).from_db().get('grades_blurb', 'Change me'),
                    'message': grade_settings.get('grades_open_class_section')
                })
        elif field_name in ['grades_submitted_class_section']:
            grade_settings = self.from_db()
            
            return render(
                request,
                'instructor/class_section_grade.html',
                {
                    'menu': None,
                    'class_section': None,
                    'grade_formset': None,
                    'students_in_class': None,
                    'is_open': True,
                    'intro': portal_lang(request).from_db().get('grades_blurb', 'Change me'),
                    'message': grade_settings.get('grades_submitted_class_section')
                })

        email_settings = self.from_db()
        if field_name in ['grades_due', 'grades_submitted_email' ]:
            if field_name == 'grades_due':
                subject = email_settings.get('grades_due_subject')
                email = email_settings.get('grades_due_email')
            if field_name == 'grades_submitted_email':
                subject = email_settings.get('grades_submitted_email_subject')
                email = email_settings.get('grades_submitted_email')

            message = Template(email)
            context = Context({
                'student_first_name': "John",
                'teacher_first_name': "John",
                'teacher_last_name': "Smith",
                'instructor_first_name': "John",
                'instructor_last_name': "Smith",
                'course': "ACC 101",
                'class_number': "12345",
                'term': "Fall 2018",
                'number_of_sections_pending_grades': "10",
                'student_last_name': "Smith",
                'student_email': "john@email.com",
                'student_list': mark_safe("<br>".join({'Student 1', 'Student 2', 'Student 3'})),
            })
            
            text_body = message.render(context)
            
            return render(
                request,
                'cis/email.html',
                {
                    'message': text_body
                }
            )

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """

        cron, created = CronTab.objects.get_or_create(
            command='notify_grades_pending'
        )
        cron.cron = self.cleaned_data.get('cron')
        cron.save()

        # Parse grade_scale and derive grades + gpa_points for backward compatibility
        grade_scale = self._parse_grade_scale(self.cleaned_data.get('grade_scale', ''))
        grades_list = [item['grade'] for item in grade_scale]
        gpa_points = {item['grade']: item['points'] for item in grade_scale}

        return {
            'grade_scale': grade_scale,
            'grades': ','.join(grades_list),
            'gpa_points': gpa_points,
            'registration_status': self.cleaned_data['registration_status'],

            'require_roster_confirmation': self.cleaned_data.get(
                'require_roster_confirmation', False),
            'roster_not_confirmed_message': self.cleaned_data.get(
                'roster_not_confirmed_message', ''),

            'reminder_dates': self.cleaned_data.get('reminder_dates', ''),
            'cron': self.cleaned_data['cron'],
            'grades_due_subject': self.cleaned_data['grades_due_subject'],
            'grades_due_email': self.cleaned_data['grades_due_email'],

            'grades_submitted_email': self.cleaned_data['grades_submitted_email'],
            'grades_submitted_email_subject': self.cleaned_data['grades_submitted_email_subject'],
            'terms': self.cleaned_data['terms'],
            'start_date': self.cleaned_data['start_date'],
            'end_date': self.cleaned_data['end_date'],

            'grades_closed': self.cleaned_data['grades_closed'],
            'grades_open': self.cleaned_data['grades_open'],
            'grades_open_class_section': self.cleaned_data['grades_open_class_section'],
            'grades_submitted_class_section': self.cleaned_data['grades_submitted_class_section'],
            'transcript_template_header': self.cleaned_data.get('transcript_template_header', ''),
            'transcript_table_header': self.cleaned_data.get('transcript_table_header', ''),
            'transcript_row_template': self.cleaned_data.get('transcript_row_template', ''),
            'transcript_template_footer': self.cleaned_data.get('transcript_template_footer', ''),
            'transcript_registration_status': self.cleaned_data.get('transcript_registration_status', ['registered']),
        }

    @staticmethod
    def get_default_grade_scale():
        """Return default grade scale as list of dicts."""
        return [
            {'grade': 'A', 'points': 4.0},
            {'grade': 'A-', 'points': 3.7},
            {'grade': 'B+', 'points': 3.3},
            {'grade': 'B', 'points': 3.0},
            {'grade': 'B-', 'points': 2.7},
            {'grade': 'C+', 'points': 2.3},
            {'grade': 'C', 'points': 2.0},
            {'grade': 'C-', 'points': 1.7},
            {'grade': 'D+', 'points': 1.3},
            {'grade': 'D', 'points': 1.0},
            {'grade': 'D-', 'points': 0.7},
            {'grade': 'F', 'points': 0.0},
        ]

    def _parse_grade_scale(self, value):
        """Parse grade scale from JSON string or return default."""
        if not value:
            return self.get_default_grade_scale()
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
            return self.get_default_grade_scale()
        except (json.JSONDecodeError, TypeError):
            return self.get_default_grade_scale()

class class_section_grades(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_class_grades"
    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        term_list = []

        for term in Term.objects.all().order_by('-code'):
            term_list.append((str(term.id), str(term)))
            
        self.fields['terms'].choices = term_list

        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

        # Include grade settings JS via crispy forms layout
        self.helper.layout = Layout(
            HTML('<script src="/static/grades/js/settings.js"></script>'),
            *self.fields.keys()
        )

    def install(self):
        grade_scale = self.get_default_grade_scale()
        defaults = {
            'grade_scale': grade_scale,
            'grades': ','.join([item['grade'] for item in grade_scale]),
            'gpa_points': {item['grade']: item['points'] for item in grade_scale},
            'grades_submitted_email': 'Change Me',
            'grades_submitted_email_subject': 'Change Me',
            'terms': '',
            'start_date': '10/10/2040',
            'end_date': '10/11/2040',
            'grades_open': '-',
            'grades_closed': '-',
            'grades_open_class_section': 'Change me',
            'grades_submitted_class_section': 'Change me',
            'transcript_template_header': '''<div class="row mb-4">
    <div class="col-8">
        <h3 class="mb-1">Concurrent Enrollment Program</h3>
        <h4 class="text-muted">Unofficial Academic Transcript</h4>
    </div>
    <div class="col-4 text-right">
        <small class="text-muted">Generated: {{generated_date}}</small>
    </div>
</div>
<div class="row mb-4">
    <div class="col-6">
        <strong>Student Information</strong><br>
        Name: {{student_name}}<br>
        Student ID: {{student_id}}
    </div>
    <div class="col-6">
        <strong>High School</strong><br>
        {{highschool}}
    </div>
</div>
<hr>''',
            'transcript_table_header': '''<tr class="bg-light">
    <th style="width: 15%;">Term</th>
    <th style="width: 35%;">Course</th>
    <th style="width: 25%;">Instructor</th>
    <th style="width: 10%;" class="text-center">Credits</th>
    <th style="width: 15%;" class="text-center">Grade</th>
</tr>''',
            'transcript_row_template': '''<tr>
    <td>{{term}}</td>
    <td>
        <strong>{{course_name}}</strong><br>
        <small class="text-muted">{{course_title}}</small>
    </td>
    <td>{{teacher}}</td>
    <td class="text-center">{{credit_hours}}</td>
    <td class="text-center"><strong>{{grade}}</strong></td>
</tr>''',
            'transcript_template_footer': '''<hr>
<div class="row mt-3">
    <div class="col-12">
        <p class="text-muted small mb-1">
            <strong>UNOFFICIAL TRANSCRIPT</strong> - This document is for informational purposes only
            and is not valid for official use. Official transcripts must be requested through the registrar's office.
        </p>
        <p class="text-muted small">
            Document generated on {{generated_date}} for {{student_name}} (ID: {{student_id}})
        </p>
    </div>
</div>''',
            'transcript_registration_status': ['registered'],
        }

        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = defaults
        setting.save()

    @classmethod
    def get_transcript_defaults(cls):
        """Return default transcript template values."""
        grade_scale = SettingForm.get_default_grade_scale()
        return {
            'grade_scale': grade_scale,
            'grades': ','.join([item['grade'] for item in grade_scale]),
            'gpa_points': {item['grade']: item['points'] for item in grade_scale},
            'transcript_template_header': '''<div class="row mb-4">
    <div class="col-8">
        <h3 class="mb-1">Concurrent Enrollment Program</h3>
        <h4 class="text-muted">Unofficial Academic Transcript</h4>
    </div>
    <div class="col-4 text-right">
        <small class="text-muted">Generated: {{generated_date}}</small>
    </div>
</div>
<div class="row mb-4">
    <div class="col-6">
        <strong>Student Information</strong><br>
        Name: {{student_name}}<br>
        Student ID: {{student_id}}
    </div>
    <div class="col-6">
        <strong>High School</strong><br>
        {{highschool}}
    </div>
</div>
<hr>''',
            'transcript_table_header': '''<tr class="bg-light">
    <th style="width: 15%;">Term</th>
    <th style="width: 35%;">Course</th>
    <th style="width: 25%;">Instructor</th>
    <th style="width: 10%;" class="text-center">Credits</th>
    <th style="width: 15%;" class="text-center">Grade</th>
</tr>''',
            'transcript_row_template': '''<tr>
    <td>{{term}}</td>
    <td>
        <strong>{{course_name}}</strong><br>
        <small class="text-muted">{{course_title}}</small>
    </td>
    <td>{{teacher}}</td>
    <td class="text-center">{{credit_hours}}</td>
    <td class="text-center"><strong>{{grade}}</strong></td>
</tr>''',
            'transcript_template_footer': '''<hr>
<div class="row mt-3">
    <div class="col-12">
        <p class="text-muted small mb-1">
            <strong>UNOFFICIAL TRANSCRIPT</strong> - This document is for informational purposes only
            and is not valid for official use. Official transcripts must be requested through the registrar's office.
        </p>
        <p class="text-muted small">
            Document generated on {{generated_date}} for {{student_name}} (ID: {{student_id}})
        </p>
    </div>
</div>''',
            'transcript_registration_status': ['registered'],
        }

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            values = setting.value

            # Backward compatibility: convert old grades/gpa_points to grade_scale
            if 'grade_scale' not in values and 'gpa_points' in values:
                gpa_points = values.get('gpa_points', {})
                if isinstance(gpa_points, dict):
                    # Preserve order from grades field if available
                    grades_list = values.get('grades', '').split(',')
                    grade_scale = []
                    for grade in grades_list:
                        grade = grade.strip()
                        if grade and grade in gpa_points:
                            grade_scale.append({
                                'grade': grade,
                                'points': gpa_points[grade]
                            })
                    # Add any grades in gpa_points not in grades list
                    for grade, points in gpa_points.items():
                        if not any(g['grade'] == grade for g in grade_scale):
                            grade_scale.append({'grade': grade, 'points': points})
                    values['grade_scale'] = grade_scale if grade_scale else SettingForm.get_default_grade_scale()

            # Merge in transcript defaults for any missing keys
            defaults = cls.get_transcript_defaults()
            for key, default_value in defaults.items():
                if key not in values or not values.get(key):
                    values[key] = default_value
            return values
        except Setting.DoesNotExist:
            return cls.get_transcript_defaults()

    def run_record(self):
        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = self._to_python()
        setting.save()

        return JsonResponse({
            'message': 'Successfully saved settings',
            'status': 'success'})
