from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.db import transaction

from .models import UserProfile, WeightRecord, current_weight_day, record_weight


class AccountLoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = '아이디'
        self.fields['username'].widget.attrs.update({'autocomplete': 'username', 'placeholder': '아이디를 입력해 주세요'})
        self.fields['password'].widget.attrs['placeholder'] = '비밀번호를 입력해 주세요'


class CustomSignupForm(UserCreationForm):
    profile_color = forms.ChoiceField(label='나만의 프로필 색상', choices=UserProfile.PROFILE_COLORS,
                                     required=False, initial='sky', help_text='선택한 색상이 상단 프로필 원에 적용됩니다. 나중에 내 정보에서 바꿀 수 있습니다.')

    email = forms.EmailField(label='복구 이메일', max_length=254, help_text='아이디 찾기와 비밀번호 재설정에 사용합니다.',
                             widget=forms.EmailInput(attrs={'autocomplete': 'email'}))
    real_name = forms.CharField(label='실명', max_length=50, required=True)
    nickname = forms.CharField(label='닉네임', max_length=50, required=True)
    current_weight = forms.FloatField(label='현재 체중 (kg)', required=False, min_value=0.01)
    target_weight = forms.FloatField(label='목표 체중 (kg)', required=False, min_value=0.01)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')
        labels = {'username': '로그인 ID'}

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        if commit:
            user.save()
            current_weight = self.cleaned_data.get('current_weight')
            UserProfile.objects.create(
                user=user,
                real_name=self.cleaned_data['real_name'],
                nickname=self.cleaned_data['nickname'],
                profile_color=self.cleaned_data.get('profile_color') or 'sky',
                start_weight=current_weight,
                current_weight=current_weight,
                target_weight=self.cleaned_data.get('target_weight'),
            )
            if current_weight is not None:
                record_weight(user, current_weight_day(), current_weight)
        return user


class UserProfileForm(forms.ModelForm):
    def clean_current_weight(self):
        weight = self.cleaned_data.get('current_weight')
        if weight is None and self.instance.user_id and WeightRecord.objects.filter(user_id=self.instance.user_id).exists():
            raise forms.ValidationError('체중 기록이 있는 경우 현재 체중을 비울 수 없습니다.')
        return weight

    @transaction.atomic
    def save(self, commit=True):
        profile = super().save(commit=commit)
        if commit and 'current_weight' in self.changed_data and profile.current_weight is not None:
            record_weight(profile.user, current_weight_day(), profile.current_weight)
        return profile

    class Meta:
        model = UserProfile
        fields = ['start_weight', 'current_weight', 'target_weight']
        labels = {
            'start_weight': '시작 체중 (kg)',
            'current_weight': '현재 체중 (kg)',
            'target_weight': '목표 체중 (kg)',
        }
        help_texts = {'current_weight': '현재 체중을 변경해 저장하면 오늘 날짜의 체중 기록에도 반영됩니다.'}
        widgets = {
            name: forms.NumberInput(attrs={'min': '0.01', 'step': 'any'})
            for name in ('start_weight', 'current_weight', 'target_weight')
        }


class ProfileUpdateForm(UserProfileForm):
    profile_color = forms.ChoiceField(label='프로필 원 색상', choices=UserProfile.PROFILE_COLORS, required=False,
                                     help_text="오른쪽 위 '내' 원에 적용됩니다. 선택 후 변경사항을 저장해 주세요.")

    def clean_profile_color(self):
        return self.cleaned_data.get('profile_color') or self.instance.badge_color_key

    recovery_email = forms.EmailField(label='복구 이메일', max_length=254, required=False,
                                     help_text='기존 계정도 이메일을 등록하면 아이디·비밀번호를 찾을 수 있습니다.')
    email_password = forms.CharField(label='이메일 변경 확인용 현재 비밀번호', required=False,
                                    widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}),
                                    help_text='복구 이메일을 변경할 때만 입력해 주세요.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['recovery_email'].initial = self.instance.user.email

    def clean(self):
        data = super().clean()
        email = data.get('recovery_email', '')
        self.update_email = self.is_bound and 'recovery_email' in self.data and email != self.instance.user.email
        if self.update_email and not self.instance.user.check_password(data.get('email_password', '')):
            self.add_error('email_password', '이메일을 변경하려면 현재 비밀번호를 정확히 입력해 주세요.')
        return data

    @transaction.atomic
    def save(self, commit=True):
        profile = super().save(commit=commit)
        if commit and getattr(self, 'update_email', False):
            profile.user.email = self.cleaned_data['recovery_email']
            profile.user.save(update_fields=['email'])
        return profile

    class Meta(UserProfileForm.Meta):
        fields = ['nickname', 'profile_color', 'start_weight', 'current_weight', 'target_weight']
        labels = {**UserProfileForm.Meta.labels, 'nickname': '닉네임'}


class ExerciseHabitForm(forms.ModelForm):
    def save(self, commit=True):
        profile = super().save(commit=False)
        if commit:
            profile.save(update_fields=self.Meta.fields)
        return profile

    class Meta:
        model = UserProfile
        fields = ['exercise_experience', 'exercise_days_per_week', 'exercise_minutes_per_session', 'preferred_exercises']
        widgets = {
            'exercise_days_per_week': forms.NumberInput(attrs={'min': 0, 'max': 7, 'step': 1}),
            'exercise_minutes_per_session': forms.NumberInput(attrs={'min': 1, 'max': 240, 'step': 1}),
            'preferred_exercises': forms.TextInput(attrs={'placeholder': '예: 걷기, 수영'}),
        }


class WeightRecordForm(forms.ModelForm):
    class Meta:
        model = WeightRecord
        fields = ['date', 'weight']
        widgets = {
            'date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'weight': forms.NumberInput(attrs={'min': '0.01', 'step': 'any', 'placeholder': 'kg'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].initial = current_weight_day()
        self.fields['date'].widget.attrs['max'] = current_weight_day().isoformat()
