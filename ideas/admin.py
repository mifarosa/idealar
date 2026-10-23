from django.contrib import admin

from .models import Feature, Idea, Project


class FeatureInline(admin.TabularInline):
    model = Feature
    extra = 0


@admin.register(Idea)
class IdeaAdmin(admin.ModelAdmin):
    list_display = ("display_title", "owner", "created_at")
    list_filter = ("owner",)
    search_fields = ("title", "body")
    inlines = [FeatureInline]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
