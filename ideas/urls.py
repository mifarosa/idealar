from django.urls import path

from . import ai_views, feature_views, project_views, views

app_name = "ideas"

urlpatterns = [
    path("", views.IdeaListView.as_view(), name="list"),
    path("ideas/new/", views.IdeaCreateView.as_view(), name="create"),
    path("ideas/<int:pk>/edit/", views.IdeaUpdateView.as_view(), name="update"),
    path("ideas/<int:pk>/delete/", views.IdeaDeleteView.as_view(), name="delete"),
    path("ideas/<int:idea_pk>/features/add/", feature_views.FeatureAddView.as_view(), name="feature-add"),
    path("ideas/<int:pk>/ai/", ai_views.IdeaEnrichView.as_view(), name="idea-enrich"),
    path("ideas/<int:pk>/suggestions/", ai_views.SuggestionResolveView.as_view(), name="suggestion-resolve"),
    path("features/<int:pk>/toggle/", feature_views.FeatureToggleView.as_view(), name="feature-toggle"),
    path("features/<int:pk>/delete/", feature_views.FeatureDeleteView.as_view(), name="feature-delete"),
    path("features/<int:pk>/copy/", feature_views.FeatureCopyView.as_view(), name="feature-copy"),
    path("projects/", project_views.ProjectListView.as_view(), name="project-list"),
    path("projects/new/", project_views.ProjectCreateView.as_view(), name="project-create"),
    path("projects/<int:pk>/", project_views.ProjectDetailView.as_view(), name="project-detail"),
    path("projects/<int:pk>/edit/", project_views.ProjectUpdateView.as_view(), name="project-update"),
    path("projects/<int:pk>/delete/", project_views.ProjectDeleteView.as_view(), name="project-delete"),
]
