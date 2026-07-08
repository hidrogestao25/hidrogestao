from django.db import migrations, models
import gestao_contratos.models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao_contratos", "0112_alter_filefields_with_short_names"),
    ]

    operations = [
        migrations.AddField(
            model_name="solicitacaocontrato",
            name="proposta_tecnica",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("propostas_tecnicas", "proposta_tecnica"),
                verbose_name="Inserir propostas técnicas",
            ),
        ),
    ]
