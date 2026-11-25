from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from .forms import CustomSignupForm, ProfileUpdateForm
from .models import UserProfile


class AppearanceRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('appearance-owner', password='test-only-pass')
        self.profile = UserProfile.objects.create(user=self.user, nickname='검증')
        self.client.force_login(self.user)

    def test_signup_color_is_saved_and_invalid_choice_rejected(self):
        data = {'username':'new-color-owner','email':'qa@example.test','real_name':'검증',
                'nickname':'검증','password1':'Testing-only-594!','password2':'Testing-only-594!','profile_color':'pink'}
        form = CustomSignupForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().userprofile.profile_color, 'pink')
        form = CustomSignupForm(dict(data, username='invalid-color-owner', profile_color='invalid'))
        self.assertFalse(form.is_valid())
        self.assertIn('profile_color', form.errors)

    def test_profile_color_changes_only_owner_and_missing_value_preserves_it(self):
        other = UserProfile.objects.create(user=User.objects.create_user('other-color-owner'))
        self.assertEqual(self.profile.profile_color, 'white')
        self.assertEqual(self.client.post(reverse('profile_update'), {'nickname':'검증','profile_color':'navy'}).status_code, 302)
        self.client.post(reverse('profile_update'), {'nickname':'검증'})
        self.profile.refresh_from_db(); other.refresh_from_db()
        self.assertEqual(self.profile.profile_color, 'navy')
        self.assertEqual(other.profile_color, 'white')
        self.assertContains(self.client.get(reverse('profile_update')), 'avatar badge-color-navy')

    def test_profile_form_without_user_validates_without_crashing(self):
        form = ProfileUpdateForm({'start_weight':'-1'})
        self.assertFalse(form.is_valid())
        self.assertIn('start_weight', form.errors)

    def test_settings_show_three_modes_and_logout_is_csrf_protected(self):
        page = self.client.get(reverse('profile_update'))
        for value in ['value="light"','value="dark"','value="system"','mobile-profile-logout']:
            self.assertContains(page, value)
        secure = Client(enforce_csrf_checks=True); secure.force_login(self.user)
        self.assertEqual(secure.get(reverse('logout')).status_code, 405)
        self.assertEqual(secure.post(reverse('logout')).status_code, 403)
        secure.get(reverse('profile_update'))
        response = secure.post(reverse('logout'), {'csrfmiddlewaretoken':secure.cookies['csrftoken'].value})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', secure.session)
