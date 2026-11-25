import math

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from zoneinfo import ZoneInfo
from django.contrib.auth.models import User # 장고의 기본 로그인 계정 모델 불러오기

class UserProfile(models.Model):
    PROFILE_COLORS = [
        ('sky', '하늘색'), ('mint', '민트색'), ('green', '초록색'),
        ('lavender', '보라색'), ('pink', '분홍색'), ('peach', '살구색'), ('navy', '남색'),
    ]
    profile_color = models.CharField('프로필 원 색상', max_length=12, choices=PROFILE_COLORS, default='sky')

    @property
    def badge_color_key(self):
        return self.profile_color if self.profile_color in dict(self.PROFILE_COLORS) else 'sky'

    # 1. 특정 로그인 계정과 이 프로필 정보를 1:1로 강력하게 연결합니다.
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    real_name = models.CharField(max_length=50, null=True, blank=True, help_text="실명")
    nickname = models.CharField(max_length=50, null=True, blank=True, help_text="닉네임")
    
    # 2. 고정된 default 값을 빼고, 사용자가 나중에 입력할 수 있도록 빈칸(null, blank)을 허용합니다.
    start_weight = models.FloatField(
        verbose_name="시작 체중 (kg)",
        help_text="목표를 시작했을 때의 체중입니다. 현재 체중을 수정해도 유지되며, 이 값을 바꾸면 진행률의 기준도 바뀝니다.",
        null=True, blank=True, validators=[MinValueValidator(0.01)],
    )
    current_weight = models.FloatField(help_text="현재 체중(kg)", null=True, blank=True, validators=[MinValueValidator(0.01)])
    target_weight = models.FloatField(help_text="목표 체중(kg)", null=True, blank=True, validators=[MinValueValidator(0.01)])

    exercise_experience = models.CharField(
        '운동 경험', max_length=20, blank=True, default='',
        choices=[('new', '운동 경험 없음'), ('beginner', '초급'), ('intermediate', '중급'), ('advanced', '고급')],
    )
    exercise_days_per_week = models.PositiveSmallIntegerField(
        '주당 운동 가능 횟수', null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(7)],
        help_text='일주일에 운동할 수 있는 날 수입니다. 0~7일로 입력해 주세요.',
    )
    exercise_minutes_per_session = models.PositiveSmallIntegerField(
        '1회 운동 가능 시간 (분)', null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(240)],
        help_text='한 번에 가능한 시간을 1~240분으로 입력해 주세요.',
    )
    preferred_exercises = models.CharField(
        '선호 운동 종목', max_length=200, blank=True, default='',
        help_text='예: 걷기, 달리기, 수영. 여러 종목은 쉼표로 구분해 주세요.',
    )

    @property
    def exercise_habits_summary(self):
        # 미입력과 주당 0일을 구분하여 AI가 없는 운동 습관을 추측하지 않게 합니다.
        days = self.exercise_days_per_week
        minutes = self.exercise_minutes_per_session
        return (
            f'운동 경험: {self.get_exercise_experience_display() or "미설정"}\n'
            f'주당 운동 가능 일수: {str(days) + "일" if days is not None else "미설정"}\n'
            f'1회 운동 가능 시간: {str(minutes) + "분" if minutes is not None else "미설정"}\n'
            f'선호 운동 종목: {self.preferred_exercises or "미설정"}'
        )

    @property
    def weight_progress_percentage(self):
        """Return a bounded goal percentage, or None when no baseline exists."""
        values = (self.start_weight, self.current_weight, self.target_weight)
        if any(value is None or not math.isfinite(value) or value <= 0 for value in values):
            return None
        if self.start_weight == self.target_weight:
            return None
        progress = (self.start_weight - self.current_weight) / (self.start_weight - self.target_weight)
        return round(max(0, min(1, progress)) * 100)
    
    def __str__(self):
        # 프로필 확인 시 로그인한 아이디(username)가 표시되도록 설정
        return f"{self.user.username}의 프로필"


def current_weight_day():
    return timezone.localdate(timezone=ZoneInfo('Asia/Seoul'))


def validate_finite_weight(value):
    if not math.isfinite(value):
        raise ValidationError('올바른 체중을 입력해 주세요.')


class WeightRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='weight_records')
    date = models.DateField('측정 날짜', default=current_weight_day)
    weight = models.FloatField('체중 (kg)', validators=[MinValueValidator(0.01), validate_finite_weight])

    class Meta:
        ordering = ['-date', '-pk']
        constraints = [models.UniqueConstraint(fields=['user', 'date'], name='unique_user_weight_date')]

    def clean(self):
        super().clean()
        if self.date and self.date > current_weight_day():
            raise ValidationError({'date': '미래 날짜의 체중은 기록할 수 없습니다.'})

    def __str__(self):
        return f'{self.user.username} / {self.date} / {self.weight}kg'


@transaction.atomic
def record_weight(user, record_date, weight):
    # 동일 날짜는 한 건만 갱신하고, 과거 기록을 입력해도 최신 체중을 되돌리지 않습니다.
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile = UserProfile.objects.select_for_update().get(pk=profile.pk)
    entry = WeightRecord(user=user, date=record_date, weight=weight)
    entry.full_clean(validate_unique=False, validate_constraints=False)
    record, _ = WeightRecord.objects.update_or_create(user=user, date=record_date, defaults={'weight': weight})
    latest = WeightRecord.objects.filter(user=user).first()
    profile.current_weight = latest.weight
    profile.save(update_fields=['current_weight'])
    return record
