"""Optional host modules, with fallbacks for tenants whose cis/myce predates them.

grades runs against both the ``myce_cis`` package (>= 0.1.7a, multi-campus) and
tenants that keep an older ``cis`` inside their own repo. Three of the modules
grades uses are missing from the latter:

* ``cis.campus_gate``: campus field and campus scoping on the reports.
  Without it the field is dropped and records are left unscoped, since a
  single-campus tenant has nothing to filter.
* ``cis.highschool_scope``: campus-scoped school pickers. Without it the
  pickers list active schools by name (the pre-v0.0.7 queryset).
* ``cis.services.tenant_services.get_tenant_override``: the SIS pusher seam.
  Without it SIS push is simply not configured.
* ``Setting.install_defaults``: seed-only settings install. Without it the
  same key-by-key merge runs here.

The ``myce.component_registry`` submodules grades registers tabs and actions on
are optional too: a host without one (e.g. no ``registration`` registry) just
doesn't get those tabs; see ``registry`` and ``register``.

Availability is checked with ``find_spec`` rather than ``try/except ImportError``
so that a real import error inside a present module still raises instead of
silently turning into the fallback.
"""
import importlib
import importlib.util
import sys


def has_module(name):
    """True when the dotted module ``name`` is importable.

    A module already in ``sys.modules`` counts as importable even with no
    ``__spec__`` (package-cis registry stand-ins, #11), where ``find_spec``
    would raise ValueError. A ``None`` entry means the import is blocked.
    """
    if name in sys.modules:
        return sys.modules[name] is not None
    try:
        return importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError, ValueError):  # missing parent / spec-less parent
        return False


def registry(module, name):
    """The ``name`` registry from ``module``, or None when the host lacks it."""
    if not has_module(module):
        return None
    return getattr(importlib.import_module(module), name, None)


def register(target, method, *args, **kwargs):
    """``@target.<method>(...)`` when ``target`` exists, else a no-op decorator."""
    if target is None:
        return lambda fn: fn
    return getattr(target, method)(*args, **kwargs)


def has_campus_gate():
    return has_module('cis.campus_gate')


def get_accessible_campuses(user):
    from cis.campus_gate import get_accessible_campuses as accessible
    return accessible(user)


def scope_report_by_campus(records, user, selected_campus_ids, campus_path):
    if not has_campus_gate():
        return records
    from cis.campus_gate import scope_report_by_campus as scope
    return scope(records, user, selected_campus_ids, campus_path=campus_path)


def apply_campus_field(form, user=None):
    """Fill a report form's ``campus`` field, or drop it without a campus gate."""
    if not has_campus_gate():
        form.fields.pop('campus', None)
    elif user is not None:
        # Only the campuses the requesting user may process (superusers see all).
        form.fields['campus'].queryset = get_accessible_campuses(user)


def picker_queryset():
    if has_module('cis.highschool_scope'):
        from cis.highschool_scope import picker_queryset as scoped
        return scoped()
    from cis.models.highschool import HighSchool
    return HighSchool.objects.filter(status__iexact='active').order_by('name')


def get_tenant_override(module_name, attr):
    """The tenant's ``attr`` from ``module_name``, or None when unsupported."""
    if not has_module('cis.services.tenant_services'):
        return None
    from cis.services import tenant_services
    lookup = getattr(tenant_services, 'get_tenant_override', None)
    return lookup(module_name, attr) if lookup else None


def install_defaults(setting_model, key, defaults):
    """``Setting.install_defaults``: create the row, or add only missing keys."""
    if hasattr(setting_model, 'install_defaults'):
        return setting_model.install_defaults(key, defaults)
    setting, created = setting_model.objects.get_or_create(
        key=key, defaults={'value': defaults})
    if created:
        return setting
    stored = setting.value if isinstance(setting.value, dict) else {}
    missing = {k: v for k, v in defaults.items() if k not in stored}
    if missing:
        stored.update(missing)
        setting.value = stored
        setting.save()
    return setting


# Portal page text ("blurbs") is moving out of cis into the portal packages
# (package-cis#81, #82). Each role's sources, most preferred first: the
# package's nested editable layout, its installed layout, then cis's copy.
PORTAL_TEXT_SOURCES = {
    'instructor': (
        ('instructor.instructor.settings.instructor_portal', 'instructor_portal'),
        ('instructor.settings.instructor_portal', 'instructor_portal'),
        ('cis.settings.instructor_portal', 'instructor_portal'),
    ),
    'faculty': (
        ('faculty.faculty.settings.faculty_portal_text', 'faculty_portal_text'),
        ('faculty.settings.faculty_portal_text', 'faculty_portal_text'),
        ('cis.settings.faculty_portal', 'faculty_portal'),
    ),
}


def portal_text(role):
    """The stored page text for the ``role`` portal, or {} when nothing owns it."""
    for module, attr in PORTAL_TEXT_SOURCES[role]:
        if has_module(module):
            value = getattr(importlib.import_module(module), attr).from_db()
            return value if isinstance(value, dict) else {}
    return {}
