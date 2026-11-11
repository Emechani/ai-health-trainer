import hashlib
from smtplib import SMTPException

from django import forms
from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import User
from django.contrib.auth.views import PasswordResetView
from django.core.cache import cache
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters


class AccountEmailForm(forms.Form):
    email = forms.EmailField(label='가입한 이메일', max_length=254,
                             widget=forms.EmailInput(attrs={'autocomplete': 'email', 'placeholder': 'name@example.com'}))


def email_delivery_ready():
    config = settings.MAILERS.get('default', {})
    backend = config.get('BACKEND', '')
    # 개발용 콘솔에 아이디나 재설정 링크가 기록되지 않도록 발송을 차단합니다.
    if not backend or backend.endswith(('.console.EmailBackend', '.dummy.EmailBackend', '.filebased.EmailBackend')):
        return False
    if backend.endswith('.smtp.EmailBackend'):
        return bool(config.get('OPTIONS', {}).get('host') and settings.DEFAULT_FROM_EMAIL)
    return True


def recovery_limited(request, email):
    # 프록시가 전달한 임의 헤더를 신뢰하지 않고, 이메일별 제한도 함께 적용합니다.
    values = (('address', request.META.get('REMOTE_ADDR', '')), ('email', email.casefold()))
    for category, value in values:
        digest = hashlib.sha256(value.encode()).hexdigest()
        key = f'account-recovery:{category}:{digest}'
        if cache.add(key, 1, timeout=3600):
            continue
        try:
            count = cache.incr(key)
        except ValueError:
            cache.add(key, 1, timeout=3600)
            count = 1
        if count > (30 if category == 'address' else 5):
            return True
    return False


class RecoveryPasswordForm(PasswordResetForm):
    email = AccountEmailForm.base_fields['email']

    def send_mail(self, subject_template_name, email_template_name, context, from_email,
                  to_email, html_email_template_name=None):
        from django.template.loader import render_to_string
        # SMTP 오류 세부 정보에 이메일·인증 링크가 포함될 수 있으므로 로그에 출력하지 않습니다.
        send_mail(''.join(render_to_string(subject_template_name, context).splitlines()),
                  render_to_string(email_template_name, context), from_email, [to_email])


class AccountPasswordResetView(PasswordResetView):
    form_class = RecoveryPasswordForm

    def form_valid(self, form):
        if not email_delivery_ready():
            form.add_error(None, '현재 이메일 발송 설정이 준비되지 않았습니다. 관리자에게 문의해 주세요.')
            return self.form_invalid(form)
        if recovery_limited(self.request, form.cleaned_data['email']):
            form.add_error(None, '요청이 많습니다. 잠시 후 다시 시도해 주세요.')
            return self.form_invalid(form)
        try:
            return super().form_valid(form)
        except (SMTPException, OSError):
            form.add_error(None, '이메일을 발송하지 못했습니다. 잠시 후 다시 시도해 주세요.')
            return self.form_invalid(form)


@never_cache
@sensitive_post_parameters('email')
def find_username(request):
    form = AccountEmailForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']
        if not email_delivery_ready():
            form.add_error(None, '현재 이메일 발송 설정이 준비되지 않았습니다. 관리자에게 문의해 주세요.')
        elif recovery_limited(request, email):
            form.add_error(None, '요청이 많습니다. 잠시 후 다시 시도해 주세요.')
        else:
            usernames = list(User.objects.filter(email__iexact=email, is_active=True)
                             .order_by('pk').values_list('username', flat=True))
            try:
                if usernames:
                    send_mail('Health Overview 아이디 안내',
                              '요청하신 로그인 아이디입니다.\n\n' + '\n'.join(usernames)
                              + '\n\n직접 요청하지 않았다면 이 메일을 무시해 주세요.',
                              settings.DEFAULT_FROM_EMAIL, [email])
                # 등록 여부와 관계없이 동일한 화면으로 이동해 계정 노출을 줄입니다.
                return redirect('username_recovery_done')
            except (SMTPException, OSError):
                form.add_error(None, '이메일을 발송하지 못했습니다. 잠시 후 다시 시도해 주세요.')
    return render(request, 'registration/find_username.html', {'form': form})
