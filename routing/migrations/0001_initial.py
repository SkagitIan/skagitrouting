from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name="RoutingImport", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("filename", models.CharField(max_length=255)), ("file_type", models.CharField(max_length=16)), ("uploaded_at", models.DateTimeField(auto_now_add=True)), ("row_count", models.PositiveIntegerField(default=0)), ("unique_stop_count", models.PositiveIntegerField(default=0)), ("original_headers", models.JSONField(default=list)), ("summary", models.JSONField(default=dict)), ("status", models.CharField(default="ready", max_length=32)),
        ], options={"ordering": ["-uploaded_at"]}),
        migrations.CreateModel(name="RoutingImportRow", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("source_row_number", models.PositiveIntegerField()), ("parcel_id", models.CharField(blank=True, max_length=128)), ("address", models.TextField(blank=True)), ("source_x", models.FloatField(blank=True, null=True)), ("source_y", models.FloatField(blank=True, null=True)), ("longitude", models.FloatField(blank=True, null=True)), ("latitude", models.FloatField(blank=True, null=True)), ("point_geometry", models.JSONField(blank=True, null=True)), ("source_data", models.JSONField(default=dict)), ("validation_status", models.CharField(default="valid", max_length=32)), ("validation_notes", models.JSONField(default=list)), ("dedupe_key", models.CharField(blank=True, db_index=True, max_length=300)), ("import_file", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rows", to="routing.routingimport")),
        ], options={"ordering": ["source_row_number"], "indexes": [models.Index(fields=["import_file", "parcel_id"], name="routing_import_row_idx")]}),
        migrations.CreateModel(name="RoutingPlan", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("mode", models.CharField(choices=[("driving", "Driving"), ("walking", "Walking")], max_length=16)), ("target_stop_count", models.PositiveIntegerField(default=60)), ("route_count", models.PositiveIntegerField(default=0)), ("algorithm_version", models.CharField(default="local-v1", max_length=32)), ("status", models.CharField(default="ready", max_length=32)), ("summary", models.JSONField(default=dict)), ("created_at", models.DateTimeField(auto_now_add=True)), ("import_file", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="plans", to="routing.routingimport")),
        ], options={"ordering": ["-created_at"]}),
        migrations.CreateModel(name="RoutingRoute", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("route_number", models.PositiveIntegerField()), ("stop_count", models.PositiveIntegerField(default=0)), ("estimated_distance_meters", models.FloatField(blank=True, null=True)), ("estimated_duration_seconds", models.FloatField(blank=True, null=True)), ("quality_score", models.FloatField(blank=True, null=True)), ("geometry", models.JSONField(blank=True, null=True)), ("plan", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="routes", to="routing.routingplan")),
        ], options={"ordering": ["route_number"], "constraints": [models.UniqueConstraint(fields=("plan", "route_number"), name="unique_routing_route_number")]}),
        migrations.CreateModel(name="RoutingStop", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("sequence", models.PositiveIntegerField()), ("parcel_id", models.CharField(blank=True, max_length=128)), ("longitude", models.FloatField(blank=True, null=True)), ("latitude", models.FloatField(blank=True, null=True)), ("street_name", models.CharField(blank=True, max_length=255)), ("street_side", models.CharField(blank=True, max_length=16)), ("coordinate_confidence", models.CharField(default="source_xy", max_length=32)), ("manually_locked", models.BooleanField(default=False)), ("import_row", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="routing.routingimportrow")), ("route", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stops", to="routing.routingroute")),
        ], options={"ordering": ["route", "sequence"], "constraints": [models.UniqueConstraint(fields=("route", "sequence"), name="unique_routing_stop_sequence")]}),
    ]
