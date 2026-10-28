"""운영 환경 변수 파일을 새로 만들며 비밀 값은 출력하지 않습니다."""
import argparse
import secrets
from pathlib import Path


def create_env(output, host):
    if not host or any(char in host for char in '/\\:*\r\n ') or host.startswith('.'):
        raise ValueError('Enter a hostname without scheme, path, wildcard or port')
    sample = Path(__file__).resolve().parents[1] / '.env.example'
    values = {'DJANGO_ENV':'production', 'DJANGO_DEBUG':'false',
              'DJANGO_SECRET_KEY':secrets.token_urlsafe(50), 'DJANGO_ALLOWED_HOSTS':host,
              'DJANGO_CSRF_TRUSTED_ORIGINS':'https://'+host, 'GOOGLE_ACTIVITY_PROVIDER':'google_health'}
    lines = []
    for line in sample.read_text(encoding='utf-8').splitlines():
        key = line.partition('=')[0]
        lines.append(key+'='+values[key] if key in values else line)
    with Path(output).open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create a NEW production env file without printing secrets.')
    parser.add_argument('--output', required=True)
    parser.add_argument('--host', required=True)
    args = parser.parse_args()
    create_env(args.output, args.host)
    print('Environment file created. Enter service keys and persistent paths directly in this file.')
