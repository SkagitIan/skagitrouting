from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import RedirectView


def health(_request):
    return JsonResponse({"status": "alive", "service": "proprietary-routing"})


urlpatterns = [
    path("", RedirectView.as_view(url="/routing/", permanent=False)),
    path("login/", auth_views.LoginView.as_view(template_name="auth/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password-reset/", auth_views.PasswordResetView.as_view(template_name="auth/password_reset.html"), name="password_reset"),
    path("admin/", admin.site.urls),
    path("routing/", include("routing.urls")),
    path("health/live/", health, name="health_live"),
]
