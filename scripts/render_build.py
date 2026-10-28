"""Render 빌드에서는 패키지·정적 파일만 준비하고 개인 DB는 건드리지 않습니다."""
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements-production.txt'], cwd=root, check=True)
    subprocess.run([sys.executable, 'manage.py', 'check'], cwd=root, check=True)
    subprocess.run([sys.executable, 'manage.py', 'collectstatic', '--noinput'], cwd=root, check=True)


if __name__ == '__main__':
    main()
