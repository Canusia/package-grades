"""Grades sidebar items (cis.menu_registry).

Ids are the legacy menu names (migrations 0003 and 0006 added them). In ce
`classes` they sit after `sections` (10) and before future_sections (20).
On a cis without the registry nothing registers.
"""
try:
    from cis.menu_registry import menu
except ImportError:   # cis without the registry: the menu migrations still apply
    menu = None

if menu is not None:
    menu.register('ce', 'grades_sis_sync', 'Grades', url='grades_ce:sis_sync',
                  parent='classes', order=15)
    menu.register('ce', 'grades_summary', 'Grade Summary', url='grades_ce:summary',
                  parent='classes', order=18)
    # Live-menu label/icon; migration 0006 first seeded "Grades" / graduation-cap.
    menu.register('instructor', 'grades', 'Class Grades', url='instructor:grades',
                  icon='fas fa-fw fa-list-ul', order=35)
    menu.register('student', 'grades', 'My Courses', url='student:grades',
                  icon='fas fa-fw fa-book', order=35)
