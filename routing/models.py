from django.db import models
from django.conf import settings


class PreinspectionWorkspace(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preinspection_workspaces")
    name = models.CharField(max_length=160)
    year = models.PositiveIntegerField(default=2026)
    state = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_opened_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="created_preinspection_workspaces")

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "updated_at"])]


class RoutingUserSettings(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="routing_settings")
    streetsmart_image_root = models.CharField(max_length=1024, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class RoutingImport(models.Model):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="routing_imports")
    filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=16)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    row_count = models.PositiveIntegerField(default=0)
    unique_stop_count = models.PositiveIntegerField(default=0)
    original_headers = models.JSONField(default=list)
    summary = models.JSONField(default=dict)
    status = models.CharField(max_length=32, default="ready")

    class Meta:
        ordering = ["-uploaded_at"]


class RoutingImportRow(models.Model):
    import_file = models.ForeignKey(RoutingImport, on_delete=models.CASCADE, related_name="rows")
    source_row_number = models.PositiveIntegerField()
    parcel_id = models.CharField(max_length=128, blank=True)
    address = models.TextField(blank=True)
    source_x = models.FloatField(null=True, blank=True)
    source_y = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    point_geometry = models.JSONField(null=True, blank=True)
    source_data = models.JSONField(default=dict)
    validation_status = models.CharField(max_length=32, default="valid")
    validation_notes = models.JSONField(default=list)
    dedupe_key = models.CharField(max_length=300, db_index=True, blank=True)

    class Meta:
        ordering = ["source_row_number"]
        indexes = [models.Index(fields=["import_file", "parcel_id"])]


class RoutingPlan(models.Model):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="routing_plans")
    import_file = models.ForeignKey(RoutingImport, on_delete=models.CASCADE, related_name="plans")
    name = models.CharField(max_length=160, blank=True)
    mode = models.CharField(max_length=16, choices=[("driving", "Driving"), ("walking", "Walking")])
    target_stop_count = models.PositiveIntegerField(default=60)
    route_count = models.PositiveIntegerField(default=0)
    algorithm_version = models.CharField(max_length=32, default="local-v1")
    status = models.CharField(max_length=32, default="ready")
    summary = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class RoutingRoute(models.Model):
    plan = models.ForeignKey(RoutingPlan, on_delete=models.CASCADE, related_name="routes")
    route_number = models.PositiveIntegerField()
    mode = models.CharField(max_length=16, choices=[("driving", "Driving"), ("walking", "Walking")], default="driving")
    stop_count = models.PositiveIntegerField(default=0)
    estimated_distance_meters = models.FloatField(null=True, blank=True)
    estimated_duration_seconds = models.FloatField(null=True, blank=True)
    quality_score = models.FloatField(null=True, blank=True)
    geometry = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["route_number"]
        constraints = [models.UniqueConstraint(fields=["plan", "route_number"], name="unique_routing_route_number")]


class RoutingStop(models.Model):
    route = models.ForeignKey(RoutingRoute, on_delete=models.CASCADE, related_name="stops")
    import_row = models.ForeignKey(RoutingImportRow, on_delete=models.PROTECT)
    sequence = models.PositiveIntegerField()
    parcel_id = models.CharField(max_length=128, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    street_name = models.CharField(max_length=255, blank=True)
    street_side = models.CharField(max_length=16, blank=True)
    coordinate_confidence = models.CharField(max_length=32, default="source_xy")
    manually_locked = models.BooleanField(default=False)

    class Meta:
        ordering = ["route", "sequence"]
        constraints = [models.UniqueConstraint(fields=["route", "sequence"], name="unique_routing_stop_sequence")]


class RoutingPlanRevision(models.Model):
    plan = models.ForeignKey(RoutingPlan, on_delete=models.CASCADE, related_name="revisions")
    revision_number = models.PositiveIntegerField()
    action = models.CharField(max_length=32)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["plan", "revision_number"], name="unique_routing_revision_number")]


class WorkspaceRevision(models.Model):
    workspace = models.ForeignKey(PreinspectionWorkspace, on_delete=models.CASCADE, related_name="revisions")
    revision_number = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=32)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["workspace", "revision_number"], name="unique_workspace_revision_number")]


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="routing_audit_events")
    action = models.CharField(max_length=64)
    object_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=128)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["object_type", "object_id"]), models.Index(fields=["actor", "created_at"])]
