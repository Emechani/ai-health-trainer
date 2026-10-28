"""기존 Gemini SDK를 사용하는 기능별 호출·오류·동시 요청 관리."""
import hashlib
import os
import random
import time
import uuid
from types import SimpleNamespace

from django.core.cache import cache
from google.api_core import exceptions


class AIError(Exception):
    def __init__(self, message, code='unavailable', retry_after=0):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


MODEL_SETTINGS = {
    'chat': 'AI_CHAT_MODEL', 'meal_plan': 'AI_MEAL_MODEL',
    'nutrition_advice': 'AI_NUTRITION_MODEL', 'food_analysis': 'AI_IMAGE_MODEL',
    'exercise': 'AI_EXERCISE_MODEL', 'feedback': 'AI_FEEDBACK_MODEL',
    'weekly_goal': 'WEEKLY_GOAL_MODEL',
}


def model_for(feature):
    default = 'gemini-3.5-flash-lite' if feature == 'weekly_goal' else (
        os.environ.get('GEMINI_MODEL', '').strip() or 'gemini-3.6-flash')
    return os.environ.get(MODEL_SETTINGS[feature], '').strip() or default


def bounded_setting(name, default, low, high):
    try:
        return max(low, min(high, int(os.environ.get(name, default))))
    except (ValueError, TypeError):
        return default


def provider_error(exc):
    # 외부 예외 원문이나 인증 정보 대신 고정 안내만 반환합니다.
    if isinstance(exc, exceptions.TooManyRequests):
        return AIError('AI 요청 한도 또는 할당량을 초과했습니다. 사용량을 확인하고 잠시 후 다시 시도해 주세요.', 'rate_limit', 60)
    if isinstance(exc, (exceptions.Unauthorized, exceptions.Forbidden)):
        return AIError('AI 인증 또는 사용 권한을 확인해 주세요.', 'authentication')
    if isinstance(exc, exceptions.NotFound):
        return AIError('설정된 AI 모델을 찾을 수 없습니다. 모델 설정을 확인해 주세요.', 'model')
    if isinstance(exc, exceptions.BadRequest):
        return AIError('AI 요청 형식이나 모델 지원 기능을 확인해 주세요.', 'request')
    if isinstance(exc, (exceptions.DeadlineExceeded, TimeoutError)):
        return AIError('AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.', 'timeout', 15)
    if isinstance(exc, exceptions.ServiceUnavailable):
        return AIError('현재 AI 모델에 요청이 몰렸거나 서비스가 불안정합니다. 잠시 후 다시 시도해 주세요.', 'overload', 15)
    return AIError('AI 연결 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.')


def generate(user, feature, contents, sdk, *, model_name=None, json_mode=False, cache_seconds=0):
    api_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not api_key:
        raise AIError('AI 연결 설정이 필요합니다. 관리자에게 문의해 주세요.', 'configuration')
    model_name = model_name or model_for(feature)
    project = hashlib.sha256(api_key.encode()).hexdigest()[:16]
    model_key = hashlib.sha256(model_name.encode()).hexdigest()[:16]
    lock_key = f'ai:lock:{user.pk}:{feature}'
    cooldown_key = f'ai:cooldown:{project}:{model_key}'
    result_key = None
    if cache_seconds and isinstance(contents, str):
        digest = hashlib.sha256(contents.encode()).hexdigest()
        result_key = f'ai:result:{project}:{user.pk}:{feature}:{model_key}:{digest}'
        stored = cache.get(result_key)
        if stored is not None:
            return SimpleNamespace(text=stored)
    cooldown = cache.get(cooldown_key)
    if cooldown:
        seconds = max(1, int(cooldown['until']-time.time()+1))
        raise AIError(cooldown['message'], cooldown['code'], seconds)
    token = uuid.uuid4().hex
    if not cache.add(lock_key, token, timeout=120):
        raise AIError('같은 AI 요청을 처리 중입니다. 잠시 기다려 주세요.', 'busy', 3)
    try:
        timeout = bounded_setting('AI_TIMEOUT_SECONDS', 25, 5, 45)
        retries = bounded_setting('AI_TRANSIENT_RETRIES', 1, 0, 1)
        sdk.configure(api_key=api_key)
        model = sdk.GenerativeModel(model_name)
        for attempt in range(retries+1):
            try:
                options = {'request_options': {'timeout': timeout, 'retry': None}}
                if json_mode:
                    options['generation_config'] = {'response_mime_type': 'application/json'}
                response = model.generate_content(contents, **options)
                text = response.text
                if not isinstance(text, str) or not text.strip():
                    raise AIError('AI 응답이 비어 있습니다. 잠시 후 다시 시도해 주세요.', 'response')
                if result_key:
                    cache.set(result_key, text, timeout=min(cache_seconds, 300))
                return SimpleNamespace(text=text)
            except AIError:
                raise
            except Exception as exc:
                transient = isinstance(exc, (exceptions.ServiceUnavailable, exceptions.DeadlineExceeded, TimeoutError))
                if transient and attempt < retries:
                    time.sleep(0.75+random.uniform(0, 0.25))
                    continue
                error = provider_error(exc)
                if error.retry_after:
                    cache.set(cooldown_key, {'until': time.time()+error.retry_after,
                        'message': str(error), 'code': error.code}, timeout=error.retry_after)
                raise error from None
    except AIError:
        raise
    except Exception as exc:
        raise provider_error(exc) from None
    finally:
        # 잠금 만료 뒤 새 요청이 잡은 잠금을 이전 요청이 해제하지 않습니다.
        if cache.get(lock_key) == token:
            cache.delete(lock_key)
