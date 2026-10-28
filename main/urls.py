from django.urls import path
from . import views # 현재 폴더(.)의 views.py를 가져옴

urlpatterns = [
    path('google-fit/connect/', views.google_fit_connect, name='google_fit_connect'),
    path('google-fit/callback/', views.google_fit_callback, name='google_fit_callback'),
    path('', views.home, name='home'), # 접속 기본 경로('')일 때 home 함수 실행
]