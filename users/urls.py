from django.urls import path
from . import views
from django.views.generic import TemplateView
from .account_recovery import find_username

urlpatterns = [
    path('find-username/', find_username, name='find_username'),
    path('find-username/done/', TemplateView.as_view(template_name='registration/username_recovery_done.html'), name='username_recovery_done'),
    path('setup/', views.profile_setup, name='profile_setup'),
    path('signup/', views.signup, name='signup'),
    path('profile/', views.profile_update, name='profile_update'),
]
