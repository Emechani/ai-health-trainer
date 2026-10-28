# 설치·배포 준비 검증 결과 (2026-10-28)

## 실행 결과

| 항목 | 결과 |
|---|---|
| 별도 가상환경 설치 | Windows / Python 3.14.6에서 운영 의존성까지 42개 설치 성공 |
| 의존성 충돌 검사 | `uv --no-cache pip check` 통과 |
| 주요 모듈 import | Django, Pillow, Gemini SDK, Google API/OAuth, requests, Waitress, Redis 성공 |
| 개발 설정 검사 | `manage.py check` 통과 |
| 운영 설정 검사 | `manage.py check --deploy` 오류 없음, HSTS 관련 경고 2개 |
| 운영 필수값 검증 | 비밀 키 누락, 호스트 누락·와일드카드, DEBUG 활성화 시 시작 차단 확인 |
| 운영 보호 설정 | 보안 쿠키·HTTPS 리디렉션·비공개 사진 URL 연결 확인 |
| Migration 변경 검사 | `makemigrations --check --dry-run`: 변경 없음 |
| 사진 접근 권한 | 별도 테스트 DB에서 2개 테스트 통과. 본인 조회, 타인 차단, 미로그인 이동, 경로 이탈 차단 |
| 백업 도구 | 가상 SQLite·이미지의 복사본 조회와 SHA-256 해시 확인. 원본 변경 없음 |
| 운영 환경 파일 생성 | 가상 파일로 강한 키 생성·운영 기본값·기존 파일 덮어쓰기 차단 확인 |
| Waitress 설정 | 설치 버전에서 문서의 신뢰 프록시 옵션 검증 |

기본 `venv`의 pip 초기화가 이 실행 환경의 임시 폴더 권한 오류로 실패하여, 공식 PyPI의 해시를 확인한 uv 설치 도구로 별도 환경을 구성했습니다. 일반 pip 방식의 설치 성공으로 보고하지 않습니다. 기존 프로젝트 가상환경은 수정하지 않았습니다.

사진 접근 권한 테스트에서 실제 HTTP/AI 호출은 차단했으며 호출 시도는 0회였습니다. 테스트 전후 기존 `db.sqlite3`의 SHA-256 값이 동일했습니다. 실제 `.env`, 사용자 토큰, 업로드 파일은 수정하지 않았습니다. 개발 Django 키는 재시작 세션 유지를 위해 기존 값을 Git 제외 로컬 파일 `.django-dev-secret`에 보존하고 코드의 직접 기재를 제거했습니다.

## 남은 경고와 미검증 범위

- `security.W005`, `security.W021`: HSTS 하위 도메인 포함·preload를 활성화하지 않았습니다. 실제 도메인의 모든 하위 도메인과 HTTPS 정책을 확인한 뒤 결정합니다. 경고를 숨기지 않았습니다.
- 실제 서버 공개, HTTPS 인증서, 프록시 요청, 서비스 자동 시작, Redis 서버 연결, SMTP 발송, 운영 도메인의 Google OAuth/API 연결은 수행하지 않았습니다.
- 실제 사용자 데이터의 백업·복구는 실행하지 않았습니다. 도구는 가상 데이터로 검증했으며 실제 운영에서는 암호화 저장소와 쓰기 중지 상태에서 복구 리허설이 필요합니다.
- 이번 검증은 설치·운영 설정·추가 보안 코드에 한정합니다. 전체 기능 테스트와 브라우저 테스트를 다시 실행하지 않았습니다.
- 기존 Gemini SDK의 지원 종료 경고는 남아 있습니다. 기존 AI 동작을 유지하기 위해 SDK나 모델을 변경하지 않았습니다.
- 다른 OS/Python 버전에서 설치는 검증하지 않았습니다.

## 수정·추가 파일

- `requirements.txt`, `constraints.txt`, `requirements-production.txt`
- `config/settings.py`, `config/urls.py`
- `.gitignore`, `.env.example`
- `main/media.py`, `main/test_private_media.py`
- `scripts/backup_data.py`, `scripts/init_production_env.py`
- `README.md`, `docs/DEPLOYMENT.md`, `docs/BACKUP.md`, 이 문서

실제 운영 준비 순서는 [배포 문서](DEPLOYMENT.md), 개인 데이터 관리와 복구 방법은 [백업 문서](BACKUP.md)를 참고하세요.
