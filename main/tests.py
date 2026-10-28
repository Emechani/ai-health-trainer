from unittest.mock import patch, Mock
from datetime import datetime, timedelta
from django.utils import timezone

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from users.models import UserProfile
from records.models import DailyRecord, Meal, Exercise


@override_settings(GOOGLE_ACTIVITY_PROVIDER='google_fit')
class HomeWeightProgressTests(TestCase):
    def fitness_home(self, segment_error=False):
        calendar_service, fitness_service = Mock(), Mock()
        calendar_service.events.return_value.list.return_value.execute.return_value = {'items': []}
        start = timezone.localtime().replace(hour=10, minute=0, second=0, microsecond=0)
        bucket = {'startTimeMillis': str(int(start.timestamp()*1000)), 'endTimeMillis': str(int((start+timedelta(minutes=30)).timestamp()*1000)),
                  'dataset': [{'point': [{'value': [{'intVal': 1500}]}]}]}
        aggregate = fitness_service.users.return_value.dataset.return_value.aggregate.return_value.execute
        aggregate.side_effect = [{'bucket': [bucket]}, RuntimeError('mock-segment-failure') if segment_error else {'bucket': [bucket]}]
        with patch('main.views.os.path.exists', return_value=True), patch('main.views.Credentials.from_authorized_user_file', return_value=Mock(valid=True)), patch('main.views.build', side_effect=[calendar_service, fitness_service]):
            return self.client.get(reverse('home'))

    def test_fitness_sync_preserves_manual_steps(self):
        daily = DailyRecord.objects.create(user=self.user, date=timezone.localdate())
        manual = Exercise.objects.create(daily_record=daily, exercise_name='걷기', start_time='09:00', end_time='09:30', steps=2000)
        self.assertEqual(self.fitness_home().status_code, 200)
        self.assertTrue(Exercise.objects.filter(pk=manual.pk, steps=2000).exists())

    def test_fitness_fetch_failure_does_not_delete_existing_records(self):
        daily = DailyRecord.objects.create(user=self.user, date=timezone.localdate())
        manual = Exercise.objects.create(daily_record=daily, exercise_name='걷기', steps=2000)
        self.assertEqual(self.fitness_home(segment_error=True).status_code, 200)
        self.assertTrue(Exercise.objects.filter(pk=manual.pk).exists())

    def test_fitness_repeated_sync_updates_only_identified_imports(self):
        from main.views import sync_google_walks
        day = timezone.localdate()
        start = timezone.localtime().replace(hour=10, minute=0, second=0, microsecond=0)
        bucket = {'startTimeMillis': int(start.timestamp()*1000), 'endTimeMillis': int((start+timedelta(minutes=30)).timestamp()*1000),
                  'dataset': [{'point': [{'value': [{'intVal': 1200}]}]}]}
        sync_google_walks(self.user, day, [bucket])
        imported = Exercise.objects.get(exercise_name=Exercise.GOOGLE_FIT_NAME)
        bucket['dataset'][0]['point'][0]['value'][0]['intVal'] = 1600
        sync_google_walks(self.user, day, [bucket])
        imported.refresh_from_db()
        self.assertEqual(imported.steps, 1600)
        self.assertEqual(Exercise.objects.count(), 1)
        with self.assertRaises(ValueError):
            sync_google_walks(self.user, day, [bucket, {'dataset': [{'point': [{'value': [{'intVal': -1}]}]}]}])
        self.assertEqual(Exercise.objects.get(pk=imported.pk).steps, 1600)

    def test_manual_edit_of_import_becomes_manual_record(self):
        from records.forms import ExerciseForm
        daily = DailyRecord.objects.create(user=self.user, date=timezone.localdate())
        imported = Exercise.objects.create(daily_record=daily, exercise_name=Exercise.GOOGLE_FIT_NAME, start_time='10:00', end_time='10:30', steps=1500)
        self.assertEqual(ExerciseForm(instance=imported).initial['exercise_name'], '걷기')
        form = ExerciseForm({'exercise_name': '걷기', 'start_time': '10:00', 'end_time': '10:30', 'steps': '1600'}, instance=imported)
        self.assertTrue(form.is_valid())
        form.save()
        self.assertEqual(Exercise.objects.get(pk=imported.pk).exercise_name, '걷기')
        self.assertFalse(ExerciseForm({'exercise_name': Exercise.GOOGLE_FIT_NAME, 'start_time': '10:00', 'end_time': '10:30'}).is_valid())

    def test_today_reminders_use_only_own_records_and_disappear_after_registration(self):
        from users.models import current_weight_day
        day = current_weight_day()
        other = User.objects.create_user(username='reminder-other')
        other_daily = DailyRecord.objects.create(user=other, date=day)
        Meal.objects.create(daily_record=other_daily, meal_type='L', food_name='다른 사용자 식사')
        Exercise.objects.create(daily_record=other_daily, exercise_name='다른 사용자 운동')
        response = self.home()
        self.assertTrue(response.context['needs_exercise_record'])
        self.assertTrue(response.context['needs_meal_record'])
        self.assertContains(response, '식단을 등록하세요!')
        daily = DailyRecord.objects.create(user=self.user, date=day)
        Meal.objects.create(daily_record=daily, meal_type='L', food_name='본인 식사')
        self.assertFalse(self.home().context['needs_meal_record'])
        self.assertTrue(self.home().context['needs_exercise_record'])
        Exercise.objects.create(daily_record=daily, exercise_name='걷기')
        response = self.home()
        self.assertFalse(response.context['needs_exercise_record'])
        self.assertNotContains(response, '식단을 등록하세요!')

    def setUp(self):
        self.user = User.objects.create_user(username='dashboard-owner')
        self.profile = UserProfile.objects.create(user=self.user, start_weight=100, current_weight=90, target_weight=80)
        self.client.force_login(self.user)

    def home(self):
        # Exercise the real view without reading credentials or calling Google.
        with patch('main.views.os.path.exists', return_value=False):
            return self.client.get(reverse('home'))

    def test_home_uses_user_baseline(self):
        response = self.home()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['start_weight'], 100)
        self.assertEqual(response.context['progress_percentage'], 50)
        self.assertContains(response, 'aria-valuenow="50"')
        self.assertContains(response, '목표 달성률 50%')

    def test_missing_baseline_prompts_setup_instead_of_using_103(self):
        self.profile.start_weight = None
        self.profile.save()
        response = self.home()
        self.assertIsNone(response.context['progress_percentage'])
        self.assertContains(response, '체중 정보 설정하기')
        self.assertNotContains(response, 'role="progressbar"')
        self.assertNotContains(response, '103.0 kg')

    def test_missing_weights_have_no_fake_target(self):
        self.profile.start_weight = self.profile.current_weight = self.profile.target_weight = None
        self.profile.save()
        response = self.home()
        self.assertContains(response, '미설정', count=3)
        self.assertNotContains(response, '93.0 kg')

    def test_equal_start_and_goal_explains_why_no_percentage(self):
        self.profile.target_weight = self.profile.start_weight
        self.profile.save()
        response = self.home()
        self.assertContains(response, '시작 체중과 목표 체중이 같아')
        self.assertNotContains(response, 'role="progressbar"')

    def test_profiles_have_independent_progress(self):
        other = User.objects.create_user(username='another-owner')
        UserProfile.objects.create(user=other, start_weight=80, current_weight=75, target_weight=60)
        self.assertEqual(self.home().context['progress_percentage'], 50)
        self.client.force_login(other)
        self.assertEqual(self.home().context['progress_percentage'], 25)

    def test_zero_percent_is_rendered_as_a_real_percentage(self):
        self.profile.current_weight = self.profile.start_weight
        self.profile.save()
        response = self.home()
        self.assertContains(response, 'aria-valuenow="0"')
        self.assertContains(response, '목표 달성률 0%')

    def test_unknown_calories_do_not_break_weekly_summary(self):
        daily = DailyRecord.objects.create(user=self.user)
        Meal.objects.create(daily_record=daily, meal_type='L', food_name='unanalysed', calories=None)
        Exercise.objects.create(daily_record=daily, exercise_name='unanalysed', calories_burned=None)
        response = self.home()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_calories_in'], 0)

    def test_corrupt_google_token_keeps_dashboard_available(self):
        with patch('main.views.os.path.exists', return_value=True), patch(
            'main.views.Credentials.from_authorized_user_file', side_effect=ValueError('mock-corrupt-token')
        ):
            self.assertEqual(self.client.get(reverse('home')).status_code, 200)

@override_settings(GOOGLE_ACTIVITY_PROVIDER='google_fit')
class WeeklyFeedbackErrorTests(TestCase):
    def test_model_setup_and_empty_reply_fail_safely(self):
        user = User.objects.create_user(username='weekly-error-user')
        UserProfile.objects.create(user=user, start_weight=100, current_weight=90, target_weight=80)
        DailyRecord.objects.create(user=user, date=timezone.localdate())
        self.client.force_login(user)
        with patch('main.views.os.path.exists', return_value=False), patch.dict('os.environ', {'GEMINI_API_KEY':'mock-key'}), patch('main.views.genai.configure'), patch('main.views.genai.GenerativeModel') as model:
            model.side_effect = RuntimeError('mock-setup-failure')
            response = self.client.post(reverse('home'), {'get_ai_feedback':'1'})
            self.assertEqual(response.status_code,200)
            self.assertContains(response,'잠시 후 다시 시도')
            model.side_effect = None
            model.return_value.generate_content.return_value.text = ''
            response = self.client.post(reverse('home'), {'get_ai_feedback':'1'})
            self.assertEqual(response.status_code,200)
            self.assertContains(response,'잠시 후 다시 시도')


@override_settings(GOOGLE_ACTIVITY_PROVIDER='google_fit')
class KoreanHomeDateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='korean-home-date')
        UserProfile.objects.create(user=self.user, start_weight=100, current_weight=90, target_weight=80)
        self.client.force_login(self.user)

    def test_configured_timezone_is_korea(self):
        from django.conf import settings
        self.assertEqual(settings.TIME_ZONE, 'Asia/Seoul')
        self.assertTrue(settings.USE_TZ)

    def test_home_moves_from_friday_to_saturday_at_korean_midnight(self):
        from datetime import date, timezone as utc_timezone
        samples = [(datetime(2026,10,9,14,59,59,tzinfo=utc_timezone.utc),date(2026,10,9)),
                   (datetime(2026,10,9,15,0,tzinfo=utc_timezone.utc),date(2026,10,10)),
                   (datetime(2026,10,9,17,47,tzinfo=utc_timezone.utc),date(2026,10,10))]
        for now, day in samples:
            with self.subTest(now=now), patch('django.utils.timezone.now',return_value=now), patch('main.views.os.path.exists',return_value=False):
                response = self.client.get(reverse('home'))
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.context['today'],day)
                self.assertEqual(response.context['reminder_day'],day)
                highlighted = [entry['date'] for entry in response.context['week_days'] if entry['is_today']]
                self.assertEqual(highlighted,[day])
                self.assertContains(response, "const renderedHomeDay = '"+day.isoformat()+"'")
                if day.day == 10:
                    self.assertContains(response,'2026년 10월 10일 토요일')

    def test_default_exercise_and_meal_dates_match_korean_today(self):
        from datetime import date, timezone as utc_timezone
        now = datetime(2026,10,9,17,47,tzinfo=utc_timezone.utc)
        with patch('django.utils.timezone.now',return_value=now):
            for name in ['today_record','meal_record']:
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.context['date'],date(2026,10,10))
            response = self.client.get(reverse('chat_history_api'),{'status':'1'})
            self.assertEqual(response.json()['today'],'2026-10-10')

@override_settings(GOOGLE_ACTIVITY_PROVIDER='google_fit')
class HomeStepCountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='steps-owner')
        self.other = User.objects.create_user(username='steps-other')
        UserProfile.objects.create(user=self.user, current_weight=90)
        self.client.force_login(self.user)
        self.daily = DailyRecord.objects.create(user=self.user, date=timezone.localdate())

    def add_steps(self, steps, daily=None, name='걷기'):
        return Exercise.objects.create(daily_record=daily or self.daily,exercise_name=name,steps=steps)

    def test_manual_steps_are_counted_only_for_owner_and_today(self):
        self.add_steps(10000)
        self.add_steps(500)
        self.add_steps(None)
        other = DailyRecord.objects.create(user=self.other,date=timezone.localdate())
        self.add_steps(99999,daily=other)
        past = DailyRecord.objects.create(user=self.user,date=timezone.localdate()-timedelta(days=1))
        self.add_steps(99999,daily=past)
        self.add_steps(8000,name=Exercise.GOOGLE_FIT_NAME)
        with patch('main.views.os.path.exists',return_value=False):
            response = self.client.get(reverse('home'))
        self.assertEqual(response.context['today_steps'],10500)
        self.assertEqual(response.context['manual_steps'],10500)
        self.assertIsNone(response.context['google_steps'])
        self.assertEqual(response.context['google_fit_status'],'not_connected')

    def fit_home(self, total=12000, error=None, creds=None):
        calendar,fitness = Mock(),Mock()
        calendar.events.return_value.list.return_value.execute.return_value={'items':[]}
        aggregate=fitness.users.return_value.dataset.return_value.aggregate.return_value.execute
        aggregate.side_effect=[error or {'bucket':[{'dataset':[{'point':[{'value':[{'intVal':total}]}]}]}]}, {'bucket':[]}]
        creds=creds or Mock(valid=True)
        with patch('main.views.os.path.exists',return_value=True), patch('main.views.Credentials.from_authorized_user_file',return_value=creds), patch('main.views.build',side_effect=[calendar,fitness]):
            return self.client.get(reverse('home'))

    def test_manual_and_google_are_not_added_twice(self):
        self.add_steps(10000)
        response=self.fit_home()
        self.assertEqual(response.context['today_steps'],12000)
        self.assertEqual(response.context['manual_steps'],10000)
        self.assertEqual(response.context['google_steps'],12000)
        self.assertEqual(response.context['google_fit_status'],'connected')

    def test_successful_google_zero_does_not_hide_manual_steps(self):
        self.add_steps(10000)
        response=self.fit_home(total=0)
        self.assertEqual(response.context['today_steps'],10000)
        self.assertEqual(response.context['google_steps'],0)
        self.assertEqual(response.context['google_fit_status'],'connected')

    def test_failed_google_query_keeps_manual_count(self):
        self.add_steps(10000)
        response=self.fit_home(error=RuntimeError('private-provider-error'))
        self.assertEqual(response.context['today_steps'],10000)
        self.assertIsNone(response.context['google_steps'])
        self.assertEqual(response.context['google_fit_status'],'error')
        self.assertNotContains(response,'private-provider-error')

    def test_invalid_grant_is_reported_without_leaking_token(self):
        from google.auth.exceptions import RefreshError
        creds=Mock(valid=False,expired=True,refresh_token='private-test-token')
        creds.refresh.side_effect=RefreshError('private-test-token')
        self.add_steps(10000)
        with patch('main.views.os.path.exists',return_value=True), patch('main.views.Credentials.from_authorized_user_file',return_value=creds),patch('main.views.build') as build:
            response=self.client.get(reverse('home'))
        self.assertEqual(response.context['google_fit_status'],'reauth_required')
        self.assertEqual(response.context['today_steps'],10000)
        self.assertNotContains(response,'private-test-token')
        build.assert_not_called()

    def test_missing_fitness_scope_does_not_request_fitness(self):
        creds=Mock(valid=True)
        from main.google_activity import CALENDAR_SCOPE
        creds.has_scopes.side_effect=lambda scopes: scopes == [CALENDAR_SCOPE]
        calendar=Mock()
        calendar.events.return_value.list.return_value.execute.return_value={'items':[]}
        with patch('main.views.os.path.exists',return_value=True),patch('main.views.Credentials.from_authorized_user_file',return_value=creds),patch('main.views.build',return_value=calendar) as build:
            response=self.client.get(reverse('home'))
        self.assertEqual(response.context['google_fit_status'],'permission_required')
        self.assertEqual(build.call_count,1)

    def test_malformed_google_count_is_not_accepted(self):
        self.add_steps(10000)
        response=self.fit_home(total=-1)
        self.assertEqual(response.context['today_steps'],10000)
        self.assertIsNone(response.context['google_steps'])
        self.assertEqual(response.context['google_fit_status'],'error')

    def test_expired_token_refresh_succeeds_in_memory(self):
        creds=Mock(valid=False,expired=True,refresh_token='mock-refresh')
        def refresh(request): creds.valid=True
        creds.refresh.side_effect=refresh
        with patch('main.views.save_google_credentials') as save:
            response=self.fit_home(creds=creds)
        save.assert_called_once_with(self.user,creds)
        creds.refresh.assert_called_once()
        self.assertEqual(response.context['google_fit_status'],'connected')
    def test_exercise_post_steps_reach_home_without_google(self):
        with patch('records.views.genai.configure'),patch('records.views.genai.GenerativeModel') as model:
            model.return_value.generate_content.return_value.text='150'
            response=self.client.post(reverse('today_record'),{'submit_exercise':'1','exercise_name':'걷기','start_time':'08:00','end_time':'08:30','steps':'10000'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(Exercise.objects.get(daily_record=self.daily).steps,10000)
        with patch('main.views.os.path.exists',return_value=False):
            home=self.client.get(reverse('home'))
        self.assertEqual(home.context['today_steps'],10000)
        self.assertContains(home,'수동 10000보')
