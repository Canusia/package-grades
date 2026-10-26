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


def has_module(name):
    """True when the dotted module ``name`` is importable."""
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:  # a parent package is missing
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


def scope_to_user_campuses(records, user, campus_path):
    """``records`` narrowed to the campuses a ce ``user`` may process (records
    with no campus stay). Superusers and non-ce roles are unchanged; without a
    campus gate nothing is scoped."""
    if not has_campus_gate() or user is None:
        return records
    from cis.campus_gate import scope_queryset_by_campus
    return scope_queryset_by_campus(records, user, campus_path=campus_path)


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


def _term_hierarchy():
    """cis's term_hierarchy (parent/sub-terms), or None on an older cis."""
    if not has_module('cis.services.term_hierarchy'):
        return None
    from cis.services import term_hierarchy
    if not all(hasattr(term_hierarchy, n) for n in ('apply_term_tree', 'descendant_groups')):
        return None
    return term_hierarchy


def apply_term_tree(field, queryset):
    """Point a term field at ``queryset``, shown as a parent/sub-term tree when
    cis supports it (validation still runs against ``queryset``)."""
    hierarchy = _term_hierarchy()
    if hierarchy:
        hierarchy.apply_term_tree(field, queryset)
    else:
        field.queryset = queryset


def term_groups(term_ids):
    """{term id: {that id + all its sub-term ids}} (just the id on an older cis)."""
    import uuid
    hierarchy = _term_hierarchy()
    if hierarchy:
        return hierarchy.descendant_groups(term_ids)
    groups = {}
    for value in term_ids:
        try:
            pk = uuid.UUID(str(getattr(value, 'pk', value)))
        except (TypeError, ValueError, AttributeError):
            continue
        groups[pk] = {pk}
    return groups


def expand_term_ids(term_ids):
    """``term_ids`` plus every sub-term of each, as a set of UUIDs."""
    return set().union(*term_groups(term_ids).values())


def current_campus_only(queryset, campus_path):
    """``queryset`` narrowed to the current campus on a multi-campus host
    (``campus_path`` leads to Campus); unchanged otherwise or with no campus."""
    if not has_module('cis.campus_context'):
        return queryset
    from cis.campus_context import current_campus_or_none, is_multi_campus
    campus = current_campus_or_none() if is_multi_campus() else None
    return queryset.filter(**{campus_path: campus}) if campus is not None else queryset


def is_ce_user(user):
    """Superuser or a member of the ce group."""
    if user is None:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return 'ce' in user.get_roles()


def _admin_role_highschools(user):
    """High schools where ``user`` holds an Active HS admin role."""
    from cis.models.highschool import HighSchool
    from cis.models.highschool_administrator import HSAdministrator
    hsadmin = HSAdministrator.objects.filter(user=user).first() if user is not None else None
    if hsadmin is None:
        return HighSchool.objects.none()
    return hsadmin.get_highschools()


def _per_campus_highschool_status():
    """True when a school's Active/Inactive status is per campus (cis
    HighSchoolCampus links; HighSchool.status is then only derived)."""
    return has_module('cis.highschool_scope') and is_multi_campus_host()


def is_multi_campus_host():
    if not has_module('cis.campus_context'):
        return False
    from cis.campus_context import is_multi_campus
    return is_multi_campus()


def admin_active_highschools(user):
    """The schools a picker offers ``user`` as an HS admin: an Active role, and
    the school Active at the current campus (per-campus status), or Active
    itself on a single-campus host."""
    schools = _admin_role_highschools(user)
    if _per_campus_highschool_status():
        from cis.highschool_scope import campus_highschools
        return schools.filter(pk__in=campus_highschools().values('pk')).order_by('name')
    return schools.filter(status__iexact='active').order_by('name')


def restrict_to_admin_schools(records, user, highschool_path, campus_path):
    """``records`` at schools where ``user`` holds an Active HS admin role and
    the school is Active: at the record's own campus (``campus_path``) when
    status is per campus, else the school's own status. Needs no current
    campus, so it holds when a report runs later as a task."""
    from django.db.models import F
    records = records.filter(**{f'{highschool_path}__in': _admin_role_highschools(user)})
    if _per_campus_highschool_status():
        return records.filter(**{
            f'{highschool_path}__campus_links__campus': F(campus_path),
            f'{highschool_path}__campus_links__status': 'Active',
        }).distinct()
    return records.filter(**{f'{highschool_path}__status__iexact': 'active'})


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
