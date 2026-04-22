from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path

from pxtx.core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", LoginView.as_view(template_name="core/login.html"), name="login"),
    path("logout/", LogoutView.as_view(next_page="/"), name="logout"),
    path("healthz/", core_views.healthz, name="healthz"),
    path("api/v1/", include("pxtx.core.api.urls")),
    path("", include("pxtx.core.urls")),
]
