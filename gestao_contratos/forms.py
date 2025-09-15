from django import forms
from .models import Contrato, Cliente, User, Proposta, EmpresaTerceira, ContratoTerceiros, SolicitacaoProspeccao, PropostaFornecedor, DocumentoContratoTerceiro

from decimal import Decimal, InvalidOperation
import re


class PropostaFornecedorForm(forms.ModelForm):
    class Meta:
        model = PropostaFornecedor
        fields = ["valor_proposta", "arquivo_proposta", "condicao_pagamento"]
        widgets = {
            'condicao_pagamento': forms.Select(attrs={'class': 'form-select'}),
            }


class ContratoForm(forms.ModelForm):
    data_inicio = forms.DateField(
        widget=forms.DateInput(
            attrs={
                'class': 'form-control datepicker',
                'type': 'text',
                'autocomplete': 'off'
            }
        ),
        input_formats=['%d-%m-%Y']
    )

    data_fim = forms.DateField(
        widget=forms.DateInput(
            attrs={
                'class': 'form-control datepicker',
                'type': 'text',
                'autocomplete': 'off'
            }
        ),
        input_formats=['%d-%m-%Y']
    )

    class Meta:
        model = Contrato
        fields = ['cod_projeto', 'cliente', 'coordenador', 'data_inicio', 'data_fim', 'valor_total', 'status', 'objeto', 'proposta']
        widgets = {
            'cod_projeto': forms.TextInput(attrs={'class': 'form-control'}),
            'proposta': forms.Select(attrs={'class': 'form-select'}),
            'cliente': forms.Select(attrs={'class': 'form-select'}),
            'coordenador': forms.Select(attrs={'class': 'form-select'}),
            'valor_total': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_valor_total'}),
            'objeto':  forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtra apenas usuários que estão no grupo "Coordenador de Contrato"
        self.fields['coordenador'].queryset = (
            User.objects.filter(grupo='coordenador', is_active=True)
        )
        self.fields['proposta'].queryset = (
            Proposta.objects.all()
        )

    def clean_valor_total(self):
        valor = self.cleaned_data['valor_total']
        try:
            return Decimal(valor)
        except:
            raise forms.ValidationError("Informe um valor válido no formato R$ 0,00.")


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = '__all__'
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'cpf_cnpj': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_cpf_cnpj'}),
            'endereco': forms.Textarea(attrs={'class': 'form-control', 'row': 3}),
            'telefone': forms.TextInput(attrs={'class': 'form-control'}),
            'email':  forms.TextInput(attrs={'class': 'form-control'}),
        }


class FornecedorForm(forms.ModelForm):
    class Meta:
        model = EmpresaTerceira
        fields = '__all__'
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'cpf_cnpj': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_cpf_cnpj'}),
            'endereco': forms.Textarea(attrs={'class': 'form-control', 'row': 3}),
            'telefone': forms.TextInput(attrs={'class': 'form-control'}),
            'email':  forms.TextInput(attrs={'class': 'form-control'}),
            'informacoes_bancarias':  forms.TextInput(attrs={'class': 'form-control'}),
            'setor_de_atuacao': forms.TextInput(attrs={'class': 'form-control'}),
            'ponto_focal': forms.TextInput(attrs={'class': 'form-control'}),
            'email_focal':  forms.TextInput(attrs={'class': 'form-control'}),
            'telefone_focal': forms.TextInput(attrs={'class': 'form-control'}),
        }


class ContratoFornecedorForm(forms.ModelForm):
    data_inicio = forms.DateField(
        widget=forms.DateInput(
            attrs={
                'class': 'form-control datepicker',
                'type': 'text',
                'autocomplete': 'off'
            }
        ),
        input_formats=['%d-%m-%Y']
    )

    data_fim = forms.DateField(
        widget=forms.DateInput(
            attrs={
                'class': 'form-control datepicker',
                'type': 'text',
                'autocomplete': 'off'
            }
        ),
        input_formats=['%d-%m-%Y']
    )

    class Meta:
        model = ContratoTerceiros
        fields = ['cod_projeto', 'empresa_terceira', 'coordenador', 'data_inicio', 'data_fim', 'valor_total', 'status', 'objeto', 'proposta']
        widgets = {
            'cod_projeto': forms.Select(attrs={'class': 'form-select'}),
            'proposta': forms.Select(attrs={'class': 'form-select'}),
            'empresa_terceira': forms.Select(attrs={'class': 'form-select'}),
            'coordenador': forms.Select(attrs={'class': 'form-select'}),
            'valor_total': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_valor_total'}),
            'objeto':  forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtra apenas usuários que estão no grupo "Coordenador de Contrato"
        self.fields['coordenador'].queryset = (
            User.objects.filter(grupo='coordenador', is_active=True)
        )
        self.fields['proposta'].queryset = (
            Proposta.objects.all()
        )

    def clean_valor_total(self):
        valor = self.cleaned_data['valor_total']
        try:
            return Decimal(valor)
        except:
            raise forms.ValidationError("Informe um valor válido no formato R$ 0,00.")


class SolicitacaoProspeccaoForm(forms.ModelForm):
    class Meta:
        model = SolicitacaoProspeccao
        fields = ['contrato', 'descricao', 'previsto_no_orcamento', 'valor_provisionado']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user and user.grupo == 'coordenador':
            self.fields['contrato'].queryset = Contrato.objects.filter(coordenador=user)
        elif user and user.grupo == 'financeiro':
            self.fields['contrato'].queryset = Contrato.objects.all()
        else:
            self.fields['contrato'].queryset = Contrato.objects.none()



class DocumentoContratoTerceiroForm(forms.ModelForm):
    valor_total = forms.CharField(required=True)  # força como texto primeiro

    class Meta:
        model = DocumentoContratoTerceiro
        fields = ["numero_contrato", "objeto", "prazo_inicio", "prazo_fim", "valor_total", "arquivo_contrato"]

    def clean_valor_total(self):
        valor = self.cleaned_data.get("valor_total")

        if valor:
            # remove pontos de milhar e troca vírgula por ponto
            valor = valor.replace(".", "").replace(",", ".")
            try:
                return Decimal(valor)
            except InvalidOperation:
                raise forms.ValidationError("Informe um valor válido no formato 1.234,56")
        return None
