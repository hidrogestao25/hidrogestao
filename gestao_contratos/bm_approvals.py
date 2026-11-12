"""Aprovação dos dois contratos de um BM com vínculo documental cruzado."""
from django.db.models import Q,F
import hashlib,json
from decimal import Decimal

SIDES=('documental','financeiro')
FIELDS=tuple(field for side in SIDES for field in (
    f'status_lider_{side}',f'aprovador_lider_{side}_id',f'data_lider_{side}',f'justificativa_lider_{side}'))

def shared(bm):
    return bool(bm and getattr(bm,'evento_id',None) and bm.evento.contrato_terceiro_id
        and bm.contrato_id!=bm.evento.contrato_terceiro_id)

def shared_query(prefix=''):
    return Q(**{prefix+'evento__contrato_terceiro__isnull':False}) & ~Q(**{
        prefix+'contrato_id':F(prefix+'evento__contrato_terceiro_id')})

def complete_query(prefix=''):
    return Q(**{prefix+f'status_lider_{side}':'aprovado' for side in SIDES},**{
        prefix+f'aprovador_lider_{side}__isnull':False for side in SIDES},**{
        prefix+f'data_lider_{side}__isnull':False for side in SIDES})

def complete(bm):
    return all(getattr(bm,f'status_lider_{side}')=='aprovado'
        and getattr(bm,f'aprovador_lider_{side}_id') and getattr(bm,f'data_lider_{side}') for side in SIDES)

def rejected(bm):
    return any(getattr(bm,f'status_lider_{side}')=='reprovado' for side in SIDES)

def contracts(bm):
    return {'documental':bm.contrato,'financeiro':bm.contrato_financeiro}

def leader_query(user,path):
    return (Q(**{path+'guarda_chuva':True,path+'cod_projeto__lider_contrato':user})
        | (Q(**{path+'guarda_chuva':False})|Q(**{path+'cod_projeto__isnull':True})) & Q(**{path+'lider_contrato':user}))

def pending_query(user):
    return shared_query() & (leader_query(user,'contrato__') & Q(status_lider_documental__isnull=True)
        | leader_query(user,'evento__contrato_terceiro__') & Q(status_lider_financeiro__isnull=True)) & ~Q(status_coordenador='reprovado') & ~Q(status_gerente='reprovado')

def pending_sides(user,bm):
    if not shared(bm) or not user or not user.is_authenticated or not user.is_active or user.grupo not in ('lider_contrato','gerente_lider','gerente_contrato'):
        return []
    if rejected(bm) or bm.status_coordenador=='reprovado' or bm.status_gerente=='reprovado':return []
    return [side for side,contract in contracts(bm).items()
        if getattr(contract.referencia_lider_contrato,'pk',None)==user.pk
        and getattr(bm,f'status_lider_{side}') in (None,'pendente')]

def rows(bm):
    if not shared(bm):return []
    return [dict(side=side,contract=contract,leader=contract.referencia_lider_contrato,
        status=getattr(bm,f'status_lider_{side}') or 'pendente',
        actor=getattr(bm,f'aprovador_lider_{side}'),date=getattr(bm,f'data_lider_{side}'),
        reason=getattr(bm,f'justificativa_lider_{side}')) for side,contract in contracts(bm).items()]

def snapshot(bm):
    return {field:(getattr(bm,field).isoformat() if field.startswith('data_') and getattr(bm,field) else getattr(bm,field)) for field in FIELDS}

def version(bm):
    fields=('contrato_id','evento_id','os_id','numero_bm','parcela_paga','valor_pago','data_pagamento',
        'data_inicial_medicao','data_final_medicao','arquivo_bm')
    content={field:str(getattr(bm,field) or '') for field in fields}
    content['valor_pago']=format(Decimal(str(bm.valor_pago)),'.2f')
    if shared(bm):
        content['contrato_financeiro_id']=bm.contrato_financeiro.pk
    return hashlib.sha256(json.dumps(content,sort_keys=True).encode()).hexdigest()
