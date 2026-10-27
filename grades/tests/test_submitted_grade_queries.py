"""#12: submitted_grade() must not query per registration inside a request.

cis calls it for every row of the CE Registrations and Drop/WD request tables.
Inside a request the final period (per term) and its statuses (per period) are
looked up once; outside a request each call reads the database as before.
"""
from django.core.signals import request_finished, request_started
from django.db import close_old_connections, connection
from django.test.utils import CaptureQueriesContext

from cis.models.section import StudentRegistration

from .base import GradesTestCase
from . import factories as f
from ..services.periods import set_status
from ..services.window import submitted_grade


def _send(signal):
    """Send a request signal the way the test client does: without
    close_old_connections, which would close the test's connection."""
    signal.disconnect(close_old_connections)
    try:
        signal.send(sender=SubmittedGradeQueryTests)
    finally:
        signal.connect(close_old_connections)


class SubmittedGradeQueryTests(GradesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.term = f.term()
        cls.bare_term = f.term()  # no grading periods: grade_status decides
        cls.final = f.period(cls.term, 'Final', f.D(2026, 1, 1), f.D(2026, 12, 31),
                             is_final=True)
        teacher = f.teacher()  # the submitted email goes to the instructor
        cls.sections = [f.section(cls.term, teacher) for _ in range(4)]
        cls.bare_sections = [f.section(cls.bare_term, teacher) for _ in range(2)]
        for section in cls.sections + cls.bare_sections:
            for _ in range(2):
                f.registration(section, grade='A')
        set_status(cls.sections[0], cls.final, 'submitted')
        set_status(cls.sections[1], cls.final, 'saved')
        cls.bare_sections[0].grade_status = 'submitted'
        cls.bare_sections[0].save()

    def setUp(self):
        _send(request_started)
        self.addCleanup(_send, request_finished)

    def _registrations(self, sections):
        return list(StudentRegistration.objects.select_related('class_section')
                    .filter(class_section__in=sections).order_by('id'))

    def _grades(self, registrations):
        with CaptureQueriesContext(connection) as ctx:
            grades = {r.id: submitted_grade(r) for r in registrations}
        return grades, len(ctx.captured_queries)

    def test_queries_do_not_grow_with_rows(self):
        few, few_queries = self._grades(self._registrations(self.sections[:2]))
        _send(request_finished)
        _send(request_started)
        many, many_queries = self._grades(
            self._registrations(self.sections + self.bare_sections))
        self.assertEqual(many_queries - few_queries, 1)  # the second term only
        self.assertLessEqual(many_queries, 3)

    def test_grades_shown_only_once_final_is_submitted(self):
        grades, _ = self._grades(self._registrations(self.sections + self.bare_sections))
        by_section = {}
        for r in self._registrations(self.sections + self.bare_sections):
            by_section.setdefault(r.class_section_id, set()).add(grades[r.id])
        self.assertEqual(by_section[self.sections[0].id], {'A'})
        self.assertEqual(by_section[self.sections[1].id], {'-'})
        self.assertEqual(by_section[self.sections[2].id], {'-'})
        self.assertEqual(by_section[self.bare_sections[0].id], {'A'})  # 0.0.x fallback
        self.assertEqual(by_section[self.bare_sections[1].id], {'-'})

    def test_status_written_mid_request_is_seen(self):
        registration = self._registrations([self.sections[2]])[0]
        self.assertEqual(submitted_grade(registration), '-')
        set_status(self.sections[2], self.final, 'submitted')
        self.assertEqual(submitted_grade(registration), 'A')

    def test_grading_period_saved_mid_request_is_seen(self):
        from ..models import GradingPeriod, SectionPeriodStatus
        registration = self._registrations([self.bare_sections[0]])[0]
        self.assertEqual(submitted_grade(registration), 'A')  # no final: grade_status
        # Written without signals, then one period save: that save alone must
        # make the next lookup see the new final period and its 'saved' row.
        final = GradingPeriod(term=self.bare_term, name='Final', sequence=1,
                              opens_on=f.D(2026, 1, 1), due_on=f.D(2026, 12, 31),
                              is_final=True)
        GradingPeriod.objects.bulk_create([final])
        SectionPeriodStatus.objects.bulk_create([SectionPeriodStatus(
            period=final, class_section=self.bare_sections[0], status='saved')])
        self.assertEqual(submitted_grade(registration), 'A')  # memo still holds
        final.save()
        self.assertEqual(submitted_grade(registration), '-')

    def test_outside_a_request_each_call_reads_the_database(self):
        _send(request_finished)
        registration = self._registrations([self.sections[3]])[0]
        self.assertEqual(submitted_grade(registration), '-')
        # Written behind the services' back: only a fresh read would see it.
        from ..models import SectionPeriodStatus
        SectionPeriodStatus.objects.bulk_create([SectionPeriodStatus(
            period=self.final, class_section=self.sections[3], status='submitted')])
        self.assertEqual(submitted_grade(registration), 'A')

    def test_cached_final_status_memoises_outside_a_request(self):
        from ..services import cached_final_status
        _send(request_finished)
        registrations = self._registrations(self.sections)
        with cached_final_status():
            _, queries = self._grades(registrations)
        self.assertEqual(queries, 2)  # the term's final period + its statuses

    def test_final_period_deleted_mid_request_is_seen(self):
        registration = self._registrations([self.sections[1]])[0]
        self.assertEqual(submitted_grade(registration), '-')  # final period: 'saved'
        self.sections[1].grade_status = 'submitted'
        self.sections[1].save()
        registration = self._registrations([self.sections[1]])[0]
        self.final.delete()
        self.assertEqual(submitted_grade(registration), 'A')  # back to grade_status

    def test_save_inside_cached_final_status_reaches_the_request(self):
        from ..services import cached_final_status
        registration = self._registrations([self.sections[2]])[0]
        self.assertEqual(submitted_grade(registration), '-')
        with cached_final_status():
            set_status(self.sections[2], self.final, 'submitted')
        self.assertEqual(submitted_grade(registration), 'A')
