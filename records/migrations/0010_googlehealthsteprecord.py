import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('records', '0009_goal_practice_plan'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='GoogleHealthStepRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(verbose_name='측정 날짜')),
                ('steps', models.PositiveBigIntegerField(verbose_name='Google Health 걸음 수')),
                ('synced_at', models.DateTimeField(auto_now=True, verbose_name='최근 연동 시각')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('user', 'date'), name='unique_health_steps_user_date')]},
        ),
    ]
