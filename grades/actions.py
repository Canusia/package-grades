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
    from .views.sis_sync import registration_queryset

    # Restrict to the Registrations tab's own rows: grade terms, a real grade,
    # roster statuses. Anything else submitted (incl. malformed ids) is ignored.
    ids = sis_push._parse_ids(request.POST.getlist('ids[]'))
    registrations = registration_queryset().filter(pk__in=ids) if ids else []
    eligible = [r.pk for r in registrations if sis_push.check_single(r) is None]
    count = sis_push.enqueue(eligible, request.user)
    message = f'{count} registration(s) queued for the SIS.'
    skipped = len(set(ids)) - count
    if skipped:
        message += f' {skipped} skipped (no grade, not in the grade terms, or a send already in progress).'
    return _done(message, 'success' if count else 'info')
