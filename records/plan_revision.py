"""대화의 주간 계획 수정안을 검증하고 명시적으로 승인된 경우에만 새 버전으로 저장합니다."""
import copy
import hashlib
import json
import math
import secrets
import time
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.db import transaction, DatabaseError
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from users.models import UserProfile
from .models import GoalPlan, SavedMealPlan, ChatMessage
from .goal_progress import weekly_exercise_limits, weekly_goal_prompt, validated_weekly_goal, weekly_goal_error

SESSION_KEY = 'pending_plan_revision'
TTL = 15 * 60


def active_plan(user, profile, today):
    monday = today - timedelta(days=today.weekday())
    return GoalPlan.objects.filter(user=user, start_date=monday, end_date=monday+timedelta(days=6),
        target_weight=profile.target_weight, meal_snapshot__schedule_version=2).first() if profile else None


def fingerprint(profile, options):
    fields = ['current_weight','target_weight','exercise_experience','exercise_days_per_week',
              'exercise_minutes_per_session','preferred_exercises']
    source = {'profile': {field:getattr(profile,field) for field in fields}, 'options':options}
    return hashlib.sha256(json.dumps(source,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def plan_fingerprint(plan):
    return hashlib.sha256(json.dumps(plan.meal_snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def clean_revision(raw, base, profile, today, request_text):
    from .views import validated_meal_plan
    if not isinstance(raw,str) or len(raw)>80000:
        raise ValueError('Invalid revision')
    data = json.loads(raw)
    if not isinstance(data,dict) or not isinstance(data.get('days'),list) or len(data['days'])!=7:
        raise ValueError('Invalid revision days')
    original = base.meal_snapshot['daily_schedule']
    limits = weekly_exercise_limits(profile)
    # 사용자가 명시한 일반 종목만 추가 후보로 허용하며 프로필은 변경하지 않습니다.
    allowed = list(limits['names'])
    for name in ['걷기','달리기','수영','자전거','요가','스트레칭','근력운동']:
        if name in request_text and name not in allowed:
            allowed.append(name)
    validation_profile = copy.copy(profile)
    validation_profile.preferred_exercises = ','.join(allowed)
    past_count = 0
    for index, item in enumerate(data['days']):
        if not isinstance(item,dict) or type(item.get('weekday')) is not int or item['weekday']!=index:
            raise ValueError('Invalid weekday')
        if base.start_date+timedelta(days=index)<today:
            day = original[index]
            past_count += bool(day['exercise_minutes'])
            # 지난 날짜는 임시 휴식으로 검증한 뒤 원래 계획을 그대로 복원합니다.
            data['days'][index] = {'weekday':index,'exercise':{'name':'','minutes':0},
                                  'action':day['action'],'meals':day['meals']}
    snapshot, _ = validated_weekly_goal(json.dumps(data,ensure_ascii=False),validation_profile,validated_meal_plan,require_daily=True)
    future = [day for day in snapshot['daily_schedule'] if base.start_date+timedelta(days=day['weekday'])>=today]
    if sum(bool(day['exercise_minutes']) for day in future)>max(0,limits['max_days']-past_count):
        raise ValueError('Weekly exercise limit exceeded')
    for index, day in enumerate(snapshot['daily_schedule']):
        if base.start_date+timedelta(days=index)<today:
            snapshot['daily_schedule'][index] = copy.deepcopy(original[index])
    snapshot['meals'] = copy.deepcopy(snapshot['daily_schedule'][0]['meals'])
    snapshot['totals'] = copy.deepcopy(snapshot['daily_schedule'][0]['totals'])
    active = [day for day in snapshot['daily_schedule'] if day['exercise_minutes']]
    exercise = {'exercise_name':' / '.join(dict.fromkeys(day['exercise_name'] for day in active))[:50],
                'exercise_days':len(active),'exercise_minutes':max((day['exercise_minutes'] for day in active),default=0)}
    changes = []
    for before, after in zip(original,snapshot['daily_schedule']):
        if before!=after:
            changes.append({'date':(base.start_date+timedelta(days=after['weekday'])).isoformat(),
                            'before':before,'after':after})
    if not changes:
        raise ValueError('No plan changes')
    return snapshot, exercise, changes


def public_proposal(pending):
    return {key:pending[key] for key in ['nonce','expires_at','changes','summary','request']}


@login_required(login_url='/accounts/login/')
@never_cache
@require_http_methods(['GET','POST'])
def plan_revision(request):
    from .views import current_chat_day, recent_record_context, messages_for_day, genai, generate_ai, model_for
    today = current_chat_day()
    profile = UserProfile.objects.filter(user=request.user).first()
    base = active_plan(request.user,profile,today)
    options = request.session.get('meal_plan_options',base.saved_meal_plan.options if base and base.saved_meal_plan else {})
    pending = request.session.get(SESSION_KEY)
    valid = bool(pending and pending.get('user_id')==request.user.pk and pending.get('date')==today.isoformat()
                 and pending.get('expires_at',0)>time.time() and base and pending.get('base_id')==base.pk
                 and pending.get('profile_signature')==fingerprint(profile,options)
                 and pending.get('base_signature')==plan_fingerprint(base))
    if request.method=='GET':
        if pending and not valid:
            request.session.pop(SESSION_KEY,None)
        return JsonResponse({'status':'success','proposal':public_proposal(pending) if valid else None,'available':bool(base)})
    try:
        data = json.loads(request.body)
    except (ValueError,UnicodeDecodeError):
        return JsonResponse({'status':'error','message':'요청 형식을 확인해 주세요.'},status=400)
    if not isinstance(data,dict):
        return JsonResponse({'status':'error','message':'요청 형식을 확인해 주세요.'},status=400)
    action = data.get('action','propose')
    if action in ('apply','dismiss'):
        nonce = data.get('nonce')
        if not valid or not isinstance(nonce,str) or len(nonce)>128 or not secrets.compare_digest(nonce.encode(),pending['nonce'].encode()):
            return JsonResponse({'status':'error','message':'수정안이 만료되었거나 계획·프로필이 바뀌었습니다. 새 수정안을 만들어 주세요.'},status=409)
        if action=='dismiss':
            request.session.pop(SESSION_KEY,None)
            return JsonResponse({'status':'success','message':'수정안을 취소했습니다. 기존 계획을 유지합니다.'})
        try:
            with transaction.atomic():
                # 동시 승인에서 같은 원본으로 중복 적용하지 않도록 프로필 행을 잠급니다.
                locked = UserProfile.objects.select_for_update().get(pk=profile.pk)
                current = active_plan(request.user,locked,today)
                if not current or current.pk!=pending['base_id'] or plan_fingerprint(current)!=pending['base_signature'] or fingerprint(locked,options)!=pending['profile_signature']:
                    return JsonResponse({'status':'error','message':'계획 또는 프로필이 바뀌었습니다. 새 수정안을 만들어 주세요.'},status=409)
                meal = SavedMealPlan.objects.create(user=request.user,date=today,
                    plan={key:pending['snapshot'][key] for key in ['summary','meals','totals','notes']},
                    options=options,model_name=pending['model_name'],profile_snapshot={
                        'current_weight':locked.current_weight,'target_weight':locked.target_weight,'start_weight':locked.start_weight})
                revised = GoalPlan.objects.create(user=request.user,start_date=base.start_date,end_date=base.end_date,
                    current_weight=locked.current_weight,target_weight=locked.target_weight,saved_meal_plan=meal,
                    meal_snapshot=pending['snapshot'],**pending['exercise'])
                ChatMessage.objects.create(user=request.user,is_ai=True,message='승인한 수정안을 이번 주 계획에 적용했습니다. 홈의 오늘 할 일과 목표 실천에서 확인하세요. 이전 계획과 실제 기록은 보존했습니다.')
        except DatabaseError:
            return JsonResponse({'status':'error','message':'수정안을 저장하지 못했습니다. 기존 계획을 유지하며, 잠시 후 다시 확인해 주세요.'},status=503)
        request.session.pop(SESSION_KEY,None)
        return JsonResponse({'status':'success','message':'수정안을 적용했습니다. 홈과 목표 실천에 반영되었습니다.',
                             'plan_url':reverse('goal_progress')+f'?plan={revised.pk}'})
    if action!='propose':
        return JsonResponse({'status':'error','message':'지원하지 않는 요청입니다.'},status=400)
    message = data.get('message')
    if not isinstance(message,str) or not message.strip() or len(message)>2000:
        return JsonResponse({'status':'error','message':'수정 요청은 1~2,000자로 입력해 주세요.'},status=400)
    if data.get('date') not in (None,today.isoformat()):
        return JsonResponse({'status':'error','message':'날짜가 바뀌었습니다. 오늘 대화에서 다시 요청해 주세요.'},status=409)
    if not base or not profile or not all(value and math.isfinite(value) and value>0 for value in [profile.current_weight,profile.target_weight]):
        return JsonResponse({'status':'error','message':'현재 목표 체중에 맞는 이번 주 목표를 목표 실천에서 먼저 생성해 주세요.'},status=400)
    if valid and pending.get('request')==message.strip():
        return JsonResponse({'status':'success','proposal':public_proposal(pending),'reply':'기존 수정안을 확인해 주세요. 적용 전에는 계획이 바뀌지 않습니다.'})
    if time.time()-request.session.get('plan_revision_last_attempt',0)<30:
        return JsonResponse({'status':'error','message':'이전 수정 요청 후 30초가 지난 다음 다시 시도해 주세요.'},status=429)
    original_profile_signature = fingerprint(profile,options)
    original_base_signature = plan_fingerprint(base)
    request.session.pop(SESSION_KEY,None)
    request.session['plan_revision_last_attempt'] = time.time()
    ChatMessage.objects.create(user=request.user,is_ai=False,message=message.strip())
    source = {'week_start':base.start_date,'week_end':base.end_date,'today':today,
              'current_weight':profile.current_weight,'target_weight':profile.target_weight,
              'exercise_habits':profile.exercise_habits_summary,'exercise_limits':weekly_exercise_limits(profile),
              'recent_records':recent_record_context(request.user,today),'food_preferences_and_restrictions':options,
              'current_plan':base.meal_snapshot,'change_request':message.strip(),
              'today_conversation':[{'is_ai':item.is_ai,'message':item.message[:1000]} for item in messages_for_day(request.user,today).order_by('-pk')[:10]]}
    for name in ['걷기','달리기','수영','자전거','요가','스트레칭','근력운동']:
        if name in message and name not in source['exercise_limits']['names']:
            source['exercise_limits']['names'].append(name)
    prompt = weekly_goal_prompt(source)+'\n이번 요청은 기존 주간 계획의 수정입니다. 변경 요청과 관련된 오늘 이후 항목만 바꾸고 나머지 항목은 그대로 유지하세요. 목표 체중·프로필은 변경하지 않습니다. 과거 날짜는 수정하지 마세요.'
    try:
        response = generate_ai(request.user,'weekly_goal',prompt,genai,model_name=model_for('weekly_goal'),json_mode=True)
        snapshot,exercise,changes = clean_revision(response.text,base,profile,today,message)
    except Exception as exc:
        if isinstance(exc,ValueError) and str(exc)=='No plan changes':
            return JsonResponse({'status':'error','message':'변경할 내용이 없습니다. 수정할 요일·운동·식단을 구체적으로 입력해 주세요.'},status=400)
        return JsonResponse({'status':'error','message':weekly_goal_error(exc,'response' if isinstance(exc,(ValueError,KeyError,TypeError)) else 'api')},status=502)
    # AI 응답을 기다리는 동안 프로필이나 원본이 바뀌면 적용을 막습니다.
    profile.refresh_from_db()
    current = active_plan(request.user,profile,today)
    if not current or current.pk!=base.pk or plan_fingerprint(current)!=original_base_signature or fingerprint(profile,options)!=original_profile_signature or current_chat_day()!=today:
        return JsonResponse({'status':'error','message':'생성 중 원래 계획이 바뀌었습니다. 다시 요청해 주세요.'},status=409)
    pending = {'user_id':request.user.pk,'date':today.isoformat(),'base_id':base.pk,
               'profile_signature':original_profile_signature,'base_signature':original_base_signature,
               'snapshot':snapshot,'exercise':exercise,'changes':changes,'summary':snapshot['summary'],
               'nonce':secrets.token_urlsafe(24),'expires_at':int(time.time()+TTL),'request':message.strip(),'model_name':model_for('weekly_goal')}
    request.session[SESSION_KEY] = pending
    reply = '주간 계획 수정안을 준비했습니다. 변경 전·후를 확인하고 ‘계획에 적용’을 눌러 주세요. 아직 기존 계획은 바뀌지 않았습니다.'
    ChatMessage.objects.create(user=request.user,is_ai=True,message=reply)
    return JsonResponse({'status':'success','proposal':public_proposal(pending),'reply':reply})
