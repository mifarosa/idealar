from django.urls import path

from . import views

app_name = "support"

urlpatterns = [
    path("destek/", views.TicketListView.as_view(), name="list"),
    path("destek/yeni/", views.TicketCreateView.as_view(), name="create"),
    path("destek/gelen/", views.InboxView.as_view(), name="inbox"),
    path("destek/<int:pk>/", views.TicketDetailView.as_view(), name="detail"),
]
