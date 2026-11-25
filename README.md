# Health Overview

## 다이어트 맞춤 식단 및 개인화 운동 추천 AI 시스템

사용자의 식사·운동·체중 기록과 목표를 모아, AI가 제안하는 주간 실천 계획을 확인하고 기록을 이어갈 수 있는 Django 웹 애플리케이션입니다. 학교 프로젝트로 개발했으며 PC와 모바일 화면을 지원합니다.

- [프로젝트 저장소](https://github.com/Emechani/ai-health-trainer)
- [웹 서비스]() — 로그인 후 이용

## 주요 기능

| 기능 | 내용 |
| --- | --- |
| 계정·프로필 관리 | 회원가입·로그인·로그아웃, 이메일을 통한 아이디 안내·비밀번호 재설정, 체중 목표·운동 습관 설정 |
| 식사 기록·영양 분석 | 음식 사진 또는 직접 입력으로 식사를 기록하고 Gemini를 통해 음식·열량·탄수화물·단백질·지방 추정 |
| 운동·체중 기록 | 운동 종목·시작/종료 시간·거리·걸음 수 및 날짜별 체중 관리 |
| 목표 실천 | 프로필과 최근 기록을 참고해 요일별 운동·휴식과 식단을 포함한 주간 계획 생성, 홈에서 오늘 할 일 확인 |
| AI 트레이너 | 저장된 기록을 참고한 상담, 날짜별 대화 조회, 주간 계획 수정안 미리보기·적용 |
| Google 연동·달력 | Google Health 걸음 수 조회·동기화, Google Calendar 일정 읽기, 날짜별 기록 조회 |
| 주간 건강 리포트 | 걸음 수·운동·식사·체중 요약, 주간 그래프, 저장된 목표와 기록 비교, AI 코멘트 저장·갱신, PDF 다운로드 |
| 화면 설정 | 모바일 반응형 화면, 프로필 색상, 라이트·다크·기기 설정에 따른 화면 모드 |

운동과 식단은 **목표 실천의 주간 계획에서 함께 확인**하도록 구성했습니다. AI와 상담한 내용만으로 계획이 자동 변경되지는 않으며, 계획 수정 모드에서 수정안을 확인하고 적용해야 합니다.

## 사용 흐름

1. 회원가입 후 현재·목표 체중과 운동 습관을 설정합니다.
2. 식사·운동·체중을 기록하고, 필요한 경우 Google 계정을 연결합니다.
3. 목표 실천에서 음식 선호·알레르기·제한 조건을 확인한 뒤 이번 주 계획을 생성합니다.
4. 홈의 오늘 할 일과 달력에서 계획·실제 기록을 확인하고 AI 트레이너와 상담합니다.
5. 주간 건강 리포트에서 기록을 돌아보고, 필요할 때 AI 분석과 PDF 다운로드를 이용합니다.

## 기술 구성

| 구분 | 사용 기술 |
| --- | --- |
| 백엔드 | Python, Django |
| 프론트엔드 | Django Templates, HTML, CSS, JavaScript |
| 데이터베이스 | SQLite, Django ORM |
| AI | Google Gemini API — 텍스트 상담·계획 생성·음식 이미지 분석 |
| 외부 연동 | Google OAuth, Google Health, Google Calendar API |
| 이메일 | SMTP를 통한 계정 복구 메일 발송 |
| PDF | ReportLab, 한글 글꼴 포함 |
| 운영 환경 | Google Cloud Compute Engine, Ubuntu, Nginx, Waitress, systemd |

Gemini는 외부 API를 이용합니다. 이 프로젝트에서 별도의 AI 모델을 직접 학습한 것은 아닙니다.

## 새 PC에서 개발 실행 (PowerShell)

검증 기준은 **Windows, CPython 3.14.6**입니다. 동일 Python 계열로 먼저 재현하세요. 기존 PC의 `venv` 폴더를 복사하지 않습니다.

```powershell
cd C:\작업폴더\my_django_project
py -3.14 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pip check
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item .env.example .env
}
```

`Copy-Item`은 **새 PC에 .env가 없는 경우에만** 실행하세요. 기존 프로젝트의 실제 `.env`를 덮어쓰지 마세요. `.env`에 실제 키는 본인이 입력하며 채팅·Git·로그에 공유하지 않습니다.

- `GEMINI_API_KEY`: 실제 API 키. 미설정이어도 일반 기록은 사용할 수 있습니다.
- `GOOGLE_ACTIVITY_PROVIDER`: Health를 사용하려면 `google_health`.
- `WEEKLY_GOAL_MODEL`: 주간 계획 생성 모델. 비워 두면 코드의 기본값을 사용합니다.
- 나머지 AI 모델 설정은 비어 있으면 기존 기본값을 사용합니다.
- `GOOGLE_HEALTH_CLIENT_SECRETS_FILE`, `GOOGLE_CLIENT_SECRETS_FILE`: 기능별 OAuth 클라이언트 JSON 경로.
- `GOOGLE_TOKEN_DIR`: 사용자별 Google 인증 토큰 저장 폴더.
- `DJANGO_EMAIL_HOST`, `DJANGO_EMAIL_PORT`, `DJANGO_EMAIL_USER`, `DJANGO_EMAIL_PASSWORD`, `DJANGO_DEFAULT_FROM_EMAIL`: 이메일 기반 계정 복구를 위한 SMTP 설정. 계정에 등록된 복구 이메일도 필요합니다.
- `DJANGO_DB_PATH`, `DJANGO_MEDIA_ROOT`: DB와 업로드 파일의 저장 위치.
- `DJANGO_ENV`, `DJANGO_SECRET_KEY`: 실행 환경과 Django 비밀키. 운영에서는 별도의 비밀키를 설정합니다.

새 계정으로 시작할 때:

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py runserver
```

브라우저에서 `http://127.0.0.1:8000/`에 접속합니다. 새 DB에는 기존 서버의 계정·기록이 포함되지 않으므로 회원가입 후 사용합니다.

**기존 데이터를 옮기는 경우 빈 DB로 시작하지 말고**, 먼저 [백업·복구 절차](docs/BACKUP.md)를 따라 DB·업로드를 복구하고 백업 후 마이그레이션 상태를 확인하세요.

Google OAuth 클라이언트 JSON은 별도의 안전한 방법으로 전달하거나 새 PC에서 다시 설정합니다. 기존 사용자 토큰을 소스 압축 파일에 포함하지 않습니다. 다른 PC에서는 재인증을 권장합니다. Health와 Calendar는 각 버튼에서 별도로 승인합니다. 로컬 콜백은 `http://127.0.0.1:8000/google-fit/callback/`입니다.

로컬 개발에서 `DJANGO_SECRET_KEY`를 별도로 지정하지 않으면 첫 실행 시 Git 제외 파일 `.django-dev-secret`에 개발용 Django 키를 보관합니다. 운영에서는 별도의 비밀키를 사용합니다.

### 기본 venv/pip 초기화가 권한 문제로 실패하는 경우

백신·관리 정책·임시 폴더 접근 권한을 확인하세요. 보안 설정을 끄지 마세요. 대안으로 공식 설치한 uv를 사용할 수 있습니다.

```powershell
uv venv --python 3.14 venv
uv pip install --python .\venv\Scripts\python.exe -r requirements.txt
```

uv는 선택적인 설치 도구이며 앱 실행 의존성이 아닙니다.

## 데이터·AI 처리 기준

- 실제 저장된 사용자 기록을 참고하며, 미기록을 미실천·0 섭취·영양 결핍으로 단정하지 않습니다.
- 주간 리포트의 걸음 수는 Google Health·이전 Google Fit·수동 기록의 날짜별 출처 집계 중 큰 값을 사용해 중복 합산을 피합니다.
- AI의 음식·열량·영양소 추정과 운동 제안은 참고 정보이며 의학적 진단·처방이 아닙니다.
- AI 주간 분석은 사용자가 요청할 때 생성해 저장합니다. PDF 다운로드는 AI를 추가 호출하지 않습니다.
- Google 연동은 읽기·조회 기능이며, Google Calendar에 일정을 자동 작성하는 기능은 포함하지 않습니다.

## 비밀정보·개인정보 관리

소스 코드와 설정 예시를 공유하며, 다음 항목은 Git에서 제외하고 PC·서버의 별도 파일 또는 환경 변수로 관리합니다.

- `.env`와 실제 API 키·이메일 비밀번호·Django 비밀키
- Google OAuth 클라이언트 JSON과 사용자 인증 토큰
- 실제 사용자 DB, 업로드한 음식 사진, 백업 파일

실제 비밀값·계정 비밀번호·토큰을 README, 이슈, 스크린샷, 커밋에 넣지 않습니다. `.gitignore`는 과거 커밋의 파일까지 삭제하는 기능은 아니므로, 새 파일을 공개하기 전에도 커밋 내용을 확인해야 합니다.

## 프로젝트 구조

```text
config/       Django 설정과 공통 URL
main/         홈 대시보드, Google 인증·활동 연동, 공통 화면 스타일
users/        회원가입·계정 복구, 프로필·운동 습관·체중 기록
records/      식사·운동 기록, 달력·AI 상담, 목표 실천, 주간 리포트·PDF
ai_engine/    Gemini 호출·오류·요청 관리
templates/    공통 화면 요소와 인증 화면
scripts/      배포·백업 등 운영 보조 도구
docs/         운영 설정·배포·백업 문서
```

## 테스트

계정·권한, 기록 처리, Google 연동, AI 응답 처리, 계획 수정, 주간 리포트·PDF 관련 자동 테스트를 포함합니다. 외부 API는 모의 응답으로 검증하며, 실제 서비스 연결 여부는 별도 설정과 확인이 필요합니다.

```powershell
.\venv\Scripts\python.exe manage.py test users records main ai_engine
```

## 의존성 파일

- `requirements.txt`: 소스에서 사용하는 직접 실행 의존성. Google API·OAuth·Gemini·Pillow·ReportLab 포함.
- `constraints.txt`: 현재 동작 환경의 간접 의존성 버전 고정. 함께 배포해야 합니다.
- `requirements-production.txt`: 기본 의존성 + Waitress + Redis 클라이언트 + WhiteNoise.

현재 사용 중인 `google-generativeai` SDK의 지원 종료 경고는 추후 SDK 전환 작업으로 남아 있습니다.

## 다음 문서

- [운영 설정과 배포 준비](docs/DEPLOYMENT.md)
- [백업·복구와 개인 파일 관리](docs/BACKUP.md)
- [Render 배포 참고](docs/RENDER.md)

`requirements.txt` 설치 성공이 운영 배포 완료를 뜻하지는 않습니다. 실제 도메인·HTTPS·서버·메일·공용 캐시·Google 운영 콜백을 준비해야 합니다.
