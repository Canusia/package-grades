"""django-admin-runner hook (grades#20).

Lets grades commands be run from the Django admin. django-admin-runner is a
dependency of grades (since 1.4.0), but the commands only show up when the
host adds ``django_admin_runner`` to INSTALLED_APPS. The ImportError fallback
covers an environment installed without dependencies: the decorator then
does nothing and every command still runs from ``manage.py``.
"""
try:
    from django_admin_runner import register_command  # noqa: F401
except ImportError:  # runner not installed: the decorator does nothing
    def register_command(*args, **kwargs):
        return lambda cls: cls
