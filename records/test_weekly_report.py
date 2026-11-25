import json
from datetime import date, time, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from ai_engine.client import AIError
from users.models import UserProfile, WeightRecord
from .goal_progress import validated_weekly_goal
from .models import DailyRecord, Exercise, GoalPlan, GoogleHealthStepRecord, Meal, WeeklyReport
from .test_goal_progress import example_week
from .views import validated_meal_plan
from .weekly_report import report_data, validated_analysis


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                     'LOCATION': 'weekly-report-tests'}})
class WeeklyReportTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.today = date(2026, 11, 25)
        self.start = date(2026, 11, 23)
        clock = patch('records.weekly_report.timezone.localdate', return_value=self.today)
        clock.start()
        self.addCleanup(clock.stop)
        self.owner = User.objects.create_user('report-owner')
        self.other = User.objects.create_user('report-other')
        self.profile = UserProfile.objects.create(user=self.owner, current_weight=100, target_weight=90,
            exercise_days_per_week=3, exercise_minutes_per_session=30, preferred_exercises='걷기')
        self.record = DailyRecord.objects.create(user=self.owner, date=self.today)
        self.exercise = Exercise.objects.create(daily_record=self.record, exercise_name='걷기',
            start_time=time(9), end_time=time(9, 30), steps=3000)
        self.meal = Meal.objects.create(daily_record=self.record, meal_type='B', food_name='아침 식사')
        self.client.force_login(self.owner)
        self.url = reverse('weekly_report')
        self.analysis = {'highlights': ['운동 기록을 남겼어요.'], 'improvements': ['시간을 꾸준히 기록해 보세요.'],
                         'next_steps': ['편안한 강도로 이어가세요.']}
        self.ai = patch('records.weekly_report.generate', return_value=SimpleNamespace(text=json.dumps(self.analysis))).start()
        self.addCleanup(patch.stopall)

    def data(self):
        return report_data(self.owner, self.start, self.today)

    def post(self):
        return self.client.post(self.url, {'action': 'analyze'})

    def plan(self):
        snapshot, exercise = validated_weekly_goal(json.dumps(example_week()), self.profile, validated_meal_plan, require_daily=True)
        return GoalPlan.objects.create(user=self.owner, start_date=self.start, end_date=self.start + timedelta(days=6),
            current_weight=100, target_weight=90, meal_snapshot=snapshot, **exercise)

    def test_stats_merge_overlapping_time_and_keep_unknown_meals(self):
        Exercise.objects.create(daily_record=self.record, exercise_name='스트레칭', start_time=time(9, 15), end_time=time(9, 45))
        Exercise.objects.create(daily_record=self.record, exercise_name='수영')
        GoogleHealthStepRecord.objects.create(user=self.owner, date=self.today, steps=5000)
        totals = self.data()['totals']
        self.assertEqual(totals['steps'], 5000)
        self.assertEqual(totals['minutes'], 45)
        self.assertEqual(totals['exercise_count'], 3)
        self.assertEqual(totals['untimed_count'], 1)
        self.assertEqual(totals['meal_days'], 1)
        self.assertEqual(totals['elapsed_days'], 3)
        self.assertEqual(self.data()['days'][0]['meal_count'], 0)

    def test_legacy_fit_and_manual_steps_do_not_double_count(self):
        Exercise.objects.create(daily_record=self.record, exercise_name=Exercise.GOOGLE_FIT_NAME,
            start_time=time(8), end_time=time(8, 30), steps=5000)
        GoogleHealthStepRecord.objects.create(user=self.owner, date=self.today, steps=5000)
        totals = self.data()['totals']
        self.assertEqual(totals['steps'], 5000)
        self.assertEqual(totals['exercise_count'], 1)
        self.assertEqual(totals['minutes'], 30)

    def test_health_only_day_and_zero_are_known_not_missing(self):
        GoogleHealthStepRecord.objects.create(user=self.owner, date=self.start, steps=0)
        GoogleHealthStepRecord.objects.create(user=self.owner, date=self.start + timedelta(days=1), steps=7000)
        data = self.data()
        self.assertTrue(data['days'][0]['known_steps'])
        self.assertEqual(data['totals']['steps'], 10000)
        self.assertEqual(data['totals']['step_days'], 3)
        self.assertEqual(data['days'][1]['bar_percent'], 100)

    def test_future_and_other_user_and_outside_week_are_excluded(self):
        for user, day in [(self.other, self.today), (self.owner, self.today + timedelta(days=1)),
                          (self.owner, self.start - timedelta(days=1))]:
            GoogleHealthStepRecord.objects.create(user=user, date=day, steps=999999)
            record = DailyRecord.objects.create(user=user, date=day)
            Exercise.objects.create(daily_record=record, exercise_name='PRIVATE_EXERCISE', steps=999999)
        data = self.data()
        self.assertEqual(data['totals']['steps'], 3000)
        self.assertEqual(data['totals']['exercise_count'], 1)
        self.assertTrue(data['days'][3]['future'])
        self.assertNotIn('PRIVATE_EXERCISE', json.dumps(data['source'], default=str))

    def test_weight_requires_two_actual_measurements(self):
        self.assertIsNone(self.data()['totals']['weight_change'])
        WeightRecord.objects.create(user=self.owner, date=self.start, weight=101)
        self.assertIsNone(self.data()['totals']['weight_change'])
        WeightRecord.objects.create(user=self.owner, date=self.today, weight=100.5)
        WeightRecord.objects.create(user=self.other, date=self.today, weight=77)
        self.assertEqual(self.data()['totals']['weight_change'], -0.5)

    def test_newest_plan_is_used_and_real_records_untouched(self):
        old = self.plan()
        new = self.plan()
        data = self.data()
        self.assertEqual(data['plan'].pk, new.pk)
        self.assertEqual(data['plan_rows'][2]['minutes'], 30)
        self.assertEqual(len(data['plan_rows']), 7)
        self.assertTrue(GoalPlan.objects.filter(pk=old.pk).exists())

    def test_get_never_calls_ai_and_page_has_navigation_and_cards(self):
        response = self.client.get(self.url)
        self.assertContains(response, '주간 건강 리포트')
        self.assertContains(response, '일주일 활동 기록')
        self.assertContains(response, 'AI 주간 분석 받기')
        self.ai.assert_not_called()

    def test_anonymous_and_csrf_are_protected(self):
        self.assertEqual(Client().get(self.url).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(self.url, {'action': 'analyze'}).status_code, 403)
        self.ai.assert_not_called()

    def test_week_selection_normalizes_to_monday_and_rejects_invalid_dates(self):
        response = self.client.get(self.url, {'week': '2026-11-18'})
        self.assertEqual(response.context['week_start'], date(2026, 11, 16))
        self.assertEqual(response.context['totals']['elapsed_days'], 7)
        for value in ('bad-date', '2026-11-30', '0001-01-01', '9999-12-31'):
            self.assertEqual(self.client.get(self.url, {'week': value}).status_code, 400)
        self.assertEqual(self.client.delete(self.url).status_code, 405)
        self.assertEqual(self.client.post(self.url, {'action': 'unknown'}).status_code, 400)

    def test_analysis_saves_and_get_and_repeat_post_reuse_result(self):
        self.assertEqual(self.post().status_code, 302)
        saved = WeeklyReport.objects.get(user=self.owner)
        self.assertEqual(saved.analysis, self.analysis)
        self.assertEqual(saved.source_hash, self.data()['fingerprint'])
        self.assertContains(self.client.get(self.url), self.analysis['highlights'][0])
        self.assertEqual(self.post().status_code, 302)
        self.ai.assert_called_once()
        self.assertEqual(WeeklyReport.objects.count(), 1)
        self.assertEqual(Exercise.objects.filter(daily_record=self.record).count(), 1)
        self.assertEqual(Meal.objects.filter(daily_record=self.record).count(), 1)

    def test_changed_records_mark_stale_and_can_refresh(self):
        self.post()
        saved_id = WeeklyReport.objects.get(user=self.owner).pk
        self.exercise.steps = 9000
        self.exercise.save()
        self.assertTrue(self.client.get(self.url).context['analysis_stale'])
        cache.clear()
        self.assertEqual(self.post().status_code, 302)
        self.assertEqual(WeeklyReport.objects.get(user=self.owner).pk, saved_id)
        self.assertFalse(self.client.get(self.url).context['analysis_stale'])
        self.assertEqual(self.ai.call_count, 2)

    def test_other_user_cannot_see_saved_analysis(self):
        self.post()
        self.client.force_login(self.other)
        response = self.client.get(self.url)
        self.assertIsNone(response.context['saved_report'])
        self.assertEqual(response.context['totals']['steps'], 0)
        self.assertNotContains(response, self.analysis['highlights'][0])
        self.assertContains(self.post(), '이번 주 기록이 아직 없습니다.')
        self.assertEqual(self.ai.call_count, 1)

    def test_empty_data_never_calls_ai(self):
        self.record.delete()
        self.assertFalse(self.data()['has_records'])
        self.assertContains(self.post(), '이번 주 기록이 아직 없습니다.')
        self.ai.assert_not_called()

    def test_inflight_record_change_is_not_saved(self):
        def change(*args, **kwargs):
            Exercise.objects.filter(pk=self.exercise.pk).update(steps=9999)
            return SimpleNamespace(text=json.dumps(self.analysis))
        self.ai.side_effect = change
        self.assertContains(self.post(), '생성 중 기록이 바뀌었습니다.')
        self.assertFalse(WeeklyReport.objects.exists())

    def test_bad_response_does_not_replace_saved_analysis(self):
        self.post()
        before = WeeklyReport.objects.get(user=self.owner).analysis
        Exercise.objects.filter(pk=self.exercise.pk).update(steps=9999)
        cache.clear()
        self.ai.return_value = SimpleNamespace(text='not json')
        self.assertContains(self.post(), '분석 형식이 맞지 않거나')
        self.assertEqual(WeeklyReport.objects.get(user=self.owner).analysis, before)

    def test_api_and_database_errors_are_safe(self):
        self.ai.side_effect = AIError('AI 연결 설정이 필요합니다.')
        self.assertContains(self.post(), 'AI 연결 설정이 필요합니다.')
        cache.clear()
        self.ai.side_effect = RuntimeError('SECRET_SERVICE_ERROR')
        response = self.post()
        self.assertContains(response, '주간 분석을 저장하지 못했습니다.')
        self.assertNotContains(response, 'SECRET_SERVICE_ERROR')
        cache.clear()
        self.ai.side_effect = None
        with patch('records.weekly_report.WeeklyReport.objects.update_or_create', side_effect=DatabaseError('SECRET_DB')):
            self.assertContains(self.post(), '주간 분석을 저장하지 못했습니다.')
        self.assertFalse(WeeklyReport.objects.exists())

    def test_duplicate_requests_are_throttled(self):
        cache.add(f'weekly-report:{self.owner.pk}', True, 60)
        self.assertContains(self.post(), '잠시 후 다시 시도해 주세요.')
        self.ai.assert_not_called()

    def test_analysis_is_escaped_not_rendered_as_html(self):
        self.analysis['highlights'] = ['<script>window.HACKED=true</script>']
        self.ai.return_value = SimpleNamespace(text=json.dumps(self.analysis))
        self.post()
        response = self.client.get(self.url)
        self.assertContains(response, '&lt;script&gt;window.HACKED=true&lt;/script&gt;')
        self.assertNotContains(response, '<script>window.HACKED=true</script>')

    def test_structured_response_validation(self):
        invalid = [None, 'x' * 12001, '[]', '{}', json.dumps(dict(self.analysis, highlights=[])),
                   json.dumps(dict(self.analysis, highlights=['a', 'b', 'c'])),
                   json.dumps(dict(self.analysis, highlights=[True])),
                   json.dumps(dict(self.analysis, highlights=[' ' * 4])),
                   json.dumps(dict(self.analysis, highlights=['x' * 501]))]
        for text in invalid:
            with self.assertRaises(ValueError):
                validated_analysis(text)
        self.assertEqual(validated_analysis(json.dumps(self.analysis)), self.analysis)
