# records/urls.py
from django.urls import path
from . import views
from .plan_revision import plan_revision

urlpatterns = [
    path('goal-progress/', views.goal_progress, name='goal_progress'),
    path('meal-plan/', views.meal_plan, name='meal_plan'),
    path('meal-plan/history/', views.meal_plan_history, name='meal_plan_history'),
    path('meal-plan/history/<int:pk>/', views.saved_meal_plan, name='saved_meal_plan'),
    path('today/', views.today_record, name='today_record'),
    path('meals/', views.today_record, {'record_type': 'meal'}, name='meal_record'),
    path('exercise/<int:pk>/edit/', views.exercise_edit, name='exercise_edit'),
    path('exercise/<int:pk>/delete/', views.exercise_delete, name='exercise_delete'),
    path('calendar/', views.exercise_calendar, name='exercise_calendar'),
    path('meal/<int:pk>/edit/', views.meal_edit, name='meal_edit'),
    path('meal/<int:pk>/delete/', views.meal_delete, name='meal_delete'),
    path('api/chat/plan-revision/', plan_revision, name='plan_revision'),
    path('api/chat/', views.ai_chat_api, name='ai_chat_api'),
    path('api/chat/history/', views.chat_history_api, name='chat_history_api'),
]
