"""CE Grades → SIS page: two DataTables feeds and the action endpoint.

The page's DataTables column configs (`SECTION_COLUMNS`, `REGISTRATION_COLUMNS`)
are defined here and handed to the template through ``json_script``; the page JS
uses them as-is, so `name` -- the ORM path drf-datatables orders and searches
on -- is declared once, next to the queryset that has to support it.
"""
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from rest_framework import viewsets

from cis.menu import draw_menu
from cis.utils import CIS_user_only

from ..actions import grade_sis_actions
from ..models import GradeSISSync, GradeSISSyncAttempt
from ..serializers import SISRegistrationSerializer, SISSectionSerializer
from ..services import sis_push
from ..services.roster import roster_statuses
from ..services.window import grade_terms

SYNC_STATUS_FILTERS = {'not_sent', GradeSISSync.QUEUED, GradeSISSync.SENT,
                       GradeSISSync.FAILED, GradeSISSync.NEEDS_MIRRORING}

_CHECKBOX = {'data': 'id', 'title': '', 'orderable': False, 'searchable': False,
             'className': 'select-checkbox'}

SECTION_COLUMNS = [
    _CHECKBOX,
    {'data': 'term_code', 'name': 'term.code', 'title': 'Term'},
    {'data': 'course_title', 'name': 'course.title', 'title': 'Course'},
    {'data': 'section_number', 'name': 'section_number', 'title': 'Section'},
    {'data': 'highschool_name', 'name': 'highschool.name', 'title': 'High School'},
    {'data': 'teacher_name', 'name': 'teacher.user.last_name,teacher.user.first_name',
     'title': 'Teacher'},
    {'data': 'graded_count', 'name': 'graded_count', 'title': 'Graded'},
    {'data': 'sent_count', 'name': 'sent_count', 'title': 'Sent'},
    {'data': 'needs_mirroring_count', 'name': 'needs_mirroring_count',
     'title': 'Needs Mirroring'},
    {'data': 'failed_count', 'name': 'failed_count', 'title': 'Failed'},
    {'data': 'not_sent_count', 'name': 'not_sent_count', 'title': 'Not Sent'},
]

REGISTRATION_COLUMNS = [
    _CHECKBOX,
    {'data': 'student_name', 'name': 'student.user.last_name,student.user.first_name',
     'title': 'Student'},
    {'data': 'student_psid', 'name': 'student.user.psid', 'title': 'PSID'},
    {'data': 'section_str', 'name': 'class_section.course.title,class_section.section_number',
     'title': 'Section'},
    {'data': 'term_code', 'name': 'class_section.term.code', 'title': 'Term'},
    {'data': 'grade', 'name': 'grade', 'title': 'Grade'},
    {'data': 'sync_status', 'name': 'grade_sis_sync.status', 'title': 'Sync Status'},
    {'data': 'sent_grade', 'name': 'grade_sis_sync.sent_grade', 'title': 'Sent Grade'},
    {'data': 'last_sent_at', 'name': 'grade_sis_sync.last_sent_at', 'title': 'Last Sent'},
    {'data': 'last_sent_by',
     'name': 'grade_sis_sync.last_sent_by.last_name,grade_sis_sync.last_sent_by.first_name',
     'title': 'Sent By'},
    {'data': 'last_error', 'name': 'grade_sis_sync.last_error', 'title': 'Error'},
    {'data': 'log_url', 'name': 'last_log_url', 'title': 'SIS Log'},
]


def _uuid_params(request, key):
    """Valid UUIDs from a comma-separated query param; junk is dropped."""
    raw = request.query_params.get(key, '')
    return sis_push._parse_ids(v for v in raw.split(',') if v)


def _roster_graded():
    """StudentRegistration rows that count as graded on the roster."""
    from cis.models.section import StudentRegistration
    qs = StudentRegistration.objects.filter(sis_push.graded_q())
    statuses = roster_statuses()
    if statuses:
        qs = qs.filter(status__in=statuses)
    return qs


def _count(extra=None):
    """Per-section count of graded roster registrations, optionally narrowed.

    A correlated subquery rather than Count() over the join: no GROUP BY, so
    drf-datatables' global search (which ORs these with plain columns) and
    ordering both stay in WHERE / ORDER BY.
    """
    qs = _roster_graded().filter(class_section=OuterRef('pk'))
    if extra is not None:
        qs = qs.filter(extra)
    qs = qs.order_by().values('class_section').annotate(n=Count('pk')).values('n')
    return Coalesce(Subquery(qs, output_field=IntegerField()), 0)


def sections_base():
    """Submitted sections in the grade terms -- the Sections tab's scope."""
    from cis.models.section import ClassSection
    return ClassSection.objects.filter(term_id__in=grade_terms(), grade_status='submitted')


def section_queryset(term_ids=None, highschool_ids=None):
    qs = sections_base()
    if term_ids:
        qs = qs.filter(term_id__in=term_ids)
    if highschool_ids:
        qs = qs.filter(highschool_id__in=highschool_ids)
    sync = 'grade_sis_sync__status'
    return (
        qs.select_related('term', 'course', 'highschool', 'teacher__user')
        .annotate(
            graded_count=_count(),
            sent_count=_count(Q(**{sync: GradeSISSync.SENT})),
            needs_mirroring_count=_count(Q(**{sync: GradeSISSync.NEEDS_MIRRORING})),
            failed_count=_count(Q(**{sync: GradeSISSync.FAILED})),
            not_sent_count=_count(Q(grade_sis_sync__isnull=True)),
        )
        .order_by('term__code', 'course__title', 'section_number')
    )


def registration_queryset(sync_status=None, term_ids=None, section_ids=None):
    """Graded roster registrations in the grade terms -- the Registrations tab.

    Also the scope `send_registrations` re-validates submitted ids against.
    """
    qs = _roster_graded().filter(class_section__term_id__in=grade_terms())
    if term_ids:
        qs = qs.filter(class_section__term_id__in=term_ids)
    if section_ids:
        qs = qs.filter(class_section_id__in=section_ids)
    wanted = [s for s in (sync_status or []) if s in SYNC_STATUS_FILTERS]
    if wanted:
        q = Q()
        if 'not_sent' in wanted:
            q |= Q(grade_sis_sync__isnull=True)
        others = [s for s in wanted if s != 'not_sent']
        if others:
            q |= Q(grade_sis_sync__status__in=others)
        qs = qs.filter(q)
    latest_log = (GradeSISSyncAttempt.objects
                  .filter(sync__registration=OuterRef('pk'))
                  .order_by('-attempted_at').values('log_url')[:1])
    return (
        qs.select_related('student__user', 'class_section__course', 'class_section__term',
                          'grade_sis_sync__last_sent_by')
        .annotate(last_log_url=Subquery(latest_log))
        .order_by('-grade_sis_sync__last_attempt_at', 'student__user__last_name')
    )


class _PusherRequired(CIS_user_only):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and sis_push.get_pusher() is not None


class SISSectionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SISSectionSerializer
    permission_classes = [_PusherRequired]

    def get_queryset(self):
        return section_queryset(term_ids=_uuid_params(self.request, 'term'),
                                highschool_ids=_uuid_params(self.request, 'highschool'))


class SISRegistrationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SISRegistrationSerializer
    permission_classes = [_PusherRequired]

    def get_queryset(self):
        raw = self.request.query_params.get('sync_status', '')
        return registration_queryset(
            sync_status=[s for s in raw.split(',') if s],
            term_ids=_uuid_params(self.request, 'term'),
            section_ids=_uuid_params(self.request, 'section'))


def sis_sync_page(request):
    from cis.models.highschool import HighSchool
    from cis.models.section import ClassSection
    from cis.models.term import Term

    context = {
        # Same call shape as other packages' CE pages (class_visit views/ce.py).
        # The sidebar is DB-settings driven; this only picks the highlight.
        'menu': draw_menu(None, 'classes', 'grades_sis_sync', 'ce'),
        'configured': sis_push.get_pusher() is not None,
    }
    if not context['configured']:
        return render(request, 'grades/sis/index.html', context)

    sections = sections_base()
    context.update({
        'config_errors': sis_push.get_config_errors(),
        'sections_url': reverse('grades_ce:sis-sections-list') + '?format=datatables',
        'registrations_url': reverse('grades_ce:sis-registrations-list') + '?format=datatables',
        'action_url': reverse('grades_ce:sis_action'),
        'bulk_actions': grade_sis_actions.for_scope('bulk', request.user),
        'section_columns': SECTION_COLUMNS,
        'registration_columns': REGISTRATION_COLUMNS,
        'terms': Term.objects.filter(pk__in=grade_terms()).order_by('code'),
        'highschools': HighSchool.objects.filter(
            pk__in=sections.values('highschool_id')).order_by('name'),
        'filter_sections': (ClassSection.objects.filter(term_id__in=grade_terms())
                            .select_related('course', 'term')
                            .order_by('term__code', 'course__title', 'section_number')),
    })
    return render(request, 'grades/sis/index.html', context)


def sis_action(request):
    action = request.POST.get('action') or request.GET.get('action') or ''
    if request.method != 'POST':
        if grade_sis_actions._find_action(action) is None:
            return JsonResponse({'outcome': 'alert', 'status': 'error',
                                 'title': 'Error', 'message': 'Invalid action.'}, status=400)
        return JsonResponse({'outcome': 'alert', 'status': 'error', 'title': 'Error',
                             'message': 'POST required.'}, status=405)
    return grade_sis_actions.dispatch(request, action)
