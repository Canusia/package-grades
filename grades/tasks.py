"""Background tasks for the grades package."""
from django_tasks import task


@task(queue_name='default')
def send_grades_to_sis(registration_ids: list, user_id: int | None) -> dict:
    """Push final grades to the SIS for the given registration ids."""
    from .services.sis_push import run_push
    return run_push(registration_ids, user_id)
