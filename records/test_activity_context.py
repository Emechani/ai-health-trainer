import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from users.models import UserProfile
from .models import DailyRecord, Exercise, GoogleHealthStepRecord
from .views import current_chat_day, recent_record_context


class ActivityContextRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('activity-context-owner')
        self.other = User.objects.create_user('activity-context-other')
        UserProfile.objects.create(user=self.user)
        self.day = current_chat_day()
        GoogleHealthStepRecord.objects.create(user=self.user, date=self.day, steps=7420)
        GoogleHealthStepRecord.objects.create(user=self.other, date=self.day, steps=999999)
        GoogleHealthStepRecord.objects.create(user=self.user, date=self.day-timedelta(days=7), steps=888888)

    def test_health_only_day_is_included_and_other_owner_and_old_days_excluded(self):
        context = recent_record_context(self.user, self.day)
        self.assertIn('7420보', context)
        self.assertNotIn('999999', context)
        self.assertNotIn('888888', context)

    def test_manual_details_are_kept_without_adding_duplicate_steps(self):
        record = DailyRecord.objects.create(user=self.user, date=self.day)
        Exercise.objects.create(daily_record=record, exercise_name='걷기', start_time='09:00',
                                end_time='09:30', distance_km=2, steps=3000)
        context = recent_record_context(self.user, self.day)
        self.assertIn('30.0분', context)
        self.assertIn('2.0km', context)
        self.assertIn('참고 걸음 수: 7420보', context)
        self.assertNotIn('10420보', context)

    def test_chat_receives_activity_even_when_habits_are_unset(self):
        self.client.force_login(self.user)
        with patch.dict('os.environ', {'GEMINI_API_KEY':'mock-only'}), patch('records.views.generate_ai', return_value=SimpleNamespace(text='모의 답변')) as ai:
            response = self.client.post(reverse('ai_chat_api'), json.dumps({'message':'내 운동을 보고 추천해 줘'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        prompt = ai.call_args.args[2]
        self.assertIn('7420보', prompt)
        self.assertIn('운동 습관의', prompt)
        self.assertIn('이 대화 기능은 프로필을 변경하지 않습니다', prompt)
        self.assertNotIn('999999', prompt)
