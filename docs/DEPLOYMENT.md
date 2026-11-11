# 설치·배포 준비

이 문서는 **배포 절차의 준비본**입니다. 아직 실제 서버를 공개하거나 기존 실행 서버를 중지하지 않았습니다. 도메인·HTTPS·Google 운영 설정·메일·데이터 저장 위치는 배포 환경에서 결정해야 합니다.

## 1. 구성과 비밀 값

`config/settings.py`는 `DJANGO_ENV=development`(기본)와 `production`을 구분합니다. 기존 manage.py/WSGI/ASGI 진입점은 유지합니다.

운영에서는 새로운 50자 이상 Django 비밀 키와 구체적인 허용 도메인이 필요합니다. 누락되거나 DEBUG가 켜지면 서버가 시작되지 않습니다. 로컬 `.django-dev-secret`은 운영에 사용하지 않습니다.

새 운영 파일은 키를 콘솔에 출력하지 않고 만들 수 있습니다. **실제 도메인으로 바꾸고, 존재하는 파일을 덮어쓰지 않습니다.**

```powershell
.\venv\Scripts\python.exe scripts\init_production_env.py --output .env.production --host health.example.com
```

생성 후 편집기에서 다음을 직접 설정하세요. 파일 내용 전체를 채팅·로그·화면 공유에 노출하지 않습니다.

| 변수 | 운영 설정 |
|---|---|
| DJANGO_ENV | production |
| DJANGO_DEBUG | false |
| DJANGO_SECRET_KEY | 도구가 생성한 운영 전용 값. 개발 키 재사용 금지 |
| DJANGO_ALLOWED_HOSTS | `health.example.com`처럼 호스트만. 여러 개는 쉼표. `*` 금지 |
| DJANGO_CSRF_TRUSTED_ORIGINS | `https://health.example.com`처럼 HTTPS 출처 |
| DJANGO_DB_PATH | 예: `C:/HealthData/db.sqlite3` 또는 `/var/lib/health/db.sqlite3` |
| DJANGO_MEDIA_ROOT | 예: `C:/HealthData/media` 또는 `/var/lib/health/media` |
| GOOGLE_TOKEN_DIR | 웹에서 공개하지 않는 영속 폴더. DB·사진과 별도 권한 관리 |
| GOOGLE_CLIENT_SECRETS_FILE | 기존 Fit 연결이 필요할 때의 비공개 JSON 경로 |
| GOOGLE_HEALTH_CLIENT_SECRETS_FILE | Health 웹 OAuth 클라이언트 JSON의 비공개 절대 경로 |
| GOOGLE_ACTIVITY_PROVIDER | google_health |
| GEMINI_API_KEY | 실제 키를 직접 설정 |
| DJANGO_CACHE_URL | 공용 Redis URL. 서비스 외부에 공개하지 않음. 자격 증명이 있으면 비밀 값으로 관리 |
| DJANGO_TRUST_PROXY_HEADERS | 아래 신뢰 프록시 구성을 완료한 경우에만 true |
| DJANGO_EMAIL_HOST / PORT / USER / PASSWORD | 메일 발송이 필요하면 실제 SMTP 설정. 기본 포트 587/TLS |
| DJANGO_DEFAULT_FROM_EMAIL | 발신 권한이 있는 메일 주소 |

빈 DB·미디어 경로를 지정하면 기존 데이터가 자동으로 옮겨지는 것은 아닙니다. 경로를 변경하기 전에 백업·복구 절차로 데이터를 준비해야 합니다. 기존 경로 기본값은 유지되어 개발 서버에서는 기존 DB·사진을 계속 사용합니다.

환경 파일을 선택합니다. 실제 OS 환경 변수에 이미 있는 값이 파일보다 우선합니다.

```powershell
$env:DJANGO_ENV_FILE=(Resolve-Path .env.production).Path
```

개발로 돌아갈 때는 새 터미널을 사용하거나 이 작업용 변수를 제거하고 기본 `.env`를 사용합니다. 서버 서비스에도 동일한 운영 환경 파일 또는 비밀 저장소 설정을 명시해야 합니다.

## 2. 운영 의존성·검사

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-production.txt
.\venv\Scripts\python.exe -m pip check
.\venv\Scripts\python.exe manage.py check --deploy
.\venv\Scripts\python.exe manage.py migrate --plan
```

`migrate --plan`은 실제 적용이 아닙니다. 쓰기 중지·백업·계획 검토 후에만 실제 `migrate`를 실행합니다. 이번 정리 작업에서는 운영 DB에 적용하지 않았습니다.

```powershell
.\venv\Scripts\python.exe manage.py collectstatic --noinput
```

정적 파일은 `STATIC_ROOT`(기본 staticfiles/)로 수집됩니다. 운영 프록시는 이 경로의 `/static/`만 공개하세요. 프로젝트 폴더 전체를 웹 루트로 지정하면 안 됩니다.

## 3. Windows/Linux WSGI 실행 예시

Waitress는 두 OS에서 사용할 수 있는 운영용 WSGI 서버입니다. 로컬 개발용 `runserver`를 외부에 공개하지 않습니다.

신뢰할 수 있는 같은 머신의 리버스 프록시 뒤에서만 아래 구성을 사용합니다.

```powershell
.\venv\Scripts\waitress-serve.exe --listen=127.0.0.1:8080 --trusted-proxy=127.0.0.1 --trusted-proxy-headers=x-forwarded-proto config.wsgi:application
```

Linux에서는 같은 옵션을 `venv/bin/waitress-serve`에 전달합니다. 서비스 관리자(systemd 또는 Windows 서비스 관리 도구)에서 작업 디렉터리·환경 변수·재시작 정책·로그 위치·권한을 지정해야 합니다. 이 명령은 이번 작업에서 실제 공개 서비스로 실행하지 않았습니다.

프록시는 HTTPS 인증서를 설치하고 HTTP를 HTTPS로 리디렉션해야 합니다. 외부의 `X-Forwarded-Proto`를 그대로 신뢰하지 말고 프록시가 직접 덮어쓰세요. 다음은 Nginx 전달 규칙의 핵심 예시이며 인증서·도메인·경로는 직접 구성해야 합니다.

```nginx
location / {
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_pass http://127.0.0.1:8080;
}
```

Waitress 포트는 외부에서 직접 접근할 수 없게 유지합니다. 배포에서 HTTPS 리디렉션이 반복되면 URL을 무작정 바꾸지 말고 신뢰 프록시 설정과 전달 헤더를 확인하세요.

## 4. 개인 파일·공용 캐시

- 운영 `DEBUG=False`에서는 `/media/...`가 로그인한 식사 기록 소유자에게만 제공됩니다. **프록시에서 media 폴더를 공개 정적 alias로 연결하지 마세요.** `/media/`도 Django로 전달합니다.
- `.env`, `.django-dev-secret`, OAuth JSON, `.google_tokens`, 개인 SQLite·백업·업로드·로그는 Git에서 제외했습니다. 이미 Git에 커밋된 파일이나 다른 백업 서비스의 복사본까지 제거하는 설정은 아닙니다.
- SQLite는 기존 DB를 유지하는 초기 배포 경로입니다. 여러 머신에서 같은 파일을 네트워크 공유하거나 고부하 쓰기를 처리하는 구성은 검증하지 않았습니다. DB 엔진 교체는 별도 작업입니다.
- 로컬 메모리 캐시는 한 프로세스에서만 동작합니다. 여러 프로세스·서버를 쓰면 Redis를 실제로 준비하고 `DJANGO_CACHE_URL`을 설정하세요. 패키지 설치가 Redis 서버 설치·연결 검증을 대신하지 않습니다. Redis는 인증·접근 제한·필요시 TLS를 적용하고 인터넷에 공개하지 않습니다.

## 5. Google 운영 연결과 로그

Google Cloud 웹 OAuth 클라이언트에 `https://실제도메인/google-fit/callback/`을 추가하세요. localhost 콜백과 다릅니다. Health와 Calendar는 서로 다른 읽기 권한과 사용자별 저장 위치를 사용합니다. OAuth 승인·개발자 접근 자격·테스트 사용자 또는 운영 검증 상태는 Google 설정에서 확인해야 합니다.

접근 로그에는 OAuth `code`, `state`, 토큰, 전체 쿼리 문자열이 남지 않도록 설정합니다. 예를 들어 Nginx 로그 형식에는 `$request_uri` 또는 `$request` 대신 `$request_method $uri $server_protocol`을 사용하세요. 요청 본문·쿠키·Authorization 헤더·개인 건강 기록은 기록하지 않습니다.

## 계정 찾기와 이메일 발송

로그인·회원가입은 공통 카드 화면을 사용합니다. 새 가입자는 복구 이메일을 입력하며, 기존 사용자는 프로필 설정에서 현재 비밀번호를 확인한 뒤 복구 이메일을 등록·변경할 수 있습니다. DB 필드 추가나 기존 사용자 데이터 변환은 필요하지 않습니다. 이메일을 등록하지 않은 기존 계정은 이메일 복구가 불가능합니다.

아이디 찾기는 활성 계정의 아이디를 이메일로만 안내합니다. 비밀번호 재설정은 Django의 일회용 토큰 검증을 사용하며, 사용한 링크를 다시 사용할 수 없습니다. 이메일 등록 여부는 완료 화면에 표시하지 않습니다. 기존 비밀번호를 조회하거나 이메일로 전송하지 않습니다.

운영 서버의 비공개 `.env`에 기존 항목 `DJANGO_EMAIL_HOST`, `DJANGO_EMAIL_PORT`, `DJANGO_EMAIL_USER`, `DJANGO_EMAIL_PASSWORD`, `DJANGO_DEFAULT_FROM_EMAIL`을 메일 공급자의 SMTP 설정으로 입력하세요. 현재 설정은 STARTTLS를 사용합니다(통상 587 포트). 실제 비밀번호나 앱 비밀번호는 Git·채팅·스크린샷에 포함하지 않습니다. 수정 후 서비스를 재시작합니다. SMTP 호스트·발신자 미설정 시 화면에서 안내하고, 콘솔·파일 백엔드에는 복구 링크와 아이디를 출력하지 않습니다. 실제 수신함 도착은 별도로 확인해야 합니다.

계정 찾기 요청은 이메일별 시간당 5회, 연결 주소별 시간당 30회로 제한합니다. 현재 Nginx→Waitress 구성의 연결 주소는 localhost이므로 주소별 제한은 서버 전체에 적용될 수 있습니다. 캐시 재시작 시 제한이 초기화되며, 여러 프로세스에서는 공유 캐시 설정이 필요합니다. 발송은 동기식이므로 응답 시간만으로 계정 존재를 추측하는 공격까지 완전히 차단하지는 않습니다. 대규모 공개 서비스에는 발송 큐·경계 요청 제한을 별도로 검토하세요.

공식 근거: [Django 비밀번호 재설정](https://docs.djangoproject.com/en/6.1/topics/auth/default/#django.contrib.auth.views.PasswordResetView).

## 6. 운영 전 남은 확인

- 실제 도메인·HTTPS 인증서·프록시·서비스 관리자 기동
- 실제 Google OAuth/Health/Calendar와 SMTP 발송
- Redis 연결 및 여러 프로세스에서의 잠금·사용자 분리
- 운영 데이터 백업·복구 리허설과 보관 위치 암호화
- 개인 사진의 본인 접근·다른 사용자 차단, 정적 파일 제공
- HSTS 기본 1시간을 도메인 정책에 맞게 검토. 하위 도메인 포함·preload는 자동 활성화하지 않았으며, 모든 하위 도메인의 HTTPS 준비와 등록 요건을 확인한 후 결정
- 기존 Gemini SDK 지원 종료 경고는 별도 SDK 전환 작업으로 남아 있음

공식 근거: [Django 배포 체크리스트](https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/), [Django Redis 캐시](https://docs.djangoproject.com/en/6.1/topics/cache/#redis), [Waitress](https://docs.pylonsproject.org/projects/waitress/en/stable/).
