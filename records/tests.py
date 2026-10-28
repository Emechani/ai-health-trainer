import json
import io
import tempfile
import shutil
from uuid import uuid4
from pathlib import Path
from datetime import date, datetime, timedelta, timezone as datetime_timezone
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from django.urls import reverse

from users.models import UserProfile
from .models import ChatMessage, DailyRecord, Meal, Exercise
from .forms import ExerciseForm
from .views import CHAT_TIMEZONE, current_chat_day


DAY = date(2026, 10, 9)
NOW = datetime(2026, 10, 9, 3, tzinfo=datetime_timezone.utc)


class DailyChatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='chat-owner')
        self.other = User.objects.create_user(username='another-user')
        self.client.force_login(self.user)
        self.profile = UserProfile.objects.create(user=self.user, start_weight=100, current_weight=90, target_weight=80)

    def chat(self, text, when, user=None, is_ai=False):
        item = ChatMessage.objects.create(user=user or self.user, message=text, is_ai=is_ai)
        ChatMessage.objects.filter(pk=item.pk).update(created_at=when)
        return item

    def history(self, day=None):
        with patch('records.views.current_chat_day', return_value=DAY):
            return self.client.get(reverse('chat_history_api'), {'date': day or DAY.isoformat()})

    def post_chat(self, body=None, **kwargs):
        with patch('records.views.current_chat_day', return_value=DAY), patch('records.views.timezone.now', return_value=NOW):
            payload = {'message': '오늘 운동 추천', 'date': DAY.isoformat()} if body is None else body
            return self.client.post(reverse('ai_chat_api'), data=json.dumps(payload), content_type='application/json', **kwargs)

    def test_korean_midnight_is_new_day_while_utc_is_previous_day(self):
        with patch('records.views.timezone.now', return_value=datetime(2026, 10, 8, 14, 59, 59, tzinfo=datetime_timezone.utc)):
            self.assertEqual(current_chat_day(), DAY - timedelta(days=1))
        with patch('records.views.timezone.now', return_value=datetime(2026, 10, 8, 15, 0, tzinfo=datetime_timezone.utc)):
            self.assertEqual(current_chat_day(), DAY)

    def test_today_excludes_yesterday_and_other_users(self):
        self.chat('어제 대화', datetime(2026, 10, 8, 14, 59, 59, tzinfo=datetime_timezone.utc))
        self.chat('오늘 대화', datetime(2026, 10, 8, 15, tzinfo=datetime_timezone.utc))
        self.chat('다른 사람 비밀', NOW, user=self.other)
        response = self.history()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['message'] for item in response.json()['messages']], ['오늘 대화'])
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_archive_retrieval_preserves_all_records(self):
        self.chat('이전 질문', datetime(2026, 10, 8, 3, tzinfo=datetime_timezone.utc))
        self.chat('이전 답변', datetime(2026, 10, 8, 4, tzinfo=datetime_timezone.utc), is_ai=True)
        count = ChatMessage.objects.count()
        response = self.history('2026-10-08')
        self.assertEqual([item['message'] for item in response.json()['messages']], ['이전 질문', '이전 답변'])
        self.assertIn('2026-10-08', response.json()['dates'])
        self.assertEqual(ChatMessage.objects.count(), count)
        self.assertEqual(self.history().json()['messages'], [])

    def test_invalid_and_future_archive_dates_are_rejected(self):
        for value in ('not-a-date', '2026-10-10', '20261009'):
            with self.subTest(value=value):
                self.assertEqual(self.history(value).status_code, 400)

    def test_status_check_does_not_return_personal_messages(self):
        self.chat('질문', NOW)
        with patch('records.views.current_chat_day', return_value=DAY):
            response = self.client.get(reverse('chat_history_api'), {'status': '1'})
        self.assertEqual(response.json(), {'status': 'success', 'today': DAY.isoformat()})

    def test_history_and_chat_require_login_and_correct_method(self):
        self.assertEqual(self.client.post(reverse('chat_history_api')).status_code, 405)
        self.assertEqual(self.client.get(reverse('ai_chat_api')).status_code, 405)
        self.client.logout()
        self.assertEqual(self.history().status_code, 302)
        self.assertEqual(self.post_chat().status_code, 302)

    def test_invalid_questions_are_not_saved(self):
        invalid_values = [[], {'message': 123}, {'message': '  '}, {'message': 'x' * 2001}]
        for value in invalid_values:
            with self.subTest(value=value):
                self.assertEqual(self.post_chat(value).status_code, 400)
        with patch('records.views.current_chat_day', return_value=DAY):
            response = self.client.post(reverse('ai_chat_api'), data='{bad json', content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ChatMessage.objects.count(), 0)

    def test_old_day_send_is_rejected_without_saving(self):
        response = self.post_chat({'message': '어제 날짜로 전송', 'date': '2026-10-08'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['today'], '2026-10-09')
        self.assertFalse(ChatMessage.objects.exists())

    def test_csrf_protection_remains_enabled(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(reverse('ai_chat_api'), data=json.dumps({'message': 'test'}), content_type='application/json')
        self.assertEqual(response.status_code, 403)

    @patch.dict('os.environ', {'GEMINI_API_KEY': 'test-only-key'})
    @patch('records.views.genai.configure')
    @patch('records.views.genai.GenerativeModel')
    def test_prompt_uses_latest_user_goal_and_only_own_records(self, model_class, configure):
        model_class.return_value.generate_content.return_value.text = '검증용 추천입니다.'
        UserProfile.objects.create(user=self.other, current_weight=65, target_weight=60)
        record = DailyRecord.objects.create(user=self.user)
        DailyRecord.objects.filter(pk=record.pk).update(date=DAY)
        Meal.objects.create(daily_record=record, meal_type='L', food_name='본인 식사', calories=500)
        other_record = DailyRecord.objects.create(user=self.other)
        DailyRecord.objects.filter(pk=other_record.pk).update(date=DAY)
        Meal.objects.create(daily_record=other_record, meal_type='L', food_name='다른 사람 식사', calories=600)
        self.chat('어제의 비밀 질문', NOW - timedelta(days=1))
        self.chat('오늘 이전 질문', NOW - timedelta(hours=1))
        self.chat('다른 사용자 질문', NOW, user=self.other)

        response = self.post_chat()
        self.assertEqual(response.status_code, 200)
        prompt = model_class.return_value.generate_content.call_args.args[0]
        self.assertIn('목표 체중: 80kg', prompt)
        self.assertIn('시작 체중: 100kg', prompt)
        self.assertIn('목표 달성률: 50%', prompt)
        self.assertIn('본인 식사', prompt)
        self.assertIn('오늘 이전 질문', prompt)
        for forbidden in ('93kg', '목표 체중: 60kg', '다른 사람 식사', '어제의 비밀 질문', '다른 사용자 질문'):
            self.assertNotIn(forbidden, prompt)
        self.profile.target_weight = 75
        self.profile.save()
        self.post_chat()
        self.assertIn('목표 체중: 75kg', model_class.return_value.generate_content.call_args.args[0])
        self.assertTrue(ChatMessage.objects.filter(user=self.user, is_ai=True, message='검증용 추천입니다.').exists())
        configure.assert_called_with(api_key='test-only-key')

    @patch.dict('os.environ', {'GEMINI_API_KEY': 'test-only-key'})
    @patch('records.views.genai.configure')
    @patch('records.views.genai.GenerativeModel')
    def test_missing_profile_does_not_invent_a_goal(self, model_class, configure):
        self.profile.delete()
        model_class.return_value.generate_content.return_value.text = '프로필을 설정해 주세요.'
        self.assertEqual(self.post_chat().status_code, 200)
        prompt = model_class.return_value.generate_content.call_args.args[0]
        self.assertIn('프로필 미설정', prompt)
        self.assertNotIn('93kg', prompt)

    @patch.dict('os.environ', {'GEMINI_API_KEY': 'test-only-key'})
    @patch('records.views.genai.configure')
    @patch('records.views.genai.GenerativeModel')
    def test_empty_goal_is_explicitly_marked_unknown(self, model_class, configure):
        self.profile.target_weight = None
        self.profile.save()
        model_class.return_value.generate_content.return_value.text = '목표를 설정해 주세요.'
        self.post_chat()
        self.assertIn('목표 체중: 미설정', model_class.return_value.generate_content.call_args.args[0])

    @patch.dict('os.environ', {'GEMINI_API_KEY': ''})
    @patch('records.views.genai.GenerativeModel')
    def test_missing_key_is_handled_without_calling_google(self, model_class):
        response = self.post_chat()
        self.assertEqual(response.status_code, 503)
        model_class.assert_not_called()
        self.assertEqual(ChatMessage.objects.filter(is_ai=False).count(), 1)
        self.assertEqual(ChatMessage.objects.filter(is_ai=True).count(), 0)

    @patch.dict('os.environ', {'GEMINI_API_KEY': 'test-only-key'})
    @patch('records.views.genai.configure')
    @patch('records.views.genai.GenerativeModel')
    def test_provider_errors_are_not_exposed_or_saved_as_replies(self, model_class, configure):
        model_class.return_value.generate_content.side_effect = RuntimeError('sensitive-provider-error')
        response = self.post_chat()
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, 'sensitive-provider-error', status_code=503)
        self.assertFalse(ChatMessage.objects.filter(is_ai=True).exists())

    @patch.dict('os.environ', {'GEMINI_API_KEY': 'test-only-key'})
    @patch('records.views.genai.configure')
    @patch('records.views.genai.GenerativeModel')
    def test_empty_ai_reply_is_not_saved(self, model_class, configure):
        model_class.return_value.generate_content.return_value.text = '  '
        self.assertEqual(self.post_chat().status_code, 503)
        self.assertFalse(ChatMessage.objects.filter(is_ai=True).exists())

    @patch('records.views.build')
    @patch('records.views.Credentials.from_authorized_user_file')
    @patch('records.views.os.path.exists', return_value=True)
    def test_calendar_initially_renders_only_today_and_archive_selector(self, exists, credentials, build):
        credentials.return_value.valid = True
        build.return_value.events.return_value.list.return_value.execute.return_value = {'items': []}
        self.chat('오늘 표시할 대화', NOW)
        self.chat('어제 숨길 대화', NOW - timedelta(days=1))
        with patch('records.views.current_chat_day', return_value=DAY):
            response = self.client.get(reverse('exercise_calendar'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '오늘 표시할 대화')
        self.assertNotContains(response, '어제 숨길 대화')
        self.assertContains(response, '2026-10-08 대화')
        self.assertContains(response, 'id="chat-date"')
        self.assertContains(response, 'scheduleMidnightCheck')


class RecordRegressionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_media = Path(tempfile.gettempdir()) / f'django-records-test-{uuid4().hex}'
        cls.test_media.mkdir()
        cls.addClassCleanup(shutil.rmtree, cls.test_media)
        media_settings = override_settings(MEDIA_ROOT=str(cls.test_media))
        media_settings.enable()
        cls.addClassCleanup(media_settings.disable)

    def setUp(self):
        self.user = User.objects.create_user(username='record-owner')
        UserProfile.objects.create(user=self.user, start_weight=100, current_weight=90, target_weight=80)
        self.client.force_login(self.user)
        self.model_patch = patch('records.views.genai.GenerativeModel')
        self.model = self.model_patch.start().return_value
        self.addCleanup(self.model_patch.stop)
        config_patch = patch('records.views.genai.configure')
        config_patch.start()
        self.addCleanup(config_patch.stop)

    def image_upload(self):
        output = io.BytesIO()
        Image.new('RGB', (16, 16), 'white').save(output, format='PNG')
        return SimpleUploadedFile('mock-food.png', output.getvalue(), content_type='image/png')

    def meal(self, response='테스트 음식,620,55,25,30', **extra):
        self.model.generate_content.return_value.text = response
        return self.client.post(reverse('today_record'), {'submit_meal': '1', 'meal_type': 'L', 'food_text': '테스트 음식', **extra})

    def exercise(self, **extra):
        self.model.generate_content.return_value.text = '150'
        return self.client.post(reverse('today_record'), {
            'submit_exercise': '1', 'exercise_name': '걷기', 'start_time': '10:00', 'end_time': '10:30',
            'distance_km': '2.5', 'steps': '3000', **extra,
        })

    def test_meal_saved_and_visible(self):
        self.assertEqual(self.meal().status_code, 302)
        record = Meal.objects.get(daily_record__user=self.user)
        self.assertEqual((record.calories, record.carbs, record.protein, record.fat), (620, 55, 25, 30))
        self.assertContains(self.client.get(reverse('meal_record')), '테스트 음식')

    def test_image_is_passed_to_model_and_stored_in_test_media(self):
        self.assertEqual(self.meal(image=self.image_upload()).status_code, 302)
        contents = self.model.generate_content.call_args.args[0]
        self.assertIsInstance(contents, list)
        self.assertIsInstance(contents[1], Image.Image)
        self.assertTrue(Meal.objects.get().image)

    def test_decimal_nutrients_are_rounded_not_concatenated(self):
        self.meal('테스트 음식,620.5,55.5,25.5,30.5')
        record = Meal.objects.get()
        self.assertEqual((record.calories, record.carbs, record.protein, record.fat), (621, 56, 26, 31))

    def test_negative_or_malformed_nutrients_are_not_saved_as_valid_numbers(self):
        for response in ('음식,-10,20,30,40', '음식,nan,20,30,40', 'unexpected response'):
            with self.subTest(response=response):
                self.meal(response)
                record = Meal.objects.latest('pk')
                self.assertIsNone(record.calories)

    def test_provider_failure_preserves_manual_food_without_fake_zero_nutrients(self):
        self.model.generate_content.side_effect = RuntimeError('mock-provider-failure')
        self.assertEqual(self.meal().status_code, 302)
        record = Meal.objects.get()
        self.assertEqual(record.food_name, '테스트 음식')
        self.assertIsNone(record.calories)
        self.assertContains(self.client.get(reverse('meal_record')), '칼로리 미분석')

    def test_exercise_is_saved_and_visible(self):
        self.assertEqual(self.exercise().status_code, 302)
        exercise = Exercise.objects.get()
        self.assertEqual((exercise.distance_km, exercise.steps, exercise.calories_burned), (2.5, 3000, 150))
        self.assertContains(self.client.get(reverse('today_record')), '걷기')

    def test_missing_times_show_form_error_instead_of_crashing(self):
        response = self.exercise(start_time='', end_time='')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['exercise_form'].errors)
        self.assertFalse(Exercise.objects.exists())

    def test_invalid_exercise_values_are_rejected(self):
        for extra in ({'steps': '-1'}, {'distance_km': '-1'}, {'end_time': '09:00'}):
            with self.subTest(extra=extra):
                response = self.exercise(**extra)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['exercise_form'].errors)
        self.assertFalse(Exercise.objects.exists())

    def test_bound_form_errors_are_preserved(self):
        response = self.exercise(exercise_name='')
        self.assertEqual(response.status_code, 200)
        self.assertIn('exercise_name', response.context['exercise_form'].errors)

    def test_past_daily_record_keeps_requested_date(self):
        self.client.get(reverse('today_record'))
        day = timezone.localdate() - timedelta(days=1)
        response = self.client.get(reverse('today_record'), {'date': day.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(DailyRecord.objects.filter(user=self.user, date=day).exists())
        self.assertEqual(DailyRecord.objects.filter(user=self.user).count(), 2)

    def test_invalid_record_date_returns_client_error(self):
        response = self.client.get(reverse('today_record'), {'date': 'not-a-date'})
        self.assertEqual(response.status_code, 400)

    def test_other_user_records_cannot_be_edited(self):
        other = User.objects.create_user(username='record-other')
        daily = DailyRecord.objects.create(user=other)
        meal = Meal.objects.create(daily_record=daily, meal_type='L', food_name='private meal')
        exercise = Exercise.objects.create(daily_record=daily, exercise_name='private exercise')
        self.assertEqual(self.client.get(reverse('meal_edit', args=[meal.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('exercise_edit', args=[exercise.pk])).status_code, 404)
        response = self.client.get(reverse('today_record'))
        self.assertNotContains(response, 'private meal')
        self.assertNotContains(response, 'private exercise')


class NutritionAdviceSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='nutrition-owner')
        UserProfile.objects.create(user=self.user, current_weight=90, target_weight=80)
        self.client.force_login(self.user)
        self.daily = DailyRecord.objects.create(user=self.user, date=current_chat_day())
        self.model_patch = patch('records.views.genai.GenerativeModel')
        self.model = self.model_patch.start().return_value
        self.addCleanup(self.model_patch.stop)
        configure = patch('records.views.genai.configure')
        configure.start()
        self.addCleanup(configure.stop)
        key = patch.dict('os.environ', {'GEMINI_API_KEY': 'mock-only'})
        key.start()
        self.addCleanup(key.stop)
        self.model.generate_content.return_value.text = json.dumps({
            'summary': '모의 영양 보완 요약',
            'items': [{'nutrient': '단백질', 'observation': '부분 기록입니다.', 'suggestion': '실제 식사와 분석값을 확인하세요.'}],
            'cautions': ['추정치이며 진단이 아닙니다.'],
        })

    def test_summary_excludes_other_users_and_preserves_unknown_values(self):
        from .nutrition import nutrition_summary
        Meal.objects.create(daily_record=self.daily, meal_type='L', food_name='본인', carbs=30, protein=None, fat=0)
        other = User.objects.create_user(username='nutrition-other')
        daily = DailyRecord.objects.create(user=other, date=current_chat_day())
        Meal.objects.create(daily_record=daily, meal_type='L', food_name='다른 사용자', protein=999)
        summary = nutrition_summary(self.user, current_chat_day())
        self.assertEqual(summary['meal_count'], 1)
        protein = next(item for item in summary['nutrients'] if item['name'] == 'protein')
        self.assertIsNone(protein['total'])
        self.assertEqual(protein['missing_count'], 1)
        fat = next(item for item in summary['nutrients'] if item['name'] == 'fat')
        self.assertEqual(fat['total'], 0)

    def test_advice_uses_only_own_records_and_is_cached_without_api_on_get(self):
        Meal.objects.create(daily_record=self.daily, meal_type='L', food_name='본인 영양 기록', protein=10)
        other = User.objects.create_user(username='nutrition-prompt-other')
        other_daily = DailyRecord.objects.create(user=other, date=current_chat_day())
        Meal.objects.create(daily_record=other_daily, meal_type='L', food_name='다른 사람 비밀 식사')
        response = self.client.post(reverse('meal_plan'), {'action': 'nutrition_advice', 'dietary_restrictions': '땅콩 제외'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith('#nutrition'))
        prompt = self.model.generate_content.call_args.args[0]
        self.assertIn('본인 영양 기록', prompt)
        self.assertIn('땅콩 제외', prompt)
        self.assertNotIn('다른 사람 비밀 식사', prompt)
        self.assertContains(self.client.get(reverse('meal_plan')), '모의 영양 보완 요약')
        self.model.generate_content.assert_called_once()

    def test_no_meals_does_not_call_api(self):
        response = self.client.post(reverse('meal_plan'), {'action': 'nutrition_advice'})
        self.assertContains(response, '식사 기록을 먼저 등록')
        self.model.generate_content.assert_not_called()

    def test_authentication_and_csrf_remain_required(self):
        self.client.logout()
        self.assertEqual(self.client.post(reverse('meal_plan'), {'action': 'nutrition_advice'}).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(reverse('meal_plan'), {'action': 'nutrition_advice'}).status_code, 403)
        self.model.generate_content.assert_not_called()

    def test_failed_response_does_not_leak_errors_or_persist_advice(self):
        Meal.objects.create(daily_record=self.daily, meal_type='L', food_name='본인')
        self.model.generate_content.side_effect = RuntimeError('mock-private-exception')
        response = self.client.post(reverse('meal_plan'), {'action': 'nutrition_advice'})
        self.assertContains(response, '영양 보완 안내를 생성하지 못했습니다')
        self.assertNotContains(response, 'mock-private-exception')
        self.assertNotIn('goal_nutrition_advice', self.client.session)


class MealPlanSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='meal-plan-owner')
        self.profile = UserProfile.objects.create(
            user=self.user, start_weight=100, current_weight=90, target_weight=80,
            exercise_experience='beginner', exercise_days_per_week=3,
            exercise_minutes_per_session=30, preferred_exercises='걷기',
        )
        self.client.force_login(self.user)
        self.url = reverse('meal_plan')
        self.model_patch = patch('records.views.genai.GenerativeModel')
        self.model = self.model_patch.start().return_value
        self.addCleanup(self.model_patch.stop)
        config_patch = patch('records.views.genai.configure')
        config_patch.start()
        self.addCleanup(config_patch.stop)
        key_patch = patch.dict('os.environ', {'GEMINI_API_KEY': 'mock-only'})
        key_patch.start()
        self.addCleanup(key_patch.stop)
        self.output = {
            'summary': '실제 목표를 참고한 모의 식단',
            'meals': [{'meal_type': code, 'food_name': '모의 메뉴', 'portion': '밥 1공기와 반찬',
                       'calories': 600, 'carbs': 70, 'protein': 30, 'fat': 20, 'reason': '모의 선정 이유'} for code in ('B', 'L', 'D')],
            'notes': ['영양 수치는 추정치입니다.'],
        }
        self.model.generate_content.return_value.text = json.dumps(self.output)

    def test_login_csrf_and_method_protection(self):
        self.client.logout()
        self.assertEqual(self.client.post(self.url).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url).status_code, 403)
        self.client.force_login(self.user)
        self.assertEqual(self.client.delete(self.url).status_code, 405)
        self.model.generate_content.assert_not_called()

    def test_generation_and_get_cache_do_not_create_food_records(self):
        self.assertEqual(self.client.post(self.url, {'food_preferences': '한식'}).status_code, 302)
        for _ in range(2):
            response = self.client.get(self.url)
            self.assertContains(response, '모의 메뉴')
            self.assertEqual(response.context['plan']['totals']['calories'], 1800)
        self.model.generate_content.assert_called_once()
        self.assertFalse(Meal.objects.exists())
        self.assertFalse(DailyRecord.objects.exists())
        self.assertFalse(ChatMessage.objects.exists())

    def test_prompt_uses_only_owner_data_and_actual_goal(self):
        other = User.objects.create_user(username='meal-plan-other')
        UserProfile.objects.create(user=other, current_weight=60, target_weight=55)
        other_record = DailyRecord.objects.create(user=other, date=current_chat_day())
        Meal.objects.create(daily_record=other_record, meal_type='L', food_name='다른 사용자 비밀 음식')
        old = DailyRecord.objects.create(user=self.user, date=current_chat_day()-timedelta(days=7))
        Meal.objects.create(daily_record=old, meal_type='L', food_name='오래된 비밀 음식')
        current = DailyRecord.objects.create(user=self.user, date=current_chat_day())
        Meal.objects.create(daily_record=current, meal_type='L', food_name='본인 최근 음식')
        self.client.post(self.url, {'user_id': other.pk, 'target_weight': '1', 'dietary_restrictions': '땅콩 제외'})
        prompt = self.model.generate_content.call_args.args[0]
        self.assertIn('본인 최근 음식', prompt)
        self.assertIn('땅콩 제외', prompt)
        self.assertIn('"target_weight": 80.0', prompt)
        self.assertIn('운동 경험: 초급', prompt)
        self.assertNotIn('다른 사용자 비밀 음식', prompt)
        self.assertNotIn('오래된 비밀 음식', prompt)

    def test_missing_goal_does_not_call_ai(self):
        self.profile.target_weight = None
        self.profile.save()
        response = self.client.post(self.url)
        self.assertContains(response, '현재 체중과 목표 체중을 먼저 설정')
        self.model.generate_content.assert_not_called()

    def test_profile_change_and_new_day_invalidate_cached_plan(self):
        self.client.post(self.url)
        self.profile.target_weight = 75
        self.profile.save()
        self.assertIsNone(self.client.get(self.url).context['plan'])
        self.client.post(self.url)
        with patch('records.views.current_chat_day', return_value=current_chat_day()+timedelta(days=1)):
            self.assertIsNone(self.client.get(self.url).context['plan'])

    def test_other_user_cannot_see_cached_plan(self):
        self.client.post(self.url)
        other = User.objects.create_user(username='different-plan-user')
        UserProfile.objects.create(user=other, current_weight=70, target_weight=65)
        self.client.force_login(other)
        self.assertNotContains(self.client.get(self.url), '모의 메뉴')
        self.assertIsNone(self.client.get(self.url).context['plan'])

    def test_provider_error_is_not_exposed_and_old_conditions_are_not_shown(self):
        self.client.post(self.url)
        self.model.generate_content.side_effect = RuntimeError('mock-secret-error')
        response = self.client.post(self.url, {'dietary_restrictions': '새 제한 조건'})
        self.assertContains(response, '식단을 생성하지 못했습니다')
        self.assertNotContains(response, 'mock-secret-error')
        self.assertIsNone(response.context['plan'])

    def test_invalid_input_and_response_are_rejected(self):
        response = self.client.post(self.url, {'food_preferences': 'x'*301})
        self.assertTrue(response.context['plan_form'].errors)
        self.model.generate_content.assert_not_called()
        self.model.generate_content.return_value.text = '{invalid-json'
        self.assertIsNone(self.client.post(self.url).context['plan'])
        from .views import validated_meal_plan
        from copy import deepcopy
        for value in (-1, float('nan'), True, '600'):
            data = deepcopy(self.output)
            data['meals'][0]['calories'] = value
            with self.assertRaises(ValueError):
                validated_meal_plan(json.dumps(data))


class CalendarRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='calendar-owner')
        self.client.force_login(self.user)
        self.credentials = Mock(valid=True)
        self.credentials.to_json.return_value = '{}'
        self.file_patch = patch('records.views.save_google_credentials')
        self.file_patch.start()
        self.addCleanup(self.file_patch.stop)
        for name, kwargs in [
            ('records.views.os.path.exists', {'return_value': True}),
            ('records.views.Credentials.from_authorized_user_file', {'return_value': self.credentials}),
            ('records.views.build', {}),
        ]:
            patcher = patch(name, **kwargs)
            result = patcher.start()
            self.addCleanup(patcher.stop)
            if name.endswith('build'):
                self.build = result
                result.return_value.events.return_value.list.return_value.execute.return_value = {'items': []}

    def test_calendar_events_are_read_and_displayed(self):
        self.build.return_value.events.return_value.list.return_value.execute.return_value = {
            'items': [{'start': {'date': '2026-10-09'}, 'summary': '모의 일정'}],
        }
        response = self.client.get(reverse('exercise_calendar'), {'year': 2026, 'month': 10})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '모의 일정')
        self.build.return_value.events.return_value.insert.assert_not_called()

    def test_expired_token_refresh_success_is_mocked(self):
        self.credentials.valid = False
        self.credentials.expired = True
        self.credentials.refresh_token = 'mock-only-token'
        response = self.client.get(reverse('exercise_calendar'))
        self.assertEqual(response.status_code, 200)
        self.credentials.refresh.assert_called_once()

    def test_refresh_failure_keeps_local_calendar_available(self):
        self.credentials.valid = False
        self.credentials.expired = True
        self.credentials.refresh_token = 'mock-only-token'
        self.credentials.refresh.side_effect = RuntimeError('mock-expired-authorization')
        response = self.client.get(reverse('exercise_calendar'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Google Calendar')

    @patch('records.views.Credentials.from_authorized_user_file', side_effect=ValueError('mock-corrupt-token'))
    def test_corrupt_token_keeps_local_calendar_available(self, credentials):
        self.assertEqual(self.client.get(reverse('exercise_calendar')).status_code, 200)

    def test_missing_connection_points_to_home_without_local_server(self):
        self.credentials.valid = False
        self.credentials.expired = False
        response = self.client.get(reverse('exercise_calendar'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '홈의 Google Calendar 연결 버튼')
        self.build.assert_not_called()

    def test_missing_oauth_connection_keeps_local_calendar_available(self):
        self.credentials.valid = False
        self.credentials.expired = False
        self.assertEqual(self.client.get(reverse('exercise_calendar')).status_code, 200)

    def test_invalid_month_returns_client_error(self):
        self.assertEqual(self.client.get(reverse('exercise_calendar'), {'month': 13}).status_code, 400)

class RecordMutationSafetyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='mutation-owner')
        self.client.force_login(self.user)
        self.daily = DailyRecord.objects.create(user=self.user, date=timezone.localdate())
        self.meal = Meal.objects.create(daily_record=self.daily, meal_type='L', food_name='기존 식사', calories=500)
        self.exercise = Exercise.objects.create(daily_record=self.daily, exercise_name='걷기')

    def test_delete_requires_post_and_csrf(self):
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        for name, item in [('meal_delete', self.meal), ('exercise_delete', self.exercise)]:
            url = reverse(name, args=[item.pk])
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(secure.post(url).status_code, 403)
            self.assertTrue(type(item).objects.filter(pk=item.pk).exists())
            self.assertEqual(self.client.post(url).status_code, 302)
            self.assertFalse(type(item).objects.filter(pk=item.pk).exists())

    def test_invalid_meal_edit_preserves_record(self):
        for data in [dict(meal_type='L',food_name='수정',calories=-1), dict(meal_type='bad',food_name='수정',calories=100), dict(meal_type='L',food_name='',calories=100), dict(meal_type='L',food_name='수정',calories=99999999999999999999)]:
            response = self.client.post(reverse('meal_edit', args=[self.meal.pk]), data)
            self.assertEqual(response.status_code, 200)
            self.meal.refresh_from_db()
            self.assertEqual((self.meal.food_name, self.meal.calories, self.meal.meal_type), ('기존 식사',500,'L'))

    def test_other_user_cannot_delete_records(self):
        other = User.objects.create_user(username='delete-other')
        self.client.force_login(other)
        for name, item in [('meal_delete',self.meal),('exercise_delete',self.exercise)]:
            self.assertEqual(self.client.post(reverse(name,args=[item.pk])).status_code,404)
            self.assertTrue(type(item).objects.filter(pk=item.pk).exists())

    def test_valid_meal_edit_and_unknown_calories(self):
        response = self.client.post(reverse('meal_edit', args=[self.meal.pk]), {'meal_type':'D','food_name':'수정 식사','calories':'350'})
        self.assertEqual(response.status_code,302)
        self.meal.refresh_from_db()
        self.assertEqual((self.meal.food_name,self.meal.calories,self.meal.meal_type),('수정 식사',350,'D'))
        self.client.post(reverse('meal_edit', args=[self.meal.pk]), {'meal_type':'D','food_name':'수정 식사','calories':''})
        self.meal.refresh_from_db()
        self.assertIsNone(self.meal.calories)
