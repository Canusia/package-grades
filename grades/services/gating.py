"""Whether grades may be entered for a class section, and by whom.

``can_enter_grades`` has three consumers -- the instructor section list badge, the
grade-entry page render, and the POST that actually writes grades -- so the
condition cannot drift between what the UI shows and what the server enforces.
"""

DEFAULT_NOT_CONFIRMED_MESSAGE = (
    'Grades cannot be entered until the class roster has been confirmed. '
    'Please review and confirm the roster on the class section page, then '
    'return here to enter grades.'
)

# The single roster_status the gate blocks. '' (never asked), 'accurate' and
# 'inaccurate' all pass -- see the design doc: '' is the default state, so
# treating it as unconfirmed would block every section that was never part of a
# verification cycle.
BLOCKED_ROSTER_STATUS = 'pending verification'


def can_enter_grades(section):
    """Return (allowed, message) for a ClassSection.

    `message` is empty when allowed. A falsy section is allowed through -- the
    caller has nothing to gate on, and the view's own ownership check has
    already run.
    """
    if section is None:
        return True, ''

    from ..settings.class_section_grades import class_section_grades

    config = class_section_grades.from_db()

    if not config.get('require_roster_confirmation'):
        return True, ''

    roster_status = (section.roster_status or '').strip().lower()
    if roster_status != BLOCKED_ROSTER_STATUS:
        return True, ''

    message = (
        config.get('roster_not_confirmed_message')
        or DEFAULT_NOT_CONFIRMED_MESSAGE
    )
    return False, message


def _submit_grades_api():
    """``(HSAdministratorPosition, codename)`` when this cis can grant Can
    submit grades per school and campus (cis >= 0.1.15a), else ``None``."""
    try:
        from cis.models.highschool_administrator import (
            HSAdminPerm, HSAdministratorPosition)
    except ImportError:  # cis before per-school HS admin permissions
        return None
    codename = getattr(HSAdminPerm, 'SUBMIT_GRADES', None)
    with_perm = getattr(HSAdministratorPosition.objects.none(), 'with_perm', None)
    if codename is None or with_perm is None or not _takes_campus(with_perm):
        return None
    return HSAdministratorPosition, codename


def _takes_campus(method):
    import inspect
    try:
        return 'campus' in inspect.signature(method).parameters
    except (TypeError, ValueError):
        return False


def submit_grades_supported():
    """Can HS admins be granted Can submit grades on this cis? Without it no
    HS admin enters grades; they see them read-only (#16)."""
    return _submit_grades_api() is not None


def submit_grades_positions(campus=None):
    """Active positions holding Can submit grades (all-campus grants, plus
    ``campus``'s own), or ``None`` when this cis cannot grant it."""
    api = _submit_grades_api()
    if api is None:
        return None
    model, codename = api
    return model.objects.filter(hsadmin__user__is_active=True).with_perm(codename, campus)


def hs_admin_can_submit_grades(user, section):
    """May this HS admin enter and submit grades for ``section``? (#16)

    Every HS admin of a school on the section sees its grades. Entering them
    needs an Active position at one of those schools (the primary, or a
    secondary school per cis#154) holding Can submit grades for the course's
    campus. A secondary-school admin still only saves their own students'
    grades as a draft (views.grade_entry)."""
    if user is None or not getattr(user, 'is_authenticated', False) or section is None:
        return False
    positions = submit_grades_positions(getattr(section.course, 'campus_id', None))
    if positions is None:
        return False
    from ..compat import section_highschool_ids
    return positions.filter(
        hsadmin__user=user, highschool_id__in=list(section_highschool_ids(section)),
    ).exists()


def submit_grade_grants(user):
    """``{(highschool_id, campus_id)}`` for which ``user`` holds Can submit
    grades through an Active position (campus ``None`` = every campus).
    Empty on a cis that cannot grant it."""
    api = _submit_grades_api()
    if api is None or user is None or not getattr(user, 'is_authenticated', False):
        return set()
    model, codename = api
    import cis.models.highschool_administrator as hsa
    grant_model = model._meta.get_field('permission_grants').related_model
    # The same permission content type with_perm() matches on.
    content_type = getattr(hsa, '_grant_ct', dict)()
    return set(grant_model.objects.filter(
        position__hsadmin__user=user, position__hsadmin__user__is_active=True,
        position__status='Active', permission__codename=codename, **content_type,
    ).values_list('position__highschool_id', 'campus_id'))


def submit_grades_admins_lookup():
    """``(highschool_id, campus_id) -> [users]``: active HS admins with a
    valid email whose position at the school holds Can submit grades for the
    campus. ``None`` when this cis cannot grant it. Results are cached for the
    lookup's lifetime (one reminder run, one submission)."""
    if not submit_grades_supported():
        return None
    from django.core.validators import validate_email

    def valid(address):
        try:
            validate_email(address)
        except Exception:
            return False
        return True

    cache = {}

    def lookup(highschool_id, campus_id):
        key = (highschool_id, campus_id)
        if key not in cache:
            users = []
            if highschool_id:
                positions = submit_grades_positions(campus_id).filter(
                    highschool_id=highschool_id).select_related('hsadmin__user')
                for position in positions:
                    person = position.hsadmin.user
                    if valid(person.email) and person not in users:
                        users.append(person)
            cache[key] = users
        return cache[key]
    return lookup


# -- Deprecated (v1.3.0) ------------------------------------------------------
# The High School Admin Grade Access setting (none/view/edit) is gone: every
# HS admin sees grades and Can submit grades decides entry (#16, #17). Kept
# for callers outside this package; they will be removed in a later release.

def hs_admin_grade_access():
    """Deprecated: 'edit' when HS admins can be granted Can submit grades on
    this cis, else 'view'. Per-user entry is hs_admin_can_submit_grades()."""
    return 'edit' if submit_grades_supported() else 'view'


def hs_admin_can_view_grades():
    """Deprecated: every HS admin of a school on the section sees grades."""
    return True


def hs_admin_grade_entry_enabled():
    """Deprecated: whether HS admin entry is possible at all on this cis. Use
    hs_admin_can_submit_grades(user, section)."""
    return submit_grades_supported()
