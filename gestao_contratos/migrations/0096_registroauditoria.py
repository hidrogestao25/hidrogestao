from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("gestao_contratos", "0095_solicitacaoordemservico_aprovacao_diretor_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RegistroAuditoria",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("object_id", models.PositiveBigIntegerField()),
                ("acao", models.CharField(choices=[("criado", "Criado"), ("atualizado", "Atualizado")], max_length=20)),
                ("modelo", models.CharField(max_length=100)),
                ("representacao_objeto", models.CharField(max_length=255)),
                ("detalhes", models.TextField(blank=True, null=True)),
                ("data_hora", models.DateTimeField(default=django.utils.timezone.now)),
                ("content_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="contenttypes.contenttype")),
                (
                    "usuario",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="registros_auditoria",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-data_hora"],
            },
        ),
    ]
