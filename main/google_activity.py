from datetime import timedelta
import re

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from google.auth.transport.requests import AuthorizedSession
from requests.exceptions import Timeout, ConnectionError

FITNESS_SCOPE = 'https://www.googleapis.com/auth/fitness.activity.read'
HEALTH_SCOPE = 'https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly'
CALENDAR_SCOPE = 'https://www.googleapis.com/auth/calendar.readonly'


class GoogleHealthError(Exception):
    def __init__(self, code, message, status=0):
        super().__init__(message)
        self.code = code
        self.status = status


def health_error_from_response(response):
    # Google 오류 원문·계정 ID·토큰·메타데이터는 화면과 로그에 전달하지 않습니다.
    reasons = set()
    try:
        payload = response.json()
        error = payload.get('error', {}) if isinstance(payload, dict) else {}
        details = error.get('details', []) if isinstance(error, dict) else []
        if isinstance(details, list):
            reasons = {item.get('reason') for item in details if isinstance(item, dict)
                       and isinstance(item.get('reason'), str)}
    except (ValueError, TypeError):
        pass
    messages = {
        'ACCOUNT_NOT_LINKED': '이 Google 계정에 Google Health 프로필이 연결되지 않았습니다. Google Health 앱에서 같은 Google 계정으로 프로필을 만들거나 기존 Fitbit 계정을 연결한 뒤 돌아와 주세요.',
        'SERVICE_DISABLED': 'Google Cloud 프로젝트에서 Google Health API가 활성화되지 않았습니다. OAuth 클라이언트를 만든 프로젝트의 API 라이브러리에서 사용 설정을 확인해 주세요.',
        'API_PRIVATE_PREVIEW_ACCESS_DENIED': '이 계정 또는 프로젝트에는 Google Health API 미리보기 접근 자격이 없습니다. Google Health 개발자 등록과 API 접근 승인을 확인해 주세요. 재로그인만으로는 해결되지 않습니다.',
        'MISSING_OAUTH_SCOPE': '걸음 수 조회에 필요한 활동·운동 읽기 권한이 없습니다. 아래 버튼으로 해당 권한을 다시 승인해 주세요.',
        'ACCESS_TOKEN_SCOPE_INSUFFICIENT': '걸음 수 조회에 필요한 활동·운동 읽기 권한이 없습니다. 아래 버튼으로 해당 권한을 다시 승인해 주세요.',
        'DISALLOWED_OAUTH_SCOPES': 'Google Health에서 허용되지 않는 권한 조합입니다. 앱의 OAuth 권한 등록과 API 접근 설정을 확인해 주세요.',
        'DATA_ACCESS_DENIED': '이 계정의 Health 데이터 접근이 거부되었습니다. 연결 계정과 데이터 공유 동의 상태를 확인해 주세요.',
        'RESOURCE_PERMISSION_DENIED': 'Google Health 리소스 접근 권한이 없습니다. 개발자 앱 등록·접근 승인과 계정 권한을 확인해 주세요.',
    }
    for code, message in messages.items():
        if code in reasons:
            return GoogleHealthError(code, message, response.status_code)
    status = response.status_code
    fallback = {
        400: 'Google Health가 조회 요청을 처리하지 못했습니다. Health 프로필 연결 상태와 날짜별 조회 설정을 확인해야 합니다.',
        401: 'Google Health 인증이 만료되었거나 유효하지 않습니다. 아래 버튼으로 다시 연결해 주세요.',
        403: 'Google Health 접근이 거부되었습니다. API 사용 설정·개발자 접근 승인·읽기 권한을 확인해 주세요.',
        404: 'Google Health 조회 리소스를 찾을 수 없습니다. API 버전과 Health 계정 연결 상태를 확인해야 합니다.',
        429: 'Google Health 요청 한도를 초과했습니다. 반복 로그인 대신 잠시 후 새로고침해 주세요.',
    }
    return GoogleHealthError(f'HTTP_{status}' if type(status) is int else 'HTTP_ERROR',
        fallback.get(status, 'Google Health 서비스 조회에 실패했습니다. 잠시 후 다시 시도해 주세요.'), status)


def activity_provider():
    provider = getattr(settings, 'GOOGLE_ACTIVITY_PROVIDER', 'google_fit')
    if provider not in ('google_fit', 'google_health'):
        raise ImproperlyConfigured('GOOGLE_ACTIVITY_PROVIDER must be google_fit or google_health')
    return provider


def activity_scope():
    return HEALTH_SCOPE if activity_provider() == 'google_health' else FITNESS_SCOPE


def activity_label():
    return 'Google Health' if activity_provider() == 'google_health' else 'Google Fit'


def activity_scopes():
    return [HEALTH_SCOPE] if activity_provider() == 'google_health' else [CALENDAR_SCOPE, FITNESS_SCOPE]


def civil_midnight(day):
    return {'date': {'year': day.year, 'month': day.month, 'day': day.day}}


def parse_health_daily_steps(payload, day):
    if not isinstance(payload, dict):
        raise ValueError('Invalid Google Health response')
    points = payload.get('rollupDataPoints', [])
    if not isinstance(points, list) or len(points) > 1 or payload.get('nextPageToken'):
        raise ValueError('Unexpected Google Health daily windows')
    if not points:
        return None
    point = points[0]
    if (not isinstance(point, dict)
            or point.get('civilStartTime', {}).get('date') != civil_midnight(day)['date']
            or point.get('civilEndTime', {}).get('date') != civil_midnight(day + timedelta(days=1))['date']):
        raise ValueError('Unexpected Google Health daily range')
    if 'steps' not in point:
        return None
    if not isinstance(point['steps'], dict):
        raise ValueError('Invalid Google Health steps')
    # protobuf JSON은 실제 0인 기본값을 생략할 수 있습니다. steps 자체가 없는 경우와 구분합니다.
    count = point['steps'].get('countSum', '0')
    if not isinstance(count, str) or not re.fullmatch(r'[0-9]{1,19}', count):
        raise ValueError('Invalid Google Health step count')
    value = int(count)
    if value > 2**63 - 1:
        raise ValueError('Google Health count exceeds int64')
    return value


def google_health_daily_steps(credentials, day):
    payload = _google_health_rollup(credentials, day, day + timedelta(days=1))
    try:
        return parse_health_daily_steps(payload, day)
    except (ValueError, TypeError, AttributeError):
        raise GoogleHealthError('INVALID_RESPONSE', 'Google Health 응답의 날짜 또는 걸음 수 형식을 확인할 수 없어 숫자를 반영하지 않았습니다.') from None


def google_health_steps_range(credentials, start, end):
    """종료일을 포함한 최대 7일을 한 번에 조회하고, 저장 전 전체 응답을 검증합니다."""
    days = (end - start).days + 1
    if not 1 <= days <= 7:
        raise ValueError('Google Health sync requires one to seven days')
    payload = _google_health_rollup(credentials, start, end + timedelta(days=1))
    try:
        if not isinstance(payload, dict) or payload.get('nextPageToken'):
            raise ValueError('Incomplete Google Health response')
        points = payload.get('rollupDataPoints', [])
        if not isinstance(points, list) or len(points) > days:
            raise ValueError('Invalid daily windows')
        values, seen = {}, set()
        allowed = {civil_midnight(start + timedelta(days=i))['date']['day']: start + timedelta(days=i) for i in range(days)}
        for point in points:
            stamp = point['civilStartTime']['date']
            day = allowed.get(stamp['day'])
            if day is None or day in seen:
                raise ValueError('Unexpected or duplicate date')
            count = parse_health_daily_steps({'rollupDataPoints': [point]}, day)
            seen.add(day)
            if count is not None:
                values[day] = count
        return values
    except (ValueError, TypeError, AttributeError, KeyError):
        raise GoogleHealthError('INVALID_RESPONSE', 'Google Health 날짜별 응답을 확인할 수 없어 기존 기록을 유지했습니다.') from None


def _google_health_rollup(credentials, start, end):
    # 공식 v4 일별 집계 API: 조회만 하며 식사·운동·Google 데이터는 변경하지 않습니다.
    body = {'range': {'start': civil_midnight(start), 'end': civil_midnight(end)},
            'windowSizeDays': 1, 'pageSize': (end - start).days + 1}
    session = AuthorizedSession(credentials)
    try:
        response = session.post(
            'https://health.googleapis.com/v4/users/me/dataTypes/steps/dataPoints:dailyRollUp',
            json=body, timeout=20, allow_redirects=False)
        if response.status_code != 200:
            raise health_error_from_response(response)
        try:
            return response.json()
        except (ValueError, TypeError, AttributeError):
            raise GoogleHealthError('INVALID_RESPONSE', 'Google Health 응답의 날짜 또는 걸음 수 형식을 확인할 수 없어 숫자를 반영하지 않았습니다.') from None
    except (Timeout, ConnectionError):
        raise GoogleHealthError('NETWORK_ERROR', 'Google Health 서버에 연결하지 못했거나 응답 시간이 초과되었습니다. 네트워크 상태를 확인하고 잠시 후 새로고침해 주세요.') from None
    finally:
        session.close()
