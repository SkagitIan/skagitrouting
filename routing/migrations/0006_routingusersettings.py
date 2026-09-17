from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("routing", "0005_preinspection_workspace"),
    ]

    operations = [
        migrations.CreateModel(
            name="RoutingUserSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("streetsmart_image_root", models.CharField(blank=True, max_length=1024)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="routing_settings", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
