from django.urls import path

from ...api_views.auth.views import InternalTokenExchangeView, LoginAPIView

urlpatterns = [
    path("login/", LoginAPIView.as_view()),
    path(
        "internal-token/",
        InternalTokenExchangeView.as_view(),
        name="internal-token",
    ),
]
