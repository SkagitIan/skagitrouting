from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("routing", "0006_routingusersettings")]
    operations = [
        migrations.AddField(
            model_name="preinspectionworkspace", name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="created_preinspection_workspaces", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="routingimport", name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="routing_imports", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="routingplan", name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="routing_plans", to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name="WorkspaceRevision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("revision_number", models.PositiveIntegerField()), ("action", models.CharField(max_length=32)),
                ("snapshot", models.JSONField(default=dict)), ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="revisions", to="routing.preinspectionworkspace")),
            ], options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(model_name="workspacerevision", constraint=models.UniqueConstraint(fields=("workspace", "revision_number"), name="unique_workspace_revision_number")),
        migrations.CreateModel(
            name="AuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=64)), ("object_type", models.CharField(max_length=64)),
                ("object_id", models.CharField(max_length=128)), ("metadata", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="routing_audit_events", to=settings.AUTH_USER_MODEL)),
            ], options={"ordering": ["-created_at"], "indexes": [models.Index(fields=("object_type", "object_id"), name="routing_audi_object_5d1dbb_idx"), models.Index(fields=("actor", "created_at"), name="routing_audi_actor_i_ee70d7_idx")]},
        ),
    ]
