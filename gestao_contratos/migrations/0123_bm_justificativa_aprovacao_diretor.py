from django.db import migrations,models


class Migration(migrations.Migration):
    dependencies=[('gestao_contratos','0122_ledger_transacional')]
    operations=[migrations.AddField(model_name='bm',name='justificativa_aprovacao_diretor',
        field=models.TextField('Justificativa da aprovação de pagamento pela Diretoria',null=True,blank=True))]
