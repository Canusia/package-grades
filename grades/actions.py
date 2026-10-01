"""SIS grade-push actions for the CE Grades → SIS page.

`grade_sis_actions` backs the page's two tabs: the `sis_sections` group renders
on the Sections tab and the `sis_registrations` group on the Registrations tab.
Both are gated by `can_push` -- a CE user on a tenant with a configured pusher --
which hides the buttons (`for_scope`) and refuses the request (`dispatch`).

`grades` is an optional package, so this registry lives here rather than in
`cis/actions`.
"""
from django.http import JsonResponse

from cis.utils import user_has_cis_role
from myce.component_registry import ActionRegistry
from myce.component_registry.registration import registration_actions

from .services import sis_push

grade_sis_actions = ActionRegistry()


def can_push(user):
    return user_has_cis_role(user) and sis_push.get_pusher() is not None


def _done(message, status='success'):
    return JsonResponse({'outcome': 'call', 'fn': 'onBulkActionComplete',
                         'args': {'title': 'Send Grades to SIS', 'message': message,
                                  'status': status}})


@grade_sis_actions.action(
    'sis_sections', slug='send_sections', label='Send to SIS', scope=['bulk'],
    icon='fas fa-paper-plane', btn_class='btn-primary',
    confirm='Send final grades for the selected class section(s) to the SIS?',
    permission=can_push)
def send_sections(request):
    # select_for_sections re-validates: malformed ids are dropped and only
    # sections in the grade terms are considered.
    ids, skipped = sis_push.select_for_sections(request.POST.getlist('ids[]'))
    count = sis_push.enqueue(ids, request.user)
    message = f'{count} registration(s) queued for the SIS.'
    if skipped:
        names = ', '.join(f'{s.course.title} {s.section_number}' for s in skipped)
        message += f' Skipped {len(skipped)} section(s) whose grades are not submitted: {names}.'
    return _done(message, 'success' if count else 'info')


@grade_sis_actions.action(
    'sis_registrations', slug='send_registrations', label='Send Selected to SIS',
    scope=['bulk'], icon='fas fa-paper-plane', btn_class='btn-primary',
    confirm='Send the selected student grade(s) to the SIS?',
    permission=can_push)
def send_registrations(request):
    """Bulk send of selected registrations -- the bulk rule, not the single one.

    Only rows on this tab's own queryset are considered (grade terms, a real
    grade, roster statuses); anything else submitted, incl. malformed ids, is
    ignored. Of those, a row is sent only when its section's grades are
    submitted and its sync state is bulk-eligible (sis_push.bulk_eligible_ids:
    never `sent`, never freshly `queued`). Re-sending a single student
    regardless of section status is the registration-detail action's job.
    """
    from .views.sis_sync import registration_queryset

    ids = sis_push._parse_ids(request.POST.getlist('ids[]'))
    registrations = list(registration_queryset().filter(pk__in=ids)) if ids else []
    submitted = [r for r in registrations if r.class_section.grade_status == 'submitted']
    not_submitted = len(registrations) - len(submitted)
    eligible = sis_push.bulk_eligible_ids(submitted)
    count = sis_push.enqueue(eligible, request.user)

    reasons = []
    if not_submitted:
        reasons.append(f'{not_submitted} section grades not submitted')
    already = len(submitted) - count
    if already:
        reasons.append(f'{already} already sent or in progress')
    ignored = len(set(ids)) - len(registrations)
    if ignored:
        reasons.append(f'{ignored} not on this page (no grade or outside the grade terms)')
    message = f'{count} registration(s) queued for the SIS.'
    if reasons:
        skipped = len(set(ids)) - count
        message += f' {skipped} skipped: ' + '; '.join(reasons) + '.'
    return _done(message, 'success' if count else 'info')


@registration_actions.action(
    'sis', slug='send_grade_to_sis', label='Send Grade to SIS', scope=['detail'],
    icon='fas fa-paper-plane', btn_class='btn-info',
    confirm="Send this student's final grade to the SIS?",
    permission=can_push)
def send_grade_to_sis(request):
    """Single-student push from the registration detail page.

    Unlike the bulk Registrations-tab action, this ignores the section's
    grade_status (sis_push.check_single) -- a staff member may need to push
    one grade before the whole section is submitted.
    """
    from cis.models.section import StudentRegistration

    ids = sis_push._parse_ids(request.POST.getlist('ids[]'))
    registration = StudentRegistration.objects.filter(pk__in=ids[:1]).first()
    if registration is None:
        return JsonResponse({'outcome': 'alert', 'status': 'error',
                             'title': 'Send Grade to SIS', 'message': 'Registration not found.'})
    reason = sis_push.check_single(registration)
    if reason:
        return JsonResponse({'outcome': 'alert', 'status': 'error',
                             'title': 'Send Grade to SIS', 'message': reason})
    count = sis_push.enqueue([registration.pk], request.user)
    # enqueue() can return 0 even though check_single() just passed: another
    # request may have queued (or started processing) this same row in
    # between. Report what actually happened, not an assumed "Queued".
    message = ('Queued. Check the Grade SIS tab for the result.' if count else
               'Already in progress. Check the Grade SIS tab for the result.')
    return JsonResponse({'outcome': 'alert', 'status': 'success', 'title': 'Send Grade to SIS',
                         'message': message})
