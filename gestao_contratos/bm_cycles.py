"""Ciclos do mesmo BM, sem duplicar caixa, NFs ou aprovações operacionais.

Leituras não criam ciclos. Os validadores SQL usam a mesma conexão da escrita,
incluindo chamadas feitas por adaptadores antigos, admin e scripts Django.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

MIGRATION = '0129_ciclos_pagamento_bm'
RESPONSIBLE_ROLES = {'lider_contrato','gerente_lider','gerente_contrato'}
CYCLE_FILTERS = [('', 'Todas as apresentações'), ('novos', 'Primeira apresentação'), ('reprogramados', 'Reapresentados com saldo'),
    ('parciais', 'BMs parcialmente pagos'), ('sem_nf', 'BMs sem NF'), ('gerencia', 'Aguardando líder do ciclo'),
    ('diretoria', 'Aguardando Diretoria do ciclo'), ('autorizado', 'Autorizados no ciclo atual'),
    ('conferencia', 'Ciclos reprovados ou em conferência')]
_operation = ContextVar('bm_cycle_operation', default={})


def enabled(conn=None):
    conn = conn or connection
    if hasattr(conn, '_bm_cycles_enabled'):
        return conn._bm_cycles_enabled
    try:
        with conn.cursor() as cursor:
            value = bool(cursor.execute("SELECT 1 FROM django_migrations WHERE app='gestao_contratos' AND name=%s", [MIGRATION]).fetchone())
    except Exception:
        value = False
    conn._bm_cycles_enabled = value
    return value


def row(db, sql, args=()):
    cursor = db.execute(sql, args)
    value = cursor.fetchone()
    return dict(zip((d[0] for d in cursor.description), (v.isoformat() if isinstance(v, date) else v for v in value))) if value else None


def rows(db, sql, args=()):
    cursor = db.execute(sql, args)
    keys = [d[0] for d in cursor.description]
    return [dict(zip(keys, (v.isoformat() if isinstance(v, date) else v for v in value))) for value in cursor.fetchall()]


def cents(value):
    return int(Decimal(str(value or 0)).quantize(Decimal('.01')) * 100)


def money(value):
    return Decimal(value) / 100


def raw_connection():
    connection.ensure_connection()
    return connection.connection


def responsible(db, state):
    """Vínculo existente, jamais uma atribuição paralela por grupo global."""
    contract=state['contract'];origin=state['origin'];project_id=state['project_id']
    if not contract or not origin:return None
    project=row(db,'SELECT lider_contrato_id FROM gestao_contratos_contrato WHERE id=?',(project_id,)) if project_id else None
    if state['bm']['os_id']:
        person_id=origin.get('lider_contrato_id') or (project or {}).get('lider_contrato_id')
        if not person_id and not project_id:person_id=contract.get('lider_contrato_id')
    else:
        person_id=(project or {}).get('lider_contrato_id') if contract.get('guarda_chuva') and project_id else contract.get('lider_contrato_id')
    return row(db,'SELECT id,username,first_name,last_name,grupo,is_active FROM gestao_contratos_user WHERE id=?',(person_id,)) if person_id else None


def head(db, bm_id):
    return row(db, '''SELECT c.* FROM gestao_contratos_ciclopagamentobm c WHERE c.bm_id=?
        AND NOT EXISTS(SELECT 1 FROM gestao_contratos_ciclopagamentobm s WHERE s.anterior_id=c.id)''', (bm_id,))


def operational(bm):
    approved = 'aprovado' in (bm['status_coordenador'], bm['status_gerente'])
    rejected = 'reprovado' in (bm['status_coordenador'], bm['status_gerente'])
    if bm['evento_id'] and bm['contrato_id'] != bm['finance_contract_id']:
        approved = approved and all(bm[f'status_lider_{side}'] == 'aprovado'
            and bm[f'aprovador_lider_{side}_id'] and bm[f'data_lider_{side}'] for side in ('documental', 'financeiro'))
    return approved and not rejected


def financial_state(db, bm_id, today=None):
    """Valores atuais por participação, sempre em centavos inteiros do ledger."""
    today = today or timezone.localdate()
    bm = row(db, 'SELECT * FROM gestao_contratos_bm WHERE id=?', (bm_id,))
    if not bm:
        raise ValidationError('BM não encontrado.')
    errors = []
    origin = row(db, 'SELECT * FROM gestao_contratos_evento WHERE id=?', (bm['evento_id'],)) if bm['evento_id'] else row(db, 'SELECT * FROM gestao_contratos_os WHERE id=?', (bm['os_id'],)) if bm['os_id'] else None
    contract_id = origin.get('contrato_terceiro_id') if origin and bm['evento_id'] else origin.get('contrato_id') if origin else None
    contract = row(db, 'SELECT * FROM gestao_contratos_contratoterceiros WHERE id=?', (contract_id,)) if contract_id else None
    project_id = origin.get('cod_projeto_id') if origin and bm['os_id'] else contract.get('cod_projeto_id') if contract else None
    bm['finance_contract_id'] = contract_id
    if not origin or not contract or bool(bm['evento_id']) == bool(bm['os_id']) or (bm['os_id'] and contract_id != bm['contrato_id']):
        errors.append('Origem financeira inválida.')
    if origin and bm['os_id'] and origin.get('status') == 'cancelada':
        errors.append('OS cancelada.')
    if contract and contract.get('status') == 'suspenso':
        errors.append('Contrato suspenso: conferir a obrigação antes de reprogramar.')
    invoices = rows(db, 'SELECT * FROM gestao_contratos_nf WHERE bm_id=? ORDER BY id', (bm_id,))
    movements = rows(db, '''SELECT p.* FROM gestao_contratos_pagamentonf p
        JOIN gestao_contratos_nf n ON n.id=p.nf_id WHERE n.bm_id=? ORDER BY p.id''', (bm_id,))
    paid_by_nf = {}
    for payment in movements:
        paid_by_nf[payment['nf_id']] = paid_by_nf.get(payment['nf_id'], 0) + (-1 if payment['tipo'] == 'estorno' else 1) * payment['centavos']
    active = [nf for nf in invoices if not nf['cancelada_em']]
    if invoices and not active:
        errors.append('Todas as NFs da participação estão canceladas: conferir a obrigação antes de reprogramar.')
    billed = sum(cents(nf['valor_pago']) for nf in active)
    paid = sum(paid_by_nf.values())
    measured = cents(bm['valor_pago'])
    if measured <= 0 or paid < 0 or paid > billed or billed > measured:
        errors.append('Divergência entre medição, faturamento e liquidação: exige conferência, sem compensações presumidas.')
    if 0 < billed == paid < measured:
        errors.append('NFs integralmente pagas com medição superior ao faturamento: conferir o valor efetivamente devido antes de reprogramar a diferença.')
    future_dates, past_dates = set(), set()
    for nf in invoices:
        nf_paid = paid_by_nf.get(nf['id'], 0)
        nf['paid_cents'] = nf_paid
        nf['balance_cents'] = 0 if nf['cancelada_em'] else cents(nf['valor_pago']) - nf_paid
        if nf['contrato_id'] != contract_id or nf['evento_id'] != bm['evento_id'] or nf['os_id'] != bm['os_id']:
            errors.append('NF com vínculo financeiro incompatível.')
        if nf['cancelada_em']:
            if nf_paid:
                errors.append('NF cancelada com caixa não estornado: exige conferência.')
            continue
        schedules = rows(db, '''SELECT p.* FROM gestao_contratos_programacaopagamento p WHERE p.nf_id=?
            AND p.cancelada=0 AND NOT EXISTS(SELECT 1 FROM gestao_contratos_programacaopagamento s WHERE s.substitui_id=p.id)''', (nf['id'],))
        scheduled = 0
        for program in schedules:
            applied = db.execute('''SELECT coalesce(sum(CASE m.tipo WHEN 'estorno' THEN -m.centavos ELSE m.centavos END),0)
                FROM gestao_contratos_pagamentonf m JOIN gestao_contratos_programacaopagamento p ON p.id=m.programacao_id
                WHERE p.grupo=?''', (program['grupo'],)).fetchone()[0]
            remaining = max(program['centavos'] - applied, 0)
            scheduled += remaining
            if remaining:
                (future_dates if date.fromisoformat(program['data_prevista']) > today else past_dates).add(program['data_prevista'])
        if scheduled > nf['balance_cents']:
            errors.append('Programação de NF superior ao saldo; conferir pagamentos sem vínculo antes de reprogramar o BM.')
        agreement = row(db, '''SELECT * FROM gestao_contratos_reprogramacaopagamento
            WHERE nf_id=? AND programacao_id IS NULL ORDER BY id DESC LIMIT 1''', (nf['id'],))
        due = agreement['novo_vencimento'] if agreement else nf['vencimento_original']
        if nf['balance_cents'] > scheduled:
            known = due or bm.get('data_pagamento')
            if known:
                (future_dates if date.fromisoformat(known) > today else past_dates).add(known)
    # Datas explícitas de parcelas/acordos permanecem protegidas, independentemente
    # da programação original cadastrada no BM.
    if future_dates and (past_dates or len(future_dates) > 1 or (billed < measured and bm.get('data_pagamento') not in future_dates)):
        errors.append('Saldo com parcelas de datas diferentes: conferir qual obrigação deve ser reapresentada, preservando os acordos existentes.')
    reference = bm.get('data_pagamento')
    not_before = reference
    if future_dates and not past_dates and len(future_dates) == 1 and billed == measured:
        not_before = max(reference or '', next(iter(future_dates)))
    if origin and origin.get('valor_pago') and cents(origin['valor_pago']) > 0:
        field = 'evento_id' if bm['evento_id'] else 'os_id'
        origin_paid = db.execute(f'''SELECT coalesce(sum(CASE p.tipo WHEN 'estorno' THEN -p.centavos ELSE p.centavos END),0)
            FROM gestao_contratos_pagamentonf p JOIN gestao_contratos_nf n ON n.id=p.nf_id WHERE n.{field}=?''', (origin['id'],)).fetchone()[0]
        if cents(origin['valor_pago']) != origin_paid:
            errors.append('Valor manual legado da origem diverge do ledger: conferência documental necessária antes da reprogramação automática.')
    version_fields = ('contrato_id', 'evento_id', 'os_id', 'numero_bm', 'parcela_paga', 'valor_pago', 'data_pagamento',
                      'data_inicial_medicao', 'data_final_medicao', 'arquivo_bm',
                      'status_coordenador','data_aprovacao_coordenador','status_gerente','data_aprovacao_gerente',
                      'aprovacao_pagamento','data_aprovacao_diretor','status_lider_documental','status_lider_financeiro',
                      'aprovador_lider_documental_id','aprovador_lider_financeiro_id','data_lider_documental','data_lider_financeiro')
    material = {field: str(bm[field] or '') for field in version_fields}
    # A primeira autorização efetiva da Diretoria pode acontecer no novo ciclo.
    # Sua projeção nos campos legados não muda o contexto já avaliado pelo líder.
    current=head(db,bm_id) if enabled() else None
    if current and current['tipo']!='inicial':
        material.pop('aprovacao_pagamento',None)
        material.pop('data_aprovacao_diretor',None)
    material['valor_pago'] = str(measured)
    material['origin'] = {key: (origin or {}).get(key) for key in ('contrato_id', 'contrato_terceiro_id', 'cod_projeto_id', 'status', 'data_prevista_pagamento')}
    leader=responsible(db,dict(contract=contract,origin=origin,project_id=project_id,bm=bm))
    material['responsavel_existente']={key:leader[key] for key in ('id','grupo','is_active')} if leader else None
    material['nf'] = [[nf[key] for key in ('id', 'contrato_id', 'evento_id', 'os_id', 'cancelada_em', 'numero_nf', 'serie', 'data_emissao', 'valor_pago', 'vencimento_original')] for nf in invoices]
    # Uma correção fiscal seguida de desfazer também exige revisão. Atualizações
    # de compatibilidade pelo caixa (data/booleano) não são alterações fiscais.
    fiscal_fields=('contrato_id','evento_id','os_id','bm_id','valor_pago','parcela_paga','arquivo_nf',
                   'numero_nf','serie','data_emissao','chave_acesso','tipo_documento')
    changed=' OR '.join(f"json_extract(a.estado_anterior,'$.{field}') IS NOT json_extract(a.estado_posterior,'$.{field}')" for field in fiscal_fields)
    material['fiscal_revisions']=db.execute(f'''SELECT a.id FROM gestao_contratos_registroauditoria a
        JOIN django_content_type t ON t.id=a.content_type_id AND t.app_label='gestao_contratos' AND t.model='nf'
        JOIN gestao_contratos_nf n ON n.id=a.object_id
        WHERE n.bm_id=? AND a.estado_anterior IS NOT NULL AND a.estado_posterior IS NOT NULL
        AND ({changed}) ORDER BY a.id''',(bm_id,)).fetchall()
    material['reversals'] = [p['id'] for p in movements if p['tipo'] == 'estorno']
    material['agreements'] = db.execute('''SELECT r.id FROM gestao_contratos_reprogramacaopagamento r JOIN gestao_contratos_nf n ON n.id=r.nf_id WHERE n.bm_id=? ORDER BY r.id''', (bm_id,)).fetchall()
    material['schedules'] = db.execute('''SELECT p.id FROM gestao_contratos_programacaopagamento p JOIN gestao_contratos_nf n ON n.id=p.nf_id WHERE n.bm_id=? ORDER BY p.id''', (bm_id,)).fetchall()
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()
    outstanding = max(measured - paid, 0)
    full = measured > 0 and measured == billed == paid and all(
        nf['contrato_id']==contract_id and nf['evento_id']==bm['evento_id'] and nf['os_id']==bm['os_id']
        and nf['balance_cents']==0 for nf in invoices)
    return dict(bm=bm, origin=origin, contract=contract, contract_id=contract_id, project_id=project_id,
                measured_cents=measured, billed_cents=billed, paid_cents=paid, balance_cents=outstanding,
                unbilled_cents=max(measured-billed, 0), invoices=invoices, movements=movements,
                full=full, errors=list(dict.fromkeys(errors)), reference=date.fromisoformat(reference) if reference else None,
                not_before=date.fromisoformat(not_before) if not_before else None,
                version=digest)


def programmed_date(state, cycle=None):
    """A programação original segue a data do BM; sucessores têm data própria."""
    if not cycle or cycle['tipo']=='inicial':
        return state['reference']
    return date.fromisoformat(cycle['data_prevista'])


def previous_programmed_date(cycle, prior=None):
    """Data apresentada na confirmação, preservada no contexto do sucessor."""
    context=cycle['contexto_inclusao']
    if isinstance(context,str):context=json.loads(context)
    value=context.get('data_programacao_anterior')
    return date.fromisoformat(value) if value else date.fromisoformat(prior['data_prevista']) if prior else None


def cycle_state(db, bm_id, today=None):
    cycle = head(db, bm_id)
    if cycle is None:
        return dict(stage='sem_ciclo', cycle=None)
    state = financial_state(db, bm_id, today)
    decisions = {d['etapa']: d for d in rows(db, 'SELECT * FROM gestao_contratos_decisaociclobm WHERE ciclo_id=?', (cycle['id'],))}
    manager = responsible(db,state)
    if state['full']:
        stage = 'liquidado'
    elif state['errors']:
        stage = 'conferencia'
    elif any(d['situacao'] == 'reprovado' for d in decisions.values()):
        stage = 'reprovado'
    elif cycle['tipo'] == 'inicial':
        stage = 'inicial'
    elif not operational(state['bm']) or state['bm']['aprovacao_pagamento'] not in {'pendente','aprovado'}:
        stage = 'conferencia'
    elif not manager or not manager['is_active'] or manager['grupo'] not in RESPONSIBLE_ROLES:
        stage = 'sem_gerente'
    elif any(d['versao_material'] != state['version'] or d['responsavel_id'] != manager['id'] for d in decisions.values()):
        stage = 'revisao'
    elif 'gerencia' not in decisions:
        stage = 'gerencia'
    elif 'diretoria' not in decisions:
        stage = 'diretoria'
    else:
        stage = 'autorizado'
    return dict(state, stage=stage, cycle=cycle, decisions=decisions, manager=manager)


def payment_error_sql(db, bm_id, amount=None):
    state = cycle_state(db, bm_id)
    if state['cycle'] is None or state['cycle']['tipo'] == 'inicial':
        return ''
    if state['stage'] != 'autorizado':
        return 'O ciclo atual do BM exige aprovação do gerente responsável e nova autorização da Diretoria; confira pendências ou revisões.'
    if amount is not None:
        director = state['decisions']['diretoria']
        linked = db.execute('''SELECT coalesce(sum(p.centavos - coalesce((SELECT sum(e.centavos)
            FROM gestao_contratos_pagamentonf e WHERE e.referencia_estorno_id=p.id),0)),0)
            FROM gestao_contratos_pagamentociclobm v JOIN gestao_contratos_pagamentonf p ON p.id=v.pagamento_id
            WHERE v.ciclo_id=?''', (state['cycle']['id'],)).fetchone()[0]
        if linked + amount > cents(director['saldo_avaliado']):
            return 'Valor superior ao saldo autorizado no ciclo atual do BM.'
    return ''


def payment_error(bm, amount=None):
    if not bm or not enabled():
        return ''
    return payment_error_sql(raw_connection(), bm.pk, cents(amount) if amount is not None else None)


def sql_stage(conn, bm_id):
    if bm_id is None or not enabled(conn):
        return 'sem_ciclo'
    return cycle_state(conn.connection, bm_id)['stage']


def period_query(first, last, prefix=''):
    from . import models as m
    from django.db.models import Q, Exists, OuterRef, Func, F, BigIntegerField
    if not enabled():
        return Q(pk__in=[])
    current = m.CicloPagamentoBM.objects.filter(bm_id=OuterRef(prefix+'pk'), sucessor__isnull=True,
        data_prevista__range=(first,last)).exclude(tipo='inicial').annotate(
        pending=Func(F('bm_id'),function='hidro_bm_cycle_balance',output_field=BigIntegerField())).filter(pending__gt=0)
    return Q(Exists(current))


def sql_amount(conn, bm_id, kind):
    if bm_id is None:return 0
    if not enabled(conn) or head(conn.connection,bm_id) is None:
        if kind == 'authorized':
            bm=row(conn.connection,'SELECT valor_pago FROM gestao_contratos_bm WHERE id=?',(bm_id,))
            return cents(bm['valor_pago']) if bm else 0
        return 0
    state=cycle_state(conn.connection,bm_id)
    if kind == 'authorized':
        return state['measured_cents'] if state['cycle']['tipo']=='inicial' else state['balance_cents']
    return state['unbilled_cents'] if kind=='unbilled' else state['balance_cents']


def apply_filter(queryset, value='', manager=None, prefix=''):
    from . import models as m
    from django.db.models import Q, Exists, OuterRef, Func, F, CharField, BigIntegerField
    from django.db.models.lookups import In
    key=prefix+'pk'
    if value in {'novos','reprogramados'}:
        if not enabled():
            return queryset if value=='novos' else queryset.none()
        current=m.CicloPagamentoBM.objects.filter(bm_id=OuterRef(key),sucessor__isnull=True).exclude(tipo='inicial')
        queryset=queryset.filter(~Q(Exists(current)) if value=='novos' else Q(Exists(current)))
        if value=='reprogramados':
            queryset=queryset.annotate(_cycle_pending=Func(F(key),function='hidro_bm_cycle_balance',output_field=BigIntegerField())).filter(_cycle_pending__gt=0)
    elif value=='sem_nf':
        queryset=queryset.filter(~Q(Exists(m.NF.objects.filter(bm_id=OuterRef(key),cancelada_em__isnull=True))))
    elif value=='parciais':
        queryset=queryset.filter(Q(In(Func(F(key),function='hidro_bm_cycle_liquidation',output_field=CharField()),['parcial'])))
    elif value in {'gerencia','diretoria','autorizado','conferencia'}:
        stages={'gerencia':['gerencia','sem_gerente'],'diretoria':['diretoria'],'autorizado':['autorizado'],'conferencia':['conferencia','reprovado','revisao']}[value]
        queryset=queryset.filter(Q(In(Func(F(key),function='hidro_bm_cycle_stage',output_field=CharField()),stages)))
    if manager:
        try:
            manager_id=int(getattr(manager,'pk',manager))
        except (TypeError,ValueError):
            return queryset.none()
        queryset=queryset.annotate(_cycle_manager=Func(F(key),function='hidro_bm_cycle_manager',output_field=BigIntegerField())).filter(_cycle_manager=manager_id)
    return queryset


@contextmanager
def cycle_transaction(bm_id, user, operation, **extra):
    from . import models as m
    from .financial_audit import financial_audit_context
    if not enabled():
        raise ValidationError('Ciclos de BM ainda não ativados; aplique e confira a migration 0129 no ambiente de destino.')
    def immediate(execute, sql, params, many, context):
        return execute('BEGIN IMMEDIATE' if connection.vendor == 'sqlite' and sql.strip().upper() == 'BEGIN' else sql, params, many, context)
    token = _operation.set(dict(operation=operation, bm_id=bm_id, actor=user.pk if user else None, **extra))
    try:
        with connection.execute_wrapper(immediate), transaction.atomic(), financial_audit_context(user):
            m.BM.objects.filter(pk=bm_id).update(id=F('id'))
            yield m.BM.objects.select_for_update().get(pk=bm_id)
    finally:
        _operation.reset(token)


def snapshot(state):
    bm = state['bm']
    previous=programmed_date(state,head(raw_connection(),bm['id']))
    return dict(contrato_id=state['contract_id'], projeto_id=state['project_id'],
                medido=str(money(state['measured_cents'])), faturado=str(money(state['billed_cents'])),
                pago=str(money(state['paid_cents'])), saldo=str(money(state['balance_cents'])),
                nfs=[dict(id=n['id'], numero=n['numero_nf'], cancelada=bool(n['cancelada_em']), saldo=str(money(n['balance_cents']))) for n in state['invoices']],
                aprovacoes_iniciais={key: bm.get(key) for key in ('status_coordenador','data_aprovacao_coordenador','status_gerente','data_aprovacao_gerente','aprovacao_pagamento','data_aprovacao_diretor')},
                responsavel_existente=responsible(raw_connection(),state),versao=state['version'],
                fonte_programacao_original='BM.data_pagamento',
                data_pagamento_bm=state['reference'].isoformat() if state['reference'] else None,
                data_programacao_anterior=previous.isoformat() if previous else None)


def operator(user, supply_only=False):
    allowed = {'suprimento'} if supply_only else {'suprimento', 'financeiro'}
    if not user or not user.is_authenticated or not user.is_active or user.grupo not in allowed:
        raise PermissionDenied('Perfil sem competência para esta operação de programação.')


def reprogramming_plan(db, bm_id, *, state=None, today=None):
    """Consulta a próxima programação, sem exigir ou criar um ciclo inicial."""
    today=today or timezone.localdate()
    state=state or financial_state(db,bm_id,today)
    current=head(db,bm_id)
    previous=programmed_date(state,current)
    result=dict(available=False,reason='',previous_date=previous,next_date=None,calendar_id=None,
        cycle_id=current['id'] if current else 0,version=state['version'],balance_cents=state['balance_cents'])
    if state['errors']:
        result['reason']='; '.join(state['errors'])
    elif state['balance_cents']<=0:
        result['reason']='BM sem saldo pendente para reprogramar.'
    elif not previous or not state['reference']:
        result['reason']='Informe a Data de pagamento no cadastro do BM.'
    elif previous>=today:
        result['reason']='A data da programação vigente ainda não passou.'
    elif not operational(state['bm']):
        result['reason']='Conclua a aprovação operacional do BM antes de reprogramar.'
    elif state['bm']['aprovacao_pagamento'] not in {'pendente','aprovado'}:
        result['reason']='A autorização inicial foi reprovada. Revise o BM antes de reprogramar.'
    elif current and db.execute("SELECT 1 FROM gestao_contratos_decisaociclobm WHERE ciclo_id=? AND situacao='reprovado'",(current['id'],)).fetchone():
        result['reason']='Ciclo reprovado: exige revisão expressa pelo Suprimento.'
    else:
        floor=max(today,previous+timedelta(days=1),state['not_before'] or state['reference'])
        calendar=row(db,'SELECT id,data_pagamento FROM gestao_contratos_calendariopagamento WHERE data_pagamento>=? ORDER BY data_pagamento LIMIT 1',(floor.isoformat(),))
        if calendar:
            result.update(available=True,calendar_id=calendar['id'],next_date=date.fromisoformat(calendar['data_pagamento']))
        else:
            result['reason']='Aguardando definição da próxima data de pagamento no calendário.'
    return result


def process_bm(bm_id, user=None, today=None, reason='', *, reprogram_only=False, expected=None):
    from . import models as m
    if user is not None:
        operator(user)
    today = today or timezone.localdate()
    if today > timezone.localdate():
        raise ValidationError('Não é permitido encerrar antecipadamente uma programação futura.')
    with cycle_transaction(bm_id, user, 'processar', today=today.isoformat()):
        db = raw_connection()
        state = financial_state(db, bm_id, today)
        created = []
        if reprogram_only:
            plan=reprogramming_plan(db,bm_id,state=state,today=today)
            if expected is not None and any(expected.get(key)!=plan[key] for key in ('cycle_id','version','balance_cents','calendar_id','next_date')):
                raise ValidationError('O BM, saldo ou calendário mudou após a abertura da confirmação. Atualize antes de reprogramar.')
            if not plan['available']:
                raise ValidationError(plan['reason'])
        if state['errors'] or not state['balance_cents'] or not state['reference']:
            return dict(created=created, reason='; '.join(state['errors']) or ('Obrigação liquidada.' if state['full'] else 'Data de pagamento do BM não informada.'))
        current = head(db, bm_id)
        if current is None:
            calendar = m.CalendarioPagamento.objects.filter(data_pagamento=state['reference']).first()
            initial = m.CicloPagamentoBM.objects.create(bm_id=bm_id, numero=1, tipo='inicial',
                data_prevista=state['reference'], calendario=calendar, saldo_inclusao=money(state['balance_cents']),
                contexto_inclusao=snapshot(state), versao_material=state['version'], registrado_por=user)
            created.append(initial.pk)
            current = head(db, bm_id)
        previous=programmed_date(state,current)
        if previous >= today:
            return dict(created=created, reason='Programação vigente.')
        if not operational(state['bm']) or state['bm']['aprovacao_pagamento'] not in {'pendente','aprovado'}:
            return dict(created=created, reason='Aprovações iniciais ainda não concluídas; não são substituídas por outro ciclo.')
        if db.execute("SELECT 1 FROM gestao_contratos_decisaociclobm WHERE ciclo_id=? AND situacao='reprovado'", (current['id'],)).fetchone():
            return dict(created=created, reason='Ciclo reprovado: exige revisão expressa, não simples troca de data.')
        floor = max(today, previous + timedelta(days=1), state['not_before'] or state['reference'])
        calendar = m.CalendarioPagamento.objects.filter(data_pagamento__gte=floor).order_by('data_pagamento').first()
        if calendar is None:
            return dict(created=created, reason='Pagamento pendente; aguardando definição de nova programação no calendário.')
        new = m.CicloPagamentoBM.objects.create(bm_id=bm_id, numero=current['numero']+1,
            anterior_id=current['id'], tipo='reprogramacao', data_prevista=calendar.data_pagamento, calendario=calendar,
            saldo_inclusao=money(state['balance_cents']), contexto_inclusao=snapshot(state),
            versao_material=state['version'], motivo=str(reason or '').strip(), registrado_por=user)
        created.append(new.pk)
        return dict(created=created, reason='Reprogramado: novas decisões gerencial e da Diretoria são obrigatórias.')


def record_first_director_authorization(bm, user, decision, reason):
    """Compatibilidade com o fluxo inicial; somente após decisão real no ciclo.

    Uma autorização anterior aprovada nunca é sobrescrita. A primeira aprovação
    efetiva é registrada com o autor/data atuais e sua referência ao novo ciclo.
    """
    from . import models as m
    from django.contrib.contenttypes.models import ContentType
    mode=_operation.get()
    if (not user.is_active or user.grupo!='diretoria' or mode.get('operation')!='decidir'
            or mode.get('actor')!=user.pk or mode.get('bm_id')!=bm.pk
            or not m.DecisaoCicloBM.objects.filter(pk=decision.pk,ciclo__bm_id=bm.pk,etapa='diretoria',
                situacao='aprovado',registrado_por_id=user.pk).exists()):
        raise PermissionDenied('A primeira autorização exige decisão real da Diretoria no ciclo atual.')
    if bm.aprovacao_pagamento!='pendente':
        return
    fields=('status_coordenador','status_gerente','aprovacao_pagamento','data_aprovacao_diretor',
            'justificativa_aprovacao_diretor','justificativa_reprovacao_diretor')
    before={key:(getattr(bm,key).isoformat() if isinstance(getattr(bm,key),date) else getattr(bm,key)) for key in fields}
    context=dict(bm_id=bm.pk,contrato_id=bm.contrato_financeiro.pk,contrato_documental_id=bm.contrato_id,
        contrato_financeiro_id=bm.contrato_financeiro.pk,evento_id=bm.evento_id,os_id=bm.os_id,
        ciclo_id=decision.ciclo_id,decisao_ciclo_id=decision.pk)
    instant=decision.registrado_em
    m.BM.objects.filter(pk=bm.pk,aprovacao_pagamento='pendente').update(aprovacao_pagamento='aprovado',
        data_aprovacao_diretor=instant,justificativa_aprovacao_diretor=reason or None,justificativa_reprovacao_diretor=None)
    after=dict(before,aprovacao_pagamento='aprovado',data_aprovacao_diretor=instant.isoformat(),
        justificativa_aprovacao_diretor=reason or None,justificativa_reprovacao_diretor=None)
    m.RegistroAuditoria.objects.create(content_type=ContentType.objects.get_for_model(m.BM),object_id=bm.pk,
        acao='atualizado',usuario=user,modelo='BM',representacao_objeto=str(bm),
        detalhes=f'Primeira autorização efetiva da Diretoria registrada na decisão do ciclo #{decision.ciclo_id}.',
        operacao_financeira='decisao_bm',estado_anterior=dict(context,**before),estado_posterior=dict(context,**after),
        justificativa=reason,autor_nome=user.get_full_name() or user.username,autor_grupo=user.grupo)


def decide(cycle_id, user, stage, approve, reason='', *, expected_version=None, expected_responsible=None):
    from . import models as m
    if not user or not user.is_authenticated or not user.is_active:
        raise PermissionDenied
    cycle = m.CicloPagamentoBM.objects.get(pk=cycle_id)
    with cycle_transaction(cycle.bm_id, user, 'decidir') as bm:
        current = cycle_state(raw_connection(), cycle.bm_id)
        if current['cycle']['id'] != cycle_id or cycle.tipo == 'inicial':
            raise ValidationError('Decida apenas o ciclo atual reapresentado; a primeira aprovação usa o fluxo original.')
        manager = current['manager']
        if expected_version is not None and expected_version != current['version']:
            raise ValidationError('O contexto foi alterado depois da abertura do formulário. Atualize antes de decidir.')
        if expected_responsible is not None and (not manager or expected_responsible != manager['id']):
            raise ValidationError('O Líder de Contrato vinculado mudou. Atualize o formulário.')
        if stage == 'gerencia':
            if not manager or manager['id'] != user.pk or user.grupo not in RESPONSIBLE_ROLES:
                raise PermissionDenied('Somente o Líder de Contrato competente já vinculado à origem financeira pode renovar a aprovação.')
        elif stage == 'diretoria':
            if user.grupo != 'diretoria':
                raise PermissionDenied('A autorização do ciclo cabe à Diretoria.')
        else:
            raise ValidationError('Etapa inválida.')
        if current['errors'] or not operational(current['bm']) or current['bm']['aprovacao_pagamento'] not in {'pendente','aprovado'}:
            raise ValidationError('BM/origem exige conferência ou conclusão das aprovações iniciais.')
        if current['stage'] not in ({'gerencia'} if stage == 'gerencia' else {'diretoria'}):
            raise ValidationError('Esta decisão não está disponível; confira reprovações, revisão material ou decisões já registradas.')
        reason = str(reason).strip()
        if len(reason) > 4000 or (not approve and not reason):
            raise ValidationError('Reprovação exige justificativa; máximo de 4.000 caracteres.')
        decision=m.DecisaoCicloBM.objects.create(ciclo=cycle, etapa=stage, situacao='aprovado' if approve else 'reprovado',
            responsavel_id=manager['id'], saldo_avaliado=money(current['balance_cents']),
            versao_material=current['version'], justificativa=reason, registrado_por=user)
        if stage=='diretoria' and approve:
            record_first_director_authorization(bm,user,decision,reason)
        return decision


def revise(cycle_id, user, reason):
    from . import models as m
    operator(user, True)
    if not str(reason).strip():
        raise ValidationError('Revisão exige justificativa expressa.')
    original = m.CicloPagamentoBM.objects.get(pk=cycle_id)
    with cycle_transaction(original.bm_id, user, 'revisar'):
        state = cycle_state(raw_connection(), original.bm_id)
        if state['cycle']['id'] != original.pk or not state['balance_cents'] or state['errors']:
            raise ValidationError('Ciclo superado, liquidado ou com divergência impeditiva.')
        scheduled=programmed_date(state,state['cycle'])
        calendar=original.calendario if original.data_prevista==scheduled else m.CalendarioPagamento.objects.filter(data_pagamento=scheduled).first()
        return m.CicloPagamentoBM.objects.create(bm_id=original.bm_id, numero=original.numero+1, anterior=original,
            tipo='revisao', data_prevista=scheduled, calendario=calendar,
            saldo_inclusao=money(state['balance_cents']), versao_material=state['version'],
            contexto_inclusao=snapshot(state), motivo=reason.strip(), registrado_por=user)
