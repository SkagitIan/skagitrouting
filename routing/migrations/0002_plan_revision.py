from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("routing", "0001_initial")]
    operations = [migrations.CreateModel(
        name="RoutingPlanRevision",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("revision_number", models.PositiveIntegerField()),
            ("action", models.CharField(max_length=32)),
            ("snapshot", models.JSONField(default=dict)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("plan", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="revisions", to="routing.routingplan")),
        ],
        options={"ordering": ["-created_at"], "constraints": [models.UniqueConstraint(fields=("plan", "revision_number"), name="unique_routing_revision_number")]},
    )]
