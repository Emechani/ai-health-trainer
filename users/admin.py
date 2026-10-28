from django.contrib import admin
from .models import UserProfile # 우리가 만든 모델 불러오기

# 관리자 페이지에 UserProfile 등록하기
admin.site.register(UserProfile)