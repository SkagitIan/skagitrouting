from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("routing", "0002_plan_revision")]

    operations = [
        migrations.AddField(
            model_name="routingplan",
            name="name",
            field=models.CharField(blank=True, max_length=160),
        ),
    ]
