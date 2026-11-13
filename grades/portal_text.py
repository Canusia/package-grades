"""Page headings and page text for the portal pages grades adds (#21).

A heading follows the menu item's label when staff renamed it (Settings →
Menu Layout); page text is the ``<menu item>_blurb`` staff saved in the role's
portal settings, then any key the page read before. cis v0.2.10a has the
shared copy (``cis.portal_text.page_heading`` / ``page_blurb``); older cis get
the fallbacks below. Nothing here may raise.

Menu item ids (menu.py): ce ``grades_sis_sync`` / ``grades_summary``,
instructor ``grades``, student ``grades``. grades adds no HS admin or faculty
menu item.
"""
import importlib
import logging

log = logging.getLogger(__name__)

#: Labels an item has had without staff renaming it: the registry label
#: (menu.py) and the label migrations 0003/0006 seeded in the settings-driven
#: menu. A menu converted from that layout keeps the old label as an override.
STOCK_LABELS = {
    ('ce', 'grades_sis_sync'): {'Grades'},
    ('ce', 'grades_summary'): {'Grade Summary'},
    ('instructor', 'grades'): {'Class Grades', 'Grades'},
    ('student', 'grades'): {'My Courses'},
}

#: role → cis setting module/class holding that portal's page text, for the
#: roles whose text cis still owns. instructor / faculty go through
#: compat.portal_text, which reads the owning package first (cis#81, #82).
_CIS_PORTALS = {
    'highschool_admin': 'highschool_admin_portal',
    'student': 'student_portal',
}
_PACKAGE_PORTALS = ('instructor', 'faculty')

_PLACEHOLDER = 'Change me'
_PLACEHOLDER_PREFIX = 'Change this in Settings'


def _cis_helper(name):
    """``cis.portal_text.<name>`` (cis v0.2.10a), or None on an older cis."""
    try:
        return getattr(importlib.import_module('cis.portal_text'), name, None)
    except Exception:
        return None


def _find_item(items, name):
    stack = list(items or ())
    while stack:
        item = stack.pop(0)
        if not isinstance(item, dict):
            continue
        if item.get('name') == name:
            return item
        stack.extend(item.get('sub_menu') or ())
    return None


def _menu_label(role, name):
    """The label ``role``'s menu gives item ``name``, or None (never raises)."""
    try:
        from cis.menu import get_role_menu
    except ImportError:   # cis without get_role_menu, or no cis
        return None
    try:
        item = _find_item(get_role_menu(role, visible_only=False), name)
    except Exception:
        log.exception('grades: could not read the %s menu', role)
        return None
    label = item.get('label') if item else None
    return label.strip() if isinstance(label, str) and label.strip() else None


def page_heading(role, name, default):
    """The renamed label of ``role``'s menu item ``name``, else ``default``."""
    stock = STOCK_LABELS.get((role, name), set())
    cis_heading = _cis_helper('page_heading')
    if cis_heading is not None:
        try:
            heading = cis_heading(role, name, default)
        except Exception:
            log.exception('grades: cis page_heading failed for %s/%s', role, name)
            return default
        return default if heading in stock else heading
    label = _menu_label(role, name)
    if label is None or label in stock:
        return default
    return label


def _stored_text(role):
    if role in _PACKAGE_PORTALS:
        from .compat import portal_text
        return portal_text(role)
    setting = _CIS_PORTALS[role]
    module = importlib.import_module(f'cis.settings.{setting}')
    return getattr(module, setting).from_db()


def page_blurb(role, name, legacy_keys=(), default=''):
    """The page text staff saved for ``role``'s menu item ``name``, else ``default``.

    Tries ``<name>_blurb`` then ``legacy_keys``; blank text and untouched
    placeholders fall through.
    """
    if role not in _CIS_PORTALS and role not in _PACKAGE_PORTALS:
        return default
    cis_blurb = _cis_helper('page_blurb')
    if cis_blurb is not None:
        try:
            return cis_blurb(role, name, legacy_keys=tuple(legacy_keys), default=default)
        except Exception:
            log.exception('grades: cis page_blurb failed for %s/%s', role, name)
            return default
    try:
        stored = _stored_text(role)
    except Exception:
        log.exception('grades: could not read the %s portal text', role)
        return default
    if not isinstance(stored, dict):
        return default
    for key in (f'{name}_blurb',) + tuple(legacy_keys):
        value = stored.get(key)
        if not isinstance(value, str):
            continue
        text = value.strip()
        if text and text != _PLACEHOLDER and not text.startswith(_PLACEHOLDER_PREFIX):
            return value
    return default
