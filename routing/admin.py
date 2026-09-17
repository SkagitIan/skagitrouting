from django.contrib import admin

from .models import AuditEvent, PreinspectionWorkspace, RoutingImport, RoutingImportRow, RoutingPlan, RoutingPlanRevision, RoutingRoute, RoutingStop, WorkspaceRevision


@admin.register(PreinspectionWorkspace)
class PreinspectionWorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "year", "revision", "updated_at", "last_opened_at")
    list_filter = ("year",)
    search_fields = ("name", "owner__username", "owner__email")
    readonly_fields = ("owner", "created_by", "name", "year", "state", "revision", "created_at", "updated_at", "last_opened_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RoutingImport)
class RoutingImportAdmin(admin.ModelAdmin):
    list_display = ("filename", "created_by", "row_count", "unique_stop_count", "status", "uploaded_at")
    readonly_fields = ("created_by", "uploaded_at", "original_headers", "summary")


@admin.register(RoutingPlan)
class RoutingPlanAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_by", "mode", "target_stop_count", "route_count", "status", "created_at")
    readonly_fields = ("created_by", "created_at", "summary")


@admin.register(RoutingImportRow, RoutingRoute, RoutingStop)
class RoutingChildAdmin(admin.ModelAdmin):
    list_display = ("id",)


@admin.register(RoutingPlanRevision, WorkspaceRevision, AuditEvent)
class ReadOnlyAuditAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at")

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
