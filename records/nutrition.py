import math
from datetime import timedelta

from .models import Meal


def nutrition_summary(user, today):
    """미분석 값을 0으로 간주하지 않고 본인의 최근 7일 기록만 요약합니다."""
    meals = list(Meal.objects.filter(
        daily_record__user=user, daily_record__date__range=[today - timedelta(days=6), today],
    ).values('daily_record__date', 'calories', 'carbs', 'protein', 'fat'))
    labels = {'calories': ('칼로리', 'kcal'), 'carbs': ('탄수화물', 'g'), 'protein': ('단백질', 'g'), 'fat': ('지방', 'g')}

    def known(value):
        return isinstance(value, (int, float)) and math.isfinite(value) and value >= 0

    nutrients = []
    for field, (label, unit) in labels.items():
        values = [meal[field] for meal in meals if known(meal[field])]
        nutrients.append({'name': field, 'label': label, 'unit': unit,
                          'total': round(sum(values), 1) if values else None,
                          'known_count': len(values), 'missing_count': len(meals) - len(values)})
    complete = [meal for meal in meals if all(known(meal[field]) for field in labels)]
    messages = []
    if not meals:
        messages.append('최근 7일 식사 기록이 없습니다. 식단을 등록하면 영양 보완 안내를 받을 수 있습니다.')
    elif len(complete) < len(meals):
        messages.append(f'{len(meals)}건 중 {len(meals) - len(complete)}건은 영양소 정보가 일부 미분석입니다. 미분석은 섭취량 0이나 영양 부족을 뜻하지 않습니다.')
    if complete and sum(meal['protein'] for meal in complete) == 0:
        messages.append('분석이 완료된 식사의 단백질이 0g으로 기록되어 있습니다. 분석값이 맞는지, 단백질 식품을 함께 먹었는지 확인해 주세요.')
    messages.append('일부 식사만 기록했을 수 있어 이 합계를 하루 섭취량이나 개인 권장량과 비교하지 않습니다.')
    return {'start_date': (today - timedelta(days=6)).isoformat(), 'end_date': today.isoformat(),
            'meal_count': len(meals), 'recorded_days': len({meal['daily_record__date'] for meal in meals}),
            'complete_count': len(complete), 'nutrients': nutrients, 'messages': messages}
