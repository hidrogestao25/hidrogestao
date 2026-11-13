"""Excel dos BMs da previsão, com datas de caixa separadas da referência do BM."""
from io import BytesIO
from django.db.models import Sum,OuterRef,Subquery,BigIntegerField,F
from django.db.models.functions import Coalesce
from django.utils import timezone
from openpyxl import Workbook
from . import models as m
from .financial_exports import table
from .permissions import can_view_object,can_access_document

HEADERS=['Fornecedor','Descrição do serviço','Observação','Medição e recebimento','Projeto','Líder de contrato','Valor previsto',
    'Valor medido','Data de referência do BM','Aprovações','Aprovação da Diretoria','Possui NF?','Data de pagamento','Justificativa da gerência']


def approval_text(bm,status_field,date_field,audit):
    status=getattr(bm,status_field)
    text=dict(m.BM.STATUS_CHOICES).get(status,status)
    if audit and audit.usuario:
        actor=audit.usuario
        text+=f' — {actor.get_full_name() or actor.username} ({actor.get_grupo_display()})'
    elif status!='pendente':text+=' — responsável não identificado'
    instant=getattr(bm,date_field)
    if instant:
        local=timezone.localtime(instant) if timezone.is_aware(instant) else instant
        text+=' — '+local.strftime('%d/%m/%Y %H:%M')
    return text


def export_bms(user,bms,approval_map,*,first,last,mode,notice=''):
    invoices=m.NF.objects.filter(bm_id__in=[bm.pk for bm in bms],cancelada_em__isnull=True).select_related(
        'contrato__cod_projeto','evento__contrato_terceiro','os__cod_projeto','bm__evento__contrato_terceiro','bm__os__cod_projeto','bm__contrato')
    nf_ids=[];has_nf=set()
    for nf in invoices:
        if can_view_object(user,nf) and can_access_document(user,nf):
            has_nf.add(nf.bm_id);nf_ids.append(nf.pk)
    reversals=m.PagamentoNF.objects.filter(referencia_estorno_id=OuterRef('pk')).order_by().values('referencia_estorno_id').annotate(total=Sum('centavos')).values('total')
    moves=m.PagamentoNF.objects.filter(nf_id__in=nf_ids,tipo='pagamento',data_pagamento__isnull=False).annotate(
        reversed_cents=Coalesce(Subquery(reversals,output_field=BigIntegerField()),0)).filter(centavos__gt=F('reversed_cents'))
    dates={}
    for bm_id,day in moves.values_list('nf__bm_id','data_pagamento').distinct():dates.setdefault(bm_id,set()).add(day)
    records=[]
    for bm in bms:
        contract=bm.contrato_financeiro;origin=bm.evento or bm.os
        info=approval_map.get(bm.pk,{})
        operational='\n'.join(label+approval_text(bm,status,day,info.get(role)) for role,label,status,day in (
            ('coordenador','Liderança: ','status_coordenador','data_aprovacao_coordenador'),
            ('gerente','Gerência: ','status_gerente','data_aprovacao_gerente')))
        if bm.compartilhado_entre_contratos:
            operational='\n'.join(
                f"Contrato {d['contract'].num_contrato}: {d['status']} — "
                f"{d['actor'].get_full_name() or d['actor'].username if d['actor'] else 'sem decisão registrada'}"
                +(f" — {timezone.localtime(d['date']):%d/%m/%Y %H:%M}" if d['date'] else '')
                for d in bm.aprovacoes_contratos)
        paid_dates=sorted(dates.get(bm.pk,()))
        paid_date=paid_dates[0] if len(paid_dates)==1 else '\n'.join(day.strftime('%d/%m/%Y') for day in paid_dates) if paid_dates else None
        planned=(bm.evento.valor_previsto if bm.evento_id else bm.os.valor if bm.os_id else None)
        director=approval_text(bm,'aprovacao_pagamento','data_aprovacao_diretor',info.get('diretor'))
        if bm.aprovacao_pagamento=='aprovado' and bm.justificativa_aprovacao_diretor:
            director+='\nJustificativa: '+bm.justificativa_aprovacao_diretor
        receipt=getattr(bm,'medicao_recebimento',None)
        records.append([contract.empresa_terceira.nome if contract and contract.empresa_terceira_id else '',
            origin.descricao if origin else '',bm.observacao or '',receipt.texto_exportacao if receipt else '',bm.projeto_referencia,bm.lider_contrato_referencia,
            planned,bm.valor_pago,bm.data_pagamento,operational,
            director,'Sim' if bm.pk in has_nf else 'Não',paid_date,bm.justificativa_reprovacao_gerente or ''])
    book=Workbook(write_only=True)
    table(book,'Boletins de Medição',HEADERS,records,money=(7,8),dates=(9,13),wrap=(2,3,4,10,11,13,14),row_height=100)
    # Multilinhas mantêm todas as datas de pagamentos parciais na mesma participação.
    table(book,'Critérios',['Critério','Valor'],[
        ['Data inicial',first or 'Sem limite inicial'],['Data limite',last],
        ['Período automático',notice or 'Sem Data Inicial, usa a data de pagamento anterior à Data Limite + 1 dia.'],
        ['Filtro de BMs','Período de medição' if mode=='medicao' else 'Data de aprovação operacional'],
        ['Valor previsto','Valor da origem Evento/OS; pode se repetir em vários BMs. Não somar essas repetições.'],
        ['Observação','Observação cadastrada no BM. Descrição do serviço é a descrição do Evento/OS.'],
        ['Medição e recebimento','Sobre medição e Sobre medição e recebimento, com seus respectivos textos.'],
        ['Justificativa da gerência','Texto registrado na avaliação gerencial do BM; em branco quando não informado.'],
        ['Possui NF?','NF ativa vinculada à participação, dentro do escopo de acesso.'],
        ['Data de pagamento','Histórico completo: datas efetivas dos pagamentos vinculados às NFs do BM com saldo líquido não estornado. Todas as datas são listadas; sem movimento, fica em branco. Não é a data de referência ou a programação futura.'],
    ],dates=(2,))
    output=BytesIO();book.save(output)
    return output.getvalue()
