from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.urls import reverse
import math

from .models import UserProfile, WeightRecord, current_weight_day, record_weight
from .forms import CustomSignupForm, UserProfileForm, ProfileUpdateForm, WeightRecordForm, ExerciseHabitForm

@login_required # 로그인한 사용자만 접근 가능하도록 보호
def profile_setup(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            return redirect('/') 
    else:
        form = UserProfileForm(instance=profile)
        
    # 2. profile_setup 함수는 profile_setup.html을 띄우도록 제자리에 위치
    return render(request, 'users/profile_setup.html', {'form': form})


def signup(request):
    if request.method == 'POST':
        form = CustomSignupForm(request.POST) # 폼 교체
        if form.is_valid():
            form.save() 
            return redirect('login') 
    else:
        form = CustomSignupForm() # 폼 교체
        
    return render(request, 'users/signup.html', {'form': form})

@login_required(login_url='/accounts/login/')
def profile_update(request):
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    today = current_weight_day()
    records = WeightRecord.objects.filter(user=request.user)
    today_record = records.filter(date=today).first()
    weight_form = WeightRecordForm(initial={'weight': today_record.weight if today_record else None})
    exercise_habit_form = ExerciseHabitForm(instance=profile)
    
    if request.method == 'POST' and request.POST.get('action') == 'record_weight':
        form = ProfileUpdateForm(instance=profile)
        weight_form = WeightRecordForm(request.POST)
        if weight_form.is_valid():
            record_weight(request.user, weight_form.cleaned_data['date'], weight_form.cleaned_data['weight'])
            return redirect(reverse('profile_update') + '#weight-history')
    elif request.method == 'POST' and request.POST.get('action') == 'save_exercise_habits':
        form = ProfileUpdateForm(instance=profile)
        exercise_habit_form = ExerciseHabitForm(request.POST, instance=profile)
        if exercise_habit_form.is_valid():
            exercise_habit_form.save()
            return redirect(reverse('profile_update') + '?habits_saved=1#exercise-habits')
    elif request.method == 'POST':
        form = ProfileUpdateForm(request.POST, instance=profile)
        if form.is_valid():
            form.save() # 현재 체중 변경 시 폼에서 오늘의 체중 기록도 함께 저장합니다.
            return redirect('home')
    else:
        form = ProfileUpdateForm(instance=profile)
        
    # 측정 날짜의 실제 간격으로 최근 30개 기록을 그립니다. 빠진 날짜는 생성하지 않습니다.
    chart_records = list(reversed(list(records.order_by('-date')[:30])))
    chart = None
    if chart_records:
        values = [record.weight for record in chart_records]
        target = profile.target_weight
        show_target = target is not None and math.isfinite(target) and target > 0
        if show_target:
            values.append(target)
        padding = max((max(values) - min(values)) * 0.15, 0.5)
        low, high = max(0, min(values) - padding), max(values) + padding
        span = (chart_records[-1].date - chart_records[0].date).days

        def y_position(weight):
            return format(204 - (weight - low) / (high - low) * 180, '.2f')

        points = [
            {'x': format(58 + (record.date - chart_records[0].date).days / span * 588, '.2f') if span else '352',
             'y': y_position(record.weight), 'record': record}
            for record in chart_records
        ]
        chart = {
            'points': points, 'line': ' '.join(f'{point["x"]},{point["y"]}' for point in points),
            'low': format(low, '.1f'), 'high': format(high, '.1f'),
            'target_y': y_position(target) if show_target else None,
            'first_date': chart_records[0].date, 'last_date': chart_records[-1].date,
        }
    return render(request, 'users/profile_update.html', {
        'form': form, 'weight_form': weight_form, 'weight_chart': chart,
        'exercise_habit_form': exercise_habit_form,
        'habits_saved': request.GET.get('habits_saved') == '1',
        'weight_records': Paginator(records, 10).get_page(request.GET.get('weight_page')),
    })
