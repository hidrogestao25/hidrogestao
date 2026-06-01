from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao_contratos", "0109_evento_aditivo"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="gerente_contrato_ausente",
            field=models.BooleanField(default=False),
        ),
    ]
