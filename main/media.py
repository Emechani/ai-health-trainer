from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from records.models import Meal


@login_required
@require_GET
def private_media(request, path):
    """운영 환경의 식사 사진은 해당 기록 소유자에게만 제공합니다."""
    get_object_or_404(Meal, image=path, daily_record__user=request.user)
    root = Path(settings.MEDIA_ROOT).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise Http404
    response = FileResponse(target.open('rb'))
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
