"""Excel dos BMs da previsão, com datas de caixa separadas da referência do BM."""
from io import BytesIO
from django.db.models import Sum,OuterRef,Subquery,BigIntegerField,F
from django.db.models.functions import Coalesce
from django.utils import timezone
from openpyxl import Workbook
from . import models as m
from .financial_exports import table
from .permissions import can_view_object,can_access_document
from django.core.exceptions import ValidationError

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
    from . import bm_cycles
    if bm_cycles.enabled():
        scoped={bm.pk:bm for bm in bms if getattr(bm,'ciclo_contexto',None)}
        history=m.CicloPagamentoBM.objects.filter(bm_id__in=scoped).select_related('anterior','registrado_por').prefetch_related(
            'decisoes__registrado_por','pagamentos_vinculados__pagamento__estornos').order_by('bm_id','numero')
        if history.count()>20000:
            raise ValidationError('Refine os filtros: a exportação suporta até 20.000 ciclos históricos de BM.')
        cycle_records=[]
        for cycle in history:
            bm=scoped[cycle.bm_id];current=bm.ciclo_contexto
            decisions={d.etapa:d for d in cycle.decisoes.all()}
            def decision_text(stage):
                decision=decisions.get(stage)
                return (f'{decision.get_situacao_display()} — {decision.registrado_por} (ID {decision.registrado_por_id}) — '
                        f'{timezone.localtime(decision.registrado_em):%d/%m/%Y %H:%M}\n{decision.justificativa}') if decision else (
                        'Aprovação inicial preservada no BM' if cycle.tipo=='inicial' else 'Sem decisão neste ciclo')
            linked=sum(link.pagamento.centavos-sum(e.centavos for e in link.pagamento.estornos.all()) for link in cycle.pagamentos_vinculados.all())
            cycle_records.append([bm.pk,bm.numero_bm,bm.contrato_financeiro.empresa_terceira.nome,bm.contrato_financeiro.num_contrato,
                bm.projeto_referencia,cycle.numero,cycle.get_tipo_display(),bm_cycles.previous_programmed_date(
                    {'contexto_inclusao':cycle.contexto_inclusao},{'data_prevista':cycle.anterior.data_prevista.isoformat()}) if cycle.anterior_id else None,
                cycle.data_prevista,cycle.saldo_inclusao,bm_cycles.money(linked),decision_text('gerencia'),decision_text('diretoria'),
                cycle.motivo or ('Pagamento não realizado no ciclo anterior — motivo não informado.' if cycle.anterior_id else ''),
                current['label'] if current['cycle'] and current['cycle']['id']==cycle.pk else 'Ciclo anterior preservado'])
        if cycle_records:
            table(book,'Ciclos de pagamento',['Participação BM ID','Número BM','Fornecedor','Contrato','Projeto','Ciclo','Tipo',
                'Data prevista anterior','Data prevista deste ciclo','Saldo na inclusão (snapshot; não somar)',
                'Pago líquido dos movimentos vinculados','Decisão gerencial','Decisão da Diretoria','Motivo','Situação'],
                cycle_records,money=(10,11),dates=(8,9),wrap=(3,7,12,13,14,15),row_height=90)
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
        ['Ciclos de pagamento','Uma participação permanece uma única medição na primeira aba. A aba de ciclos é histórica; saldos de inclusão são snapshots de tentativas, não novas obrigações a somar. Pagamentos efetivos continuam no ledger da NF.'],
        ['Programação original','A programação original atual usa a Data de pagamento cadastrada no BM. A aba histórica conserva as datas registradas em cada ciclo; reprogramações mantêm a data anterior confirmada no contexto do sucessor.'],
    ],dates=(2,))
    output=BytesIO();book.save(output)
    return output.getvalue()
