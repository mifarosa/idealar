from django.urls import path

from . import views

app_name = "kanban"

urlpatterns = [
    path("kanban/", views.BoardView.as_view(), name="board"),
    path("kanban/add/", views.TaskAddView.as_view(), name="add"),
    path("kanban/ideas/add/", views.IdeaAddView.as_view(), name="add-idea"),
    path("kanban/tasks/<int:pk>/move/", views.TaskMoveView.as_view(), name="move"),
    path("kanban/tasks/<int:pk>/rename/", views.TaskRenameView.as_view(), name="rename"),
    path("kanban/tasks/<int:pk>/delete/", views.TaskDeleteView.as_view(), name="delete"),
]
