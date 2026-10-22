from django.urls import include, path

urlpatterns = [
    path("", include("backend.core.urls")),
]
