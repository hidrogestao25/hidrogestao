from django.db import migrations, models

import gestao_contratos.models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao_contratos", "0111_contratoterceiros_ocultar_home_contrato_vencido"),
    ]

    operations = [
        migrations.AlterField(
            model_name="solicitacaocontrato",
            name="cronograma",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("cronograma", "cronograma"),
                verbose_name="Inserir cronograma",
            ),
        ),
        migrations.AlterField(
            model_name="solicitacaoprospeccao",
            name="cronograma",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("cronograma", "cronograma"),
                verbose_name="Inserir cronograma",
            ),
        ),
        migrations.AlterField(
            model_name="propostafornecedor",
            name="arquivo_proposta",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("orcamentos", "orcamento"),
                verbose_name="Inserir Orçamento PDF",
            ),
        ),
        migrations.AlterField(
            model_name="contratoterceiros",
            name="num_contrato_arquivo",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("contrato_do_fornecedor", "contrato_fornecedor"),
                verbose_name="Inserir arquivo do contrato com fornecedor",
            ),
        ),
        migrations.AlterField(
            model_name="solicitacaoordemservico",
            name="arquivo_os",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("OS", "solicitacao_os"),
                verbose_name="Inserir arquivo da Ordem de Serviço",
            ),
        ),
        migrations.AlterField(
            model_name="os",
            name="arquivo_os",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("OS", "ordem_servico"),
                verbose_name="Inserir arquivo da Ordem de Serviço",
            ),
        ),
        migrations.AlterField(
            model_name="evento",
            name="arquivo",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("produto_do_fornecedor", "evidencia_evento"),
                verbose_name="Inserir arquivo para comprovação de entrega",
            ),
        ),
        migrations.AlterField(
            model_name="documentobm",
            name="minuta_boletim",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("Minuta boletim", "minuta_bm"),
            ),
        ),
        migrations.AlterField(
            model_name="documentobm",
            name="minuta_boletim_assinado",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("Minuta boletim/assinados", "minuta_bm_assinado"),
            ),
        ),
        migrations.AlterField(
            model_name="bm",
            name="arquivo_bm",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("BM", "boletim_medicao"),
                verbose_name="Inserir arquivo do Boletim de Medição",
            ),
        ),
        migrations.AlterField(
            model_name="nf",
            name="arquivo_nf",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("NF/Fornecedor", "nf_fornecedor"),
                verbose_name="Inserir arquivo da Nota Fiscal",
            ),
        ),
        migrations.AlterField(
            model_name="nfcliente",
            name="arquivo_nf",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("NF/Cliente", "nf_cliente"),
                verbose_name="Inserir arquivo da Nota Fiscal",
            ),
        ),
        migrations.AlterField(
            model_name="documentocontrato",
            name="arquivo",
            field=models.FileField(
                max_length=255,
                upload_to=gestao_contratos.models.ShortenedUploadPath("contratos/documentos", "documento_contrato"),
            ),
        ),
        migrations.AlterField(
            model_name="documentocontratoterceiro",
            name="arquivo_contrato",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("contratos", "minuta_contrato"),
                verbose_name="Contrato em PDF",
            ),
        ),
        migrations.AlterField(
            model_name="documentocontratoterceiro",
            name="arquivo_contrato_assinado",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("contratos/assinados", "contrato_assinado"),
                verbose_name="Contrato assinado em PDF",
            ),
        ),
        migrations.AlterField(
            model_name="aditivocontratoterceiro",
            name="arquivo_aditivo",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("aditivos_fornecedor", "aditivo"),
            ),
        ),
        migrations.AlterField(
            model_name="aditivocontratoterceiro",
            name="arquivo_aditivo_assinado",
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=gestao_contratos.models.ShortenedUploadPath("aditivos_fornecedor_assinados", "aditivo_assinado"),
            ),
        ),
    ]
