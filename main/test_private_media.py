import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from django.contrib.auth.models import User, AnonymousUser
from django.http import Http404
from django.test import TestCase, RequestFactory, override_settings

from records.models import DailyRecord, Meal
from .media import private_media


class PrivateMediaSafetyTests(TestCase):
    def setUp(self):
        self.root = Path(tempfile.gettempdir()) / ('private-media-' + uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        config = override_settings(MEDIA_ROOT=self.root)
        config.enable()
        self.addCleanup(config.disable)
        self.user = User.objects.create_user(username='media-owner')
        self.other = User.objects.create_user(username='media-other')
        daily = DailyRecord.objects.create(user=self.user)
        Meal.objects.create(daily_record=daily, meal_type='B', food_name='test', image='meal_images/test.jpg')
        (self.root/'meal_images').mkdir()
        (self.root/'meal_images/test.jpg').write_bytes(b'test-image')

    def request(self, user):
        request = RequestFactory().get('/media/meal_images/test.jpg')
        request.user = user
        return request

    def test_only_owner_receives_file_and_no_public_cache(self):
        response = private_media(self.request(self.user), 'meal_images/test.jpg')
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            self.assertEqual(b''.join(response.streaming_content), b'test-image')
        finally:
            response.close()
        with self.assertRaises(Http404):
            private_media(self.request(self.other), 'meal_images/test.jpg')

    def test_anonymous_is_redirected_and_traversal_is_rejected(self):
        self.assertEqual(private_media(self.request(AnonymousUser()), 'meal_images/test.jpg').status_code, 302)
        daily = DailyRecord.objects.get(user=self.user)
        Meal.objects.create(daily_record=daily, meal_type='B', food_name='bad', image='../outside.jpg')
        with self.assertRaises(Http404):
            private_media(self.request(self.user), '../outside.jpg')
