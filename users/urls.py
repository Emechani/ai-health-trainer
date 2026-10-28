from django.urls import path
from . import views

urlpatterns = [
    path('setup/', views.profile_setup, name='profile_setup'),
    path('signup/', views.signup, name='signup'),
    path('profile/', views.profile_update, name='profile_update'),
]