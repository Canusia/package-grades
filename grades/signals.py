"""
Grades app signals.

Signal handlers for grade-related events.

The grades-submitted confirmation email used to be a ClassSection pre_save
receiver here (final period only, instructor only). Since v1.3.0 it is sent
from the grade POST for every grading period (``services.submitted_email``).
"""
from django.core.signals import request_finished, request_started
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver


from cis.models.section import ClassSection, StudentRegistration


@receiver(post_save, sender=StudentRegistration)
def flag_grade_change(sender, instance, created, update_fields=None, **kwargs):
    """Flag a sent grade that has since changed as needing to be re-sent.

    Compares against the grade the SIS last accepted (`sent_grade`), so no
    FieldTracker on cis is needed. Queued/failed rows are left alone: the next
    send reads the current grade anyway.
    """
    if created:
        return
    if update_fields is not None and 'grade' not in update_fields:
        return

    from django.utils import timezone

    from .models import GradeSISSync
    from .services.sis_push import normalize_grade

    sync = GradeSISSync.objects.filter(
        registration_id=instance.pk,
        status__in=[GradeSISSync.SENT, GradeSISSync.NEEDS_MIRRORING],
    ).first()
    if sync is None:
        return

    changed = normalize_grade(instance.grade) != sync.sent_grade
    if changed and sync.status == GradeSISSync.SENT:
        sync.status = GradeSISSync.NEEDS_MIRRORING
        sync.grade_changed_at = timezone.now()
        sync.save(update_fields=['status', 'grade_changed_at'])
    elif not changed and sync.status == GradeSISSync.NEEDS_MIRRORING:
        sync.status = GradeSISSync.SENT
        sync.grade_changed_at = None
        sync.save(update_fields=['status', 'grade_changed_at'])


# submitted_grade()'s per-request memo (#12): started and dropped with each
# request, and cleared whenever a grading period or a section's period status
# is saved, or a grading period deleted, so a change made mid-request is seen
# by the next lookup. No post_delete receiver on SectionPeriodStatus: its rows
# go only when their section or period does, and a receiver would cost cis
# Django's fast cascade delete on every ClassSection delete.
def _connect_final_status_memo():
    from .models import GradingPeriod, SectionPeriodStatus
    from .services import window
    request_started.connect(window.start_request_memo,
                            dispatch_uid='grades_final_status_memo_start')
    request_finished.connect(window.end_request_memo,
                             dispatch_uid='grades_final_status_memo_end')
    post_save.connect(window.clear_request_memo, sender=GradingPeriod,
                      dispatch_uid='grades_final_status_memo_period_saved')
    post_delete.connect(window.clear_request_memo, sender=GradingPeriod,
                        dispatch_uid='grades_final_status_memo_period_deleted')
    post_save.connect(window.clear_request_memo, sender=SectionPeriodStatus,
                      dispatch_uid='grades_final_status_memo_status_saved')


_connect_final_status_memo()
