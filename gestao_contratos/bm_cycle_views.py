"""Ações explícitas de programação e renovação, integradas ao detalhe existente do BM."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from . import bm_cycles as cycles, models as m
from .permissions import can_view_object, can_access_document, is_internal

LABELS = dict(sem_ciclo='Programação original', inicial='Programação inicial', liquidado='Integralmente pago',
    conferencia='Exige conferência', reprovado='Ciclo reprovado — revisão expressa necessária',
    revisao='Condições alteradas — renovar decisões', sem_gerente='Líder de Contrato responsável ausente ou sem competência',
    gerencia='Aguardando nova aprovação do Líder de Contrato', diretoria='Aguardando nova autorização da Diretoria',
    autorizado='Autorizado no ciclo atual')


def access(user, bm):
    origin = bm.evento or bm.os or bm.contrato
    return is_internal(user) and can_view_object(user, bm) and can_access_document(user, bm) and can_view_object(user, origin)


def info(bm, user, *, history=False):
    if not cycles.enabled() or not access(user, bm):
        return None
    state = cycles.cycle_state(cycles.raw_connection(), bm.pk)
    if state['cycle'] is None:
        state.update(cycles.financial_state(cycles.raw_connection(), bm.pk))
        state.update(manager=cycles.responsible(cycles.raw_connection(), state), decisions={})
    cycle = state['cycle']
    manager = state['manager']
    state.update(label=LABELS[state['stage']], measured=cycles.money(state['measured_cents']),
        billed=cycles.money(state['billed_cents']), paid=cycles.money(state['paid_cents']), balance=cycles.money(state['balance_cents']),
        liquidacao='Integralmente pago' if state['full'] else 'Parcialmente pago' if state['paid_cents']>0 else 'NF cadastrada não paga' if any(not n['cancelada_em'] for n in state['invoices']) else 'Sem NF',
        can_reprogram=user.grupo in {'suprimento','financeiro'} and state['balance_cents']>0,
        can_decide=bool(cycle and ((state['stage']=='gerencia' and manager and manager['id']==user.pk and user.grupo in cycles.RESPONSIBLE_ROLES)
            or (state['stage']=='diretoria' and user.grupo=='diretoria'))),
        stage_to_decide='gerencia' if state['stage']=='gerencia' else 'diretoria',
        can_revise=bool(cycle and user.grupo=='suprimento' and state['balance_cents']>0 and not state['errors']),
        detail_url=reverse('detalhe_bm_financeiro',args=[bm.pk])+'#programacao-bm',
        previous_date=None, scheduled_date=state['reference'])
    if state['can_reprogram']:
        state['reprogramming']=cycles.reprogramming_plan(cycles.raw_connection(),bm.pk,state=state)
    if cycle:
        state['scheduled_date']=cycles.programmed_date(state,cycle)
        if cycle['anterior_id']:
            prior=cycles.row(cycles.raw_connection(),'SELECT data_prevista FROM gestao_contratos_ciclopagamentobm WHERE id=?',(cycle['anterior_id'],))
            state['previous_date']=cycles.previous_programmed_date(cycle,prior)
    from django.utils import timezone
    if state['balance_cents']>0 and not state['errors']:
        if not state['reference']:
            state['pending_reason']='Aguardando a Data de pagamento no cadastro do BM.'
        elif (state.get('scheduled_date') or state['reference']) < timezone.localdate():
            from datetime import timedelta
            floor=max(timezone.localdate(),(state.get('scheduled_date') or state['reference'])+timedelta(days=1),state['not_before'] or state['reference'])
            if not m.CalendarioPagamento.objects.filter(data_pagamento__gte=floor).exists():
                state['pending_reason']='Pagamento pendente — aguardando definição de nova programação no calendário.'
    if history:
        state['history']=list(m.CicloPagamentoBM.objects.filter(bm=bm).select_related('registrado_por','anterior')
            .prefetch_related('decisoes__registrado_por','pagamentos_vinculados__pagamento__estornos').order_by('-numero')[:50])
        for item in state['history']:
            item.pago_liquido=sum((link.pagamento.valor-sum((e.valor for e in link.pagamento.estornos.all()),cycles.money(0))
                                  for link in item.pagamentos_vinculados.all()),cycles.money(0))
    return state


class DecisaoForm(forms.Form):
    acao = forms.ChoiceField(choices=[('aprovar','Aprovar'),('reprovar','Reprovar')],widget=forms.Select(attrs={'class':'form-select'}))
    justificativa = forms.CharField(required=False,max_length=4000,label='Justificativa — obrigatória para reprovar',widget=forms.Textarea(attrs={'class':'form-control','rows':3}))
    versao = forms.CharField(widget=forms.HiddenInput)
    responsavel = forms.IntegerField(widget=forms.HiddenInput)

    def clean(self):
        data=super().clean()
        if data.get('acao')=='reprovar' and not str(data.get('justificativa','')).strip():
            self.add_error('justificativa','Justificativa obrigatória para reprovar o ciclo.')
        return data


class ReprogramarForm(forms.Form):
    motivo=forms.CharField(required=False,max_length=4000,label='Motivo da pendência (opcional)',widget=forms.Textarea(attrs={'class':'form-control','rows':3}))
    cycle_id=forms.IntegerField(min_value=0,widget=forms.HiddenInput)
    version=forms.CharField(widget=forms.HiddenInput)
    balance_cents=forms.IntegerField(min_value=1,widget=forms.HiddenInput)
    calendar_id=forms.IntegerField(min_value=1,widget=forms.HiddenInput)
    next_date=forms.DateField(widget=forms.HiddenInput)


def get_bm(request, bm_id):
    bm=get_object_or_404(m.BM.objects.select_related('contrato','evento__contrato_terceiro','os__contrato'),pk=bm_id)
    if not access(request.user,bm):
        raise Http404
    return bm


@login_required
@require_http_methods(['GET','POST'])
def reprogramar(request,bm_id):
    cycles.operator(request.user)
    if not cycles.enabled():
        return HttpResponse('Reprogramação ainda não ativada neste ambiente.',status=409)
    from .views import approval_return_url
    from django.utils.formats import number_format
    bm=get_bm(request,bm_id)
    current=info(bm,request.user)
    plan=cycles.reprogramming_plan(cycles.raw_connection(),bm.pk,state=current)
    back=approval_return_url(request,reverse('detalhe_bm_financeiro',args=[bm.pk]))
    initial={key:plan[key] for key in ('cycle_id','version','balance_cents','calendar_id','next_date')}
    form=ReprogramarForm(request.POST if request.method=='POST' else None,initial=initial)
    status=200 if plan['available'] else 409
    if request.method=='POST':
        if form.is_valid():
            data=form.cleaned_data
            try:
                result=cycles.process_bm(bm.pk,request.user,reason=data['motivo'],reprogram_only=True,
                    expected={key:data[key] for key in initial})
                created=m.CicloPagamentoBM.objects.get(pk=result['created'][-1])
                amount=number_format(created.saldo_inclusao,decimal_pos=2,force_grouping=True)
                messages.success(request,f'BM {bm.numero_bm} reprogramado para {created.data_prevista:%d/%m/%Y}. Saldo: R$ {amount}. Nova aprovação do Líder de Contrato e da Diretoria necessária.')
                return HttpResponseRedirect(back)
            except ValidationError as error:
                form.add_error(None,' '.join(error.messages));status=409
            except (IntegrityError,OperationalError):
                form.add_error(None,'Não foi possível confirmar. Atualize e confira a programação antes de repetir.');status=409
        else:
            status=400
    return render(request,'financeiro/reprogramar_bm.html',dict(bm=bm,ciclo=current,plan=plan,form=form,back=back),status=status)


@login_required
@require_http_methods(['GET','POST'])
def decidir(request, ciclo_id, etapa):
    cycle=get_object_or_404(m.CicloPagamentoBM,bm__isnull=False,pk=ciclo_id) if cycles.enabled() else None
    if cycle is None:
        return HttpResponse('Reprogramação ainda não ativada neste ambiente.',status=409)
    bm=get_bm(request,cycle.bm_id)
    current=info(bm,request.user,history=True)
    if (etapa=='gerencia' and (not current['manager'] or current['manager']['id']!=request.user.pk or request.user.grupo not in cycles.RESPONSIBLE_ROLES)) or (etapa=='diretoria' and request.user.grupo!='diretoria'):
        return HttpResponse('Sem competência para decidir este ciclo.',status=403)
    if etapa not in {'gerencia','diretoria'} or current['cycle']['id']!=cycle.pk:
        return HttpResponse('Etapa ou ciclo superado.',status=409)
    form=DecisaoForm(request.POST or None,initial={'versao':current['version'],'responsavel':current['manager']['id'] if current['manager'] else None})
    status=200
    if request.method=='POST':
        if form.is_valid():
            data=form.cleaned_data
            try:
                cycles.decide(cycle.pk,request.user,etapa,data['acao']=='aprovar',data.get('justificativa',''),expected_version=data['versao'],expected_responsible=data['responsavel'])
                return redirect('detalhe_bm_financeiro',bm_id=bm.pk)
            except ValidationError as error:
                form.add_error(None,' '.join(error.messages));status=409
            except (IntegrityError,OperationalError):
                form.add_error(None,'Não foi possível confirmar. Atualize e confira o ciclo antes de repetir.');status=409
        else:
            status=400
    return render(request,'financeiro/decidir_ciclo_bm.html',dict(bm=bm,ciclo=current,form=form,etapa=etapa),status=status)


@login_required
@require_POST
def processar(request, bm_id=None):
    """Compatibilidade de URLs antigas: nenhum cadastro em lote pela interface."""
    cycles.operator(request.user)
    if bm_id:
        get_bm(request,bm_id)
        return redirect('reprogramar_bm',bm_id=bm_id)
    messages.info(request,'Escolha Reprogramar BM na linha do boletim que deseja reapresentar.')
    from urllib.parse import urlencode
    return HttpResponseRedirect(reverse('previsao_pagamentos')+'?'+urlencode(request.GET))


@login_required
@require_POST
def revisar(request,ciclo_id):
    cycles.operator(request.user,True)
    if not cycles.enabled():
        return HttpResponse('Reprogramação ainda não ativada neste ambiente.',status=409)
    cycle=get_object_or_404(m.CicloPagamentoBM,pk=ciclo_id)
    get_bm(request,cycle.bm_id)
    try:
        cycles.revise(cycle.pk,request.user,request.POST.get('justificativa',''))
    except ValidationError as error:
        return HttpResponse(' '.join(error.messages),status=409)
    except (IntegrityError,OperationalError):
        return HttpResponse('O ciclo foi alterado ou está em uso. Atualize antes de repetir.',status=409)
    return redirect('detalhe_bm_financeiro',bm_id=cycle.bm_id)
