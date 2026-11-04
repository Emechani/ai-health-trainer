"""Render의 영구 디스크를 준비하고 단일 WSGI 프로세스로 실행합니다."""
import os
import subprocess
import sys
from pathlib import Path


def main():
    if os.environ.get('RENDER') != 'true':
        raise RuntimeError('This entry point is for Render only')
    if os.environ.get('DJANGO_ENV') != 'production':
        raise RuntimeError('Render must use DJANGO_ENV=production')
    root = Path(__file__).resolve().parents[1]
    data = Path('/var/data')
    if not data.is_dir():
        raise RuntimeError('Attach the persistent disk at /var/data before starting')
    for name in ('DJANGO_DB_PATH', 'DJANGO_MEDIA_ROOT', 'GOOGLE_TOKEN_DIR'):
        value = Path(os.environ.get(name, '')).resolve()
        if not value.is_relative_to(data) or value == data:
            raise RuntimeError(f'{name} must point inside /var/data')
        (value.parent if name == 'DJANGO_DB_PATH' else value).mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    sys.path.insert(0, str(root))
    command = [sys.executable, 'manage.py', 'migrate']
    pending = subprocess.run(command + ['--check'], cwd=root, capture_output=True)
    database = Path(os.environ['DJANGO_DB_PATH'])
    if pending.returncode and database.exists() and database.stat().st_size:
        # 스키마 적용 전 DB·사진 사본을 보존합니다. 이전 서버가 중지된 단일 디스크 배포용입니다.
        from backup_data import backup
        backup(database, Path(os.environ['DJANGO_MEDIA_ROOT']), data / 'backups')
        print('Pre-migration backup saved on the persistent disk.', flush=True)
    subprocess.run(command + ['--noinput'], cwd=root, check=True)
    from config.wsgi import application
    from waitress import serve
    # Render가 외부 HTTPS를 종료합니다. 전달 헤더를 무제한 신뢰하지 않고 WSGI 스킴을 지정합니다.
    serve(application, host='0.0.0.0', port=int(os.environ.get('PORT', '10000')),
          threads=4, url_scheme='https', clear_untrusted_proxy_headers=True)


if __name__ == '__main__':
    main()
