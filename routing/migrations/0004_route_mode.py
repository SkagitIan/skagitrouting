from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("routing", "0003_plan_name")]

    operations = [
        migrations.AddField(
            model_name="routingroute",
            name="mode",
            field=models.CharField(
                choices=[("driving", "Driving"), ("walking", "Walking")],
                default="driving",
                max_length=16,
            ),
        ),
    ]
