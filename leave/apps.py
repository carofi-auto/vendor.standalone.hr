from django.apps import AppConfig
from django.conf import settings


class LeaveConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "leave"

    def ready(self):
        from django.urls import include, path

        from horilla.urls import urlpatterns
        from leave import signals  # noqa: F401
        from leave import signals_carofi  # noqa: F401

        settings.APPS.append("leave")
        urlpatterns.append(
            path("leave/", include("leave.urls")),
        )
        super().ready()
