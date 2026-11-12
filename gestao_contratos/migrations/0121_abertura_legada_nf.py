from decimal import Decimal
from django.db import migrations
from django.utils import timezone


def _forwards(apps,editor):
    if editor.connection.cursor().execute("SELECT 1 FROM django_migrations WHERE app='gestao_contratos' AND name='0122_ledger_transacional'").fetchone():
        return  # Depois da ativação, pagamentos novos nunca viram aberturas legadas.
    NF=apps.get_model('gestao_contratos','NF')
    Payment=apps.get_model('gestao_contratos','PagamentoNF')
    Audit=apps.get_model('gestao_contratos','RegistroAuditoria')
    for nf in NF.objects.filter(financeiro_autorizou=True).iterator():
        if nf.valor_pago<=0:raise RuntimeError(f'NF paga #{nf.pk} sem valor positivo: revisão humana antes da ativação.')
        if Payment.objects.filter(nf_id=nf.pk,origem_registro='legado_nf_integral').exists():continue
        events=Audit.objects.filter(content_type__app_label='gestao_contratos',content_type__model='nf',object_id=nf.pk).order_by('-data_hora','-pk')
        actor=None
        for event in events:
            state=event.estado_posterior or {}
            if event.operacao_financeira=='pagamento' or (event.operacao_financeira=='criacao' and state.get('financeiro_autorizou')) or (event.operacao_financeira is None and 'paga anteriormente: não; pagamento realizado após edição: sim.' in (event.detalhes or '')):
                actor=event.usuario_id;break
        Payment.objects.create(nf_id=nf.pk,valor=nf.valor_pago,data_pagamento=nf.data_pagamento,tipo='pagamento',
            registrado_por_id=actor,origem_registro='legado_nf_integral',chave_idempotencia=f'legado-nf:{nf.pk}',
            comprovante=nf.comprovante_pagamento.name if nf.comprovante_pagamento else '',
            observacao='Abertura do indicador legado integral; registrado_em é o instante da migração, não o recebimento pelo fornecedor.')
    old=sum((n.valor_pago for n in NF.objects.filter(financeiro_autorizou=True)),Decimal('0'))
    new=sum((p.valor for p in Payment.objects.all()),Decimal('0'))
    if old!=new:raise RuntimeError('Conciliação da abertura legada divergiu; ativação impedida.')


def _backwards(apps,editor):
    Payment=apps.get_model('gestao_contratos','PagamentoNF')
    if Payment.objects.exclude(origem_registro='legado_nf_integral').exists() or apps.get_model('gestao_contratos','ProgramacaoPagamento').objects.exists() or apps.get_model('gestao_contratos','ReprogramacaoPagamento').objects.exists():
        raise RuntimeError('Movimentos/acordos novos impedem reversão destrutiva; preserve o ledger e corrija progressivamente.')
    Payment.objects.all().delete()


def forwards(apps,editor):
    from gestao_contratos.payment_context import ledger_context
    with ledger_context(bootstrap=True):_forwards(apps,editor)


def backwards(apps,editor):
    from gestao_contratos.payment_context import ledger_context
    with ledger_context(bootstrap=True):_backwards(apps,editor)


class Migration(migrations.Migration):
    dependencies=[('gestao_contratos','0120_movimentos_programacao_nf')]
    operations=[migrations.RunPython(forwards,backwards)]
