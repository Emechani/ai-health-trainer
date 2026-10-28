import json
from datetime import timedelta,time
from unittest.mock import patch
from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase,TransactionTestCase,SimpleTestCase,Client,override_settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from users.models import UserProfile
from .models import Meal,Exercise,DailyRecord,SavedMealPlan,GoalPlan
from .goal_progress import nutrition_similarity,goal_progress_data,weekly_goal_error,weekly_record_context,validated_weekly_goal


def example_plan():
    return {'summary':'목표를 참고한 식단','meals':[{'meal_type':code,'label':label,'food_name':'예시 밥과 반찬',
        'portion':'1인분','calories':600,'carbs':70,'protein':30,'fat':20,'reason':'일반 식사 예시'}
        for code,label in [('B','아침'),('L','점심'),('D','저녁')]],
        'totals':{'calories':1800,'carbs':210,'protein':90,'fat':60},'notes':['개인 처방이 아닙니다.']}


def example_week():
    days=[]
    for weekday in range(7):
        meal=example_plan()
        for item in meal['meals']:
            item['food_name']=f'{weekday}요일 음식 {item["meal_type"]}'
        active=weekday in (0,2,4)
        days.append({'weekday':weekday, 'exercise':{'name':'걷기' if active else '', 'minutes':20 if active else 0},
            'action':'세 끼와 오늘 활동을 기록해 보세요.', 'meals':meal['meals']})
    return {'weekly_focus':'이번 주 걷기와 세 끼 기록','motivation':'작은 실천을 이어가 보세요.',
        'reason':'가능 시간 안에서 편안하게 걷고 쉬세요.','notes':['추정치입니다. 성분을 확인하세요.'], 'days':days}


class GoalSimilarityTests(SimpleTestCase):
    def test_model_overload_is_distinct_from_connection_failure(self):
        from google.api_core.exceptions import ServiceUnavailable
        message=weekly_goal_error(ServiceUnavailable('Model high demand private-api-error'),'api')
        self.assertIn('현재 Gemini 모델에 요청이 몰려',message)
        self.assertNotIn('private-api-error',message)
        self.assertIn('일시적으로 연결할 수 없습니다',weekly_goal_error(ServiceUnavailable('offline'),'api'))

    def test_equal_half_excess_missing_and_zero(self):
        target={'calories':600,'carbs':70,'protein':30,'fat':20}
        self.assertEqual(nutrition_similarity(target,target),1)
        self.assertEqual(nutrition_similarity({key:value/2 for key,value in target.items()},target),.5)
        self.assertEqual(nutrition_similarity({key:value*3 for key,value in target.items()},target),0)
        self.assertIsNone(nutrition_similarity(dict(target,protein=None),target))
        self.assertIsNone(nutrition_similarity(dict(target,protein=-1),target))
        self.assertIsNone(nutrition_similarity(dict(target,protein=True),target))
        self.assertEqual(nutrition_similarity(dict(target,fat=0),dict(target,fat=0)),1)


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                     'LOCATION': 'goal-progress-isolated-tests'}})
class GoalProgressSafetyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user=User.objects.create_user(username='goal-owner')
        self.other=User.objects.create_user(username='goal-other')
        self.profile=UserProfile.objects.create(user=self.user,start_weight=100,current_weight=90,target_weight=80,
            exercise_days_per_week=3,exercise_minutes_per_session=30,preferred_exercises='걷기, 수영')
        self.client.force_login(self.user)
        self.today=timezone.localdate()
        self.saved=SavedMealPlan.objects.create(user=self.user,date=self.today,plan=example_plan(),options={},model_name='mock',profile_snapshot={'current_weight':90,'target_weight':80})

    def plan(self,**kwargs):
        data={'user':self.user,'start_date':self.today-timedelta(days=6),'end_date':self.today,
            'current_weight':90,'target_weight':80,'meal_snapshot':example_plan(),
            'exercise_name':'걷기','exercise_days':3,'exercise_minutes':20,'saved_meal_plan':self.saved}
        data.update(kwargs)
        return GoalPlan.objects.create(**data)

    def meals(self,day,user=None,factor=1):
        daily,_=DailyRecord.objects.get_or_create(user=user or self.user,date=day)
        for code in ['B','L','D']:
            Meal.objects.create(daily_record=daily,meal_type=code,food_name='식사',calories=600*factor,carbs=70*factor,protein=30*factor,fat=20*factor)
        return daily

    def post(self,**kwargs):
        api_error=kwargs.pop('_api_error', None)
        response_data=kwargs.pop('_ai_response', example_week())
        with patch.dict('os.environ',{'GEMINI_API_KEY':'mock-key'}), patch('records.views.genai.GenerativeModel') as model:
            model.return_value.generate_content.return_value.text=json.dumps(response_data,ensure_ascii=False)
            if api_error:
                model.return_value.generate_content.side_effect=api_error
            response=self.client.post(reverse('goal_progress'),kwargs)
            self.ai_calls=model.return_value.generate_content.call_count
            self.ai_model=model.call_args.args[0] if model.called else None
            return response

    def test_weekly_model_is_independent_of_other_ai_features(self):
        with patch.dict('os.environ',{'WEEKLY_GOAL_MODEL':'','GEMINI_MODEL':'gemini-3.6-flash'}):
            self.assertEqual(self.post().status_code,302)
        self.assertEqual(self.ai_model,'gemini-3.5-flash-lite')

    def test_weekly_input_is_bounded_and_owner_only(self):
        daily=DailyRecord.objects.create(user=self.user,date=self.today)
        for index in range(23):
            Meal.objects.create(daily_record=daily,meal_type='B',food_name='가'*200,calories=600)
        for index in range(16):
            Exercise.objects.create(daily_record=daily,exercise_name='걷기')
        other=DailyRecord.objects.create(user=self.other,date=self.today)
        Meal.objects.create(daily_record=other,meal_type='B',food_name='다른 사용자 음식')
        result=weekly_record_context(self.user,self.today)
        self.assertEqual(len(result['meals']),21)
        self.assertEqual(len(result['exercises']),14)
        self.assertTrue(result['more_meals_omitted'])
        self.assertTrue(result['more_exercises_omitted'])
        self.assertTrue(all(len(item['food_name'])==60 for item in result['meals']))

    def test_page_and_creation_use_ai_with_actual_goal(self):
        with patch('records.views.genai.GenerativeModel') as model:
            self.assertContains(self.client.get(reverse('goal_progress')),'AI가 정해 주는 이번 주 목표')
            model.assert_not_called()
        response=self.post(user_id=self.other.pk,target_weight='1',exercise_days='7')
        self.assertEqual(self.ai_calls,1)
        self.assertEqual(response.status_code,302)
        goal=GoalPlan.objects.get()
        self.assertEqual((goal.user,goal.current_weight,goal.target_weight),(self.user,90,80))
        self.assertEqual(goal.start_date,self.today-timedelta(days=self.today.weekday()))
        self.assertEqual(goal.end_date,goal.start_date+timedelta(days=6))
        self.assertEqual(goal.exercise_days,3)
        self.assertContains(self.client.get(response.url),'전체 실천')
        self.assertFalse(Meal.objects.exists())
        self.assertEqual(self.post().status_code,302)
        self.assertEqual(self.ai_calls,0)
        self.assertEqual(GoalPlan.objects.count(),1)

    def test_other_user_plan_and_meal_choice_are_blocked(self):
        goal=self.plan(user=self.other)
        self.assertEqual(self.client.get(reverse('goal_progress'),{'plan':goal.pk}).status_code,404)
        self.saved.user=self.other
        self.saved.save()
        self.assertEqual(self.post(meal_plan=self.saved.pk).status_code,302)
        own=GoalPlan.objects.get(user=self.user)
        self.assertNotEqual(own.saved_meal_plan_id,self.saved.pk)
        self.assertEqual(own.saved_meal_plan.user,self.user)

    def test_csrf_and_login_are_required(self):
        secure=Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        self.assertEqual(secure.post(reverse('goal_progress'),{}).status_code,403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('goal_progress')).status_code,302)
        self.assertFalse(GoalPlan.objects.exists())

    def test_goal_and_availability_changes_cannot_be_bypassed(self):
        bad={'weekly_focus':'이번 주 목표','motivation':'함께 해요','reason':'이유',
             'exercise':{'name':'걷기','days':4,'minutes':20},'meal_plan':example_plan()}
        self.assertEqual(self.post(_ai_response=bad).status_code,302)
        self.assertFalse(GoalPlan.objects.exists())
        self.assertEqual(SavedMealPlan.objects.count(),1)
        self.profile.target_weight=75
        self.profile.save()
        session=self.client.session
        session.pop('weekly_goal_last_attempt',None)
        session.save()
        self.assertEqual(self.post(target_weight='1').status_code,302)
        self.assertEqual(GoalPlan.objects.get().target_weight,75)

    def test_failure_reason_survives_cooldown_without_exposing_api_error(self):
        from google.api_core.exceptions import ResourceExhausted
        response=self.post(_api_error=ResourceExhausted('private-api-error'))
        self.assertEqual(response.status_code,302)
        page=self.client.get(response.url)
        self.assertContains(page,'AI 요청 한도 또는 할당량을 초과했습니다.')
        self.assertNotContains(page,'private-api-error')
        self.assertGreater(page.context['goal_retry_seconds'],0)
        repeated=self.post()
        self.assertEqual(self.ai_calls,0)
        self.assertContains(repeated,'AI 요청 한도 또는 할당량을 초과했습니다.')
        self.assertFalse(GoalPlan.objects.exists())

    def daily_plan(self):
        from .views import validated_meal_plan
        snapshot,exercise=validated_weekly_goal(json.dumps(example_week()),self.profile,validated_meal_plan,require_daily=True)
        monday=self.today-timedelta(days=self.today.weekday())
        return self.plan(start_date=monday,end_date=monday+timedelta(days=6),meal_snapshot=snapshot,**exercise)

    def test_daily_rest_does_not_fill_exercise_gauge(self):
        goal=self.daily_plan()
        rest=goal.start_date+timedelta(days=1)
        daily,_=DailyRecord.objects.get_or_create(user=self.user,date=rest)
        Exercise.objects.create(daily_record=daily,exercise_name='걷기',start_time=time(10),end_time=time(11))
        progress=goal_progress_data(goal,goal.end_date)
        self.assertEqual(progress['exercise_percent'],0)
        self.assertTrue(progress['rows'][1]['rest'])

    def test_daily_meals_and_exercise_use_each_days_targets(self):
        goal=self.daily_plan()
        for offset in range(7):
            daily=self.meals(goal.start_date+timedelta(days=offset))
            if offset in (0,2,4):
                Exercise.objects.create(daily_record=daily,exercise_name='걷기',start_time=time(10),end_time=time(10,20))
        progress=goal_progress_data(goal,goal.end_date)
        self.assertEqual(progress['total_percent'],100)
        self.assertTrue(progress['daily_schedule'])
        self.assertEqual(progress['today_plan']['date'],goal.end_date)
        self.assertNotEqual(progress['rows'][0]['planned_meals'][0]['food_name'],progress['rows'][1]['planned_meals'][0]['food_name'])
        goal.meal_snapshot['daily_schedule'][1]['meals'][0]['calories']=1200
        progress=goal_progress_data(goal,goal.end_date)
        self.assertEqual(progress['rows'][1]['meals'][0]['similarity'],87.5)
        self.assertEqual(progress['rows'][0]['meals'][0]['similarity'],100)

    def test_daily_validation_rejects_missing_dates_and_excess_training(self):
        from .views import validated_meal_plan
        for change in ['missing','duplicate','minutes','days']:
            data=example_week()
            if change=='missing': data['days'].pop()
            elif change=='duplicate': data['days'][1]['weekday']=0
            elif change=='minutes': data['days'][0]['exercise']['minutes']=100
            else: data['days'][1]['exercise']={'name':'걷기','minutes':20}
            with self.subTest(change=change),self.assertRaises(ValueError):
                validated_weekly_goal(json.dumps(data),self.profile,validated_meal_plan,require_daily=True)

    def test_complete_week_caps_at_100_and_ignores_other_users(self):
        goal=self.plan()
        for offset in range(7):
            daily=self.meals(goal.start_date+timedelta(days=offset))
            Exercise.objects.create(daily_record=daily,exercise_name='걷기',start_time=time(10),end_time=time(11))
        self.meals(self.today,self.other)
        progress=goal_progress_data(goal,self.today)
        self.assertEqual(progress['total_percent'],100)
        self.assertEqual(progress['meal_count_compared'],21)
        self.assertEqual(progress['exercise_days_done'],3)
        self.assertEqual(progress['exercise_percent'],100)

    def test_duplicate_intervals_and_wrong_exercise_do_not_fill_gauge(self):
        goal=self.plan()
        daily,_=DailyRecord.objects.get_or_create(user=self.user,date=self.today)
        for _ in range(2):Exercise.objects.create(daily_record=daily,exercise_name='걷기',start_time=time(10),end_time=time(10,10))
        Exercise.objects.create(daily_record=daily,exercise_name='달리기',start_time=time(8),end_time=time(12))
        progress=goal_progress_data(goal,self.today)
        self.assertEqual(progress['rows'][-1]['minutes'],10)
        self.assertEqual(progress['exercise_percent'],16.7)

    def test_meal_fragments_are_aggregated_and_unknown_is_not_zero(self):
        goal=self.plan(exercise_days=0,exercise_minutes=0)
        daily=self.meals(self.today,factor=.5)
        Meal.objects.create(daily_record=daily,meal_type='B',food_name='나머지',calories=300,carbs=35,protein=15,fat=10)
        progress=goal_progress_data(goal,self.today)
        self.assertEqual(progress['rows'][-1]['meals'][0]['similarity'],100)
        self.assertEqual(progress['rows'][-1]['meals'][1]['similarity'],50)
        Meal.objects.filter(daily_record=daily,meal_type='B').update(protein=None)
        progress=goal_progress_data(goal,self.today)
        self.assertIsNone(progress['rows'][-1]['meals'][0]['similarity'])
        self.assertEqual(progress['rows'][-1]['meals'][0]['status'],'비교 불가')
        self.assertIsNone(progress['exercise_percent'])

    def test_future_and_outside_window_do_not_count(self):
        goal=self.plan(start_date=self.today,end_date=self.today+timedelta(days=6))
        self.meals(self.today+timedelta(days=1))
        self.meals(self.today-timedelta(days=1))
        progress=goal_progress_data(goal,self.today)
        self.assertEqual(progress['total_percent'],0)
        self.assertEqual(progress['meal_count_compared'],0)
        self.assertTrue(progress['rows'][1]['future'])

    def test_regeneration_and_snapshot_do_not_overwrite_previous_plan(self):
        first=self.plan()
        self.assertEqual(self.post().status_code,302)
        self.saved.plan=example_plan()
        self.saved.plan['summary']='보관 식단 변경'
        self.saved.save()
        first.refresh_from_db()
        self.assertEqual(first.meal_snapshot['summary'],'목표를 참고한 식단')
        self.assertEqual(GoalPlan.objects.count(),2)
        self.profile.target_weight=75
        self.profile.save()
        self.assertTrue(self.client.get(reverse('goal_progress'),{'plan':first.pk}).context['goal_changed'])


class GoalMigrationSafetyTests(TransactionTestCase):
    def test_existing_archive_and_meals_are_preserved(self):
        previous=[('records','0008_saved_meal_plans')]
        executor=MigrationExecutor(connection)
        try:
            executor.migrate(previous)
            apps=executor.loader.project_state(previous).apps
            user=apps.get_model('auth','User').objects.create(username='before-goal')
            saved=apps.get_model('records','SavedMealPlan').objects.create(user=user,date=timezone.localdate(),plan=example_plan(),options={'food_preferences':'한식'},model_name='mock')
            executor=MigrationExecutor(connection)
            latest=[('records','0009_goal_practice_plan')]
            executor.migrate(latest)
            apps=executor.loader.project_state(latest).apps
            reloaded=apps.get_model('records','SavedMealPlan').objects.get(pk=saved.pk)
            self.assertEqual(reloaded.plan,example_plan())
            self.assertEqual(reloaded.options,{'food_preferences':'한식'})
            self.assertEqual(reloaded.profile_snapshot,{})
            self.assertEqual(apps.get_model('records','GoalPlan').objects.count(),0)
        finally:
            executor=MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
