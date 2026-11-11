import re
from smtplib import SMTPException
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .forms import CustomSignupForm, ProfileUpdateForm
from .models import UserProfile


@override_settings(MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}},
                   DEFAULT_FROM_EMAIL='health@example.com', ALLOWED_HOSTS=['testserver'])
class AccountRecoveryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.password = 'SecureExample_42!'
        self.user = User.objects.create_user('account-owner', email='owner@example.com', password=self.password)
        self.profile = UserProfile.objects.create(user=self.user, nickname='owner')

    def test_duplicate_signup_is_rejected_and_existing_user_unchanged(self):
        response = self.client.post(reverse('signup'), {
            'username': self.user.username, 'email': 'new@example.com',
            'real_name': '테스트', 'nickname': 'new',
            'password1': 'OtherSecureExample_72!', 'password2': 'OtherSecureExample_72!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('username', response.context['form'].errors)
        self.assertEqual(User.objects.count(), 1)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'owner@example.com')

    def test_signup_stores_email_and_requires_valid_email(self):
        values = {'username': 'new-account', 'email': 'new@example.com', 'real_name': '테스트',
                  'nickname': 'new', 'password1': 'OtherSecureExample_72!', 'password2': 'OtherSecureExample_72!'}
        form = CustomSignupForm(values)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().email, 'new@example.com')
        self.assertIn('email', CustomSignupForm({**values, 'username': 'other', 'email': ''}).errors)

    def test_auth_and_recovery_pages_render_with_shared_style(self):
        for name in ('login', 'signup', 'find_username', 'password_reset', 'password_reset_done',
                     'username_recovery_done', 'password_reset_complete'):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'auth-shell')
        self.assertContains(self.client.get(reverse('login')), reverse('find_username'))

    def test_login_preserves_safe_next_and_rejects_external_redirect(self):
        for destination, expected in (('/users/profile/', '/users/profile/'), ('https://evil.example/', '/')):
            self.client.logout()
            response = self.client.post(reverse('login'), {
                'username': self.user.username, 'password': self.password, 'next': destination})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, expected)

    def test_username_is_sent_only_by_email_and_unknown_has_same_response(self):
        response = self.client.post(reverse('find_username'), {'email': 'OWNER@example.com'})
        self.assertRedirects(response, reverse('username_recovery_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.user.username, mail.outbox[0].body)
        unknown = self.client.post(reverse('find_username'), {'email': 'missing@example.com'})
        self.assertEqual(unknown.url, response.url)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotContains(self.client.get(response.url), self.user.username)

    def test_inactive_account_does_not_receive_username_or_reset(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        for name in ('find_username', 'password_reset'):
            self.client.post(reverse(name), {'email': self.user.email})
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_uses_https_and_token_is_single_use(self):
        response = self.client.post(reverse('password_reset'), {'email': self.user.email}, secure=True)
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r'https://testserver(/accounts/reset/\S+)', mail.outbox[0].body).group(1)
        confirm = self.client.get(link)
        self.assertEqual(confirm.status_code, 302)
        self.assertTrue(self.client.get(confirm.url).context['validlink'])
        changed = self.client.post(confirm.url, {
            'new_password1': 'ChangedSecure_72!', 'new_password2': 'ChangedSecure_72!'})
        self.assertRedirects(changed, reverse('password_reset_complete'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('ChangedSecure_72!'))
        self.assertFalse(self.client.get(link).context['validlink'])

    def test_unknown_email_does_not_send_reset(self):
        response = self.client.post(reverse('password_reset'), {'email': 'unknown@example.com'})
        self.assertEqual(response.url, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_email_limit_applies_across_recovery_routes(self):
        for _ in range(5):
            self.client.post(reverse('find_username'), {'email': self.user.email})
        response = self.client.post(reverse('password_reset'), {'email': self.user.email})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '요청이 많습니다')
        self.assertEqual(len(mail.outbox), 5)

    @override_settings(MAILERS={'default': {'BACKEND': 'django.core.mail.backends.console.EmailBackend'}})
    def test_console_backend_does_not_print_account_or_token(self):
        with patch('builtins.print') as output:
            for name in ('find_username', 'password_reset'):
                response = self.client.post(reverse(name), {'email': self.user.email})
                self.assertContains(response, '이메일 발송 설정이 준비되지 않았습니다')
            output.assert_not_called()

    def test_smtp_failure_has_friendly_error(self):
        with patch('users.account_recovery.send_mail', side_effect=SMTPException('unavailable')):
            for name in ('find_username', 'password_reset'):
                response = self.client.post(reverse(name), {'email': self.user.email})
                self.assertContains(response, '이메일을 발송하지 못했습니다')

    def test_profile_email_change_requires_current_password(self):
        values = {'nickname': 'owner', 'recovery_email': 'changed@example.com'}
        form = ProfileUpdateForm(values, instance=self.profile)
        self.assertFalse(form.is_valid())
        self.assertIn('email_password', form.errors)
        form = ProfileUpdateForm({**values, 'email_password': self.password}, instance=self.profile)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'changed@example.com')

    def test_omitted_email_keeps_existing_email_and_cannot_edit_other_user(self):
        other = User.objects.create_user('other-user', email='other@example.com')
        self.client.force_login(self.user)
        response = self.client.post(reverse('profile_update'), {'nickname': 'updated', 'user': other.pk})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.user.email, 'owner@example.com')
        self.assertEqual(other.email, 'other@example.com')

    def test_recovery_post_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        for name in ('find_username', 'password_reset'):
            self.assertEqual(client.post(reverse(name), {'email': self.user.email}).status_code, 403)
