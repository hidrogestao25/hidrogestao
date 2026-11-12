"""Consultas operacionais. Mutações continuam nas views BM/NF existentes."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe
from . import financial_queries as fq,financial_operations as fo
from .financial_forms import operational_form


def query_context(request,mode='contas'):
    form=operational_form(request,mode)
    params=request.GET.copy();params.pop('page',None)
    return dict(financial_form=form,pagination_query=params.urlencode(),financial_period='Todo o histórico' if form.is_valid() and form.cleaned_data.get('historico') else 'Período selecionado')


@login_required
@require_safe
def contas_a_pagar(request,paid_only=False):
    if not fq.can_view_financial_panel(request.user): return HttpResponse('Acesso restrito.',status=403)
    context=query_context(request)
    context['paid_only']=paid_only
    form=context['financial_form']
    if form.is_valid():
        qs=fo.accounts_query(request.user,form.cleaned_data,paid_only=paid_only)
        page=Paginator(fq.eager_nfs(qs).order_by('-data_pagamento','-pk'),20).get_page(request.GET.get('page'))
        context.update(rows=fo.account_rows(page,request.user,request.get_full_path()),page_obj=page,totals=fo.account_totals(qs))
    return render(request,'financeiro/contas.html',context)


@login_required
@require_safe
def orcamento_financeiro(request):
    if not fq.can_view_financial_panel(request.user):return HttpResponse('Acesso restrito.',status=403)
    context=query_context(request,'orcamento')
    form=context['financial_form']
    if form.is_valid():
        contracts=fo.budget_contracts(form.cleaned_data)
        page=Paginator(contracts,20).get_page(request.GET.get('page'))
        context.update(rows=fo.budget_rows(request.user,form.cleaned_data,page),page_obj=page,data_valid=True)
    return render(request,'financeiro/orcamento.html',context)


@login_required
@require_safe
def planejamento_mensal(request):
    if not fq.can_view_financial_panel(request.user):return HttpResponse('Acesso restrito.',status=403)
    context=query_context(request,'mensal')
    form=context['financial_form']
    if form.is_valid():
        try:projection=fo.monthly_projection(request.user,form.cleaned_data)
        except fo.ProjectionLimit as error:return HttpResponse(str(error),status=400)
        page=Paginator(projection['rows'],20).get_page(request.GET.get('page'))
        context.update(rows=list(page),page_obj=page,breakdown=projection['details'][:50],breakdown_count=len(projection['details']),
            totals=projection['totals'],data_valid=True)
        chart_rows=[row for row in projection['rows'] if row['month']][-36:]
        if chart_rows:
            from plotly import graph_objects as go
            from plotly.offline import plot,get_plotlyjs_version
            figure=go.Figure()
            for metric,label in (('planned','Planejado por Evento/OS'),('paid','Pago líquido efetivo'),('scheduled','Parcelas futuras'),('rescheduled','Parcelas reprogramadas'),('authorized_unpaid','Saldo autorizado sem programação'),('other_unpaid','Demais saldos sem programação')):
                figure.add_bar(name=label,x=[r['month'].strftime('%m/%Y') for r in chart_rows],y=[float(r[metric]) for r in chart_rows])
            figure.update_layout(barmode='group',title='Comparação mensal · até 36 últimos meses dos filtros',yaxis_title='Reais',legend=dict(orientation='h'),height=450)
            context.update(chart=plot(figure,output_type='div',include_plotlyjs=False,config={'responsive':True,'displaylogo':False}),plotly_version=get_plotlyjs_version())
    return render(request,'financeiro/planejamento_mensal.html',context)


@login_required
@require_safe
def relatorio_operacional(request,kind):
    if not fq.can_view_financial_panel(request.user):return HttpResponse('Acesso restrito.',status=403)
    if kind not in {'contas','pagamentos','contratos','mensal'}:return HttpResponse('Relatório inválido.',status=400)
    form=operational_form(request,'orcamento' if kind=='contratos' else 'mensal' if kind=='mensal' else 'contas')
    if not form.is_valid():return HttpResponse('Revise os filtros.',status=400)
    from .financial_exports import export_report
    try:content=export_report(request.user,kind,form)
    except fo.ProjectionLimit as error:return HttpResponse(str(error),status=400)
    response=HttpResponse(content,content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition']=f'attachment; filename="financeiro_{kind}.xlsx"'
    response['Cache-Control']='private, no-store';response['X-Content-Type-Options']='nosniff'
    return response
