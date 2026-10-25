"""'See Preview' on the Grades settings page (#5): every link names a field
that preview() handles, and the class-section previews render the configured
message through the packaged template."""
import re
import uuid

from django.contrib.auth import get_user_model
from django.contrib.messages.storage.cookie import CookieStorage
from django.http import HttpRequest
from django.test import RequestFactory
from .base import GradesTestCase as TestCase

from cis.models.settings import Setting
from cis.models.term import AcademicYear, Term

from ..settings.class_section_grades import class_section_grades
from .test_settings_gaps import legacy_value

User = get_user_model()
LINK = re.compile(r"do_bulk_action\(\\?'class_section_grades\\?', \\?'(\w+)\\?'\)")


class SettingsPreviewTests(TestCase):
    def setUp(self):
        ay = AcademicYear.objects.create(name=f'AY-{uuid.uuid4().hex[:6]}')
        term = Term.objects.create(academic_year=ay, code=uuid.uuid4().hex[:6], label='Fall')
        Setting.objects.update_or_create(
            key=class_section_grades.key,
            defaults={'value': {**legacy_value(term.id),
                                'grades_open_class_section': 'HOW-TO-MARKER',
                                'grades_submitted_class_section': 'SUBMITTED-MARKER'}})
        self.user = User.objects.create_superuser(
            username=f'su_{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')

    def _preview(self, field_name):
        request = RequestFactory().get('/x')
        request.user = self.user
        request.session = {}
        request._messages = CookieStorage(request)
        return class_section_grades(HttpRequest()).preview(request, field_name)

    def _links(self):
        form = class_section_grades(HttpRequest())
        return {name for field in form.fields.values()
                for name in LINK.findall(str(field.help_text or ''))}

    def test_class_section_previews_render_the_message(self):
        for field_name, marker in (('grades_open_class_section', 'HOW-TO-MARKER'),
                                   ('grades_submitted_class_section', 'SUBMITTED-MARKER')):
            response = self._preview(field_name)
            self.assertEqual(response.status_code, 200, field_name)
            self.assertIn(marker, response.content.decode(), field_name)

    def test_old_submitted_link_name_still_previews(self):
        response = self._preview('grades_submitted')
        self.assertEqual(response.status_code, 200)
        self.assertIn('SUBMITTED-MARKER', response.content.decode())

    def test_every_preview_link_is_handled(self):
        links = self._links()
        self.assertIn('grades_submitted_class_section', links)
        self.assertNotIn('grades_submitted', links)
        for name in links:
            self.assertIsNotNone(self._preview(name), name)
