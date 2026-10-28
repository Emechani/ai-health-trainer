from django.db import connection, DatabaseError
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health_check(request):
    """외부 API나 개인 기록을 조회하지 않는 서버·DB 상태 검사입니다."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({'status': 'unavailable'}, status=503)
    response = JsonResponse({'status': 'ok'})
    response['Cache-Control'] = 'no-store'
    return response
