from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import IntegrityError,OperationalError
from django.http import JsonResponse,Http404
from django.shortcuts import get_object_or_404,render,redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods,require_safe
from . import models as m,financial_queries as fq,payment_queries as pq,payment_services as service
from .payment_forms import PaymentForm,ReversalForm,ScheduleForm,AgreementForm


ACTIONS={'pagamento':(PaymentForm,'Registrar pagamento por movimento'),'estorno':(ReversalForm,'Estornar movimento'),
    'programacao':(ScheduleForm,'Programar ou revisar parcela futura'),'acordo':(AgreementForm,'Registrar acordo já realizado')}


@login_required
@require_http_methods(['GET','POST'])
def invoice_action(request,nf_id,action,movement_id=None):
    service.operator(request.user,supply_only=action=='estorno')
    if action not in ACTIONS:raise Http404
    nf=get_object_or_404(fq.eager_nfs(m.NF.objects.all()),pk=nf_id)
    parent=get_object_or_404(m.PagamentoNF,nf=nf,pk=movement_id,tipo='pagamento') if action=='estorno' else None
    form_class,title=ACTIONS[action]
    form=form_class(request.POST if request.method=='POST' else None,request.FILES if request.method=='POST' else None,nf=nf)
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data
        common=dict(nf_id=nf.pk,user=request.user,key=data['key'])
        try:
            if action=='pagamento':result,created=service.record_payment(**common,valor=data['valor'],data_pagamento=data['data_pagamento'],comprovante=data.get('comprovante'),observacao=data.get('observacao',''),programacao_id=getattr(data.get('programacao'),'pk',None))
            elif action=='estorno':result,created=service.reverse_payment(movement_id=parent.pk,user=request.user,key=data['key'],valor=data['valor'],data_estorno=data['data_estorno'],motivo=data['motivo'])
            elif action=='programacao':result,created=service.schedule(**common,valor=data['valor'],data_prevista=data['data_prevista'],motivo=data['motivo'],substitui_id=getattr(data.get('substitui'),'pk',None),cancelada=data['cancelada'],observacao=data.get('observacao',''))
            else:result,created=service.renegotiate(**common,novo_vencimento=data['novo_vencimento'],motivo=data['motivo'],programacao_id=getattr(data.get('programacao'),'pk',None),responsavel_acordo=data.get('responsavel_acordo',''),documento=data.get('documento'),observacao=data.get('observacao',''))
            if request.headers.get('X-Requested-With')=='XMLHttpRequest':return JsonResponse({'success':True,'id':result.pk,'created':created})
            return redirect('detalhe_nf',nf_id=nf.pk)
        except ValidationError as error:form.add_error(None,' '.join(error.messages))
        except (IntegrityError,OperationalError):return JsonResponse({'success':False,'error':'Operação não gravada. Confira o saldo e as autorizações e repita com a mesma chave se necessário.'},status=409)
    if request.method=='POST':return JsonResponse({'success':False,'errors':form.errors},status=400)
    context=dict(form=form,nf=nf,title=title,action=action,parent=parent,state=pq.financial_state(nf))
    template='financeiro/_payment_form.html' if request.headers.get('X-Requested-With')=='XMLHttpRequest' else 'financeiro/payment_action.html'
    return render(request,template,context)


@login_required
@require_safe
def payment_list(request):
    from . import financial_operations as fo
    from .financial_views import query_context
    from django.core.paginator import Paginator
    from django.http import HttpResponse
    from django.db.models import Sum,Q
    if not fq.can_view_financial_panel(request.user):return HttpResponse('Acesso restrito.',status=403)
    context=query_context(request)
    form=context['financial_form']
    if form.is_valid():
        moves=fo.payments_query(request.user,form.cleaned_data)
        totals=moves.aggregate(pay=Sum('centavos',filter=Q(tipo='pagamento'),default=0),reverse=Sum('centavos',filter=Q(tipo='estorno'),default=0))
        page=Paginator(moves.select_related('nf__contrato__empresa_terceira','nf__bm','registrado_por','referencia_estorno').order_by('-data_pagamento','-pk'),20).get_page(request.GET.get('page'))
        attention=set(fq.financial_nfs().filter(pk__in=[p.nf_id for p in page]).filter(fq.nf_attention_query()).values_list('pk',flat=True))
        for payment in page:payment.requires_review=payment.nf_id in attention
        net=pq.money(totals['pay']-totals['reverse'])
        context.update(movements=page,page_obj=page,data_valid=True,paid=pq.money(totals['pay']),reversed=pq.money(totals['reverse']),net=net,totals={'paid':net})
    return render(request,'financeiro/pagamentos_movimentos.html',context)
