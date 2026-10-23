from django.urls import path

from . import views

app_name = "ideas"

urlpatterns = [
    path("", views.IdeaListView.as_view(), name="list"),
    path("ideas/new/", views.IdeaCreateView.as_view(), name="create"),
    path("ideas/<int:pk>/edit/", views.IdeaUpdateView.as_view(), name="update"),
    path("ideas/<int:pk>/delete/", views.IdeaDeleteView.as_view(), name="delete"),
]
