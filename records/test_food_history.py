import json
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase,TransactionTestCase,Client
from django.urls import reverse
from django.utils import timezone
from users.models import UserProfile
from .models import Meal,DailyRecord,SavedMealPlan
from .nutrition import nutrition_summary


class NutritionAndMealArchiveSafetyTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user(username='archive-owner')
        self.other=User.objects.create_user(username='archive-other')
        UserProfile.objects.create(user=self.user,current_weight=90,target_weight=80,exercise_days_per_week=3,exercise_minutes_per_session=30)
        self.client.force_login(self.user)
        self.day=timezone.localdate()
        self.plan={'summary':'보관용 식단','meals':[{'meal_type':code,'food_name':'보관 메뉴','portion':'밥과 반찬',
            'calories':600,'carbs':70,'protein':30,'fat':20,'reason':'일반 식사 예시'} for code in ['B','L','D']],
            'notes':['추정치이며 개인 처방이 아닙니다.']}
        model_patch=patch('records.views.genai.GenerativeModel')
        self.model=model_patch.start().return_value
        self.addCleanup(model_patch.stop)
        self.model.generate_content.return_value.text=json.dumps(self.plan)
        configure=patch('records.views.genai.configure')
        configure.start()
        self.addCleanup(configure.stop)
        key=patch.dict('os.environ',{'GEMINI_API_KEY':'mock-only'})
        key.start()
        self.addCleanup(key.stop)

    def meal(self):
        daily=DailyRecord.objects.create(user=self.user,date=self.day)
        return Meal.objects.create(daily_record=daily,meal_type='L',food_name='수정 전',calories=500,carbs=60,protein=20,fat=10)

    def generate(self):
        from .test_goal_progress import example_week
        if self.model.generate_content.return_value.text != 'invalid response':
            weekly = example_week()
            weekly['weekly_focus'] = self.plan['summary']
            for day in weekly['days']:
                day['meals'] = self.plan['meals']
            self.model.generate_content.return_value.text = json.dumps(weekly)
        self.client.post(reverse('goal_progress'), {'action':'save_food_options','food_preferences':'한식','dietary_restrictions':'우유 제외'})
        return self.client.post(reverse('goal_progress'))

    def test_manual_nutrients_reload_and_affect_summary(self):
        meal=self.meal()
        response=self.client.get(reverse('meal_edit',args=[meal.pk]))
        self.assertEqual(response.context['form'].initial['protein'],20)
        response=self.client.post(reverse('meal_edit',args=[meal.pk]),{'meal_type':'L','food_name':'수정 후','calories':'450','carbs':'50','protein':'30','fat':'0'})
        self.assertEqual(response.status_code,302)
        meal.refresh_from_db()
        self.assertEqual((meal.carbs,meal.protein,meal.fat),(50,30,0))
        summary=nutrition_summary(self.user,self.day)
        self.assertEqual([row['total'] for row in summary['nutrients']],[450,50,30,0])
        self.assertIn('일부 식사만 기록',summary['messages'][-1])

    def test_blank_and_zero_are_distinct_and_invalid_input_does_not_save(self):
        meal=self.meal()
        data={'meal_type':'L','food_name':'수정 전','calories':'500','carbs':'60','protein':'20','fat':'10'}
        for value in ['-1','2.5','NaN','10001']:
            response=self.client.post(reverse('meal_edit',args=[meal.pk]),dict(data,protein=value))
            self.assertEqual(response.status_code,200)
            meal.refresh_from_db()
            self.assertEqual(meal.protein,20)
        self.client.post(reverse('meal_edit',args=[meal.pk]),dict(data,protein='',fat='0'))
        meal.refresh_from_db()
        self.assertIsNone(meal.protein)
        self.assertEqual(meal.fat,0)
        self.assertEqual(nutrition_summary(self.user,self.day)['complete_count'],0)

    def test_other_user_cannot_edit_macros(self):
        meal=self.meal()
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('meal_edit',args=[meal.pk]),{'protein':'99'}).status_code,404)
        meal.refresh_from_db()
        self.assertEqual(meal.protein,20)

    def test_generation_archives_without_get_duplicates_or_food_records(self):
        self.assertEqual(self.generate().status_code,302)
        saved=SavedMealPlan.objects.get()
        self.assertEqual((saved.user,saved.date,saved.options['dietary_restrictions']),(self.user,self.day,'우유 제외'))
        self.assertEqual(saved.plan['totals']['calories'],1800)
        for _ in range(2):self.client.get(reverse('meal_plan'))
        self.assertEqual(SavedMealPlan.objects.count(),1)
        self.model.generate_content.assert_called_once()
        self.assertFalse(Meal.objects.exists())
        self.assertFalse(DailyRecord.objects.exists())

    def test_same_week_regeneration_reuses_saved_plan(self):
        self.generate()
        first=SavedMealPlan.objects.get()
        self.plan['summary']='다시 생성한 식단'
        self.model.generate_content.return_value.text=json.dumps(self.plan)
        self.generate()
        self.assertEqual(SavedMealPlan.objects.filter(date=self.day).count(),1)
        first.refresh_from_db()
        self.assertEqual(first.plan['summary'],'보관용 식단')

    def test_history_remains_after_session_clear_and_profile_change(self):
        self.generate()
        saved=SavedMealPlan.objects.get()
        UserProfile.objects.filter(user=self.user).update(current_weight=85,target_weight=75)
        self.client.logout()
        self.client.force_login(self.user)
        response=self.client.get(reverse('saved_meal_plan',args=[saved.pk]))
        self.assertContains(response,'보관용 식단')
        self.assertContains(response,'우유 제외')
        self.assertContains(response,'읽기 전용')
        self.assertEqual(response.context['plan']['totals']['protein'],90)
        self.model.generate_content.assert_called_once()

    def test_archive_access_requires_owner_login_and_read_only_method(self):
        self.generate()
        saved=SavedMealPlan.objects.get()
        detail=reverse('saved_meal_plan',args=[saved.pk])
        self.assertEqual(self.client.post(detail).status_code,405)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(detail).status_code,404)
        self.assertNotContains(self.client.get(reverse('meal_plan_history')),'1800')
        self.client.logout()
        self.assertEqual(self.client.get(detail).status_code,302)
        self.assertEqual(self.client.get(reverse('meal_plan_history')).status_code,302)
        self.assertEqual(SavedMealPlan.objects.count(),1)

    def test_generation_keeps_csrf_protection(self):
        secure=Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        self.assertEqual(secure.post(reverse('meal_plan'),{'action':'meal_plan'}).status_code,403)
        self.assertFalse(SavedMealPlan.objects.exists())

    def test_history_date_filter_pagination_empty_and_invalid_dates(self):
        empty=self.client.get(reverse('meal_plan_history'))
        self.assertContains(empty,'보관된 식단이 없습니다')
        self.generate()
        saved=SavedMealPlan.objects.get()
        SavedMealPlan.objects.bulk_create([SavedMealPlan(user=self.user,date=self.day-timedelta(days=1),plan=saved.plan,options={},model_name='mock') for _ in range(11)])
        response=self.client.get(reverse('meal_plan_history'))
        self.assertEqual(len(response.context['history_page']),10)
        response=self.client.get(reverse('meal_plan_history'),{'date':self.day.isoformat()})
        self.assertEqual(response.context['history_page'].paginator.count,1)
        for value in ['bad-date',(self.day+timedelta(days=1)).isoformat()]:
            response=self.client.get(reverse('meal_plan_history'),{'date':value})
            self.assertTrue(response.context['history_form'].errors)
            self.assertEqual(response.context['history_page'].paginator.count,0)

    def test_failed_generation_and_nutrition_advice_do_not_archive(self):
        self.model.generate_content.return_value.text='invalid response'
        self.assertEqual(self.generate().status_code,302)
        self.assertFalse(SavedMealPlan.objects.exists())
        self.meal()
        self.model.generate_content.return_value.text=json.dumps({'summary':'부분 기록 안내','items':[{'nutrient':'기록','observation':'부분 기록','suggestion':'확인해 주세요'}],'cautions':['결핍을 진단하지 않습니다.']})
        response=self.client.post(reverse('meal_plan'),{'action':'nutrition_advice'})
        self.assertEqual(response.status_code,302)
        self.assertFalse(SavedMealPlan.objects.exists())


class MealArchiveMigrationSafetyTests(TransactionTestCase):
    def test_new_table_preserves_existing_meal_nutrients(self):
        previous=[('records','0007_alter_dailyrecord_date')]
        latest=[('records','0008_saved_meal_plans')]
        executor=MigrationExecutor(connection)
        try:
            executor.migrate(previous)
            apps=executor.loader.project_state(previous).apps
            user=apps.get_model('auth','User').objects.create(username='pre-archive-user')
            daily=apps.get_model('records','DailyRecord').objects.create(user=user,date=timezone.localdate())
            meal=apps.get_model('records','Meal').objects.create(daily_record=daily,meal_type='L',food_name='기존 식사',calories=500,carbs=60,protein=None,fat=0)
            executor=MigrationExecutor(connection)
            executor.migrate(latest)
            apps=executor.loader.project_state(latest).apps
            meal=apps.get_model('records','Meal').objects.get(pk=meal.pk)
            self.assertEqual((meal.food_name,meal.calories,meal.carbs,meal.protein,meal.fat),('기존 식사',500,60,None,0))
            self.assertEqual(apps.get_model('records','SavedMealPlan').objects.count(),0)
        finally:
            executor=MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
