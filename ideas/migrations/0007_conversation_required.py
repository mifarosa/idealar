import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ideas", "0006_move_messages_into_conversations")]

    operations = [
        migrations.RemoveConstraint(model_name="chatmessage", name="chat_message_single_scope"),
        migrations.RemoveIndex(model_name="chatmessage", name="ideas_chatm_owner_i_ee87a8_idx"),
        migrations.RemoveField(model_name="chatmessage", name="owner"),
        migrations.RemoveField(model_name="chatmessage", name="idea"),
        migrations.RemoveField(model_name="chatmessage", name="project"),
        migrations.AlterField(
            model_name="chatmessage",
            name="conversation",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="ideas.conversation"
            ),
        ),
    ]
