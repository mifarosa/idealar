from django.db import migrations

TITLE_CHARS = 50


def _title_for(first_user_message: str) -> str:
    text = first_user_message.strip().replace("\n", " ")
    return text if len(text) <= TITLE_CHARS else text[: TITLE_CHARS - 1].rstrip() + "…"


def group_messages_into_conversations(apps, schema_editor):
    """Each existing (owner, idea, project) thread becomes one conversation so no chat history is lost."""
    ChatMessage = apps.get_model("ideas", "ChatMessage")
    Conversation = apps.get_model("ideas", "Conversation")
    scopes = ChatMessage.objects.order_by().values_list("owner_id", "idea_id", "project_id").distinct()
    for owner_id, idea_id, project_id in scopes:
        messages = ChatMessage.objects.filter(owner_id=owner_id, idea_id=idea_id, project_id=project_id).order_by("id")
        first_user = messages.filter(role="user").first()
        conversation = Conversation.objects.create(
            owner_id=owner_id,
            idea_id=idea_id,
            project_id=project_id,
            title=_title_for(first_user.content) if first_user else "Sohbet",
        )
        messages.update(conversation=conversation)


class Migration(migrations.Migration):
    dependencies = [("ideas", "0005_conversations")]

    operations = [migrations.RunPython(group_messages_into_conversations, migrations.RunPython.noop)]
