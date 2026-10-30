import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def drop_instance_wide_models(apps, schema_editor):
    # Rows were shared by the whole instance and referenced env variables for keys; they belong to nobody now.
    apps.get_model("ideas", "AIModel").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("ideas", "0010_ai_models"),
    ]

    operations = [
        migrations.AddField(
            "aimodel",
            "owner",
            models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="ai_models", to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(drop_instance_wide_models, migrations.RunPython.noop),
        migrations.AlterField(
            "aimodel",
            "owner",
            models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ai_models", to=settings.AUTH_USER_MODEL),
        ),
        migrations.RemoveField("aimodel", "key_env"),
        migrations.AddField("aimodel", "api_key_sealed", models.TextField(blank=True, default=""), preserve_default=False),
        migrations.AddField("aimodel", "key_hint", models.CharField(blank=True, default="", max_length=4), preserve_default=False),
    ]
