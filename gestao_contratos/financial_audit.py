"""Contexto mínimo para a trilha transacional de NF, escrita pelo SQLite.

Sem função registrada, escritas externas de NF falham em vez de escapar da trilha.
O proprietário do banco continua capaz de modificar o schema: limite documentado.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import re

from django.db.backends.signals import connection_created

_context = ContextVar('financial_audit', default=None)


def guard_writes(execute,sql,params,many,context):
    """Falha fechada se uma reconstrução futura perder os triggers."""
    target=re.match(r'^\s*(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|DELETE\s+FROM)\s+["\[]?(gestao_contratos_nf|gestao_contratos_registroauditoria|gestao_contratos_pagamentonf|gestao_contratos_programacaopagamento|gestao_contratos_reprogramacaopagamento|gestao_contratos_ciclopagamentobm|gestao_contratos_decisaociclobm|gestao_contratos_pagamentociclobm)\b',sql,re.I)
    if target and not sql.lstrip().upper().startswith('INSERT INTO "GESTAO_CONTRATOS_REGISTROAUDITORIA"'):
        expected={'hidro_nf_audit_insert','hidro_nf_audit_update','hidro_nf_audit_delete',
            'hidro_nf_paid_reason','hidro_nf_delete_reason','hidro_nf_requires_bm',
            'hidro_nf_authorized_insert','hidro_nf_authorized_update',
            'hidro_financial_audit_no_update','hidro_financial_audit_no_delete'}
        with context['connection'].cursor() as cursor:
            found={row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'hidro_%'")}
            dual=cursor.execute("SELECT 1 FROM django_migrations WHERE app='gestao_contratos' AND name='0127_bm_aprovacao_duas_liderancas'").fetchone()
        if dual:
            expected|={'hidro_bm_dual_insert','hidro_bm_dual_decision','hidro_bm_dual_revision',
                'hidro_bm_dual_director','hidro_pagamento_dual_bm','hidro_evento_dual_revision'}
        with context['connection'].cursor() as cursor:
            cycles=cursor.execute("SELECT 1 FROM django_migrations WHERE app='gestao_contratos' AND name='0129_ciclos_pagamento_bm'").fetchone()
        if cycles:
            from .bm_cycle_sql import TRIGGERS
            expected |= TRIGGERS
        from .payment_context import _mode,LEDGER_TRIGGERS
        if not _mode.get().get('bootstrap') and (target.group(1).lower() not in {'gestao_contratos_nf','gestao_contratos_registroauditoria'} or 'hidro_nf_compat_insert' in found):
            expected|=LEDGER_TRIGGERS
        if not expected.issubset(found):
            from django.db import DatabaseError
            raise DatabaseError('Trilha financeira incompleta. Valide/aplique as migrations antes de gravar.')
    return execute(sql,params,many,context)


@contextmanager
def financial_audit_context(user=None, reason=''):
    token = _context.set((user, reason))
    try:
        yield
    finally:
        _context.reset(token)


def metadata():
    from .middleware import get_current_user, get_current_request
    current = _context.get()
    request = get_current_request()
    user, reason = current if current is not None else (
        get_current_user(), request.POST.get('justificativa_correcao', '') if request else '')
    authenticated = bool(user and user.is_authenticated)
    return json.dumps(dict(usuario_id=user.pk if authenticated else None,
        autor_nome=(user.get_full_name() or user.username)[:255] if authenticated else None,
        autor_grupo=user.grupo if authenticated else None, justificativa=str(reason or '').strip()[:4000]))


def validate_nf_save(instance):
    """Valida antes de gravar arquivos; os triggers cobrem também update/SQL."""
    from django.core.exceptions import ValidationError
    from types import SimpleNamespace
    from .permissions import payment_registration_error, PAID_NF_READ_ONLY_MESSAGE
    info=json.loads(metadata())
    old=type(instance).objects.filter(pk=instance.pk).first() if instance.pk else None
    changed=False
    if old:
        for field in instance._meta.fields:
            if field.primary_key: continue
            left=getattr(old,field.attname);right=getattr(instance,field.attname)
            if hasattr(right,'_committed'):
                if not right._committed: changed=True
                left=getattr(left,'name',None);right=right.name
            if left!=right: changed=True
    if old and (old.financeiro_autorizou or old.possui_pagamentos) and changed:
        if info.get('autor_grupo')=='financeiro': raise ValidationError(PAID_NF_READ_ONLY_MESSAGE)
        if info.get('autor_grupo')!='suprimento':raise ValidationError('Correção de NF com movimentos exige Suprimento.')
        if not info.get('justificativa'): raise ValidationError({'justificativa_correcao':'Informe o motivo da correção da NF paga.'})
    from .payment_context import _mode
    if instance.financeiro_autorizou and not _mode.get().get('legacy') and (not old or not old.financeiro_autorizou):
        error=payment_registration_error(SimpleNamespace(grupo='financeiro'),instance.bm,instance.evento or instance.os)
        if error: raise ValidationError({'financeiro_autorizou':error})


def configure(connection, **kwargs):
    if connection.vendor == 'sqlite' and connection.connection is not None:
        connection.connection.create_function('hidro_financial_context', 0, metadata)
        from .payment_context import mode_json,project_invoice
        connection.connection.create_function('hidro_ledger_mode',0,mode_json)
        connection.connection.create_function('hidro_project_invoice',1,lambda nf_id:project_invoice(connection,nf_id))
        from . import bm_cycles, bm_cycle_sql
        connection.connection.create_function('hidro_validar_ciclo_bm',2,
            lambda kind,payload:bm_cycle_sql.validate_record(connection.connection,kind,payload))
        def cycle_payment_error(nf_id,amount):
            nf=bm_cycles.row(connection.connection,'SELECT bm_id FROM gestao_contratos_nf WHERE id=?',(nf_id,))
            return bm_cycles.payment_error_sql(connection.connection,nf['bm_id'],amount) if nf and nf['bm_id'] else 'NF sem BM válido.'
        connection.connection.create_function('hidro_ciclo_erro_pagamento',2,cycle_payment_error)
        connection.connection.create_function('hidro_vincular_pagamento_ciclo',1,
            lambda payment_id:bm_cycle_sql.link_payment(connection,payment_id))
        connection.connection.create_function('hidro_bm_cycle_stage',1,
            lambda bm_id:bm_cycles.sql_stage(connection,bm_id))
        connection.connection.create_function('hidro_bm_cycle_authorized',1,
            lambda bm_id:int(bm_cycles.sql_stage(connection,bm_id) in ('sem_ciclo','inicial','autorizado','liquidado')))
        for amount_kind in ('balance','authorized','unbilled'):
            connection.connection.create_function('hidro_bm_cycle_'+amount_kind+('_cents' if amount_kind=='authorized' else ''),1,
                lambda bm_id,kind=amount_kind:bm_cycles.sql_amount(connection,bm_id,kind))
        def cycle_manager(bm_id):
            if bm_id is None or not bm_cycles.enabled(connection):return 0
            state=bm_cycles.financial_state(connection.connection,bm_id)
            manager=bm_cycles.responsible(connection.connection,state)
            return manager['id'] if manager else 0
        def liquidation(bm_id):
            if bm_id is None:return 'nao_pago'
            state=bm_cycles.financial_state(connection.connection,bm_id)
            return 'integral' if state['full'] else 'parcial' if state['paid_cents']>0 and state['balance_cents']>0 else 'nao_pago'
        connection.connection.create_function('hidro_bm_cycle_manager',1,cycle_manager)
        connection.connection.create_function('hidro_bm_cycle_liquidation',1,liquidation)
        if guard_writes not in connection.execute_wrappers:
            connection.execute_wrappers.append(guard_writes)


def install():
    from django.db import connections
    connection_created.connect(configure, dispatch_uid='hidro_financial_context')
    for connection in connections.all(initialized_only=True):
        configure(connection)
