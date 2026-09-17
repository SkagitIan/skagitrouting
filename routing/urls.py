from django.urls import path

from . import views

app_name = "routing"

urlpatterns = [
    path("", views.workspace_page, name="workspace"),
    path("pictometry/diagnostic/", views.pictometry_diagnostic, name="pictometry_diagnostic"),
    path("oversight/", views.oversight_page, name="oversight"),
    path("oversight/workspaces/<int:workspace_id>/", views.oversight_workspace, name="oversight_workspace"),
    path("admin/", views.admin_dashboard, name="admin_dashboard"),
    path("admin/users/new/", views.admin_user_create, name="admin_user_create"),
    path("admin/users/<int:user_id>/", views.admin_user_detail, name="admin_user_detail"),
    path("api/workspaces/", views.workspace_collection, name="workspace_collection"),
    path("api/workspaces/<int:workspace_id>/", views.workspace_detail, name="workspace_detail"),
    path("api/workspaces/<int:workspace_id>/state/", views.workspace_state, name="workspace_state"),
    path("api/settings/", views.routing_user_settings, name="routing_user_settings"),
    path("sales-cycle/", views.sales_cycle, name="sales_cycle"),
    path("parcel/<str:parcel_id>/sketch/", views.parcel_sketch, name="parcel_sketch"),
    path("parcel/<str:parcel_id>/sketch/image/", views.parcel_sketch_image, name="parcel_sketch_image"),
    path("parcel/<str:parcel_id>/streetsmart/", views.parcel_streetsmart, name="parcel_streetsmart"),
    path("parcel/<str:parcel_id>/streetsmart/image/", views.parcel_streetsmart_image, name="parcel_streetsmart_image"),
    path("parcel/<str:parcel_id>/streetsmart/save/", views.save_streetsmart_image, name="save_streetsmart_image"),
    path("routes/", views.routes_page, name="routes"),
    path("routes/import/", views.import_file, name="import"),
    path("routes/plan/", views.create_plan, name="create_plan"),
    path("routes/plans/", views.plans_list, name="plans"),
    path("routes/plan/<int:plan_id>/optimize/", views.optimize_plan, name="optimize_plan"),
    path("routes/plan/<int:plan_id>/route/<int:route_id>/optimize/", views.optimize_route, name="optimize_route"),
    path("routes/plan/<int:plan_id>/route/<int:route_id>/mode/", views.set_route_mode, name="set_route_mode"),
    path("routes/plan/<int:plan_id>/route/<int:route_id>/reverse/", views.reverse_route, name="reverse_route"),
    path("routes/plan/<int:plan_id>/route/<int:route_id>/reset/", views.reset_route, name="reset_route"),
    path("routes/plan/<int:plan_id>/move-stop/", views.move_stop, name="move_stop"),
    path("routes/plan/<int:plan_id>/stop/<int:stop_id>/remove/", views.remove_stop, name="remove_stop"),
    path("routes/plan/<int:plan_id>/add-stop/", views.add_stop, name="add_stop"),
    path("routes/plan/<int:plan_id>/available-stops/", views.available_stops, name="available_stops"),
    path("routes/plan/<int:plan_id>/", views.plan_detail, name="plan_detail"),
    path("routes/plan/<int:plan_id>/export/", views.export_plan, name="export_plan"),
    path("routes/plan/<int:plan_id>/route/<int:route_id>/export/", views.export_route, name="export_route"),
]
