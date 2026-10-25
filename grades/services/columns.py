"""Student columns on the grade grid, tenant-configurable (spec §3).

The package defines BUILTIN columns and the default selection. A tenant may
choose and extend them by shipping ``services/grades_columns.py`` in its
TENANT_SERVICES_APP with ``columns(builtin, default_keys) -> list[Column]``.
Grading-period columns are always appended by the grid, never listed here.
"""
from dataclasses import dataclass
from typing import Callable

from ..compat import get_tenant_override


@dataclass(frozen=True)
class Column:
    key: str
    header: str
    value: Callable
    sortable: bool = True


def _user(reg):
    return reg.student.user


def _highschool(reg):
    hs = reg.student.highschool if reg.student.highschool_id else reg.highschool
    return str(hs) if hs else ''


BUILTIN = {
    'last_name': Column('last_name', 'Last Name', lambda r: _user(r).last_name),
    'first_name': Column('first_name', 'First Name', lambda r: _user(r).first_name),
    'psid': Column('psid', 'Student ID', lambda r: _user(r).psid or ''),
    'highschool': Column('highschool', 'High School', _highschool),
}
DEFAULT_KEYS = ['last_name', 'first_name', 'psid']


def get_columns():
    tenant = get_tenant_override('grades_columns', 'columns')
    if tenant is not None:
        chosen = tenant(dict(BUILTIN), list(DEFAULT_KEYS))
        if chosen and all(isinstance(c, Column) for c in chosen):
            return list(chosen)
    return [BUILTIN[k] for k in DEFAULT_KEYS]
