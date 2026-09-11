from django.urls import path

from ...api_views.auth.views import (
    InternalTokenExchangeView,
    LoginAPIView,
    PasswordResetAPIView,
)

urlpatterns = [
    path("login/", LoginAPIView.as_view()),
    path("reset-password/", PasswordResetAPIView.as_view(), name="api-reset-password"),
    # Carofi: server.connect.admin exchanges a shared service token for a
    # per-employee JWT. Consumed by the HR/Leave module on client.web.admin.
    path(
        "internal-token/",
        InternalTokenExchangeView.as_view(),
        name="internal-token",
    ),
]
