from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao_contratos", "0107_avaliacaofornecedor_os"),
    ]

    operations = [
        migrations.AlterField(
            model_name="configuracaosla",
            name="tipo_fluxo",
            field=models.CharField(
                choices=[
                    ("prospeccao", "Prospeccao"),
                    ("contratacao", "Contratacao"),
                    ("aditivo", "Aditivo"),
                    ("os", "Ordem de Servico"),
                    ("bm", "Boletim de Medicao"),
                ],
                max_length=30,
            ),
        ),
    ]
