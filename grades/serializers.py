"""Slim DataTables serializers for the CE Grades → SIS page.

Each field here is one table column and nothing more: drf-datatables trims only
top-level fields, so nested serializers would ship whole. The count and log-url
columns are queryset annotations (see views/sis_sync.py), not method fields, so
they can be ordered and searched.
"""
from django.utils import dateformat, timezone
from rest_framework import serializers

from cis.models.section import ClassSection, StudentRegistration

# Same rendering as the registration Grade SIS tab's |date:"m/d/Y g:i A".
DATE_FMT = 'm/d/Y g:i A'


def _full_name(user):
    return f'{user.last_name}, {user.first_name}' if user else ''


class SISSectionSerializer(serializers.ModelSerializer):
    term_code = serializers.CharField(source='term.code')
    course_title = serializers.CharField(source='course.title')
    highschool_name = serializers.SerializerMethodField()
    teacher_name = serializers.SerializerMethodField()
    graded_count = serializers.IntegerField()
    sent_count = serializers.IntegerField()
    needs_mirroring_count = serializers.IntegerField()
    failed_count = serializers.IntegerField()
    not_sent_count = serializers.IntegerField()

    class Meta:
        model = ClassSection
        fields = ['id', 'term_code', 'course_title', 'section_number',
                  'highschool_name', 'teacher_name', 'graded_count', 'sent_count',
                  'needs_mirroring_count', 'failed_count', 'not_sent_count']
        datatables_always_serialize = fields

    def get_highschool_name(self, obj):
        return obj.highschool.name if obj.highschool_id else ''

    def get_teacher_name(self, obj):
        return _full_name(obj.teacher.user) if obj.teacher_id else ''


class SISRegistrationSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_psid = serializers.SerializerMethodField()
    section_str = serializers.SerializerMethodField()
    term_code = serializers.CharField(source='class_section.term.code')
    sync_status = serializers.SerializerMethodField()
    sent_grade = serializers.SerializerMethodField()
    last_sent_at = serializers.SerializerMethodField()
    last_sent_by = serializers.SerializerMethodField()
    last_error = serializers.SerializerMethodField()
    log_url = serializers.CharField(source='last_log_url', default='')

    class Meta:
        model = StudentRegistration
        fields = ['id', 'student_name', 'student_psid', 'section_str', 'term_code', 'grade',
                  'sync_status', 'sent_grade', 'last_sent_at', 'last_sent_by',
                  'last_error', 'log_url']
        datatables_always_serialize = fields

    def _sync(self, obj):
        return getattr(obj, 'grade_sis_sync', None)

    def get_student_name(self, obj):
        return _full_name(obj.student.user)

    def get_student_psid(self, obj):
        return obj.student.user.psid or ''

    def get_section_str(self, obj):
        cs = obj.class_section
        return f'{cs.course.title} / {cs.section_number}'

    def get_sync_status(self, obj):
        sync = self._sync(obj)
        return sync.get_status_display() if sync else 'Not Sent'

    def get_sent_grade(self, obj):
        sync = self._sync(obj)
        return sync.sent_grade if sync else ''

    def get_last_sent_at(self, obj):
        sync = self._sync(obj)
        if not (sync and sync.last_sent_at):
            return ''
        return dateformat.format(timezone.localtime(sync.last_sent_at), DATE_FMT)

    def get_last_sent_by(self, obj):
        sync = self._sync(obj)
        return _full_name(sync.last_sent_by) if sync else ''

    def get_last_error(self, obj):
        sync = self._sync(obj)
        return sync.last_error if sync else ''
