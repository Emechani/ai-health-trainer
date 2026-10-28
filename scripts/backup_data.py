"""SQLite와 업로드 파일만 백업합니다. 인증 정보는 포함하지 않습니다."""
import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def backup(database, media, output):
    database, media, output = (Path(path).resolve() for path in (database, media, output))
    project = Path(__file__).resolve().parents[1]
    if not database.is_file() or not media.is_dir():
        raise ValueError('Database file and media directory must exist')
    if output.is_relative_to(project) or output.is_relative_to(media):
        raise ValueError('Backup output must be outside the project and media directory')
    # 다른 위치의 비밀 파일까지 따라가지 않도록 링크·접합점을 거부합니다.
    for path in [media, *media.rglob('*')]:
        if path.is_symlink() or path.is_junction():
            raise ValueError('Media links/junctions are not supported')
    target = output / datetime.now(timezone.utc).strftime('health-%Y%m%dT%H%M%S%fZ')
    target.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(database.as_uri()+'?mode=ro', uri=True) as source, \
            sqlite3.connect(target/'database.sqlite3') as destination:
        source.backup(destination)
        if destination.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Backup database integrity check failed')
    shutil.copytree(media, target/'media')
    files = [target/'database.sqlite3', *sorted(path for path in (target/'media').rglob('*') if path.is_file())]
    manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'format_version': 1,
                'contains_credentials': False,
                'files': {str(path.relative_to(target)): {'sha256': digest(path), 'bytes': path.stat().st_size} for path in files}}
    (target/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    # 파일·경로·개인 정보가 포함된 자세한 목록은 콘솔에 출력하지 않습니다.
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pause application writes before making a consistent DB + media backup.')
    parser.add_argument('--database', required=True)
    parser.add_argument('--media-root', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    target = backup(args.database, args.media_root, args.output)
    print('Backup complete:', target)
