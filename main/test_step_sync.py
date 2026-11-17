from datetime import date, timedelta, time
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from main.google_activity import GoogleHealthError, civil_midnight, google_health_steps_range
from records.models import DailyRecord, Exercise, GoogleHealthStepRecord
from users.models import current_weight_day


class StepRangeParsingTests(SimpleTestCase):
    def point(self, day, count):
        return {'civilStartTime': civil_midnight(day), 'civilEndTime': civil_midnight(day + timedelta(days=1)),
                'steps': {'countSum': count}}

    def fetch(self, points):
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {'rollupDataPoints': points}
        with patch('main.google_activity.AuthorizedSession', return_value=session):
            result = google_health_steps_range(Mock(), date(2026, 10, 30), date(2026, 11, 3))
        session.close.assert_called_once()
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(session.post.call_args.kwargs['json']['windowSizeDays'], 1)
        return result

    def test_range_crosses_month_and_distinguishes_zero_and_missing(self):
        first, last = date(2026, 10, 30), date(2026, 11, 3)
        self.assertEqual(self.fetch([self.point(first, '4000'), self.point(last, '0')]), {first: 4000, last: 0})
        self.assertEqual(self.fetch([]), {})

    def test_invalid_or_duplicate_days_and_negative_counts_are_rejected(self):
        point = self.point(date(2026, 11, 3), '20')
        for points in ([point, point], [self.point(date(2026, 11, 4), '20')],
                       [self.point(date(2026, 11, 3), '-1')], [self.point(date(2026, 11, 3), 20)]):
            with self.subTest(points=points), self.assertRaises(GoogleHealthError):
                self.fetch(points)


@override_settings(GOOGLE_ACTIVITY_PROVIDER='google_health', ALLOWED_HOSTS=['testserver'])
class StepSyncTests(TestCase):
    def setUp(self):
        cache.clear()
        self.today = date(2026, 11, 17)
        self.user = User.objects.create_user('steps-owner')
        self.other = User.objects.create_user('steps-other')
        self.client.force_login(self.user)

    def sync(self, values=None, error=None):
        credentials = Mock(valid=True)
        credentials.has_scopes.return_value = True
        with patch('main.views.Credentials.from_authorized_user_file', return_value=credentials), \
             patch('main.views.current_weight_day', return_value=self.today), \
             patch('main.views.google_health_steps_range', return_value=values or {}, side_effect=error) as fetch:
            response = self.client.post(reverse('sync_health_steps'), {'user': self.other.pk, 'date': '2099-01-01'})
        return response, fetch

    def test_save_update_and_preserve_manual_exercise(self):
        daily = DailyRecord.objects.create(user=self.user, date=self.today)
        exercise = Exercise.objects.create(daily_record=daily, exercise_name='걷기', start_time=time(10),
                                          end_time=time(10, 30), steps=1500, calories_burned=70)
        response, fetch = self.sync({self.today: 4000})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(fetch.call_args.args[1:], (date(2026, 11, 15), self.today))
        cache.clear()
        self.sync({self.today: 5000})
        self.assertEqual(GoogleHealthStepRecord.objects.count(), 1)
        self.assertEqual(GoogleHealthStepRecord.objects.get().steps, 5000)
        exercise.refresh_from_db()
        self.assertEqual((exercise.steps, exercise.calories_burned), (1500, 70))
        self.assertEqual(Exercise.objects.count(), 1)

    def test_no_data_and_failure_keep_previous_steps(self):
        GoogleHealthStepRecord.objects.create(user=self.user, date=self.today, steps=4000)
        for error in (None, GoogleHealthError('NETWORK_ERROR', '연결 실패')):
            cache.clear()
            self.sync(error=error)
            self.assertEqual(GoogleHealthStepRecord.objects.get().steps, 4000)

    def test_saved_steps_do_not_create_meal_or_exercise_days(self):
        self.sync({self.today: 0})
        self.assertEqual(GoogleHealthStepRecord.objects.get().steps, 0)
        self.assertFalse(DailyRecord.objects.exists())

    def test_other_user_record_is_not_modified(self):
        other = GoogleHealthStepRecord.objects.create(user=self.other, date=self.today, steps=9999)
        self.sync({self.today: 3500})
        other.refresh_from_db()
        self.assertEqual(other.steps, 9999)
        self.assertEqual(GoogleHealthStepRecord.objects.get(user=self.user).steps, 3500)

    def test_repeat_click_is_limited_without_second_api_call(self):
        self.sync({self.today: 100})
        _, fetch = self.sync({self.today: 200})
        fetch.assert_not_called()
        self.assertEqual(GoogleHealthStepRecord.objects.get().steps, 100)

    def test_login_post_and_csrf_required(self):
        self.assertEqual(self.client.get(reverse('sync_health_steps')).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(reverse('sync_health_steps')).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(reverse('sync_health_steps')).status_code, 403)

    def test_missing_credentials_does_not_save_or_call_health(self):
        with patch('main.views.Credentials.from_authorized_user_file', side_effect=FileNotFoundError), \
             patch('main.views.google_health_steps_range') as fetch:
            self.client.post(reverse('sync_health_steps'))
        fetch.assert_not_called()
        self.assertFalse(GoogleHealthStepRecord.objects.exists())

    def test_duplicate_day_constraint(self):
        GoogleHealthStepRecord.objects.create(user=self.user, date=self.today, steps=10)
        with self.assertRaises(IntegrityError), transaction.atomic():
            GoogleHealthStepRecord.objects.create(user=self.user, date=self.today, steps=20)

    def test_home_and_calendar_display_only_own_saved_steps(self):
        today = current_weight_day()
        GoogleHealthStepRecord.objects.create(user=self.user, date=today, steps=4321)
        GoogleHealthStepRecord.objects.create(user=self.other, date=today, steps=9876)
        with patch('main.views.os.path.exists', return_value=False), \
             patch('records.views.calendar_credentials', return_value=None), \
             patch('main.views.google_health_daily_steps') as daily_fetch, \
             patch('records.views.build') as calendar_fetch:
            home = self.client.get(reverse('home'))
            calendar = self.client.get(reverse('exercise_calendar'), {'year': today.year, 'month': today.month})
        for response in (home, calendar):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, '4321보')
            self.assertNotContains(response, '9876보')
        self.assertContains(home, '걸음 수 연동하기')
        daily_fetch.assert_not_called()
        calendar_fetch.assert_not_called()
