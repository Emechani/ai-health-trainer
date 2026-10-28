from datetime import date,timedelta
from unittest.mock import Mock,patch
from django.test import SimpleTestCase,override_settings
from django.core.exceptions import ImproperlyConfigured
from .google_activity import (activity_provider,activity_scope,FITNESS_SCOPE,HEALTH_SCOPE,
                              parse_health_daily_steps,google_health_daily_steps,civil_midnight,
                              GoogleHealthError,health_error_from_response)


class GoogleHealthStepSafetyTests(SimpleTestCase):
    day=date(2026,10,21)

    def test_known_errors_show_fixed_safe_actions(self):
        for reason,status in [('ACCOUNT_NOT_LINKED',400),('SERVICE_DISABLED',403),
                             ('API_PRIVATE_PREVIEW_ACCESS_DENIED',403),('MISSING_OAUTH_SCOPE',403)]:
            response=Mock(status_code=status)
            response.json.return_value={'error':{'message':'private-account-or-token',
                'details':[{'reason':reason,'metadata':{'secret':'private-account-or-token'}}]}}
            error=health_error_from_response(response)
            self.assertEqual(error.code,reason)
            self.assertNotIn('private-account-or-token',str(error))

    def test_unknown_error_body_is_not_exposed(self):
        response=Mock(status_code=403)
        response.json.return_value={'error':{'message':'private-error',
            'details':[{'reason':'private-reason'}]}}
        error=health_error_from_response(response)
        self.assertEqual(error.code,'HTTP_403')
        self.assertNotIn('private',str(error))

    def test_http_failure_does_not_return_zero_and_closes_session(self):
        session=Mock()
        session.post.return_value.status_code=400
        session.post.return_value.json.return_value={'error':{'details':[{'reason':'ACCOUNT_NOT_LINKED'}]}}
        with patch('main.google_activity.AuthorizedSession',return_value=session),self.assertRaises(GoogleHealthError) as caught:
            google_health_daily_steps(Mock(),self.day)
        self.assertEqual(caught.exception.code,'ACCOUNT_NOT_LINKED')
        session.close.assert_called_once()

    def payload(self,count='4185'):
        return {'rollupDataPoints':[{'civilStartTime':civil_midnight(self.day),
                'civilEndTime':civil_midnight(self.day+timedelta(days=1)), 'steps':{'countSum':count}}]}

    def test_fit_is_default_and_invalid_or_mobile_provider_is_rejected(self):
        with override_settings(GOOGLE_ACTIVITY_PROVIDER='google_fit'):
            self.assertEqual(activity_provider(),'google_fit')
            self.assertEqual(activity_scope(),FITNESS_SCOPE)
        with override_settings(GOOGLE_ACTIVITY_PROVIDER='google_health'):
            self.assertEqual(activity_scope(),HEALTH_SCOPE)
        for invalid in ['health_connect','bad']:
            with override_settings(GOOGLE_ACTIVITY_PROVIDER=invalid),self.assertRaises(ImproperlyConfigured):
                activity_provider()

    def test_health_integer_string_and_explicit_zero(self):
        self.assertEqual(parse_health_daily_steps(self.payload(),self.day),4185)
        self.assertEqual(parse_health_daily_steps(self.payload('0'),self.day),0)
        payload=self.payload()
        payload['rollupDataPoints'][0]['steps']={}
        self.assertEqual(parse_health_daily_steps(payload,self.day),0)

    def test_no_data_is_unknown_not_zero(self):
        self.assertIsNone(parse_health_daily_steps({},self.day))
        self.assertIsNone(parse_health_daily_steps({'rollupDataPoints':[]},self.day))
        payload=self.payload()
        del payload['rollupDataPoints'][0]['steps']
        self.assertIsNone(parse_health_daily_steps(payload,self.day))

    def test_negative_fraction_boolean_and_invalid_counts_are_rejected(self):
        for count in ['-1','1.2','NaN','１２',True,None,3,'9223372036854775808']:
            with self.subTest(count=count),self.assertRaises(ValueError):
                parse_health_daily_steps(self.payload(count),self.day)

    def test_other_dates_and_overlapping_or_incomplete_windows_are_rejected(self):
        payload=self.payload()
        payload['rollupDataPoints'][0]['civilStartTime']=civil_midnight(self.day-timedelta(days=1))
        with self.assertRaises(ValueError):parse_health_daily_steps(payload,self.day)
        payload=self.payload()
        payload['rollupDataPoints']*=2
        with self.assertRaises(ValueError):parse_health_daily_steps(payload,self.day)
        payload=self.payload()
        payload['nextPageToken']='mock-more-data'
        with self.assertRaises(ValueError):parse_health_daily_steps(payload,self.day)

    def test_health_request_uses_official_read_only_daily_rollup(self):
        session=Mock()
        session.post.return_value.status_code=200
        session.post.return_value.json.return_value=self.payload()
        with patch('main.google_activity.AuthorizedSession',return_value=session):
            self.assertEqual(google_health_daily_steps(Mock(),self.day),4185)
        call=session.post.call_args
        self.assertEqual(call.args[0],'https://health.googleapis.com/v4/users/me/dataTypes/steps/dataPoints:dailyRollUp')
        self.assertEqual(call.kwargs['json']['range']['start'],civil_midnight(self.day))
        self.assertEqual(call.kwargs['json']['range']['end'],civil_midnight(self.day+timedelta(days=1)))
        self.assertEqual(call.kwargs['timeout'],20)
        self.assertFalse(call.kwargs['allow_redirects'])
        session.close.assert_called_once()

    def test_request_failure_closes_session_without_false_result(self):
        session=Mock()
        session.post.side_effect=RuntimeError('mock-timeout')
        with patch('main.google_activity.AuthorizedSession',return_value=session),self.assertRaises(RuntimeError):
            google_health_daily_steps(Mock(),self.day)
        session.close.assert_called_once()
