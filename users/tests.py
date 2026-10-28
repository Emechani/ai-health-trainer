from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from datetime import timedelta
import re

from .forms import CustomSignupForm, ProfileUpdateForm, ExerciseHabitForm
from .models import UserProfile, WeightRecord, current_weight_day, record_weight


class ExerciseHabitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='habit-owner')
        self.profile = UserProfile.objects.create(user=self.user, start_weight=100, current_weight=90, target_weight=80)
        self.client.force_login(self.user)
        self.data = {
            'action': 'save_exercise_habits', 'exercise_experience': 'beginner',
            'exercise_days_per_week': '3', 'exercise_minutes_per_session': '30',
            'preferred_exercises': '걷기, 수영',
        }

    def test_save_and_reload_preserves_weights_and_history(self):
        record_weight(self.user, current_weight_day(), 90)
        self.assertEqual(self.client.post(reverse('profile_update'), self.data).status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.start_weight, self.profile.current_weight, self.profile.target_weight), (100, 90, 80))
        self.assertEqual((self.profile.exercise_days_per_week, self.profile.exercise_minutes_per_session), (3, 30))
        self.assertEqual(WeightRecord.objects.get(user=self.user).weight, 90)
        response = self.client.get(reverse('profile_update'))
        self.assertEqual(response.context['exercise_habit_form'].initial['preferred_exercises'], '걷기, 수영')
        self.assertContains(response, '운동 습관 저장')

    def test_invalid_values_do_not_save(self):
        for values in ({'exercise_days_per_week': '8'}, {'exercise_days_per_week': '-1'},
                       {'exercise_days_per_week': '1.5'}, {'exercise_minutes_per_session': '0'},
                       {'exercise_minutes_per_session': '241'}, {'exercise_experience': 'invalid'},
                       {'preferred_exercises': 'x' * 201}):
            with self.subTest(values=values):
                response = self.client.post(reverse('profile_update'), {**self.data, **values})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['exercise_habit_form'].errors)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.exercise_days_per_week)

    def test_zero_days_is_retained_as_zero(self):
        self.client.post(reverse('profile_update'), {**self.data, 'exercise_days_per_week': '0'})
        self.profile.refresh_from_db()
        self.assertIn('주당 운동 가능 일수: 0일', self.profile.exercise_habits_summary)

    def test_optional_fields_can_be_cleared(self):
        self.client.post(reverse('profile_update'), self.data)
        self.client.post(reverse('profile_update'), {key: '' for key in self.data} | {'action': 'save_exercise_habits'})
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.exercise_days_per_week)
        self.assertEqual(self.profile.preferred_exercises, '')
        self.assertIn('운동 경험: 미설정', self.profile.exercise_habits_summary)

    def test_posted_ids_and_weights_cannot_change_other_profile_or_weight(self):
        other = User.objects.create_user(username='habit-other')
        other_profile = UserProfile.objects.create(user=other, preferred_exercises='축구')
        self.client.post(reverse('profile_update'), {**self.data, 'user': other.pk, 'id': other_profile.pk, 'current_weight': '1'})
        other_profile.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(other_profile.preferred_exercises, '축구')
        self.assertEqual(self.profile.preferred_exercises, '걷기, 수영')
        self.assertEqual(self.profile.current_weight, 90)

    def test_login_and_csrf_required(self):
        from django.test import Client
        self.client.logout()
        self.assertEqual(self.client.post(reverse('profile_update'), self.data).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(reverse('profile_update'), self.data).status_code, 403)

    def test_chat_uses_saved_habits_without_real_api(self):
        import json
        from unittest.mock import patch
        self.client.post(reverse('profile_update'), self.data)
        with patch.dict('os.environ', {'GEMINI_API_KEY': 'mock-only'}), patch('records.views.genai.configure'), patch('records.views.genai.GenerativeModel') as model:
            model.return_value.generate_content.return_value.text = '모의 운동 조언'
            response = self.client.post(reverse('ai_chat_api'), data=json.dumps({'message': '운동을 추천해줘'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        prompt = model.return_value.generate_content.call_args.args[0]
        for value in ('운동 경험: 초급', '주당 운동 가능 일수: 3일', '1회 운동 가능 시간: 30분', '선호 운동 종목: 걷기, 수영'):
            self.assertIn(value, prompt)


class WeightProgressTests(SimpleTestCase):
    def test_progress_and_limits(self):
        cases = [
            (100, 100, 80, 0), (100, 90, 80, 50), (100, 80, 80, 100),
            (100, 75, 80, 100), (100, 105, 80, 0),
            (60, 65, 70, 50), (60, 72, 70, 100), (60, 58, 70, 0),
        ]
        for start, current, target, expected in cases:
            with self.subTest(start=start, current=current, target=target):
                profile = UserProfile(start_weight=start, current_weight=current, target_weight=target)
                self.assertEqual(profile.weight_progress_percentage, expected)

    def test_missing_invalid_and_equal_weights_are_not_fabricated(self):
        for start, current, target in [
            (None, 90, 80), (100, None, 80), (100, 90, None),
            (80, 80, 80), (0, 90, 80), (100, -1, 80),
            (float('nan'), 90, 80), (100, float('inf'), 80),
        ]:
            with self.subTest(start=start, current=current, target=target):
                profile = UserProfile(start_weight=start, current_weight=current, target_weight=target)
                self.assertIsNone(profile.weight_progress_percentage)

    def test_invalid_weight_input_is_rejected(self):
        for field in ('start_weight', 'current_weight', 'target_weight'):
            for invalid in ('0', '-1', 'nan', 'inf', 'not-a-number'):
                data = {'nickname': 'test', 'start_weight': '100', 'current_weight': '90', 'target_weight': '80'}
                data[field] = invalid
                with self.subTest(field=field, value=invalid):
                    form = ProfileUpdateForm(data)
                    self.assertFalse(form.is_valid())
                    self.assertIn(field, form.errors)


class ProfileWeightTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='profile-owner', password='test-password')
        self.profile = UserProfile.objects.create(user=self.user, start_weight=100, current_weight=95, target_weight=80)
        self.client.force_login(self.user)

    def test_current_weight_update_keeps_baseline(self):
        response = self.client.post(reverse('profile_update'), {
            'nickname': 'owner', 'start_weight': '100', 'current_weight': '90', 'target_weight': '80',
        })
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.start_weight, 100)
        self.assertEqual(self.profile.current_weight, 90)
        self.assertEqual(self.profile.weight_progress_percentage, 50)

    def test_baseline_and_goal_can_be_corrected(self):
        self.client.post(reverse('profile_update'), {
            'nickname': 'owner', 'start_weight': '110', 'current_weight': '95', 'target_weight': '80',
        })
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.weight_progress_percentage, 50)

    def test_invalid_request_does_not_change_database(self):
        response = self.client.post(reverse('profile_update'), {
            'nickname': 'owner', 'start_weight': '-10', 'current_weight': '90', 'target_weight': '80',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'has-error')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.start_weight, 100)
        self.assertEqual(self.profile.current_weight, 95)

    def test_other_user_profile_cannot_be_changed_by_posting_id(self):
        other = User.objects.create_user(username='other')
        other_profile = UserProfile.objects.create(user=other, start_weight=70, current_weight=65, target_weight=60)
        self.client.post(reverse('profile_update'), {
            'user': other.pk, 'id': other_profile.pk, 'nickname': 'owner',
            'start_weight': '100', 'current_weight': '90', 'target_weight': '80',
        })
        other_profile.refresh_from_db()
        self.assertEqual(other_profile.current_weight, 65)
        self.assertEqual(other_profile.start_weight, 70)

    def test_setup_reuses_existing_profile(self):
        response = self.client.post(reverse('profile_setup'), {
            'start_weight': '100', 'current_weight': '90', 'target_weight': '80',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UserProfile.objects.filter(user=self.user).count(), 1)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_weight, 90)

    def test_missing_profile_data_has_no_default_60(self):
        self.profile.start_weight = self.profile.current_weight = self.profile.target_weight = None
        self.profile.save()
        response = self.client.get(reverse('profile_update'))
        form = response.context['form']
        for field in ('start_weight', 'current_weight', 'target_weight'):
            self.assertIsNone(form[field].value())
        self.assertContains(response, '미설정', count=3)

    def test_profile_requires_login(self):
        self.client.logout()
        for url_name in ('profile_setup', 'profile_update'):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.url)


class SignupWeightTests(TestCase):
    def signup_form(self, username, current='', target=''):
        return CustomSignupForm({
            'username': username, 'real_name': '테스트', 'nickname': '테스트',
            'password1': 'ExampleSafePass_92!', 'password2': 'ExampleSafePass_92!',
            'current_weight': current, 'target_weight': target,
        })

    def test_signup_uses_actual_initial_weight_as_baseline(self):
        form = self.signup_form('new-user', '82.5', '75')
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.userprofile.start_weight, 82.5)
        self.assertEqual(user.userprofile.current_weight, 82.5)
        self.assertEqual(user.userprofile.weight_progress_percentage, 0)

    def test_optional_weights_are_not_filled_with_invented_values(self):
        form = self.signup_form('empty-user')
        self.assertTrue(form.is_valid(), form.errors)
        profile = form.save().userprofile
        self.assertIsNone(profile.start_weight)
        self.assertIsNone(profile.current_weight)
        self.assertIsNone(profile.target_weight)

    def test_invalid_signup_weights_are_rejected(self):
        for current, target in [('0', '70'), ('-1', '70'), ('80', '-2'), ('inf', '70')]:
            with self.subTest(current=current, target=target):
                self.assertFalse(self.signup_form('invalid-user', current, target).is_valid())


class BaselineMigrationTests(TransactionTestCase):
    def test_exercise_habit_migration_preserves_profile_and_weight_records(self):
        previous = [('users', '0004_weight_history')]
        latest = [('users', '0005_userprofile_exercise_days_per_week_and_more')]
        executor = MigrationExecutor(connection)
        try:
            executor.migrate(previous)
            apps = executor.loader.project_state(previous).apps
            user = apps.get_model('auth', 'User').objects.create(username='before-habits')
            profile = apps.get_model('users', 'UserProfile').objects.create(
                user=user, nickname='기존 프로필', start_weight=100, current_weight=90, target_weight=80,
            )
            entry = apps.get_model('users', 'WeightRecord').objects.create(user=user, date=current_weight_day(), weight=90)
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            apps = executor.loader.project_state(latest).apps
            saved = apps.get_model('users', 'UserProfile').objects.get(pk=profile.pk)
            self.assertEqual((saved.nickname, saved.start_weight, saved.current_weight, saved.target_weight), ('기존 프로필', 100, 90, 80))
            self.assertIsNone(saved.exercise_days_per_week)
            self.assertEqual(saved.exercise_experience, '')
            self.assertEqual(apps.get_model('users', 'WeightRecord').objects.get(pk=entry.pk).weight, 90)
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_profile_is_preserved_with_unknown_baseline(self):
        previous = [('users', '0002_userprofile_nickname_userprofile_real_name')]
        latest = [('users', '0003_weight_progress_baseline')]
        executor = MigrationExecutor(connection)
        try:
            executor.migrate(previous)
            old_apps = executor.loader.project_state(previous).apps
            old_user = old_apps.get_model('auth', 'User').objects.create(username='legacy-user')
            old_profile = old_apps.get_model('users', 'UserProfile').objects.create(
                user=old_user, nickname='기존 사용자', current_weight=91.5, target_weight=80,
            )
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            apps = executor.loader.project_state(latest).apps
            profile = apps.get_model('users', 'UserProfile').objects.get(pk=old_profile.pk)
            self.assertEqual(profile.current_weight, 91.5)
            self.assertEqual(profile.target_weight, 80)
            self.assertEqual(profile.nickname, '기존 사용자')
            self.assertEqual(profile.user_id, old_user.pk)
            self.assertIsNone(profile.start_weight)
        finally:
            # 이후 테스트가 새 체중 기록 테이블을 사용할 수 있도록 최신 스키마로 복원합니다.
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())


class WeightHistoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='weight-owner')
        self.profile = UserProfile.objects.create(user=self.user, start_weight=100, current_weight=95, target_weight=80)
        self.today = current_weight_day()
        self.client.force_login(self.user)

    def save_day(self, day, weight, **extra):
        return self.client.post(reverse('profile_update'), {
            'action': 'record_weight', 'date': day.isoformat(), 'weight': str(weight), **extra,
        })

    def test_save_today_updates_current_without_changing_goal_or_baseline(self):
        response = self.save_day(self.today, 92.5)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(WeightRecord.objects.get(user=self.user, date=self.today).weight, 92.5)
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.start_weight, self.profile.current_weight, self.profile.target_weight), (100, 92.5, 80))

    def test_past_date_is_saved_with_its_actual_date(self):
        day = self.today - timedelta(days=7)
        self.save_day(day, 96)
        self.assertTrue(WeightRecord.objects.filter(user=self.user, date=day, weight=96).exists())

    def test_same_day_is_updated_without_duplicates(self):
        self.save_day(self.today, 92)
        self.save_day(self.today, 91.5)
        self.assertEqual(WeightRecord.objects.filter(user=self.user).count(), 1)
        self.assertEqual(WeightRecord.objects.get(user=self.user).weight, 91.5)

    def test_past_addition_and_edit_do_not_roll_back_latest_weight(self):
        self.save_day(self.today, 90)
        self.save_day(self.today - timedelta(days=7), 98)
        self.save_day(self.today - timedelta(days=7), 97)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_weight, 90)

    def test_latest_date_controls_current_even_if_input_order_is_reversed(self):
        self.save_day(self.today - timedelta(days=5), 94)
        self.save_day(self.today - timedelta(days=2), 92)
        self.save_day(self.today - timedelta(days=10), 98)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_weight, 92)

    def test_profile_weight_update_is_also_saved_today(self):
        response = self.client.post(reverse('profile_update'), {
            'nickname': 'owner', 'start_weight': '100', 'current_weight': '91.2', 'target_weight': '80',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(WeightRecord.objects.get(user=self.user, date=self.today).weight, 91.2)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.start_weight, 100)
        self.assertEqual(self.profile.target_weight, 80)

    def test_unchanged_profile_weight_does_not_invent_a_measurement_date(self):
        self.client.post(reverse('profile_update'), {
            'nickname': 'renamed', 'start_weight': '100', 'current_weight': '95', 'target_weight': '80',
        })
        self.assertFalse(WeightRecord.objects.filter(user=self.user).exists())

    def test_invalid_and_future_records_do_not_change_database(self):
        for value in ('0', '-1', 'nan', 'inf', '1e309', 'not-a-number', ''):
            with self.subTest(value=value):
                response = self.save_day(self.today, value)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['weight_form'].errors)
        response = self.save_day(self.today + timedelta(days=1), 90)
        self.assertEqual(response.status_code, 200)
        self.assertIn('date', response.context['weight_form'].errors)
        self.assertFalse(WeightRecord.objects.exists())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_weight, 95)

    def test_cannot_clear_current_weight_when_history_exists(self):
        self.save_day(self.today, 90)
        response = self.client.post(reverse('profile_update'), {
            'nickname': 'owner', 'start_weight': '100', 'current_weight': '', 'target_weight': '80',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('current_weight', response.context['form'].errors)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.current_weight, 90)

    def test_user_id_and_record_id_cannot_modify_another_user(self):
        other = User.objects.create_user(username='weight-other')
        other_profile = UserProfile.objects.create(user=other, current_weight=65)
        other_record = WeightRecord.objects.create(user=other, date=self.today, weight=65)
        self.save_day(self.today, 90, user=other.pk, id=other_record.pk)
        other_record.refresh_from_db()
        other_profile.refresh_from_db()
        self.assertEqual(other_record.weight, 65)
        self.assertEqual(other_profile.current_weight, 65)
        response = self.client.get(reverse('profile_update'))
        self.assertEqual([item.user_id for item in response.context['weight_records']], [self.user.pk])

    def test_weight_record_save_requires_login(self):
        self.client.logout()
        self.assertEqual(self.save_day(self.today, 90).status_code, 302)
        self.assertFalse(WeightRecord.objects.exists())

    def test_latest_thirty_graph_points_and_ten_per_page(self):
        WeightRecord.objects.bulk_create([
            WeightRecord(user=self.user, date=self.today - timedelta(days=i), weight=90 + i / 10)
            for i in range(35)
        ])
        response = self.client.get(reverse('profile_update'))
        points = response.context['weight_chart']['points']
        self.assertEqual(len(points), 30)
        self.assertEqual(points[0]['record'].date, self.today - timedelta(days=29))
        self.assertEqual(points[-1]['record'].date, self.today)
        self.assertEqual(len(response.context['weight_records']), 10)
        self.assertContains(response, 'stroke-dasharray="6 5"')
        self.assertEqual(response.context['weight_records'].paginator.count, 35)
        page4 = self.client.get(reverse('profile_update'), {'weight_page': 4})
        self.assertEqual(len(page4.context['weight_records']), 5)

    def test_edit_button_contains_exact_date_and_weight(self):
        self.save_day(self.today, 91.25)
        response = self.client.get(reverse('profile_update'))
        self.assertContains(response, f'data-date="{self.today.isoformat()}" data-weight="91.25"')
        self.assertContains(response, "document.getElementById('id_date').value = button.dataset.date")

    def test_no_history_displays_empty_state_without_fake_points(self):
        response = self.client.get(reverse('profile_update'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['weight_chart'])
        self.assertContains(response, '아직 날짜별 체중 기록이 없습니다.')
        self.assertNotContains(response, '<polyline')

    def test_single_measurement_has_finite_svg_coordinates(self):
        self.save_day(self.today, 91)
        response = self.client.get(reverse('profile_update'))
        line = response.context['weight_chart']['line']
        self.assertRegex(line, r'^\d+(?:\.\d+)?,\d+(?:\.\d+)?$')
        self.assertNotIn('nan', line.lower())
