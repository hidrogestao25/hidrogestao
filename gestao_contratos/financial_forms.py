"""Filtros das consultas operacionais, sem novos campos de obrigação/pagamento."""
from django import forms
from .forms import FiltroFinanceiroForm
from . import models as m


class OperationalFilterForm(FiltroFinanceiroForm):
    numero_nf=forms.CharField(label='Número da NF',required=False,max_length=64)
    pesquisa=forms.CharField(label='Pesquisar fornecedor, NF, contrato ou projeto',required=False,max_length=120)
    situacao=forms.ChoiceField(label='Situação financeira',required=False,choices=[
        ('','Todas'),('aguardando','Aguardando autorização'),('autorizada','Autorizada para pagamento'),
        ('paga','Paga'),('conferencia','Exige conferência')])
    centro=forms.ModelChoiceField(label='Centro de trabalho do líder técnico',required=False,
        queryset=m.CentroDeTrabalho.objects.order_by('codigo','pk'))
    liquidacao=forms.ChoiceField(label='Liquidação',required=False,choices=[('','Todas'),('nao_paga','Não paga'),('parcial','Parcialmente paga'),('integral','Integralmente paga')])
    vencimento=forms.ChoiceField(label='Vencimento',required=False,choices=[('','Todos'),('vencida','Vencida'),('a_vencer','A vencer'),('desconhecido','Vencimento não informado')])
    reprogramada=forms.BooleanField(label='Somente reprogramadas',required=False)
    nf_id=forms.IntegerField(label='ID preciso da NF',required=False,min_value=1,max_value=9223372036854775807,widget=forms.HiddenInput)
    tipo_movimento=forms.ChoiceField(label='Tipo de movimento (relatório de pagamentos)',required=False,choices=[('','Pagamentos e estornos'),('pagamento','Pagamento'),('estorno','Estorno')])

    def __init__(self,*args,mode='contas',**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['coordenador'].label='Líder Técnico (opcional)'
        if mode in {'orcamento','mensal'}:
            for key in ('numero_nf','pesquisa','situacao','pagamento','autorizacao','numero_bm','bm_id','liquidacao','vencimento','reprogramada','nf_id','tipo_movimento'):
                self.fields.pop(key,None)
        for field in self.fields.values():
            if not isinstance(field.widget,forms.HiddenInput):
                field.widget.attrs['class']='form-check-input' if isinstance(field,forms.BooleanField) else 'form-select' if isinstance(field.widget,forms.Select) else 'form-control'


def operational_form(request,mode='contas'):
    params=request.GET.copy()
    if not any(params.get(k) for k in ('data_inicial','data_limite','historico')):
        params['historico']='on'
    return OperationalFilterForm(params,user=request.user,mode=mode)
