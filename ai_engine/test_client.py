from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable

from .client import AIError, generate, model_for


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                     'LOCATION': 'ai-client-isolated-tests'}})
class AIClientSafetyTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        env = patch.dict('os.environ', {'GEMINI_API_KEY': 'test-only', 'AI_TRANSIENT_RETRIES': '0',
            'AI_TIMEOUT_SECONDS': '25', 'AI_CHAT_MODEL': '', 'WEEKLY_GOAL_MODEL': '', 'GEMINI_MODEL': ''})
        env.start()
        self.addCleanup(env.stop)
        self.sdk = Mock()
        self.sdk.GenerativeModel.return_value.generate_content.return_value.text = '안내'
        self.user = SimpleNamespace(pk=1)

    def test_models_and_timeout_are_centralized(self):
        self.assertEqual(model_for('weekly_goal'), 'gemini-3.5-flash-lite')
        self.assertEqual(model_for('chat'), 'gemini-3.6-flash')
        generate(self.user, 'chat', '질문', self.sdk)
        self.assertEqual(self.sdk.GenerativeModel.return_value.generate_content.call_args.kwargs[
            'request_options'], {'timeout': 25, 'retry': None})

    def test_concurrent_user_feature_is_blocked(self):
        cache.add('ai:lock:1:chat', 'other-request', timeout=120)
        with self.assertRaises(AIError) as caught:
            generate(self.user, 'chat', '질문', self.sdk)
        self.assertEqual(caught.exception.code, 'busy')
        self.sdk.GenerativeModel.assert_not_called()
        self.assertEqual(cache.get('ai:lock:1:chat'), 'other-request')

    def test_rate_limit_blocks_same_model_without_leaking_error(self):
        self.sdk.GenerativeModel.return_value.generate_content.side_effect = ResourceExhausted('secret-error')
        for user in [self.user, SimpleNamespace(pk=2)]:
            with self.assertRaises(AIError) as caught:
                generate(user, 'chat', '질문', self.sdk)
            self.assertEqual(caught.exception.code, 'rate_limit')
            self.assertNotIn('secret-error', str(caught.exception))
        self.assertEqual(self.sdk.GenerativeModel.return_value.generate_content.call_count, 1)

    def test_cached_feedback_is_separated_by_user(self):
        generate(self.user, 'feedback', '요약', self.sdk, cache_seconds=60)
        generate(self.user, 'feedback', '요약', self.sdk, cache_seconds=60)
        generate(SimpleNamespace(pk=2), 'feedback', '요약', self.sdk, cache_seconds=60)
        self.assertEqual(self.sdk.GenerativeModel.return_value.generate_content.call_count, 2)

    def test_only_one_transient_retry_and_final_lock_release(self):
        self.sdk.GenerativeModel.return_value.generate_content.side_effect = [ServiceUnavailable('busy'), SimpleNamespace(text='성공')]
        with patch.dict('os.environ', {'AI_TRANSIENT_RETRIES': '1'}), patch('ai_engine.client.time.sleep') as sleep:
            self.assertEqual(generate(self.user, 'chat', '질문', self.sdk).text, '성공')
        sleep.assert_called_once()
        self.assertEqual(self.sdk.GenerativeModel.return_value.generate_content.call_count, 2)
        self.assertIsNone(cache.get('ai:lock:1:chat'))

    def test_empty_reply_is_not_cached_and_lock_is_released(self):
        self.sdk.GenerativeModel.return_value.generate_content.return_value.text = ' '
        with self.assertRaises(AIError):
            generate(self.user, 'feedback', '요약', self.sdk, cache_seconds=60)
        self.assertIsNone(cache.get('ai:lock:1:feedback'))
        self.sdk.GenerativeModel.return_value.generate_content.return_value.text = '성공'
        self.assertEqual(generate(self.user, 'feedback', '요약', self.sdk, cache_seconds=60).text, '성공')
