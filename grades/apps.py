from django.apps import AppConfig


_CONFIGURATORS_BASE = [
    {
        'name': 'class_section_grades',
        'title': 'Class Grades Settings',
        'description': 'Configure grade scale and GPA points, grade submission window dates, reminder notifications, email templates for grades due and submitted confirmations, and unofficial transcript templates.',
        'categories': [
            '3'
        ]
    },
]


_REPORTS_BASE = [
    {
        'name': 'grade_by_highschool',
        'title': 'Grade Distribution by High School',
        'description': 'Analyze grade distribution, success rates, and DFW rates by high school',
        'categories': [
            'High School'
        ],
        'available_for': [
            'ce'
        ]
    },
    {
        'name': 'grade_by_course',
        'title': 'Grade Distribution by Course',
        'description': 'Analyze grade distribution, success rates, and DFW rates by course',
        'categories': [
            'Classes'
        ],
        'available_for': [
            'ce'
        ]
    },
    {
        'name': 'grade_by_demographics',
        'title': 'Grade Distribution by Demographics',
        'description': 'Analyze grade distribution by gender, ethnicity, first-gen status, grade level, or parent education',
        'categories': [
            'Students'
        ],
        'available_for': [
            'ce'
        ]
    },
]


class GradesConfig(AppConfig):
    """Production config — package installed 1-deep via pip (``grades``)."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'grades'
    verbose_name = 'Grades'

    CONFIGURATORS = [
        {**entry, 'app': 'grades'}
        for entry in _CONFIGURATORS_BASE
    ]

    REPORTS = [
        {**entry, 'app': 'grades'}
        for entry in _REPORTS_BASE
    ]

    def ready(self):
        """Import signals and tab registrations when the app is ready."""
        from . import signals  # noqa: F401
        from . import tabs  # noqa: F401


class DevGradesConfig(AppConfig):
    """Dev config — editable submodule, 2-deep (``grades.grades``)."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'grades.grades'
    verbose_name = 'Dev - Grades'

    CONFIGURATORS = [
        {**entry, 'app': 'grades.grades'}
        for entry in _CONFIGURATORS_BASE
    ]

    REPORTS = [
        {**entry, 'app': 'grades.grades'}
        for entry in _REPORTS_BASE
    ]

    def ready(self):
        """Import signals and tab registrations when the app is ready."""
        from . import signals  # noqa: F401
        from . import tabs  # noqa: F401
