"""CE Grade Scales pages, the period form's scale field, and in-use guards."""
from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.urls import reverse

from ..forms.grading_period import GradingPeriodForm
from ..models import GradeScale, GradeScaleEntry, PeriodGrade
from ..services import scales
from . import factories as f
from .base import GradesTestCase
from .test_grade_scales import make_scale

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None


def entries_post(rows, prefix='entries', initial=0):
    """POST data for the letters formset. rows: dicts with grade/points/flag/id/delete."""
    data = {f'{prefix}-TOTAL_FORMS': str(len(rows)), f'{prefix}-INITIAL_FORMS': str(initial),
            f'{prefix}-MIN_NUM_FORMS': '0', f'{prefix}-MAX_NUM_FORMS': '1000'}
    for i, row in enumerate(rows):
        data[f'{prefix}-{i}-grade'] = row.get('grade', '')
        data[f'{prefix}-{i}-points'] = row.get('points', '')
        data[f'{prefix}-{i}-sequence'] = str(i)
        if row.get('flag'):
            data[f'{prefix}-{i}-asks_last_attendance'] = 'on'
        if row.get('id'):
            data[f'{prefix}-{i}-id'] = str(row['id'])
        if row.get('delete'):
            data[f'{prefix}-{i}-DELETE'] = 'on'
    return data


class _CEBase(GradesTestCase):
    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    @classmethod
    def setUpTestData(cls):
        get_user_model().objects.get_or_create(username='cron', defaults={'email': 'cron@example.com'})
        f.grades_setting(grades='A,B,C,F')
        cls.ce = get_user_model().objects.create_user(
            username='cescale@example.com', email='cescale@example.com', password='x', is_staff=True)
        cls.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        if getattr(cls, 'campus', None) is not None:
            from cis.signals.staff_campus import add_process_campuses
            add_process_campuses(cls.ce, [cls.campus])

    def setUp(self):
        self.client.force_login(self.ce)
        self.campus = scales.current_campus()


class ScaleListTests(_CEBase):
    def test_list_creates_the_default_from_the_setting(self):
        resp = self.client.get(reverse('grades_ce:grade_scales'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Standard')
        self.assertContains(resp, 'A, B, C, F')
        self.assertTrue(GradeScale.objects.filter(is_default=True).exists())

    def test_non_ce_user_is_refused(self):
        self.client.logout()
        resp = self.client.get(reverse('grades_ce:grade_scales'))
        self.assertEqual(resp.status_code, 302)


class ScaleEditTests(_CEBase):
    def test_add_a_scale_with_a_flagged_letter(self):
        data = {'name': 'Final letters', 'description': '', 'is_active': 'on',
                **entries_post([{'grade': 'A', 'points': '4'}, {'grade': 'F', 'points': '0', 'flag': True},
                                {'grade': ''}])}   # an added row left blank is ignored
        resp = self.client.post(reverse('grades_ce:add_grade_scale'), data, follow=True)
        self.assertContains(resp, 'Saved grade scale "Final letters".')
        scale = GradeScale.objects.get(name='Final letters')
        self.assertEqual(scales.Scale(name='x', entries=tuple(
            scales.ScaleEntry(e.grade, e.points, e.asks_last_attendance)
            for e in scale.entries.order_by('sequence'))).letters(), ['A', 'F'])
        self.assertEqual(list(scale.entries.filter(asks_last_attendance=True)
                              .values_list('grade', flat=True)), ['F'])
        self.assertFalse(scale.is_default)

    def test_making_a_scale_default_replaces_the_old_default(self):
        old = make_scale('Old', ['A'], campus=self.campus, is_default=True)
        data = {'name': 'New', 'is_active': 'on', 'is_default': 'on',
                **entries_post([{'grade': 'P'}])}
        self.client.post(reverse('grades_ce:add_grade_scale'), data)
        old.refresh_from_db()
        self.assertFalse(old.is_default)
        self.assertTrue(GradeScale.objects.get(name='New').is_default)

    def test_default_cannot_be_unset_directly(self):
        std = make_scale('Std', ['A'], campus=self.campus, is_default=True)
        entry = std.entries.get()
        data = {'name': 'Std', 'is_active': 'on',
                **entries_post([{'grade': 'A', 'id': entry.id}], initial=1)}
        resp = self.client.post(reverse('grades_ce:edit_grade_scale', args=[std.id]), data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Make another scale the default')

    def _scale_with_marks(self):
        std = make_scale('Std', ['A', 'B', 'F'], campus=self.campus, is_default=True)
        term = f.term()
        mid = f.period(term, 'Mid', date(2020, 1, 1), date(2020, 2, 1))
        reg = f.registration(f.section(term))
        PeriodGrade.objects.create(period=mid, registration=reg, grade='B')
        return std

    def test_removing_a_letter_in_use_is_refused(self):
        std = self._scale_with_marks()
        rows = [{'grade': e.grade, 'id': e.id, 'delete': e.grade == 'B'}
                for e in std.entries.order_by('sequence')]
        data = {'name': 'Std', 'is_active': 'on', 'is_default': 'on',
                **entries_post(rows, initial=3)}
        resp = self.client.post(reverse('grades_ce:edit_grade_scale', args=[std.id]), data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'cannot be removed or renamed: B (1)')
        self.assertTrue(std.entries.filter(grade='B').exists())

    def test_flag_and_new_letters_are_allowed_while_in_use(self):
        std = self._scale_with_marks()
        rows = [{'grade': e.grade, 'id': e.id, 'flag': e.grade == 'F'}
                for e in std.entries.order_by('sequence')] + [{'grade': 'W'}]
        data = {'name': 'Std', 'is_active': 'on', 'is_default': 'on',
                **entries_post(rows, initial=3)}
        resp = self.client.post(reverse('grades_ce:edit_grade_scale', args=[std.id]), data)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(std.entries.get(grade='F').asks_last_attendance)
        self.assertTrue(std.entries.filter(grade='W').exists())

    def test_duplicate_letters_are_refused(self):
        data = {'name': 'Dup', 'is_active': 'on',
                **entries_post([{'grade': 'A'}, {'grade': 'A'}])}
        resp = self.client.post(reverse('grades_ce:add_grade_scale'), data)
        self.assertContains(resp, 'Each grade can appear once: A.')


class ScaleDuplicateDeleteTests(_CEBase):
    def test_duplicate_copies_letters_and_flags(self):
        std = make_scale('Std', ['A', 'F'], campus=self.campus, is_default=True,
                         last_attendance=['F'])
        resp = self.client.post(reverse('grades_ce:duplicate_grade_scale', args=[std.id]))
        copy = GradeScale.objects.get(name='Copy of Std')
        self.assertRedirects(resp, reverse('grades_ce:edit_grade_scale', args=[copy.id]),
                             fetch_redirect_response=False)
        self.assertFalse(copy.is_default)
        self.assertEqual(list(copy.entries.filter(asks_last_attendance=True)
                              .values_list('grade', flat=True)), ['F'])

    def test_delete_refused_for_default_and_used_scales(self):
        std = make_scale('Std', ['A'], campus=self.campus, is_default=True)
        used = make_scale('Used', ['A'], campus=self.campus)
        f.period(f.term(), 'Final', date(2020, 1, 1), date(2020, 2, 1), grade_scale=used)
        spare = make_scale('Spare', ['A'], campus=self.campus)
        for record in (std, used):
            self.client.post(reverse('grades_ce:delete_grade_scale', args=[record.id]))
            self.assertTrue(GradeScale.objects.filter(pk=record.pk).exists())
        self.client.post(reverse('grades_ce:delete_grade_scale', args=[spare.id]))
        self.assertFalse(GradeScale.objects.filter(pk=spare.pk).exists())


class PeriodScaleFieldTests(_CEBase):
    def _form(self, term, instance=None, **data):
        base = {'name': 'Mid', 'sequence': 1, 'opens_on': '2020-01-01', 'due_on': '2020-02-01',
                'reminder_frequency_days': 0, 'remind_days_before_due': 0}
        base.update(data)
        return GradingPeriodForm(term=term, instance=instance, data=base)

    def test_choices_are_active_scales_with_a_named_default(self):
        make_scale('Std', ['A'], campus=self.campus, is_default=True)
        mid = make_scale('Mid S/U', ['S', 'U'], campus=self.campus)
        inactive = make_scale('Old', ['X'], campus=self.campus)
        inactive.is_active = False
        inactive.save()
        form = GradingPeriodForm(term=f.term())
        field = form.fields['grade_scale']
        self.assertEqual(field.empty_label, 'Default (Std)')
        self.assertIn(mid, field.queryset)
        self.assertNotIn(inactive, field.queryset)

    def test_scale_saved_on_the_period(self):
        mid = make_scale('Mid S/U', ['S', 'U'], campus=self.campus)
        form = self._form(f.term(), grade_scale=str(mid.id))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().grade_scale, mid)

    def test_switching_scale_refused_when_marks_would_be_stranded(self):
        make_scale('Std', ['A', 'B'], campus=self.campus, is_default=True)
        su = make_scale('S/U', ['S', 'U'], campus=self.campus)
        ab = make_scale('AB+', ['A', 'B', 'P'], campus=self.campus)
        term = f.term()
        period = f.period(term, 'Mid', date(2020, 1, 1), date(2020, 2, 1))
        PeriodGrade.objects.create(period=period, registration=f.registration(f.section(term)),
                                   grade='B')
        form = self._form(term, instance=period, grade_scale=str(su.id))
        self.assertFalse(form.is_valid())
        self.assertIn('not on that scale: B (1)', str(form.errors['grade_scale']))
        form = self._form(term, instance=period, grade_scale=str(ab.id))
        self.assertTrue(form.is_valid(), form.errors)


class GradeEntryUsesPeriodScaleTests(GradesTestCase):
    def test_picker_offers_the_periods_scale_and_keeps_an_off_scale_mark(self):
        from ..forms.section import ClassSectionGradeForm
        f.grades_setting(grades='A,B')
        su = make_scale('S/U', ['S', 'U'], campus=scales.current_campus())
        period = f.period(f.term(), 'Mid', date(2020, 1, 1), date(2020, 2, 1), grade_scale=su)
        form = ClassSectionGradeForm(scale=period.scale(), initial={'grade': 'B'})
        self.assertEqual([c[0] for c in form.fields['grade'].choices], ['', 'S', 'U', 'B'])


class SettingsPageTests(GradesTestCase):
    def test_settings_page_links_to_grade_scales_instead_of_the_editor(self):
        from django.test import RequestFactory
        from ..settings.class_section_grades import class_section_grades
        f.grades_setting()
        form = class_section_grades(RequestFactory().get('/'))
        layout = list(form.helper.layout)
        html = ''.join(getattr(item, 'html', '') for item in layout)
        self.assertIn(reverse('grades_ce:grade_scales'), html)
        # Not rendered, so not posted: saving the settings keeps the saved scale.
        self.assertNotIn('grade_scale', [i for i in layout if isinstance(i, str)])


class ReviewFixPageTests(_CEBase):
    def test_scale_name_is_escaped_in_messages(self):
        data = {'name': '<img src=x onerror=alert(1)>', 'is_active': 'on',
                **entries_post([{'grade': 'A'}])}
        resp = self.client.post(reverse('grades_ce:add_grade_scale'), data, follow=True)
        self.assertNotContains(resp, '<img src=x onerror=alert(1)>')
        self.assertContains(resp, '&lt;img src=x onerror=alert(1)&gt;')

    def test_grade_longer_than_a_final_grade_holds_is_refused(self):
        data = {'name': 'Long', 'is_active': 'on', **entries_post([{'grade': 'In Progress'}])}
        resp = self.client.post(reverse('grades_ce:add_grade_scale'), data)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(GradeScale.objects.filter(name='Long').exists())

    def test_points_without_a_grade_are_an_error_not_dropped(self):
        data = {'name': 'Pts', 'is_active': 'on',
                **entries_post([{'grade': 'A'}, {'grade': '', 'points': '3'}])}
        resp = self.client.post(reverse('grades_ce:add_grade_scale'), data)
        self.assertContains(resp, 'Enter a grade, or clear the points')

    def test_default_swap_refused_when_it_would_strand_marks(self):
        old = make_scale('Std', ['A', 'B'], campus=self.campus, is_default=True)
        term = f.term()
        mid = f.period(term, 'Mid', date(2020, 1, 1), date(2020, 2, 1))
        PeriodGrade.objects.create(period=mid, registration=f.registration(f.section(term)),
                                   grade='B')
        data = {'name': 'PNP', 'is_active': 'on', 'is_default': 'on',
                **entries_post([{'grade': 'P'}, {'grade': 'NP'}])}
        resp = self.client.post(reverse('grades_ce:add_grade_scale'), data)
        self.assertContains(resp, 'already have grades this scale does not offer: B (1)')
        old.refresh_from_db()
        self.assertTrue(old.is_default)
        # With the letter added, the swap goes through and keeps a history row.
        data = {'name': 'PNP', 'is_active': 'on', 'is_default': 'on',
                **entries_post([{'grade': 'P'}, {'grade': 'B'}])}
        self.client.post(reverse('grades_ce:add_grade_scale'), data)
        old.refresh_from_db()
        self.assertFalse(old.is_default)
        self.assertEqual(old.history.first().is_default, False)

    def test_campus_staff_cannot_change_the_shared_scale_on_multi_campus(self):
        if self.campus is None:
            self.skipTest('single-campus host')
        shared = make_scale('Shared', ['A'])
        resp = self.client.post(reverse('grades_ce:delete_grade_scale', args=[shared.id]))
        self.assertEqual(resp.status_code, 403)
        resp = self.client.post(reverse('grades_ce:duplicate_grade_scale', args=[shared.id]))
        self.assertEqual(GradeScale.objects.get(name='Copy of Shared').campus, self.campus)
