from django import forms
from django.utils import timezone
import math
from .models import Meal, Exercise, SavedMealPlan


class MealPlanForm(forms.Form):
    food_preferences = forms.CharField(
        label='선호 음식·식사 방식', max_length=300, required=False,
        widget=forms.TextInput(attrs={'placeholder': '예: 한식 위주, 간단한 아침'}),
    )
    dietary_restrictions = forms.CharField(
        label='알레르기·피해야 할 음식', max_length=300, required=False,
        help_text='알레르기와 식사 제한 사항을 입력해 주세요. 빈칸은 제한 없음이 아닌 미입력으로 처리합니다.',
        widget=forms.TextInput(attrs={'placeholder': '예: 땅콩 알레르기, 우유 제외'}),
    )

class MealForm(forms.ModelForm):
    class Meta:
        model = Meal
        # 사용자는 이제 '식사 종류(아침/점심/저녁)'와 '사진'만 올립니다.
        fields = ['meal_type', 'image'] 
        labels = {
            'meal_type': '식사 종류',
            'image': '음식 사진 업로드'
        }

class MealEditForm(forms.ModelForm):
    calories = forms.IntegerField(label='칼로리 (kcal)', required=False, min_value=0, max_value=2147483647)
    carbs = forms.IntegerField(label='탄수화물 (g)', required=False, min_value=0, max_value=10000)
    protein = forms.IntegerField(label='단백질 (g)', required=False, min_value=0, max_value=10000)
    fat = forms.IntegerField(label='지방 (g)', required=False, min_value=0, max_value=10000)

    class Meta:
        model = Meal
        fields = ['meal_type', 'food_name', 'calories', 'carbs', 'protein', 'fat']


class ExerciseForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['start_time'].required = True
        self.fields['end_time'].required = True
        if self.instance.pk and self.instance.exercise_name == Exercise.GOOGLE_FIT_NAME:
            # 사용자가 직접 수정한 연동 기록은 일반 수동 기록으로 보존합니다.
            self.initial['exercise_name'] = '걷기'

    def clean_exercise_name(self):
        value = self.cleaned_data['exercise_name'].strip()
        if not value:
            raise forms.ValidationError('운동 종목을 입력해 주세요.')
        if value == Exercise.GOOGLE_FIT_NAME:
            raise forms.ValidationError('Google 자동 연동 표시는 제외하고 운동 종목을 입력해 주세요.')
        return value

    def clean_distance_km(self):
        value = self.cleaned_data.get('distance_km')
        if value is not None and (not math.isfinite(value) or value < 0):
            raise forms.ValidationError('운동 거리는 0 이상의 숫자로 입력해 주세요.')
        return value

    def clean_steps(self):
        value = self.cleaned_data.get('steps')
        if value is not None and value < 0:
            raise forms.ValidationError('걸음 수는 0 이상으로 입력해 주세요.')
        return value

    def clean(self):
        data = super().clean()
        start, end = data.get('start_time'), data.get('end_time')
        if start and end and end <= start:
            self.add_error('end_time', '종료 시간은 시작 시간보다 늦어야 합니다.')
        return data

    # 🔥 이 한 줄이 핵심입니다! 정해진 목록이 아니더라도 무조건 텍스트로 받아들이도록 강제합니다.
    exercise_name = forms.CharField(
        max_length=50, 
        widget=forms.TextInput(attrs={'placeholder': '종목 직접 입력', 'id': 'id_exercise_name'}),
        label='운동 종목'
    )

    class Meta:
        model = Exercise
        # 👇 fields 리스트 맨 끝에 'steps'를 추가합니다.
        fields = ['exercise_name', 'start_time', 'end_time', 'distance_km', 'steps']
        widgets = {
            'start_time': forms.TimeInput(format='%H:%M', attrs={'type': 'time'}),
            'end_time': forms.TimeInput(format='%H:%M', attrs={'type': 'time'}),
            'distance_km': forms.NumberInput(attrs={'step': '0.01', 'placeholder': '예: 3.5'}),
            # 👇 걸음 수 입력 위젯도 추가해 줍니다.
            'steps': forms.NumberInput(attrs={'placeholder': '예: 5000'}),
        }
        labels = {
            'exercise_name': '운동 종목',
            'start_time': '시작 시간',
            'end_time': '종료 시간',
            'distance_km': '운동 거리(km)',
            'steps': '걸음 수(보)', # 화면에 보여질 라벨
        }


class MealPlanHistoryFilterForm(forms.Form):
    date = forms.DateField(label='생성 날짜', required=False,
                           widget=forms.DateInput(attrs={'type': 'date'}))

    def clean_date(self):
        value = self.cleaned_data.get('date')
        if value and value > timezone.localdate():
            raise forms.ValidationError('오늘 또는 과거 날짜를 선택해 주세요.')
        return value


class GoalPlanForm(forms.Form):
    meal_plan = forms.ModelChoiceField(label='목표에 맞춘 식단 예시', queryset=SavedMealPlan.objects.none())
    exercise_name = forms.CharField(label='실천할 운동 종목', max_length=50, required=False,
                                    widget=forms.TextInput(attrs={'placeholder': '예: 걷기'}))
    exercise_days = forms.IntegerField(label='7일 동안 운동할 일수', min_value=0, max_value=7)
    exercise_minutes = forms.IntegerField(label='운동하는 날의 목표 시간 (분)', min_value=1, max_value=240, required=False)

    def __init__(self, *args, user, profile, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        if profile and profile.current_weight is not None and profile.target_weight is not None:
            self.fields['meal_plan'].queryset = SavedMealPlan.objects.filter(
                user=user, profile_snapshot__current_weight=profile.current_weight,
                profile_snapshot__target_weight=profile.target_weight)
        self.initial.setdefault('meal_plan', self.fields['meal_plan'].queryset.first())
        self.fields['meal_plan'].label_from_instance = lambda item: f'{item.date} · {item.plan.get("summary", "식단 예시")[:45]}'

    def clean(self):
        data = super().clean()
        days = data.get('exercise_days')
        minutes = data.get('exercise_minutes')
        name = data.get('exercise_name', '').strip()
        data['exercise_name'] = name
        if days and (not name or minutes is None):
            raise forms.ValidationError('운동할 종목과 목표 시간을 입력해 주세요.')
        if self.profile:
            available_days = self.profile.exercise_days_per_week
            available_minutes = self.profile.exercise_minutes_per_session
            if days is not None and available_days is not None and days > available_days:
                self.add_error('exercise_days', '프로필의 운동 가능 일수 이하로 설정해 주세요.')
            if days and minutes is not None and available_minutes is not None and minutes > available_minutes:
                self.add_error('exercise_minutes', '프로필의 운동 가능 시간 이하로 설정해 주세요.')
        if days == 0:
            data['exercise_minutes'] = 0
            data['exercise_name'] = ''
        return data
