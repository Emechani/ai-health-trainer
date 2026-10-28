# Render 첫 배포

이 구성은 기존 SQLite와 화면을 유지하는 **유료 Starter 웹 서비스 1개 + 영구 디스크 1GB**용입니다. 생성 화면의 실제 금액을 확인하고 승인한 뒤 배포하세요. 무료 서비스로 바꾸면서 디스크를 빼면 DB·사진·Google 인증 정보가 재시작 때 사라질 수 있습니다.

## 1. GitHub

비공개 저장소를 만들고 코드만 올립니다. `.env`, 개발 키, OAuth JSON, 토큰, 개인 DB, media/, meal_images/, venv/는 업로드하지 않습니다. 기존 PC의 계정·기록·사진은 첫 배포에 자동 이전되지 않습니다. 클라우드는 빈 DB로 시작하며 회원가입으로 새 계정을 만듭니다. 기존 데이터 이전은 백업 후 별도 작업으로 진행합니다.

## 2. Render Blueprint

1. Render에 로그인합니다.
2. **New → Blueprint**에서 GitHub 저장소를 선택합니다. GitHub 연결 권한은 해당 저장소만 선택하세요.
3. `render.yaml`이 표시되는지 확인합니다. 서비스 이름이 이미 있다면 새 고유 이름을 사용하세요.
4. `DJANGO_SECRET_KEY`에 새 운영 키(50자 이상)를 직접 입력합니다. Render의 자동 생성 값은 44자이므로 이 프로젝트의 검사 기준에 맞지 않습니다.
5. 서비스 1개, Singapore, Starter, 디스크 `/var/data` 1GB와 실제 청구 금액을 확인한 뒤 생성합니다. 자동 배포는 꺼 두었습니다.

운영 키가 필요하면 로컬에서 다음 명령으로 별도 파일을 만들고 편집기에서 해당 값만 복사할 수 있습니다. 기존 파일을 덮어쓰지 않으며 키는 콘솔에 출력하지 않습니다.

```powershell
.\venv\Scripts\python.exe scripts\init_production_env.py --output .env.render --host health.example.com
```

이때 예시 도메인은 도구에 필요한 자리표시자입니다. 파일 전체를 Render에 올리지 말고 **DJANGO_SECRET_KEY 값만** 입력하세요. Render 기본 호스트·HTTPS 출처는 서버의 `RENDER_EXTERNAL_HOSTNAME`에서 등록됩니다. 실제 커스텀 도메인을 쓰면 별도로 `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`를 설정하세요.

## 3. 비밀 설정

- Render **Environment**에 `GEMINI_API_KEY`를 직접 입력합니다. 로컬 `.env` 전체를 복사하거나 키를 채팅에 보내지 않습니다.
- Google 연동은 **Secret Files**에 `credentials_google_health.json` 이름으로 웹 OAuth JSON을 직접 등록합니다. 서버 경로는 `/etc/secrets/credentials_google_health.json`입니다. JSON은 GitHub에 올리지 않습니다.
- Google Cloud의 같은 웹 OAuth 클라이언트에 `https://실제서비스.onrender.com/google-fit/callback/`을 승인된 리디렉션 URI로 추가합니다. 개발용 localhost URI도 유지할 수 있습니다.
- 배포 주소에서 Health와 Calendar를 각각 재인증합니다. 로컬 사용자 토큰을 복사하지 않습니다.
- 이메일을 쓸 경우 SMTP 환경 변수를 설정합니다. 설정 전 비밀번호 재설정 메일은 발송되지 않습니다.

## 4. 빌드와 실행

- Python 3.14.6을 고정합니다. 빌드 단계는 의존성 설치와 `collectstatic`만 실행합니다. 빌드 때는 영구 디스크에 접근하지 않습니다.
- 실행 단계에서 `/var/data` 존재와 DB·사진·토큰 경로를 검사합니다. 해당 디스크를 연결하지 않은 서비스로 배포하지 마세요.
- 새 클라우드 DB에 Migration을 적용합니다. 기존 클라우드 DB에 미적용 Migration이 있으면 적용 전 DB와 사진을 `/var/data/backups`에 보존합니다. 이 사본은 다른 장치의 별도 백업을 대체하지 않으며 용량과 보관 기간을 관리해야 합니다.
- Waitress는 단일 프로세스로 `PORT`에 바인딩합니다. Render의 외부 HTTPS 종료에 맞춰 WSGI 스킴을 HTTPS로 지정합니다. 개인 사진은 Django 소유자 검사 후 제공하고 공개 정적 파일만 WhiteNoise가 제공합니다.
- `/healthz/`는 DB 연결만 확인하고 AI·Google API를 호출하지 않습니다. 자동 배포를 켜거나 Migration이 있는 업데이트를 배포하기 전에는 백업·중단 시간을 확인하세요.

## 5. 접속 후 직접 확인

1. 배포 로그의 빌드 성공과 서비스 **Live**, `/healthz/`의 `{"status":"ok"}` 확인
2. HTTPS에서 회원가입·로그인·프로필 저장
3. 운동·식사·사진 저장 후 새로고침과 재시작 후 유지 확인
4. Google OAuth 운영 URI 추가 후 각각 연결
5. Gemini 키 설정 후 필요한 최소 횟수로 AI 응답 확인
6. 다른 계정으로 개인 기록·사진 접근 차단 확인

첫 배포 전에는 이 항목들이 클라우드에서 검증되었다고 판단하지 않습니다.

## 로컬 사전 점검 결과 (2026-10-28)

- Linux x86_64 / Python 3.14.6 대상 의존성 해석 성공. 실제 Linux 빌드·실행 성공을 대신하지 않습니다.
- 별도 임시 DB에서 운영 설정으로 상태 확인 200, DB 오류 시 503, 로그인 페이지 200, 관리자 정적 CSS 200 확인.
- 허용되지 않은 Host 400, HTTP→HTTPS 이동, Render 기본 도메인의 CSRF 출처, 미로그인 개인 사진 접근 차단 확인.
- 실제 외부 HTTP·AI 호출 0회. 기존 DB 해시 변경 없음.
- GitHub 비공개 저장소 생성 완료. 이 문서 작성 시점에는 코드 업로드·Render 서비스 생성·공개 URL 검증은 아직 진행 중입니다.

공식 안내: [Django 배포](https://render.com/docs/deploy-django), [영구 디스크](https://render.com/docs/disks), [Python 버전](https://render.com/docs/python-version), [Blueprint 설정](https://render.com/docs/blueprint-spec).
