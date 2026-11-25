import copy
import json
from datetime import date,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth.models import User
from django.db import DatabaseError
from django.test import TestCase,Client,override_settings
from django.urls import reverse
from users.models import UserProfile
from .models import GoalPlan,SavedMealPlan,DailyRecord,Exercise
from .test_goal_progress import example_week
from .goal_progress import validated_weekly_goal
from .views import validated_meal_plan
from .plan_revision import SESSION_KEY


@override_settings(GOOGLE_ACTIVITY_PROVIDER='google_health',GOOGLE_TOKEN_DIR=Path(__file__).parent/'__missing_revision_test_tokens__')
class PlanRevisionTests(TestCase):
    def setUp(self):
        self.today=date(2026,11,25)
        day=patch('records.views.current_chat_day',return_value=self.today);day.start();self.addCleanup(day.stop)
        self.user=User.objects.create_user('revision-owner')
        self.profile=UserProfile.objects.create(user=self.user,current_weight=100,target_weight=90,
            exercise_days_per_week=3,exercise_minutes_per_session=30,preferred_exercises='걷기')
        self.raw=example_week()
        snapshot,exercise=validated_weekly_goal(json.dumps(self.raw),self.profile,validated_meal_plan,require_daily=True)
        self.base=GoalPlan.objects.create(user=self.user,start_date=date(2026,11,23),end_date=date(2026,11,29),
            current_weight=100,target_weight=90,meal_snapshot=snapshot,**exercise)
        record=DailyRecord.objects.create(user=self.user,date=self.today)
        self.record=Exercise.objects.create(daily_record=record,exercise_name='걷기',start_time='09:00',end_time='09:30',steps=3000)
        self.client.force_login(self.user)
        self.url=reverse('plan_revision')
        self.changed=copy.deepcopy(self.raw)
        self.changed['days'][2]['exercise']['minutes']=10
        self.ai=patch('records.views.generate_ai',return_value=SimpleNamespace(text=json.dumps(self.changed))).start()
        self.addCleanup(patch.stopall)

    def post(self,action='propose',**values):
        data={'action':action,'message':'오늘부터 걷기를 10분으로 줄여줘','date':self.today.isoformat(),**values}
        return self.client.post(self.url,json.dumps(data),content_type='application/json')

    def proposal(self):
        response=self.post()
        self.assertEqual(response.status_code,200,response.content)
        return response.json()['proposal']

    def test_preview_does_not_change_plan_and_can_be_restored(self):
        draft=self.proposal()
        self.assertEqual(GoalPlan.objects.count(),1)
        self.assertEqual(SavedMealPlan.objects.count(),0)
        self.base.refresh_from_db()
        self.assertEqual(self.base.meal_snapshot['daily_schedule'][2]['exercise_minutes'],20)
        self.assertEqual(self.client.get(self.url).json()['proposal']['nonce'],draft['nonce'])
        self.assertEqual(len(draft['changes']),1)
        self.assertNotIn('snapshot',draft)
        self.assertEqual(self.post().json()['proposal']['nonce'],draft['nonce'])
        self.ai.assert_called_once()

    def test_apply_creates_new_active_plan_and_preserves_records_and_previous_days(self):
        draft=self.proposal()
        response=self.post('apply',nonce=draft['nonce'],snapshot={'malicious':'ignored'})
        self.assertEqual(response.status_code,200,response.content)
        revised=GoalPlan.objects.filter(user=self.user).first()
        self.assertNotEqual(revised.pk,self.base.pk)
        self.assertEqual(revised.meal_snapshot['daily_schedule'][2]['exercise_minutes'],10)
        self.assertEqual(revised.meal_snapshot['daily_schedule'][:2],self.base.meal_snapshot['daily_schedule'][:2])
        self.assertTrue(Exercise.objects.filter(pk=self.record.pk,steps=3000).exists())
        self.assertEqual(GoalPlan.objects.count(),2)
        self.assertEqual(self.client.get(reverse('goal_progress')).context['active_week_plan'].pk,revised.pk)
        with patch('main.views.timezone.localdate',return_value=self.today):
            home=self.client.get(reverse('home'))
        self.assertEqual(home.context['home_goal_plan'].pk,revised.pk)
        self.assertEqual(home.context['home_today_plan']['target_minutes'],10)
        self.assertEqual(self.post('apply',nonce=draft['nonce']).status_code,409)
        self.assertEqual(GoalPlan.objects.count(),2)

    def test_cancel_keeps_original_plan(self):
        draft=self.proposal()
        self.assertEqual(self.post('dismiss',nonce=draft['nonce']).status_code,200)
        self.assertIsNone(self.client.get(self.url).json()['proposal'])
        self.assertEqual(GoalPlan.objects.count(),1)

    def test_other_user_cannot_read_or_apply_proposal(self):
        draft=self.proposal()
        other=User.objects.create_user('revision-other')
        UserProfile.objects.create(user=other,current_weight=100,target_weight=90)
        self.client.force_login(other)
        self.assertIsNone(self.client.get(self.url).json()['proposal'])
        self.assertEqual(self.post('apply',nonce=draft['nonce']).status_code,409)

    def test_expired_proposal_is_rejected(self):
        draft=self.proposal();session=self.client.session
        session[SESSION_KEY]['expires_at']=0;session.save()
        self.assertEqual(self.post('apply',nonce=draft['nonce']).status_code,409)

    def test_profile_changed_after_preview_is_rejected(self):
        draft=self.proposal()
        UserProfile.objects.filter(pk=self.profile.pk).update(target_weight=85)
        self.assertEqual(self.post('apply',nonce=draft['nonce']).status_code,409)
        self.assertEqual(GoalPlan.objects.count(),1)

    def test_profile_changed_during_ai_is_rejected(self):
        def change(*args,**kwargs):
            UserProfile.objects.filter(pk=self.profile.pk).update(exercise_minutes_per_session=15)
            return SimpleNamespace(text=json.dumps(self.changed))
        self.ai.side_effect=change
        self.assertEqual(self.post().status_code,409)
        self.assertNotIn(SESSION_KEY,self.client.session)

    def test_modified_original_plan_is_rejected(self):
        draft=self.proposal()
        self.base.meal_snapshot['summary']='다른 수정'
        self.base.save(update_fields=['meal_snapshot'])
        self.assertEqual(self.post('apply',nonce=draft['nonce']).status_code,409)

    def test_limits_and_invalid_response_are_rejected(self):
        self.changed['days'][2]['exercise']['minutes']=90
        self.ai.return_value.text=json.dumps(self.changed)
        self.assertEqual(self.post().status_code,502)
        self.assertNotIn(SESSION_KEY,self.client.session)
        self.assertEqual(GoalPlan.objects.count(),1)

    def test_past_ai_changes_are_ignored(self):
        self.changed['days'][0]['action']='과거를 바꾸라는 AI 응답'
        self.ai.return_value.text=json.dumps(self.changed)
        draft=self.proposal()
        self.assertEqual([item['date'] for item in draft['changes']],[self.today.isoformat()])

    def test_requested_swimming_is_allowed_without_changing_preferences(self):
        self.changed['days'][2]['exercise']['name']='수영'
        self.ai.return_value.text=json.dumps(self.changed)
        response=self.post(message='오늘 걷기를 수영 10분으로 바꿔줘')
        self.assertEqual(response.status_code,200,response.content)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.preferred_exercises,'걷기')

    def test_database_failure_rolls_back_all_new_plan_data(self):
        draft=self.proposal()
        with patch('records.plan_revision.GoalPlan.objects.create',side_effect=DatabaseError('private database details')):
            response=self.post('apply',nonce=draft['nonce'])
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private database details',response.content.decode())
        self.assertEqual(SavedMealPlan.objects.count(),0)
        self.assertEqual(GoalPlan.objects.count(),1)

    def test_methods_login_csrf_and_malformed_requests(self):
        self.assertEqual(self.client.delete(self.url).status_code,405)
        self.assertEqual(self.client.post(self.url,'[]',content_type='application/json').status_code,400)
        self.assertEqual(self.post(message='').status_code,400)
        self.assertEqual(self.post(date='2026-11-24').status_code,409)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user)
        self.assertEqual(secure.post(self.url,'{}',content_type='application/json').status_code,403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code,302)
        self.ai.assert_not_called()

    def test_missing_active_plan_does_not_call_ai(self):
        self.base.delete()
        self.assertEqual(self.post().status_code,400)
        self.ai.assert_not_called()

    def test_invalid_nonce_and_next_day_do_not_apply(self):
        draft=self.proposal()
        self.assertEqual(self.post('apply',nonce='잘못된 값').status_code,409)
        with patch('records.views.current_chat_day',return_value=self.today+timedelta(days=1)):
            self.assertEqual(self.post('apply',nonce=draft['nonce']).status_code,409)
