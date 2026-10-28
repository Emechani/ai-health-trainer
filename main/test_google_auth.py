import json
import tempfile
import shutil
from uuid import uuid4
import time
from datetime import datetime, timedelta, timezone as datetime_timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from google.oauth2.credentials import Credentials

from .google_auth import FITNESS_SCOPE, SCOPES, google_token_path, save_google_credentials, google_oauth_flow


class GoogleOAuthTests(TestCase):
    def setUp(self):
        root = Path(tempfile.gettempdir()) / ('django-oauth-' + uuid4().hex)
        root.mkdir()
        self.tmp_root = root
        self.addCleanup(shutil.rmtree, root)
        self.config_file = root / 'client.json'
        self.config_file.write_text(json.dumps({'installed': {
            'client_id': 'mock-client', 'client_secret': 'mock-secret',
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': ['http://localhost'],
        }}))
        config = override_settings(GOOGLE_ACTIVITY_PROVIDER='google_fit', GOOGLE_TOKEN_DIR=str(root/'tokens'),
                                  GOOGLE_CLIENT_SECRETS_FILE=str(self.config_file),
                                  ALLOWED_HOSTS=['testserver','127.0.0.1','localhost'])
        config.enable()
        self.addCleanup(config.disable)
        self.user = User.objects.create_user(username='oauth-owner')
        self.other = User.objects.create_user(username='oauth-other')
        self.client.force_login(self.user)
        request_patch = patch('main.views.Request', return_value=Mock(side_effect=AssertionError('No network in OAuth tests')))
        request_patch.start()
        self.addCleanup(request_patch.stop)

    def start(self, client=None):
        return (client or self.client).post(reverse('google_fit_connect'), HTTP_HOST='127.0.0.1:8000')

    def callback(self, **params):
        params.setdefault('state', self.client.session['google_oauth_pending']['state'])
        return self.client.get(reverse('google_fit_callback'), params)

    def credentials(self, granted=None):
        credentials = Credentials('mock-access-token', refresh_token='mock-refresh-token',
                           token_uri='https://oauth2.googleapis.com/token', client_id='mock-client',
                           client_secret='mock-secret', scopes=SCOPES,
                           granted_scopes=SCOPES if granted is None else granted)
        credentials.expiry = datetime.now(datetime_timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
        return credentials

    def home(self):
        with patch('main.views.build') as build:
            build.return_value.events.return_value.list.return_value.execute.return_value = {'items':[]}
            build.return_value.users.return_value.dataset.return_value.aggregate.return_value.execute.return_value = {'bucket':[]}
            return self.client.get(reverse('home'))

    def test_unconnected_home_has_automatic_post_and_manual_button(self):
        response = self.home()
        self.assertTrue(response.context['auto_google_auth'])
        self.assertContains(response, 'google-fit-connect-form')
        self.assertContains(response, "document.getElementById('google-fit-connect-form').submit()")
        self.assertContains(response, 'csrfmiddlewaretoken')

    def test_start_creates_random_state_pkce_and_local_callback(self):
        response = self.start()
        self.assertEqual(response.status_code,302)
        query=parse_qs(urlparse(response.url).query)
        pending=self.client.session['google_oauth_pending']
        self.assertEqual(query['state'],[pending['state']])
        self.assertEqual(query['code_challenge_method'],['S256'])
        self.assertGreater(len(pending['verifier']),43)
        self.assertEqual(query['redirect_uri'],['http://127.0.0.1:8000/google-fit/callback/'])
        self.assertEqual(query['prompt'],['consent'])
        self.assertEqual(query['access_type'],['offline'])
        self.assertIn(FITNESS_SCOPE,query['scope'][0])
        self.assertIn('no-store',response['Cache-Control'])

    def test_start_requires_login_post_and_csrf(self):
        self.assertEqual(self.client.get(reverse('google_fit_connect')).status_code,405)
        secure=Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        self.assertEqual(secure.post(reverse('google_fit_connect')).status_code,403)
        self.client.logout()
        self.assertEqual(self.start().status_code,302)
        self.assertNotIn('google_oauth_pending',self.client.session)

    def test_valid_callback_saves_only_owners_token_and_returns_home(self):
        self.start()
        verifier=self.client.session['google_oauth_pending']['verifier']
        flow=Mock(credentials=self.credentials())
        with patch('main.views.google_oauth_flow',return_value=flow) as factory:
            response=self.callback(code='mock-auth-code')
        self.assertEqual(response.url,reverse('home'))
        flow.fetch_token.assert_called_once_with(code='mock-auth-code',timeout=20)
        self.assertEqual(factory.call_args.args[2],verifier)
        self.assertTrue(google_token_path(self.user).exists())
        self.assertFalse(google_token_path(self.other).exists())
        self.assertNotIn('google_oauth_pending',self.client.session)
        self.assertEqual(response['Referrer-Policy'],'no-referrer')
        self.assertNotIn('mock-access-token',str(dict(self.client.session)))
        home=self.home()
        self.assertFalse(home.context['auto_google_auth'])
        self.assertEqual(home.context['google_fit_status'],'connected')

    def test_wrong_or_non_ascii_state_is_rejected_without_exchange(self):
        self.start()
        with patch('main.views.google_oauth_flow') as factory:
            for state in ['wrong','가짜','']:
                response=self.callback(code='mock-code',state=state)
                self.assertEqual(response.status_code,400)
            factory.assert_not_called()
        self.assertFalse(google_token_path(self.user).exists())

    def test_other_user_or_other_session_cannot_complete_flow(self):
        self.start()
        pending=dict(self.client.session['google_oauth_pending'])
        other_client=Client()
        other_client.force_login(self.other)
        with patch('main.views.google_oauth_flow') as factory:
            self.assertEqual(other_client.get(reverse('google_fit_callback'),{'state':pending['state'],'code':'mock-code'}).status_code,400)
            session=other_client.session
            session['google_oauth_pending']=pending
            session.save()
            self.assertEqual(other_client.get(reverse('google_fit_callback'),{'state':pending['state'],'code':'mock-code'}).status_code,400)
            factory.assert_not_called()

    def test_expired_state_does_not_exchange_or_loop(self):
        self.start()
        session=self.client.session
        session['google_oauth_pending']['created_at']=time.time()-601
        session.save()
        with patch('main.views.google_oauth_flow') as factory:
            self.assertEqual(self.callback(code='mock-code').status_code,302)
            factory.assert_not_called()
        self.assertFalse(self.home().context['auto_google_auth'])

    def test_cancellation_returns_home_without_automatic_retry(self):
        self.start()
        with patch('main.views.google_oauth_flow') as factory:
            response=self.callback(error='access_denied')
            factory.assert_not_called()
        self.assertEqual(response.url,reverse('home'))
        home=self.home()
        self.assertFalse(home.context['auto_google_auth'])
        self.assertContains(home,'Google 계정 연결 · 재인증')
        self.assertContains(home,'Google 연결을 완료하지 않았습니다')
        self.assertFalse(self.home().context['auto_google_auth'])

    def test_failed_exchange_preserves_existing_token_and_does_not_leak_error(self):
        save_google_credentials(self.user,self.credentials())
        before=google_token_path(self.user).read_bytes()
        self.start()
        flow=Mock()
        flow.fetch_token.side_effect=RuntimeError('mock-private-client-secret')
        with patch('main.views.google_oauth_flow',return_value=flow):
            self.callback(code='mock-code')
        self.assertEqual(google_token_path(self.user).read_bytes(),before)
        self.assertNotIn('mock-private-client-secret',str(dict(self.client.session)))

    def test_partial_scope_consent_is_not_saved_as_fitness_connected(self):
        self.start()
        flow=Mock(credentials=self.credentials(granted=['https://www.googleapis.com/auth/calendar.readonly']))
        with patch('main.views.google_oauth_flow',return_value=flow):
            self.callback(code='mock-code')
        self.assertFalse(google_token_path(self.user).exists())
        home=self.home()
        self.assertFalse(home.context['auto_google_auth'])
        self.assertContains(home,'걸음 수 읽기 권한')

    def test_callback_is_single_use(self):
        self.start()
        state=self.client.session['google_oauth_pending']['state']
        with patch('main.views.google_oauth_flow',return_value=Mock(credentials=self.credentials())):
            self.callback(code='mock-code')
            self.assertEqual(self.client.get(reverse('google_fit_callback'),{'state':state,'code':'mock-code'}).status_code,400)

    def test_missing_config_stops_automatic_loop_and_retains_manual_retry(self):
        with override_settings(GOOGLE_CLIENT_SECRETS_FILE=str(self.tmp_root/'missing.json')):
            response=self.start()
        self.assertEqual(response.url,reverse('home'))
        self.assertNotIn('google_oauth_pending',self.client.session)
        self.assertFalse(self.home().context['auto_google_auth'])

    def test_home_and_calendar_read_only_current_users_file(self):
        save_google_credentials(self.user,self.credentials())
        save_google_credentials(self.other,self.credentials())
        self.home()
        with patch('records.views.Credentials.from_authorized_user_file',return_value=Mock(valid=True)) as loader,patch('records.views.build') as build:
            build.return_value.events.return_value.list.return_value.execute.return_value={'items':[]}
            self.assertEqual(self.client.get(reverse('exercise_calendar')).status_code,200)
            self.assertEqual(loader.call_args.args[0],str(google_token_path(self.user)))

    def test_only_granted_scopes_are_persisted(self):
        save_google_credentials(self.user,self.credentials(granted=[FITNESS_SCOPE]))
        loaded=Credentials.from_authorized_user_file(str(google_token_path(self.user)))
        self.assertTrue(loaded.has_scopes([FITNESS_SCOPE]))
        self.assertFalse(loaded.has_scopes(['https://www.googleapis.com/auth/calendar.readonly']))

    def test_cookie_backed_session_is_not_used_for_pkce_storage(self):
        with override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies'):
            client=Client()
            client.force_login(self.user)
            with patch('main.views.google_oauth_flow') as factory:
                self.start(client)
                factory.assert_not_called()

    def test_non_loopback_http_and_hosted_installed_client_are_rejected(self):
        for uri in ['http://example.com/google-fit/callback/','https://example.com/google-fit/callback/']:
            with self.assertRaises(ValueError):
                google_oauth_flow(uri,'mock-state','mock-verifier')

    def test_expired_or_missing_scope_token_triggers_automatic_reauthentication(self):
        save_google_credentials(self.user, self.credentials())
        expired = Mock(valid=False,expired=True,refresh_token='mock-refresh')
        expired.refresh.side_effect=RuntimeError('mock-revoked')
        missing_scope = Mock(valid=True)
        missing_scope.has_scopes.return_value=False
        for credentials in [expired,missing_scope]:
            with self.subTest(credentials=credentials),patch('main.views.Credentials.from_authorized_user_file',return_value=credentials):
                response=self.home()
                self.assertTrue(response.context['auto_google_auth'])
                self.assertIn('no-store',response['Cache-Control'])

    def test_api_unauthorized_also_requests_reauthentication(self):
        from googleapiclient.errors import HttpError
        from httplib2 import Response
        save_google_credentials(self.user,self.credentials())
        with patch('main.views.build') as build:
            build.return_value.events.return_value.list.return_value.execute.return_value={'items':[]}
            build.return_value.users.return_value.dataset.return_value.aggregate.return_value.execute.side_effect=HttpError(Response({'status':401}),b'{}')
            response=self.client.get(reverse('home'))
        self.assertEqual(response.context['google_fit_status'],'reauth_required')
        self.assertTrue(response.context['auto_google_auth'])

    def health_config(self):
        original=json.loads(self.config_file.read_text())
        config=original.get('installed',original.get('web'))
        self.config_file.write_text(json.dumps({'web':config}))
        return override_settings(GOOGLE_ACTIVITY_PROVIDER='google_health',GOOGLE_HEALTH_CLIENT_SECRETS_FILE=str(self.config_file))

    def test_health_authorization_requests_read_scope_and_preserves_fit_file(self):
        from .google_activity import HEALTH_SCOPE, CALENDAR_SCOPE
        save_google_credentials(self.user,self.credentials())
        fit_path=google_token_path(self.user)
        fit_bytes=fit_path.read_bytes()
        with self.health_config():
            response=self.start()
            scopes=parse_qs(urlparse(response.url).query)['scope'][0].split()
            self.assertEqual(parse_qs(urlparse(response.url).query)['include_granted_scopes'],['false'])
            self.assertIn(HEALTH_SCOPE,scopes)
            self.assertNotIn(CALENDAR_SCOPE,scopes)
            self.assertNotIn(FITNESS_SCOPE,scopes)
            self.assertNotEqual(google_token_path(self.user),fit_path)
            flow=Mock(credentials=self.credentials(granted=[HEALTH_SCOPE]))
            with patch('main.views.google_oauth_flow',return_value=flow):
                self.assertEqual(self.callback(code='mock-code').url,reverse('home'))
            self.assertTrue(google_token_path(self.user).exists())
            self.assertFalse(google_token_path(self.other).exists())
            with patch('main.views.google_health_daily_steps',return_value=4185) as health:
                home=self.home()
            self.assertEqual(home.context['google_steps'],4185)
            self.assertEqual(home.context['activity_provider_label'],'Google Health')
            self.assertFalse(home.context['auto_google_auth'])
            health.assert_called_once()
        self.assertEqual(fit_path.read_bytes(),fit_bytes)

    def test_health_rejects_returned_legacy_fit_scope_before_saving(self):
        from .google_activity import HEALTH_SCOPE,CALENDAR_SCOPE
        with self.health_config():
            self.start()
            flow=Mock(credentials=self.credentials(granted=[HEALTH_SCOPE,CALENDAR_SCOPE,FITNESS_SCOPE]))
            with patch('main.views.google_oauth_flow',return_value=flow),patch('main.views.save_google_credentials') as save:
                self.callback(code='mock-code')
            save.assert_not_called()
            self.assertIn('이전 Google Fit 권한',self.client.session['google_oauth_notice'])

    def test_calendar_consent_and_storage_are_separate_from_health(self):
        from .google_activity import HEALTH_SCOPE,CALENDAR_SCOPE
        from .google_auth import google_calendar_token_path
        with self.health_config():
            response=self.client.post(reverse('google_fit_connect'),{'purpose':'calendar'},HTTP_HOST='127.0.0.1:8000')
            self.assertEqual(parse_qs(urlparse(response.url).query)['scope'][0].split(),[CALENDAR_SCOPE])
            flow=Mock(credentials=self.credentials(granted=[CALENDAR_SCOPE]))
            with patch('main.views.google_oauth_flow',return_value=flow):
                self.callback(code='mock-code')
            self.assertTrue(google_calendar_token_path(self.user).exists())
            self.assertFalse(google_token_path(self.user).exists())
            self.assertFalse(google_calendar_token_path(self.other).exists())

    def test_new_health_consent_preserves_previous_calendar_credentials(self):
        from .google_activity import HEALTH_SCOPE,CALENDAR_SCOPE
        from .google_auth import google_calendar_token_path,calendar_credentials
        with self.health_config():
            save_google_credentials(self.user,self.credentials(granted=[HEALTH_SCOPE,CALENDAR_SCOPE]))
            previous=google_token_path(self.user).read_bytes()
            save_google_credentials(self.user,self.credentials(granted=[HEALTH_SCOPE]))
            self.assertEqual(google_calendar_token_path(self.user).read_bytes(),previous)
            self.assertTrue(calendar_credentials(self.user).has_scopes([CALENDAR_SCOPE]))
            loaded=Credentials.from_authorized_user_file(str(google_token_path(self.user)))
            self.assertFalse(loaded.has_scopes([CALENDAR_SCOPE]))

    def test_provider_switch_during_oauth_does_not_store_wrong_token(self):
        self.start()
        with self.health_config(),patch('main.views.google_oauth_flow') as factory:
            self.assertEqual(self.callback(code='mock-code').url,reverse('home'))
            factory.assert_not_called()
            self.assertFalse(google_token_path(self.user).exists())
        self.assertFalse(google_token_path(self.user).exists())

    def test_health_refuses_installed_client_and_does_not_loop(self):
        with override_settings(GOOGLE_ACTIVITY_PROVIDER='google_health',GOOGLE_HEALTH_CLIENT_SECRETS_FILE=str(self.config_file)):
            self.assertEqual(self.start().url,reverse('home'))
            response=self.home()
            self.assertFalse(response.context['auto_google_auth'])
            self.assertContains(response,'Google 계정 연결 · 재인증')

    def test_health_no_data_and_error_keep_manual_records_without_fit_fallback(self):
        from .google_activity import HEALTH_SCOPE,CALENDAR_SCOPE
        from records.models import DailyRecord,Exercise
        from django.utils import timezone
        daily=DailyRecord.objects.create(user=self.user,date=timezone.localdate())
        manual=Exercise.objects.create(daily_record=daily,exercise_name='걷기',steps=10000)
        with self.health_config():
            save_google_credentials(self.user,self.credentials(granted=[HEALTH_SCOPE,CALENDAR_SCOPE]))
            with patch('main.views.google_health_daily_steps',return_value=None):
                response=self.home()
            self.assertEqual(response.context['today_steps'],10000)
            self.assertIsNone(response.context['google_steps'])
            self.assertEqual(response.context['google_fit_status'],'no_data')
            self.assertFalse(response.context['auto_google_auth'])
            with patch('main.views.google_health_daily_steps',side_effect=ValueError('mock-bad-response')):
                response=self.home()
            self.assertEqual(response.context['today_steps'],10000)
            self.assertEqual(response.context['google_fit_status'],'error')
        manual.refresh_from_db()
        self.assertEqual(manual.steps,10000)
        self.assertEqual(Exercise.objects.count(),1)

    def test_returned_extra_scopes_are_verified_and_accepted(self):
        from .google_auth import fetch_google_token
        from oauthlib.oauth2.rfc6749.tokens import OAuth2Token
        from oauthlib.oauth2.rfc6749.parameters import validate_token_parameters
        requested=SCOPES
        actual=SCOPES+['openid']
        token=OAuth2Token({'access_token':'mock-access','refresh_token':'mock-refresh',
                          'token_type':'Bearer','scope':' '.join(actual),
                          'expires_at':time.time()+3600},old_scope=requested)
        with self.assertRaises(Warning) as warning:
            validate_token_parameters(token)
        flow=google_oauth_flow('http://127.0.0.1:8000/google-fit/callback/','mock-state','mock-verifier')
        with patch.object(flow,'fetch_token',side_effect=warning.exception):
            fetch_google_token(flow,'mock-code')
        self.assertTrue(flow.credentials.valid)
        self.assertTrue(flow.credentials.has_scopes([FITNESS_SCOPE]))
        self.assertIn('openid',flow.credentials.granted_scopes)

    def test_scope_warning_without_required_permission_is_rejected(self):
        from .google_auth import fetch_google_token
        warning=Warning('mock-scope-change')
        warning.token={'access_token':'mock-access','scope':'openid'}
        flow=Mock()
        flow.fetch_token.side_effect=warning
        with self.assertRaises(ValueError):fetch_google_token(flow,'mock-code')

    def test_callback_reports_storage_failure_without_revealing_secrets(self):
        self.start()
        with patch('main.views.google_oauth_flow',return_value=Mock(credentials=self.credentials())),patch('main.views.save_google_credentials',side_effect=PermissionError('mock-private-secret')):
            self.callback(code='mock-code')
        self.assertIn('인증 저장 실패',self.client.session['google_oauth_notice'])
        self.assertNotIn('mock-private-secret',self.client.session['google_oauth_notice'])

    def test_callback_reports_invalid_grant_and_missing_refresh_token(self):
        from oauthlib.oauth2 import InvalidGrantError
        self.start()
        flow=Mock()
        flow.fetch_token.side_effect=InvalidGrantError(description='mock-private-secret')
        with patch('main.views.google_oauth_flow',return_value=flow):self.callback(code='mock-code')
        self.assertIn('인증 코드 확인 실패',self.client.session['google_oauth_notice'])
        self.assertNotIn('mock-private-secret',self.client.session['google_oauth_notice'])
        self.start()
        credentials=self.credentials()
        credentials._refresh_token=None
        with patch('main.views.google_oauth_flow',return_value=Mock(credentials=credentials)):
            self.callback(code='mock-code')
        self.assertIn('지속 연결 승인 실패',self.client.session['google_oauth_notice'])
