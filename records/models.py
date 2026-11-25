from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

# 1. 하루 단위 데이터 묶음 (특정 날짜의 식사+운동을 하나로 연결)
class DailyRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField(default=timezone.localdate, help_text="기록 날짜")
    
    class Meta:
        unique_together = ['user', 'date'] # 한 사용자는 하루에 하나의 통합 기록만 가짐

    def __str__(self):
        return f"{self.user.username}님의 기록 - {self.date}"

class GoogleHealthStepRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField('측정 날짜')
    steps = models.PositiveBigIntegerField('Google Health 걸음 수')
    synced_at = models.DateTimeField('최근 연동 시각', auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'date'], name='unique_health_steps_user_date')]


# 2. 개별 식사 기록 (UC5 음식 분류 모델 연동 대비)
class Meal(models.Model):
    MEAL_TYPES = (
        ('B', '아침'),
        ('L', '점심'),
        ('D', '저녁'),
        ('S', '간식'),
    )
    daily_record = models.ForeignKey(DailyRecord, related_name='meals', on_delete=models.CASCADE)
    meal_type = models.CharField(max_length=1, choices=MEAL_TYPES)
    food_name = models.CharField(max_length=100)
    calories = models.IntegerField(null=True, blank=True)
    
    # 👇 새롭게 추가되는 영양소 및 이미지 저장 공간
    carbs = models.IntegerField(null=True, blank=True, help_text="탄수화물(g)")
    protein = models.IntegerField(null=True, blank=True, help_text="단백질(g)")
    fat = models.IntegerField(null=True, blank=True, help_text="지방(g)")
    image = models.ImageField(upload_to='meal_images/', null=True, blank=True)

    def __str__(self):
        return f"{self.get_meal_type_display()} - {self.food_name}"

# 3. 개별 운동 기록
class Exercise(models.Model):
    # 기존 스키마를 유지하면서 새 Google 연동 기록을 수동 기록과 구분합니다.
    GOOGLE_FIT_NAME = '걷기 (Google Fit)'
    daily_record = models.ForeignKey(DailyRecord, related_name='exercises', on_delete=models.CASCADE)
    
    # 🔥 choices 옵션을 완전히 삭제하고 평범한 텍스트 기둥으로 만듭니다.
    exercise_name = models.CharField(max_length=50) 
    
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    distance_km = models.FloatField(null=True, blank=True) 
    steps = models.IntegerField(null=True, blank=True, verbose_name="걸음 수")
    calories_burned = models.IntegerField(null=True, blank=True)

class ChatMessage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField(verbose_name="메시지 내용")
    is_ai = models.BooleanField(default=False, verbose_name="AI 여부") # False면 사용자, True면 AI
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        sender = "AI" if self.is_ai else "User"
        return f"[{sender}] {self.message[:20]}"


class SavedMealPlan(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_meal_plans')
    date = models.DateField('식단 생성 날짜', default=timezone.localdate)
    plan = models.JSONField('생성된 식단')
    options = models.JSONField('생성 당시 식사 조건', default=dict)
    model_name = models.CharField('생성 모델', max_length=100)
    profile_snapshot = models.JSONField('생성 당시 체중 목표', default=dict)
    created_at = models.DateTimeField('보관 시각', auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at', '-pk']
        indexes = [models.Index(fields=['user', 'date'], name='saved_plan_user_date_idx')]

    def __str__(self):
        return f'{self.date} 맞춤 식단'


class GoalPlan(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='goal_plans')
    start_date = models.DateField('시작 날짜')
    end_date = models.DateField('종료 날짜')
    current_weight = models.FloatField('시작 당시 현재 체중')
    target_weight = models.FloatField('계획 당시 목표 체중')
    saved_meal_plan = models.ForeignKey(SavedMealPlan, null=True, on_delete=models.SET_NULL)
    meal_snapshot = models.JSONField('계획 당시 식단')
    exercise_name = models.CharField('운동 종목', max_length=50, blank=True)
    exercise_days = models.PositiveSmallIntegerField('주당 운동 목표 일수')
    exercise_minutes = models.PositiveSmallIntegerField('하루 운동 목표 시간')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']


class WeeklyReport(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='weekly_reports')
    start_date = models.DateField('리포트 시작 날짜')
    source_hash = models.CharField('분석한 기록 식별값', max_length=64)
    analysis = models.JSONField('주간 AI 분석')
    model_name = models.CharField('분석 모델', max_length=100)
    updated_at = models.DateTimeField('분석 시각', auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'start_date'], name='unique_weekly_report_user_date')]
