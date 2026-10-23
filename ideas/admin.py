from django.contrib import admin

from .models import Idea


@admin.register(Idea)
class IdeaAdmin(admin.ModelAdmin):
    list_display = ("display_title", "owner", "created_at")
    list_filter = ("owner",)
    search_fields = ("title", "body")
