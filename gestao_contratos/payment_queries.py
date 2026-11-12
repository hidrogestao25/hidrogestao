"""Projeções exatas em centavos; movimentos são a única fonte de liquidação."""
from decimal import Decimal
from django.db.models import Sum,Case,When,F,Value,BigIntegerField,OuterRef,Subquery,Exists,DateField,Q
from django.db.models.functions import Coalesce,Cast,Round
from . import models as m


def money(cents):return (Decimal(cents or 0)/Decimal(100)).quantize(Decimal('.01'))


def cents(value):
    amount=Decimal(str(value))
    if not amount.is_finite() or amount!=amount.quantize(Decimal('.01')):raise ValueError('Use valor finito com no máximo duas casas decimais.')
    return int(amount*100)


def signed_cents():return Case(When(tipo='estorno',then=-F('centavos')),default=F('centavos'),output_field=BigIntegerField())


def cash_total(invoices,first=None,last=None):
    moves=m.PagamentoNF.objects.filter(nf_id__in=invoices.values('pk'))
    if first:moves=moves.filter(data_pagamento__gte=first)
    if last:moves=moves.filter(data_pagamento__lte=last)
    return money(moves.aggregate(total=Sum(signed_cents(),default=0))['total'])


def origin_cash(queryset,kind,first=None,last=None):
    """Valores e datas reais por origem, sem consultar suas projeções legadas."""
    moves=m.PagamentoNF.objects.filter(**{'nf__'+kind+'_id__in':queryset.values('pk')})
    if first:moves=moves.filter(data_pagamento__gte=first)
    if last:moves=moves.filter(data_pagamento__lte=last)
    result={}
    for row in moves.order_by().values('nf__'+kind+'_id','data_pagamento').annotate(total=Sum(signed_cents())):
        result.setdefault(row['nf__'+kind+'_id'],[]).append((row['data_pagamento'],money(row['total'])))
    return result


def cash_amount(rows):return sum((value for _,value in rows),Decimal('0.00'))


def cash_date(rows):return max((day for day,_ in rows if day),default=None)


def invoice_paid_cents(nf):
    if hasattr(nf,'ledger_paid_cents'):return nf.ledger_paid_cents
    return nf.movimentos.aggregate(total=Sum(signed_cents(),default=0))['total']


def invoice_annotations(queryset):
    moves=m.PagamentoNF.objects.filter(nf_id=OuterRef('pk')).order_by().values('nf_id').annotate(total=Sum(signed_cents())).values('total')
    agreements=m.ReprogramacaoPagamento.objects.filter(nf_id=OuterRef('pk'),programacao__isnull=True).order_by('-pk')
    receipts=m.PagamentoNF.objects.filter(nf_id=OuterRef('pk')).exclude(comprovante='').exclude(comprovante__isnull=True).order_by('-data_pagamento','-pk')
    schedules=active_schedules().filter(nf_id=OuterRef('pk'),restante_centavos__gt=0)
    scheduled=schedules.order_by().values('nf_id').annotate(total=Sum('restante_centavos')).values('total')
    from django.utils import timezone
    return queryset.annotate(ledger_paid_cents=Coalesce(Subquery(moves,output_field=BigIntegerField()),0),
        ledger_has_payments=Exists(m.PagamentoNF.objects.filter(nf_id=OuterRef('pk'))),
        ledger_has_program_history=Exists(m.ProgramacaoPagamento.objects.filter(nf_id=OuterRef('pk'))),
        ledger_due=Coalesce(Subquery(agreements.values('novo_vencimento')[:1]),'vencimento_original',output_field=DateField()),
        ledger_renegotiated=Exists(m.ReprogramacaoPagamento.objects.filter(nf_id=OuterRef('pk'))),
        ledger_last_receipt=Subquery(receipts.values('comprovante')[:1]),
        ledger_scheduled_cents=Coalesce(Subquery(scheduled,output_field=BigIntegerField()),0),
        ledger_next_installment=Subquery(schedules.order_by('data_prevista','pk').values('data_prevista')[:1]),
        ledger_overdue_installment=Exists(schedules.filter(data_prevista__lt=timezone.localdate())),
        ledger_fiscal_cents=Cast(Round(F('valor_pago')*100),BigIntegerField())).annotate(ledger_balance_cents=Case(
            When(cancelada_em__isnull=False,then=Value(0)),default=F('ledger_fiscal_cents')-F('ledger_paid_cents'),output_field=BigIntegerField()))


def active_schedules(nf=None):
    qs=m.ProgramacaoPagamento.objects.filter(sucessora__isnull=True,cancelada=False)
    qs=qs.filter(nf__cancelada_em__isnull=True)
    if nf is not None:qs=qs.filter(nf=nf)
    paid=m.PagamentoNF.objects.filter(nf_id=OuterRef('nf_id'),programacao__grupo=OuterRef('grupo')).order_by().values('nf_id').annotate(total=Sum(signed_cents())).values('total')
    return qs.annotate(liquidado_centavos=Coalesce(Subquery(paid,output_field=BigIntegerField()),0)).annotate(restante_centavos=F('centavos')-F('liquidado_centavos'))


def financial_state(nf,today=None):
    from django.utils import timezone
    today=today or timezone.localdate()
    paid=invoice_paid_cents(nf);balance=0 if nf.cancelada_em else cents(nf.valor_pago)-paid
    schedule=list(active_schedules(nf).filter(restante_centavos__gt=0).order_by('data_prevista','pk'))
    raw=sum(p.restante_centavos for p in schedule)
    last=nf.reprogramacoes.filter(programacao__isnull=True).order_by('-pk').first()
    due=last.novo_vencimento if last else nf.vencimento_original
    scheduled=min(max(raw,0),max(balance,0));unscheduled=max(balance-scheduled,0)
    overdue=balance>0 and (any(p.data_prevista<today for p in schedule) or (unscheduled>0 and due and due<today))
    return dict(paid=money(paid),balance=money(balance),scheduled=money(scheduled),unscheduled=money(unscheduled),
        raw_scheduled=money(raw),overprogrammed=raw>balance,due=due,next_installment=schedule[0] if schedule else None,
        schedules=schedule,overdue=bool(overdue),due_label='Vencida' if overdue else 'A vencer' if balance>0 and (due or schedule) else 'Vencimento não informado.' if balance>0 else 'Sem saldo pendente',
        liquidation='Integralmente paga' if paid>0 and balance==0 else 'Parcialmente paga' if paid>0 else 'Não paga',
        renegotiated=nf.reprogramacoes.exists())
