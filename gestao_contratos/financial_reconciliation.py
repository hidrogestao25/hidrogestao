"""Conferência por participação/origem; nunca liquida ou corrige lançamentos."""
from decimal import Decimal
from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum, Count, Q, OuterRef, Subquery, DecimalField, F, Exists,BigIntegerField
from django.db.models.functions import Coalesce, Cast, TruncDate,Round
from django.urls import reverse
from . import models as m
from . import financial_queries as fq
from . import payment_queries as pq
from .permissions import can_view_object, can_access_document

UNKNOWN_ACTOR='Responsável não identificado no histórico disponível.'
MONEY=DecimalField(max_digits=20,decimal_places=2)


def get_valor_total_aditivado(aditivo,valor_base=None):
    """Metodologia existente: novo_valor_total é acréscimo, não absoluto."""
    if not aditivo or aditivo.novo_valor_total is None: return valor_base
    previous=aditivo.valor_total_anterior if aditivo.valor_total_anterior is not None else valor_base
    return aditivo.novo_valor_total if previous is None else previous+aditivo.novo_valor_total


def contract_reference(contract,latest=None,*,loaded=False):
    if latest is None and not loaded:
        latest=contract.aditivos.filter(arquivo_aditivo_assinado__isnull=False).exclude(arquivo_aditivo_assinado='').order_by('-documento_assinado_enviado_em','-criado_em','-pk').first()
    return get_valor_total_aditivado(latest,contract.valor_total) or Decimal('0')


def contract_position(contract,stats,reference):
    stats=dict(stats)
    stats.update(unpaid=stats.get('saldo_pendente',stats['faturado']-stats['pago']),measured_billed=stats['medido']-stats['faturado'],
        planned_measured=stats['previsto']-stats['medido'])
    alerts=[]
    if contract.guarda_chuva:
        alerts.append('Guarda-chuva: conferir por OS/projeto; o valor cadastral não é teto uniforme de liquidação.')
    elif reference and (stats['medido']>reference or stats['pago']>reference):
        alerts.append('Medição ou pagamento supera o valor contratual vigente cadastrado — conferir aditivos e escopo.')
    if stats['medido']>stats['previsto']:alerts.append('Medição superior ao planejamento cadastrado — conferir.')
    if stats['faturado']>stats['medido']:alerts.append('Valor faturado superior ao valor medido — verificar.')
    return dict(contract=contract,stats=stats,reference=reference,alerts=alerts)


def with_bm_totals(queryset):
    invoices=m.NF.objects.filter(bm_id=OuterRef('pk'),cancelada_em__isnull=True).order_by().values('bm_id')
    billed=invoices.annotate(total=Sum('valor_pago')).values('total')
    paid=m.PagamentoNF.objects.filter(nf__bm_id=OuterRef('pk')).order_by().values('nf__bm_id').annotate(total=Sum(pq.signed_cents())).values('total')
    return queryset.annotate(nf_billed=Coalesce(Subquery(billed,output_field=MONEY),Decimal('0')),
        nf_paid_centavos=Coalesce(Subquery(paid,output_field=BigIntegerField()),0))


def bm_totals(bm,nfs):
    totals=nfs.aggregate(billed=Sum('valor_pago',filter=Q(cancelada_em__isnull=True),default=Decimal('0')),count=Count('pk'))
    totals['paid']=pq.money(m.PagamentoNF.objects.filter(nf_id__in=nfs.values('pk')).aggregate(total=Sum(pq.signed_cents(),default=0))['total'])
    totals.update(measured=bm.valor_pago,measured_billed=bm.valor_pago-totals['billed'],unpaid=totals['billed']-totals['paid'])
    return totals


def bm_reconciliation_row(bm,user,next_url=''):
    row=fq.bm_row(bm,user,next_url)
    row.update(billed=bm.nf_billed,paid=bm.nf_paid,difference=bm.valor_pago-bm.nf_billed,unpaid=bm.nf_billed-bm.nf_paid)
    if bm.nf_billed>bm.valor_pago:
        row['reasons'].append('Valor faturado superior ao valor medido — verificar.')
    origin=bm.evento if bm.evento_id else bm.os
    planned=(origin.valor_previsto if bm.evento_id else origin.valor) if origin else None
    if planned is not None:
        scope=fq.financial_bms().filter(**{('evento_id' if bm.evento_id else 'os_id'):origin.pk})
        total=scope.aggregate(total=Sum('valor_pago',default=Decimal('0')))['total']
        if total>planned:
            row['reasons'].append('Medições da origem superiores ao valor planejado do Evento/OS — conferir escopo e revisões.')
    if bm.data_inicial_medicao and bm.data_final_medicao and bm.data_inicial_medicao>bm.data_final_medicao:
        row['reasons'].append('Período de medição com início posterior ao fim — conferir datas.')
    return row


def identified_creation_query(nf_ref=OuterRef('pk')):
    return m.RegistroAuditoria.objects.filter(content_type__app_label='gestao_contratos',content_type__model='nf',
        object_id=nf_ref,acao='criado').filter(Q(usuario__isnull=False)|Q(autor_nome__isnull=False))


def diagnostic_nfs(queryset):
    payment=m.RegistroAuditoria.objects.filter(content_type__app_label='gestao_contratos',content_type__model='nf',object_id=OuterRef('pk')).filter(
        Q(operacao_financeira__in=['pagamento','liquidacao'])|Q(operacao_financeira='criacao',estado_posterior__financeiro_autorizou=1)).order_by('-data_hora','-pk')
    return fq.financial_nfs().filter(pk__in=queryset.values('pk')).annotate(
        identified_creation=Exists(identified_creation_query()),
        first_payment_day=Subquery(m.PagamentoNF.objects.filter(nf_id=OuterRef('pk'),tipo='pagamento',data_pagamento__isnull=False).order_by('data_pagamento','pk').values('data_pagamento')[:1]),
        measured_at_payment=Cast(Subquery(payment.values('estado_posterior__bm_valor_medido')[:1]),MONEY),
        authorization_day=TruncDate('bm__data_aprovacao_diretor'),
        measurement_end_day=TruncDate('bm__data_final_medicao')).filter(
            fq.nf_attention_query() | Q(numero_nf__isnull=True) | Q(numero_nf='') | Q(identified_creation=False)
            | Q(ledger_paid_cents__gt=0,data_emissao__gt=F('first_payment_day'))
            | Q(ledger_paid_cents__gt=0,authorization_day__gt=F('first_payment_day'))
            | Q(ledger_paid_cents__gt=0,measurement_end_day__gt=F('first_payment_day'))
            | (Q(ledger_paid_cents__gt=0,measured_at_payment__isnull=False)&~Q(measured_at_payment=F('bm__valor_pago'))))


def nf_diagnostic_reasons(nf):
    reasons=fq.nf_review_reasons(nf)
    if not nf.numero_nf: reasons.append('Documento sem identificação fiscal cadastrada; legado permitido.')
    if hasattr(nf,'identified_creation') and not nf.identified_creation: reasons.append(UNKNOWN_ACTOR)
    payment_day=getattr(nf,'first_payment_day',None) or nf.movimentos.filter(tipo='pagamento',data_pagamento__isnull=False).order_by('data_pagamento').values_list('data_pagamento',flat=True).first()
    if nf.total_pago>0 and payment_day and nf.data_emissao and payment_day<nf.data_emissao:
        reasons.append('Data de pagamento anterior à emissão — conferir o contexto e as datas informadas.')
    if nf.total_pago>0 and payment_day and nf.bm_id:
        from django.utils import timezone
        for field,label in (('data_aprovacao_diretor','autorização atual da Diretoria'),('data_final_medicao','conclusão da medição')):
            value=getattr(nf.bm,field)
            if value:
                day=timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
                if payment_day<day:
                    reasons.append(f'Data de pagamento anterior à {label} — conferir o contexto; não há alteração automática.')
        payment=m.RegistroAuditoria.objects.filter(content_type__app_label='gestao_contratos',content_type__model='nf',object_id=nf.pk).filter(
            Q(operacao_financeira__in=['pagamento','liquidacao'])|Q(operacao_financeira='criacao',estado_posterior__financeiro_autorizou=1)).order_by('-data_hora','-pk').first()
        if payment:
            state=payment.estado_posterior or {}
            if state.get('bm_valor_medido') is not None and Decimal(str(state['bm_valor_medido']))!=nf.bm.valor_pago:
                reasons.append('Valor medido do BM alterado após o registro do pagamento — conferir o histórico disponível.')
    return reasons


def possible_duplicates(nf):
    candidates=m.NF.objects.filter(contrato__empresa_terceira_id=nf.contrato.empresa_terceira_id).exclude(pk=nf.pk)
    match=Q(pk__in=[])
    if nf.chave_acesso:
        match |= Q(chave_acesso=nf.chave_acesso,tipo_documento=nf.tipo_documento)
    if nf.numero_nf:
        match |= Q(numero_nf=nf.numero_nf,serie=nf.serie,tipo_documento=nf.tipo_documento,
            data_emissao=nf.data_emissao,valor_pago=nf.valor_pago)
    return candidates.filter(match).order_by('-pk')


def legacy_origins(kind,contract=None):
    model=m.Evento if kind=='evento' else m.OS
    qs=model.objects.all()
    if kind=='evento': qs=qs.filter(contrato_terceiro__isnull=False)
    if contract: qs=qs.filter(**{('contrato_terceiro' if kind=='evento' else 'contrato'):contract})
    invoices=m.PagamentoNF.objects.filter(**{'nf__'+kind+'_id':OuterRef('pk')}).order_by().values('nf__'+kind+'_id').annotate(total=Sum(pq.signed_cents())).values('total')
    return qs.annotate(nf_paid_centavos=Coalesce(Subquery(invoices,output_field=BigIntegerField()),0),
        origin_paid=Coalesce('valor_pago',Decimal('0')),origin_paid_centavos=Cast(Round(Coalesce('valor_pago',Decimal('0'))*100),BigIntegerField())).exclude(origin_paid_centavos=F('nf_paid_centavos'))


def can_view_audit(user,event):
    if not event.operacao_financeira: return False
    if fq.can_view_financial_panel(user): return True
    states=[s for s in (event.estado_anterior,event.estado_posterior) if s]
    if not states: return False
    try:
        for state in states:
            nf=m.NF(id=event.object_id,contrato_id=state.get('contrato_id'),evento_id=state.get('evento_id'),os_id=state.get('os_id'))
            if not (can_view_object(user,nf) and can_access_document(user,nf)): return False
            if state.get('bm_id'):
                bm=m.BM.objects.get(pk=state['bm_id'])
                if not (can_view_object(user,bm) and can_access_document(user,bm)): return False
    except (m.Evento.DoesNotExist,m.OS.DoesNotExist,m.ContratoTerceiros.DoesNotExist,m.BM.DoesNotExist):
        return False
    return True


def audit_rows(events,user):
    result=[]
    for event in events:
        if not can_view_audit(user,event): continue
        before=event.estado_anterior or {};after=event.estado_posterior or {}
        changes=[dict(field=key,before=before.get(key),after=after.get(key)) for key in sorted(set(before)|set(after)) if before.get(key)!=after.get(key)]
        labels={'bm_numero':'Número do BM','bm_valor_medido':'Valor medido do BM','bm_operacional_lider':'Aprovação operacional da liderança',
            'bm_operacional_gerente':'Aprovação operacional da gerência','bm_diretoria':'Autorização da Diretoria',
            'bm_data_autorizacao':'Data da autorização do BM','financeiro_autorizou':'Liquidação integral', 'liquidado_centavos':'Pago líquido (R$)', 'movimento_id':'Movimento', 'programacao_id':'Parcela programada', 'origem_registro':'Origem do registro', 'referencia_estorno_id':'Movimento estornado'}
        for change in changes:
            key=change['field']
            if key=='liquidado_centavos':
                for side in ('before','after'):
                    if change[side] is not None:change[side]=str(pq.money(change[side]))
            if key in labels: change['field']=labels[key]
            else:
                try: change['field']=str(m.NF._meta.get_field(key[:-3] if key.endswith('_id') else key).verbose_name).capitalize()
                except Exception: change['field']=key
        documents=[]
        for side,state in (('anterior',before),('posterior',after)):
            for field in ('arquivo_nf','comprovante_pagamento','documento_acordo'):
                if state.get(field): documents.append(dict(label=f'{field} ({side})',url=reverse('documento_historico_nf',args=[event.pk,side,field])))
        operation={'criacao':'Cadastro da NF','alteracao':'Alteração de dados/documento','pagamento':'Pagamento registrado',
            'liquidacao':'Liquidação por movimento','estorno':'Estorno identificado','programacao':'Programação / revisão de parcela',
            'reprogramacao':'Registro de acordo de prazo','cancelamento':'Cancelamento lógico da NF',
            'correcao_paga':'Correção posterior ao pagamento','desmarcacao':'Pagamento desmarcado','exclusao':'Exclusão da NF'}
        result.append(dict(event=event,title=operation.get(event.operacao_financeira,event.operacao_financeira),actor=event.autor_nome or (event.usuario.get_full_name() or event.usuario.username if event.usuario else UNKNOWN_ACTOR),
            changes=changes,documents=documents))
    return result


def filtered_legacy_origins(data,kind):
    filters=data.filters
    qs=legacy_origins(kind,filters.get('contrato'))
    path='contrato_terceiro' if kind=='evento' else 'contrato'
    if filters.get('origem') and filters['origem']!=kind: return qs.none()
    if filters.get('referencia'): qs=qs.filter(pk=filters['referencia'])
    if filters.get('fornecedor'): qs=qs.filter(**{path+'__empresa_terceira':filters['fornecedor']})
    if filters.get('projeto'): qs=qs.filter(**{('cod_projeto' if kind=='os' else path+'__cod_projeto'):filters['projeto']})
    for key,predicate,own in (('coordenador',fq.contract_coordinator_query,lambda x:Q(coordenador=x)),
            ('lider_contrato',fq.leader_assignment_query,fq.leader_assignment_query)):
        if filters.get(key):
            contracts=m.ContratoTerceiros.objects.filter(pk=OuterRef(path+'_id')).filter(predicate(filters[key]))
            qs=qs.filter(Exists(contracts)|(own(filters[key]) if kind=='os' else Q(pk__in=[])))
    if any(filters.get(key) for key in ('bm_id','numero_bm','autorizacao','pagamento')):
        qs=qs.filter(Exists(data.bms_scope.filter(**{kind+'_id':OuterRef('pk')})))
    return fq.in_period(qs,filters,'data_pagamento')
