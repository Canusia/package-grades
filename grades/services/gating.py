"""Whether grades may be entered for a class section.

One function, three consumers -- the instructor section list badge, the
grade-entry page render, and the POST that actually writes grades -- so the
condition cannot drift between what the UI shows and what the server enforces.
"""

DEFAULT_NOT_CONFIRMED_MESSAGE = (
    'Grades cannot be entered until the class roster has been confirmed. '
    'Please review and confirm the roster on your class section page, then '
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
