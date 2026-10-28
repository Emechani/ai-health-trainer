# AI 다이어트·운동 추천 시스템

Django 기반 식사·운동·체중 기록, AI 식단·주간 실천 계획, Google Health/Calendar 읽기 연동 프로젝트입니다.

## 새 PC에서 개발 실행 (PowerShell)

검증 기준은 **Windows, CPython 3.14.6**입니다. 동일 Python 계열로 먼저 재현하세요. 기존 PC의 `venv` 폴더를 복사하지 않습니다.

```powershell
cd C:\작업폴더\my_django_project
py -3.14 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pip check
Copy-Item .env.example .env
```

`Copy-Item`은 **새 PC에 .env가 없는 경우에만** 실행하세요. 기존 프로젝트의 실제 `.env`를 덮어쓰지 마세요. `.env`에 실제 키는 본인이 입력하며 채팅·Git·로그에 공유하지 않습니다.

- `GEMINI_API_KEY`: 실제 API 키. 미설정이어도 일반 기록은 사용할 수 있습니다.
- `GOOGLE_ACTIVITY_PROVIDER`: Health를 사용하려면 `google_health`.
- `WEEKLY_GOAL_MODEL`: 비워 두면 `gemini-3.5-flash-lite`.
- 나머지 AI 모델 설정은 비어 있으면 기존 기본값을 사용합니다.

새 계정으로 시작할 때:

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py runserver
```

**기존 데이터를 옮기는 경우 빈 DB로 시작하지 말고**, 먼저 [백업·복구 절차](docs/BACKUP.md)를 따라 DB·업로드를 복구하고 백업 후 마이그레이션 상태를 확인하세요.

Google OAuth 클라이언트 JSON은 별도의 안전한 방법으로 전달하거나 새 PC에서 다시 설정합니다. 기존 사용자 토큰을 소스 압축 파일에 포함하지 않습니다. 다른 PC에서는 재인증을 권장합니다. Health와 Calendar는 각 버튼에서 별도로 승인합니다. 로컬 콜백은 `http://127.0.0.1:8000/google-fit/callback/`입니다.

첫 실행 시 Git 제외 파일 `.django-dev-secret`에 개발용 Django 키를 보관합니다. 기존 PC에서는 세션 보존을 위해 이전 개발 키를 이 로컬 파일로 옮겼습니다. 운영에서는 이 키를 재사용하지 않습니다.

### 기본 venv/pip 초기화가 권한 문제로 실패하는 경우

백신·관리 정책·임시 폴더 접근 권한을 확인하세요. 보안 설정을 끄지 마세요. 대안으로 공식 설치한 uv를 사용할 수 있습니다.

```powershell
uv venv --python 3.14 venv
uv pip install --python .\venv\Scripts\python.exe -r requirements.txt
```

uv는 선택적인 설치 도구이며 앱 실행 의존성이 아닙니다.

## 의존성 파일

- `requirements.txt`: 소스에서 사용하는 직접 실행 의존성. Google API·OAuth·Gemini·Pillow 포함.
- `constraints.txt`: 현재 동작 환경의 간접 의존성 버전 고정. 함께 배포해야 합니다.
- `requirements-production.txt`: 기본 의존성 + Waitress + Redis 클라이언트.

모델·SDK를 임의로 업그레이드하지 않았습니다. 기존 `google-generativeai`의 지원 종료 경고는 별도 전환 작업으로 남아 있습니다.

## 다음 문서

- [Render 첫 배포](docs/RENDER.md)
- [운영 설정과 배포 준비](docs/DEPLOYMENT.md)
- [백업·복구와 개인 파일 관리](docs/BACKUP.md)

`requirements.txt` 설치 성공이 운영 배포 완료를 뜻하지는 않습니다. 실제 도메인·HTTPS·서버·메일·공용 캐시·Google 운영 콜백을 준비해야 합니다.
