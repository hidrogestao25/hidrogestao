import uuid
from django import forms
from .forms import parse_decimal_from_form_value
from .validation import validate_upload
from .payment_queries import active_schedules


class ActionForm(forms.Form):
    key=forms.CharField(widget=forms.HiddenInput,max_length=128)
    def __init__(self,*args,nf,**kwargs):
        self.nf=nf
        super().__init__(*args,**kwargs)
        if not self.is_bound:self.initial['key']=str(uuid.uuid4())
        for field in self.fields.values():
            field.widget.attrs['class']='form-select' if isinstance(field.widget,forms.Select) else 'form-control'
    def clean_valor(self):return parse_decimal_from_form_value(self.cleaned_data.get('valor'))


class PaymentForm(ActionForm):
    valor=forms.CharField(label='Valor do novo pagamento',max_length=20)
    data_pagamento=forms.DateField(label='Data efetiva declarada',widget=forms.DateInput(attrs={'type':'date'}))
    programacao=forms.ModelChoiceField(label='Vínculo explícito com parcela (opcional)',queryset=active_schedules().none(),required=False)
    comprovante=forms.FileField(label='Comprovante do movimento (opcional)',required=False,validators=[validate_upload])
    observacao=forms.CharField(label='Observação',required=False,max_length=4000,widget=forms.Textarea(attrs={'rows':2}))
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['programacao'].queryset=active_schedules(self.nf).filter(restante_centavos__gt=0)
        self.fields['programacao'].label_from_instance=lambda p:f'#{p.pk} · {p.data_prevista:%d/%m/%Y} · R$ {p.valor_previsto}'


class ReversalForm(ActionForm):
    valor=forms.CharField(label='Valor do estorno',max_length=20)
    data_estorno=forms.DateField(label='Data efetiva declarada do estorno',widget=forms.DateInput(attrs={'type':'date'}))
    motivo=forms.CharField(label='Justificativa obrigatória',max_length=4000,widget=forms.Textarea(attrs={'rows':3}))


class ScheduleForm(ActionForm):
    valor=forms.CharField(label='Valor total da parcela programada',max_length=20)
    data_prevista=forms.DateField(label='Data prevista',widget=forms.DateInput(attrs={'type':'date'}))
    motivo=forms.CharField(label='Justificativa',max_length=4000,widget=forms.Textarea(attrs={'rows':2}))
    observacao=forms.CharField(label='Observação',required=False,max_length=4000,widget=forms.Textarea(attrs={'rows':2}))
    substitui=forms.ModelChoiceField(label='Revisar parcela existente (opcional)',queryset=active_schedules().none(),required=False)
    cancelada=forms.BooleanField(label='Cancelar a parcela futura indicada (preserva histórico)',required=False)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['substitui'].queryset=active_schedules(self.nf)


class AgreementForm(ActionForm):
    novo_vencimento=forms.DateField(label='Novo vencimento já acordado',widget=forms.DateInput(attrs={'type':'date'}))
    motivo=forms.CharField(label='Motivo do acordo',max_length=4000,widget=forms.Textarea(attrs={'rows':2}))
    programacao=forms.ModelChoiceField(label='Somente esta parcela (vazio = saldo inteiro)',queryset=active_schedules().none(),required=False)
    responsavel_acordo=forms.CharField(label='Responsável pelo acordo, quando conhecido',max_length=255,required=False)
    documento=forms.FileField(label='Documento do acordo (opcional)',required=False,validators=[validate_upload])
    observacao=forms.CharField(label='Observação',max_length=4000,required=False,widget=forms.Textarea(attrs={'rows':2}))
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['programacao'].queryset=active_schedules(self.nf).filter(restante_centavos__gt=0)
