from django.urls import path

from . import ai_views, chat_views, feature_views, project_views, views

app_name = "ideas"

urlpatterns = [
    path("", views.IdeaListView.as_view(), name="list"),
    path("ideas/new/", views.IdeaCreateView.as_view(), name="create"),
    path("ideas/<int:pk>/", views.IdeaListView.as_view(), name="detail"),
    path("ideas/<int:pk>/edit/", views.IdeaUpdateView.as_view(), name="update"),
    path("ideas/<int:pk>/delete/", views.IdeaDeleteView.as_view(), name="delete"),
    path("ideas/<int:idea_pk>/features/add/", feature_views.FeatureAddView.as_view(), name="feature-add"),
    path("ideas/<int:pk>/ai/", ai_views.IdeaEnrichView.as_view(), name="idea-enrich"),
    path("ideas/<int:pk>/similar/check/", ai_views.SimilarCheckView.as_view(), name="idea-similar-check"),
    path("ideas/<int:pk>/similar/<int:index>/", ai_views.SimilarDecideView.as_view(), name="idea-similar-decide"),
    path("ideas/<int:pk>/suggestions/", ai_views.SuggestionResolveView.as_view(), name="suggestion-resolve"),
    path("chat/", chat_views.ConversationListView.as_view(), name="chat"),
    path("ideas/<int:idea_pk>/chat/", chat_views.ConversationListView.as_view(), name="idea-chat"),
    path("projects/<int:project_pk>/chat/", chat_views.ConversationListView.as_view(), name="project-chat"),
    path("chat/c/<int:pk>/", chat_views.ConversationView.as_view(), name="conversation"),
    path("chat/c/<int:pk>/delete/", chat_views.ConversationDeleteView.as_view(), name="conversation-delete"),
    path("chat/messages/<int:pk>/actions/<int:index>/", chat_views.ChatActionView.as_view(), name="chat-action"),
    path("features/<int:pk>/toggle/", feature_views.FeatureToggleView.as_view(), name="feature-toggle"),
    path("features/<int:pk>/edit/", feature_views.FeatureEditView.as_view(), name="feature-edit"),
    path("features/<int:pk>/delete/", feature_views.FeatureDeleteView.as_view(), name="feature-delete"),
    path("features/<int:pk>/copy/", feature_views.FeatureCopyView.as_view(), name="feature-copy"),
    path("projects/", project_views.ProjectListView.as_view(), name="project-list"),
    path("projects/new/", project_views.ProjectCreateView.as_view(), name="project-create"),
    path("projects/<int:pk>/", project_views.ProjectDetailView.as_view(), name="project-detail"),
    path("projects/<int:pk>/edit/", project_views.ProjectUpdateView.as_view(), name="project-update"),
    path("projects/<int:pk>/inspect/", project_views.ProjectInspectView.as_view(), name="project-inspect"),
    path("projects/<int:pk>/matches/<int:index>/", project_views.ProjectMatchDecideView.as_view(), name="project-match-decide"),
    path("projects/<int:pk>/delete/", project_views.ProjectDeleteView.as_view(), name="project-delete"),
]
