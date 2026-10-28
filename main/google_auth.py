import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from django.conf import settings
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from .google_activity import FITNESS_SCOPE, CALENDAR_SCOPE, activity_provider, activity_scope, activity_scopes

SCOPES = [CALENDAR_SCOPE, FITNESS_SCOPE]


def google_token_path(user):
    # 공용 token.json을 임의의 사용자에게 배정하지 않습니다.
    directory = Path(getattr(settings, 'GOOGLE_TOKEN_DIR', settings.BASE_DIR / '.google_tokens'))
    if activity_provider() == 'google_health':
        directory = directory / 'google_health'
    return directory / f'user_{int(user.pk)}.json'


def google_calendar_token_path(user):
    directory = Path(getattr(settings, 'GOOGLE_TOKEN_DIR', settings.BASE_DIR / '.google_tokens'))
    return directory / 'calendar' / f'user_{int(user.pk)}.json'


def calendar_credentials(user, fallback=None):
    path = google_calendar_token_path(user)
    if path.exists():
        return Credentials.from_authorized_user_file(str(path))
    if fallback is not None and fallback.has_scopes([CALENDAR_SCOPE]):
        return fallback
    # 이전 사용자별 Fit 연결도 캘린더 읽기 권한이 있으면 계속 사용할 수 있습니다.
    legacy = Path(getattr(settings, 'GOOGLE_TOKEN_DIR', settings.BASE_DIR / '.google_tokens')) / f'user_{int(user.pk)}.json'
    if legacy.exists():
        credentials = Credentials.from_authorized_user_file(str(legacy))
        if credentials.has_scopes([CALENDAR_SCOPE]):
            return credentials
    raise ValueError('Calendar connection required')


def save_google_credentials(user, credentials, *, purpose='activity'):
    data = json.loads(credentials.to_json())
    if credentials.granted_scopes is not None:
        granted = credentials.granted_scopes
        data['scopes'] = granted.split() if isinstance(granted, str) else list(granted)
    target = google_calendar_token_path(user) if purpose == 'calendar' else google_token_path(user)
    if purpose != 'calendar' and activity_provider() == 'google_health' and target.exists():
        calendar_target = google_calendar_token_path(user)
        # 사용자가 새 Health 권한을 승인할 때 이전 Calendar 연결을 별도 위치에 보존합니다.
        try:
            previous = json.loads(target.read_text(encoding='utf-8'))
        except (ValueError, UnicodeError):
            previous = {}
        scopes = previous.get('scopes', []) if isinstance(previous, dict) else []
        scopes = scopes.split() if isinstance(scopes, str) else scopes
        if isinstance(scopes, list) and CALENDAR_SCOPE in scopes and not calendar_target.exists():
            _write_credentials(calendar_target, previous)
    _write_credentials(target, data)


def _write_credentials(target, data):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(data, stream)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def google_oauth_flow(redirect_uri, state, verifier, *, purpose='activity'):
    if activity_provider() == 'google_health':
        path = Path(settings.GOOGLE_HEALTH_CLIENT_SECRETS_FILE)
    else:
        path = Path(getattr(settings, 'GOOGLE_CLIENT_SECRETS_FILE', settings.BASE_DIR / 'credentials.json'))
    config = json.loads(path.read_text(encoding='utf-8'))
    if activity_provider() == 'google_health' and 'web' not in config:
        raise ValueError('Google Health requires a web OAuth client')
    parsed = urlparse(redirect_uri)
    loopback = parsed.hostname in ('127.0.0.1', 'localhost', '::1')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and loopback):
        raise ValueError('OAuth callback requires HTTPS or loopback')
    if 'installed' in config and not loopback:
        raise ValueError('Hosted service requires a web OAuth client')
    scopes = [CALENDAR_SCOPE] if purpose == 'calendar' else activity_scopes()
    return Flow.from_client_config(config, scopes=scopes, state=state, redirect_uri=redirect_uri,
                                   code_verifier=verifier, autogenerate_code_verifier=False)



def fetch_google_token(flow, code, *, required_scope=None):
    try:
        return flow.fetch_token(code=code, timeout=20)
    except Warning as warning:
        # Google이 기존 승인 권한을 함께 돌려주면 OAuthlib이 scope 변경 Warning을 예외로 던집니다.
        # 검증을 전역 해제하지 않고, 실제 토큰과 필수 읽기 권한을 확인한 경우만 수용합니다.
        token = getattr(warning, 'token', None)
        if not isinstance(token, dict) or not token.get('access_token'):
            raise ValueError('Invalid Google authorization response') from None
        scope = token.get('scope', [])
        if isinstance(scope, str):
            scope = scope.split()
        if not isinstance(scope, (list, tuple, set)) or (required_scope or activity_scope()) not in scope:
            raise ValueError('Required activity scope not granted') from None
        flow.oauth2session.token = dict(token)
        flow.oauth2session.scope = list(scope)
        return dict(token)
