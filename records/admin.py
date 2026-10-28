from django.contrib import admin
from .models import DailyRecord, Meal, Exercise

admin.site.register(DailyRecord)
admin.site.register(Meal)
admin.site.register(Exercise)