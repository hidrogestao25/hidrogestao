"""Projeções operacionais sobre as NFs existentes; nenhuma escrita financeira."""
from decimal import Decimal
from urllib.parse import urlencode
from django.db.models import Q,Sum,Count,Case,When,Value,CharField,OuterRef,Subquery,Exists,F,DateField
from django.db.models.functions import TruncMonth
from django.urls import reverse
from . import financial_queries as fq,financial_reconciliation as fr,models as m
from . import payment_queries as pq

STATES={'aguardando':'Aguardando autorização','autorizada':'Autorizada para pagamento',
    'paga':'Paga','conferencia':'Exige conferência'}


def accounts_query(user,filters,*,paid_only=False):
    data=fq.FinancialData(user,filters)
    qs=data.nfs.annotate(operation_state=Case(
        When(fq.nf_attention_query(),then=Value('conferencia')),
        When(financeiro_autorizou=True,then=Value('paga')),
        When(fq.authorized_query('bm__'),then=Value('autorizada')),
        default=Value('aguardando'),output_field=CharField()))
    if paid_only: qs=qs.filter(ledger_paid_cents__gt=0)
    if filters.get('nf_id'):qs=qs.filter(pk=filters['nf_id'])
    if filters.get('liquidacao')=='nao_paga':qs=qs.filter(ledger_paid_cents=0,cancelada_em__isnull=True)
    elif filters.get('liquidacao')=='parcial':qs=qs.filter(ledger_paid_cents__gt=0,ledger_balance_cents__gt=0)
    elif filters.get('liquidacao')=='integral':qs=qs.filter(ledger_paid_cents__gt=0,ledger_balance_cents=0,cancelada_em__isnull=True)
    if filters.get('reprogramada'):qs=qs.filter(ledger_renegotiated=True)
    from django.utils import timezone
    overdue=Q(ledger_overdue_installment=True)|(Q(ledger_due__lt=timezone.localdate())&Q(ledger_scheduled_cents__lt=F('ledger_balance_cents')))
    if filters.get('vencimento')=='vencida':qs=qs.filter(overdue,ledger_balance_cents__gt=0)
    elif filters.get('vencimento')=='a_vencer':qs=qs.filter(~overdue,ledger_balance_cents__gt=0).filter(Q(ledger_due__isnull=False)|Q(ledger_next_installment__isnull=False))
    elif filters.get('vencimento')=='desconhecido':qs=qs.filter(ledger_due__isnull=True,ledger_next_installment__isnull=True,ledger_balance_cents__gt=0)
    if filters.get('numero_nf'): qs=qs.filter(numero_nf__icontains=filters['numero_nf'])
    if filters.get('pesquisa'):
        value=filters['pesquisa']
        qs=qs.filter(Q(numero_nf__icontains=value)|Q(contrato__empresa_terceira__nome__icontains=value)
            |Q(contrato__num_contrato__icontains=value)|Q(contrato__cod_projeto__cod_projeto__icontains=value)
            |Q(os__cod_projeto__cod_projeto__icontains=value))
    if filters.get('situacao'): qs=qs.filter(operation_state=filters['situacao'])
    return qs


def payments_query(user,filters):
    scoped=accounts_query(user,{**filters,'historico':True})
    moves=m.PagamentoNF.objects.filter(nf_id__in=scoped.values('pk'))
    if filters.get('tipo_movimento'):moves=moves.filter(tipo=filters['tipo_movimento'])
    return fq.in_period(moves,filters,'data_pagamento')


def account_totals(queryset):
    totals=queryset.aggregate(count=Count('pk'),billed=Sum('valor_pago',filter=Q(cancelada_em__isnull=True),default=Decimal('0')),
        paid_cents=Sum('ledger_paid_cents',default=0),unpaid_cents=Sum('ledger_balance_cents',default=0),
        **{state:Count('pk',filter=Q(operation_state=state)) for state in STATES})
    totals['paid']=pq.money(totals.pop('paid_cents'));totals['unpaid']=pq.money(totals.pop('unpaid_cents'))
    return totals


def account_rows(queryset,user,next_url=''):
    rows=fq.nf_rows(queryset,user,next_url)
    for row in rows:
        row['operation_state']=STATES[row['record'].operation_state]
        row['history_url']=reverse('historico_financeiro')+f'?nf_id={row["id"]}'
        params={'historico':'on','visao':'nf','contrato':row['record'].contrato_id}
        if row['record'].bm_id:params['bm_id']=row['record'].bm_id
        row['diagnostic_url']=reverse('conferencia_financeira')+'?'+urlencode(params)
        nf=row['record']
        from django.utils import timezone
        overdue=nf.ledger_balance_cents>0 and (nf.ledger_overdue_installment or (nf.ledger_due and nf.ledger_due<timezone.localdate() and nf.ledger_scheduled_cents<nf.ledger_balance_cents))
        row['due_label']='Vencida' if overdue else 'A vencer' if nf.ledger_balance_cents>0 and (nf.ledger_due or nf.ledger_next_installment) else 'Vencimento não informado.' if nf.ledger_balance_cents>0 else 'Sem saldo pendente'
        row.update(due=nf.ledger_due,next_installment=nf.ledger_next_installment,renegotiated=nf.ledger_renegotiated,
            scheduled=pq.money(min(nf.ledger_scheduled_cents,max(nf.ledger_balance_cents,0))),
            unscheduled=pq.money(max(nf.ledger_balance_cents-nf.ledger_scheduled_cents,0)),overprogrammed=nf.ledger_scheduled_cents>nf.ledger_balance_cents)
    return rows


def budget_contracts(filters):
    qs=fq.financial_filter_choices(coordinator=getattr(filters.get('coordenador'),'pk',None),
        leader=getattr(filters.get('lider_contrato'),'pk',None),supplier=getattr(filters.get('fornecedor'),'pk',None),
        project=getattr(filters.get('projeto'),'pk',None))['contrato']
    if filters.get('contrato'):qs=qs.filter(pk=filters['contrato'].pk)
    if filters.get('centro'):
        owned=m.ContratoTerceiros.objects.filter(pk=OuterRef('pk')).filter(fq.technical_center_query(filters['centro']))
        orders=m.OS.objects.filter(contrato_id=OuterRef('pk'),coordenador__centros=filters['centro'])
        if filters.get('projeto'):orders=orders.filter(cod_projeto=filters['projeto'])
        qs=qs.filter(Exists(owned)|Exists(orders))
    return qs


def budget_rows(user,filters,contracts):
    contracts=list(contracts)
    grouped=fq.FinancialData(user,filters).indicators(by_contract=True)
    latest=m.AditivoContratoTerceiro.objects.filter(contrato_id=OuterRef('pk'),arquivo_aditivo_assinado__isnull=False).exclude(arquivo_aditivo_assinado='').order_by('-documento_assinado_enviado_em','-criado_em','-pk')
    mapping=dict(m.ContratoTerceiros.objects.filter(pk__in=[c.pk for c in contracts]).annotate(latest_id=Subquery(latest.values('pk')[:1])).values_list('pk','latest_id'))
    amendments=m.AditivoContratoTerceiro.objects.in_bulk([pk for pk in mapping.values() if pk])
    rows=[]
    for contract in contracts:
        reference=fr.contract_reference(contract,amendments.get(mapping.get(contract.pk)),loaded=True)
        row=fr.contract_position(contract,grouped[contract.pk],reference)
        row['accounts_url']=reverse('contas_a_pagar')+'?'+urlencode({'historico':'on','contrato':contract.pk})
        rows.append(row)
    return rows


class ProjectionLimit(ValueError):pass


def monthly_projection(user,filters):
    """Caixa por movimento e obrigações futuras por programação/prazo confiável."""
    from collections import defaultdict
    from django.utils import timezone
    data=fq.FinancialData(user,filters)
    metrics=('planned','paid','scheduled','rescheduled','authorized_unpaid','other_unpaid','review_balance','overdue')
    groups={}

    def period(qs,field):
        if filters.get('historico'):return qs
        return qs.filter(Q(**{field+'__range':[filters['data_inicial'],filters['data_limite']]})|Q(**{field+'__isnull':True}))

    def add(qs,day,value,supplier,project,metric,in_cents=False,obligation=False):
        grouping=qs.order_by().annotate(month=TruncMonth(day),supplier_id=F(supplier+'__pk'),supplier_label=F(supplier+'__nome'),
            project_id=F(project+'__pk'),project_label=F(project+'__cod_projeto')).values('month','supplier_id','supplier_label','project_id','project_label')
        rows=grouping.annotate(total=Sum(value,default=0),overdue_total=Sum(value,filter=Q(**{day+'__lt':timezone.localdate()}),default=0))
        for row in rows.iterator(chunk_size=200):
            key=(row['month'],row['supplier_id'],row['project_id'])
            if key not in groups:
                if len(groups)>=10000:raise ProjectionLimit('Refine os filtros para até 10.000 grupos mensais.')
                groups[key]=dict(month=row['month'],supplier=row['supplier_label'] or 'Sem fornecedor',project=row['project_label'] or 'Sem projeto',**{name:Decimal('0') for name in metrics})
            convert=pq.money if in_cents else Decimal
            groups[key][metric]+=convert(row['total'])
            if obligation:groups[key]['overdue']+=convert(row['overdue_total'])

    def origin_groups(qs,prefix=''):
        for kind in ('evento','os','sem_origem'):
            scoped=qs
            if kind=='evento':scoped=scoped.filter(**{prefix+'evento__isnull':False})
            elif kind=='os':scoped=scoped.filter(**{prefix+'evento__isnull':True,prefix+'os__isnull':False})
            else:scoped=scoped.filter(**{prefix+'evento__isnull':True,prefix+'os__isnull':True})
            yield scoped,prefix+('os__cod_projeto' if kind=='os' else 'contrato__cod_projeto')

    for qs,value in data.planned_origins(use_period=False):
        contract='contrato_terceiro' if qs.model is m.Evento else 'contrato'
        add(period(qs,'data_prevista_pagamento'),'data_prevista_pagamento',value,contract+'__empresa_terceira',
            contract+'__cod_projeto' if qs.model is m.Evento else 'cod_projeto','planned')
    for qs,project in origin_groups(data.payments,'nf__'):
        add(qs,'data_pagamento',pq.signed_cents(),'nf__contrato__empresa_terceira',project,'paid',True)
    pending=data.nfs_scope.filter(ledger_balance_cents__gt=0,cancelada_em__isnull=True)
    conflicting=pending.filter(ledger_scheduled_cents__gt=F('ledger_balance_cents'))
    for qs,project in origin_groups(conflicting.annotate(projection_day=Value(None,output_field=DateField()))):
        add(qs,'projection_day','ledger_balance_cents','contrato__empresa_terceira',project,'review_balance',True)
    consistent=pending.exclude(pk__in=conflicting.values('pk'))
    programs=pq.active_schedules().filter(nf_id__in=consistent.values('pk'),restante_centavos__gt=0)
    revised=Q(substitui__isnull=False)|Q(acordo__isnull=False)
    for condition,metric in ((~revised,'scheduled'),(revised,'rescheduled')):
        for qs,project in origin_groups(programs.filter(condition),'nf__'):
            add(period(qs,'data_prevista'),'data_prevista','restante_centavos','nf__contrato__empresa_terceira',project,metric,True,True)
    unscheduled=consistent.annotate(unprogrammed_cents=F('ledger_balance_cents')-F('ledger_scheduled_cents')).filter(unprogrammed_cents__gt=0)
    ready=fq.authorized_query('bm__')&~fq.nf_attention_query()
    for condition,metric in ((ready,'authorized_unpaid'),(~ready,'other_unpaid')):
        for qs,project in origin_groups(unscheduled.filter(condition)):
            add(period(qs,'ledger_due'),'ledger_due','unprogrammed_cents','contrato__empresa_terceira',project,metric,True,True)
    monthly=defaultdict(lambda:{name:Decimal('0') for name in metrics})
    for item in groups.values():
        for metric in metrics:monthly[item['month']][metric]+=item[metric]
    rows=[dict(month=month,**values) for month,values in sorted(monthly.items(),key=lambda pair:(pair[0] is None,pair[0]))]
    details=sorted(groups.values(),key=lambda row:(row['month'] is None,row['month'],row['supplier'],row['project']))
    return dict(rows=rows,details=details,totals={metric:sum((r[metric] for r in rows),Decimal('0')) for metric in metrics})
