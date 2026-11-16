"""Única rotina de liquidação: writer lock SQLite, idempotência e ledger append-only."""
from contextlib import contextmanager
from decimal import Decimal
from datetime import date
from hashlib import sha256
import json
from types import SimpleNamespace
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import connection,transaction
from django.db.models import Sum
from django.utils import timezone
from . import models as m
from .financial_audit import financial_audit_context
from .payment_queries import cents,money,invoice_paid_cents,active_schedules
from .permissions import payment_registration_error
from .validation import validate_upload


def operator(user,supply_only=False):
    if not user or not user.is_authenticated or not user.is_active or user.grupo not in ({'suprimento'} if supply_only else {'financeiro','suprimento'}):
        raise PermissionDenied('Operação financeira não autorizada para este perfil.')


def ready():
    with connection.cursor() as cursor:
        installed=cursor.execute("SELECT 1 FROM django_migrations WHERE app='gestao_contratos' AND name='0122_ledger_transacional'").fetchone()
    if not installed:raise ValidationError('Fase 5 não ativada: migração e conciliação pendentes.')


@contextmanager
def financial_transaction(nf_id):
    # Intercepta apenas o BEGIN deste serviço, sem mudar a configuração global.
    # BEGIN IMMEDIATE adquire o writer lock antes de qualquer leitura do saldo.
    def immediate(execute,sql,params,many,context):
        if connection.vendor=='sqlite' and sql.strip().upper()=='BEGIN':sql='BEGIN IMMEDIATE'
        return execute(sql,params,many,context)
    ready()
    with connection.execute_wrapper(immediate),transaction.atomic():
        with connection.cursor() as cursor:cursor.execute('UPDATE gestao_contratos_nf SET id=id WHERE id=%s',[nf_id])
        yield m.NF.objects.select_related('bm','evento','os','contrato').get(pk=nf_id)


def positive(value):
    try:amount=cents(value)
    except (ValueError,TypeError,ArithmeticError) as error:raise ValidationError(str(error)) from error
    if amount<=0:raise ValidationError('Informe um valor positivo em centavos.')
    return amount


def token(scope,user,nf_id,key):
    if not key or len(str(key))>128:raise ValidationError('Chave de idempotência ausente ou inválida.')
    return sha256(f'{scope}:{user.pk}:{nf_id}:{key}'.encode()).hexdigest()


def payload_hash(values,file=None):
    digest=sha256(json.dumps(values,sort_keys=True,default=str,ensure_ascii=False).encode())
    if file:
        validate_upload(file)
        position=file.tell();file.seek(0)
        for chunk in file.chunks():digest.update(chunk)
        file.seek(position)
    return digest.hexdigest()


def save_record(record):
    """Não reescreve arquivos anteriores; limpa apenas upload novo de insert negado."""
    fields=[field for field in record._meta.fields if isinstance(field,m.models.FileField)]
    fresh=[field.name for field in fields if getattr(record,field.name) and not getattr(record,field.name)._committed]
    try:record.save()
    except Exception:
        for name in fresh:
            file=getattr(record,name)
            if file._committed:
                file.close();file.storage.delete(file.name)
        raise
    return record


def validate_payment(nf):
    if nf.cancelada_em:raise ValidationError('NF cancelada não admite novas liquidações.')
    nf.clean()
    error=payment_registration_error(SimpleNamespace(grupo='financeiro'),nf.bm,nf.evento or nf.os)
    if error:raise ValidationError(error)


def record_payment(*,nf_id,user,valor,data_pagamento,key,comprovante=None,observacao='',programacao_id=None):
    operator(user);amount=positive(valor)
    if not isinstance(data_pagamento,date):raise ValidationError('Informe a data efetiva declarada do pagamento.')
    idem=token('pagamento',user,nf_id,key)
    fingerprint=payload_hash(dict(nf=nf_id,centavos=amount,data=data_pagamento,observacao=observacao,programacao=programacao_id),comprovante)
    ready()
    # Retry de operação já confirmada não é uma nova liquidação, mesmo se a
    # autorização tiver sido invalidada depois. O conteúdo deve ser idêntico.
    existing=m.PagamentoNF.objects.filter(chave_idempotencia=idem).first()
    if existing:
        if existing.payload_hash!=fingerprint:raise ValidationError('A chave já foi utilizada com outro conteúdo.')
        return existing,False
    with financial_audit_context(user),financial_transaction(nf_id) as nf:
        existing=m.PagamentoNF.objects.filter(chave_idempotencia=idem).first()
        if existing:
            if existing.payload_hash!=fingerprint:raise ValidationError('A chave já foi utilizada com outro conteúdo.')
            return existing,False
        validate_payment(nf)
        from . import bm_cycles
        cycle_error=bm_cycles.payment_error(nf.bm, money(amount))
        if cycle_error:raise ValidationError(cycle_error)
        if amount>cents(nf.valor_pago)-invoice_paid_cents(nf):raise ValidationError('Pagamento superior ao saldo fiscal disponível.')
        program=None
        if programacao_id:
            program=active_schedules(nf).filter(pk=programacao_id).first()
            if not program:raise ValidationError('Selecione uma programação atual da mesma NF ou deixe sem vínculo.')
        payment=m.PagamentoNF(nf=nf,valor=money(amount),data_pagamento=data_pagamento,tipo='pagamento',
            registrado_por=user,programacao=program,observacao=observacao,comprovante=comprovante,
            chave_idempotencia=idem,payload_hash=fingerprint)
        return save_record(payment),True


def reverse_payment(*,movement_id,user,valor,data_estorno,motivo,key):
    operator(user,True);amount=positive(valor)
    if not isinstance(data_estorno,date):raise ValidationError('Informe a data efetiva do estorno.')
    if not str(motivo).strip():raise ValidationError('Justificativa de estorno é obrigatória.')
    parent=m.PagamentoNF.objects.get(pk=movement_id)
    idem=token('estorno',user,parent.nf_id,key)
    fingerprint=payload_hash(dict(parent=movement_id,centavos=amount,data=data_estorno,motivo=motivo))
    with financial_audit_context(user,motivo),financial_transaction(parent.nf_id):
        existing=m.PagamentoNF.objects.filter(chave_idempotencia=idem).first()
        if existing:
            if existing.payload_hash!=fingerprint:raise ValidationError('Chave reutilizada com outro estorno.')
            return existing,False
        if parent.tipo!='pagamento':raise ValidationError('O estorno deve referenciar um pagamento original.')
        reversed_cents=parent.estornos.aggregate(total=Sum('centavos',default=0))['total']
        if amount>parent.centavos-reversed_cents:raise ValidationError('Estorno superior ao saldo reversível do movimento.')
        record=m.PagamentoNF(nf_id=parent.nf_id,valor=money(amount),data_pagamento=data_estorno,tipo='estorno',
            registrado_por=user,referencia_estorno=parent,programacao_id=parent.programacao_id,justificativa=motivo,
            chave_idempotencia=idem,payload_hash=fingerprint)
        return save_record(record),True


def schedule(*,nf_id,user,valor,data_prevista,motivo,key,substitui_id=None,acordo=None,cancelada=False,observacao=''):
    operator(user);amount=positive(valor)
    if not isinstance(data_prevista,date):raise ValidationError('Informe a data prevista da parcela.')
    if cancelada and not substitui_id:raise ValidationError('Indique a parcela atual que será cancelada.')
    if not str(motivo).strip():raise ValidationError('Informe o motivo da programação ou revisão.')
    idem=token('programacao',user,nf_id,key)
    with financial_audit_context(user,motivo),financial_transaction(nf_id) as nf:
        existing=m.ProgramacaoPagamento.objects.filter(chave_idempotencia=idem).first()
        if existing:
            if (existing.valor_previsto,existing.data_prevista,existing.substitui_id,existing.cancelada,existing.justificativa,existing.observacao)!=(money(amount),data_prevista,substitui_id,cancelada,motivo,observacao):raise ValidationError('Chave reutilizada com outra programação.')
            return existing,False
        if nf.cancelada_em:raise ValidationError('NF cancelada.')
        balance=cents(nf.valor_pago)-invoice_paid_cents(nf)
        if balance<=0:raise ValidationError('NF sem saldo pendente.')
        previous=None;already=0
        current=list(active_schedules(nf))
        if substitui_id:
            previous=next((p for p in current if p.pk==substitui_id),None)
            if not previous:raise ValidationError('Programação substituída ou cancelada; atualize a página.')
            already=previous.liquidado_centavos
            if amount<already:raise ValidationError('A revisão não pode reduzir o valor abaixo do já liquidado explicitamente nesta programação.')
        raw=sum(max(p.restante_centavos,0) for p in current if not previous or p.pk!=previous.pk)
        remaining=0 if cancelada else max(amount-already,0)
        if raw+remaining>balance and (not previous or remaining>max(previous.restante_centavos,0)):
            raise ValidationError('Programação superior ao saldo disponível; confira pagamentos sem vínculo e revise as parcelas existentes.')
        kwargs=dict(nf=nf,valor_previsto=money(amount),data_prevista=data_prevista,justificativa=motivo,registrado_por=user,
            chave_idempotencia=idem,substitui=previous,acordo=acordo,cancelada=cancelada,observacao=observacao)
        if previous:kwargs['grupo']=previous.grupo
        return save_record(m.ProgramacaoPagamento(**kwargs)),True


def renegotiate(*,nf_id,user,novo_vencimento,motivo,key,programacao_id=None,responsavel_acordo='',documento=None,observacao=''):
    operator(user)
    if not isinstance(novo_vencimento,date):raise ValidationError('Informe o novo vencimento acordado.')
    if not str(motivo).strip():raise ValidationError('Informe o motivo do acordo já realizado.')
    if documento:validate_upload(documento)
    idem=token('acordo',user,nf_id,key)
    with financial_audit_context(user,motivo),financial_transaction(nf_id) as nf:
        existing=m.ReprogramacaoPagamento.objects.filter(chave_idempotencia=idem).first()
        if existing:
            if (existing.novo_vencimento,existing.motivo,existing.programacao_id,existing.responsavel_acordo,existing.observacao)!=(novo_vencimento,motivo,programacao_id,responsavel_acordo,observacao):raise ValidationError('Chave reutilizada com outro acordo.')
            return existing,False
        current=list(active_schedules(nf).filter(restante_centavos__gt=0))
        if programacao_id:
            target=next((p for p in current if p.pk==programacao_id),None)
            if not target:raise ValidationError('Parcela atual com saldo não encontrada.')
            before=target.data_prevista
        else:
            target=None
            last=nf.reprogramacoes.filter(programacao__isnull=True).order_by('-pk').first()
            before=last.novo_vencimento if last else nf.vencimento_original
        agreement=save_record(m.ReprogramacaoPagamento(nf=nf,programacao=target,vencimento_anterior=before,novo_vencimento=novo_vencimento,
            motivo=motivo,registrado_por=user,responsavel_acordo=responsavel_acordo,documento=documento,observacao=observacao,chave_idempotencia=idem))
        for program in ([target] if target else current):
            schedule(nf_id=nf.pk,user=user,valor=program.valor_previsto,data_prevista=novo_vencimento,motivo=motivo,
                key=f'acordo-{agreement.pk}-{program.pk}',substitui_id=program.pk,acordo=agreement,observacao=program.observacao)
        return agreement,True


def cancel_invoice(*,nf_id,user,motivo):
    operator(user,True)
    if not str(motivo).strip():raise ValidationError('Justificativa de cancelamento obrigatória.')
    with financial_audit_context(user,motivo),financial_transaction(nf_id) as nf:
        if nf.cancelada_em:return nf,False
        for payment in nf.movimentos.filter(tipo='pagamento').order_by('pk'):
            remaining=payment.centavos-payment.estornos.aggregate(total=Sum('centavos',default=0))['total']
            if remaining:reverse_payment(movement_id=payment.pk,user=user,valor=money(remaining),data_estorno=timezone.localdate(),motivo=motivo,key=f'cancelamento-{nf.pk}-{payment.pk}')
        # Revisões de programação são preservadas; a NF cancelada as retira da previsão.
        m.NF.objects.filter(pk=nf.pk).update(cancelada_em=timezone.now(),cancelada_por=user,motivo_cancelamento=motivo)
        nf.refresh_from_db()
        return nf,True
