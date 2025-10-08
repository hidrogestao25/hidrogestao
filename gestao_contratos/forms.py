from django import forms
from .models import Contrato, Cliente, User, Proposta, EmpresaTerceira, ContratoTerceiros, SolicitacaoProspeccao, PropostaFornecedor, DocumentoContratoTerceiro, DocumentoBM, Evento
from django.contrib import messages
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
import re

class ISODateInput(forms.DateInput):
    input_type = 'date'  # garante que seja um <input type="date">

    def format_value(self, value):
        if value is None:
            return ''
        if isinstance(value, str):
            return ''
        if isinstance(value, (date, datetime)):
            return value.strftime('%Y-%m-%d')
        # Para outros tipos, converte para string
        return str(value)

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
        required=False,
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
        valor = self.cleaned_data.get('valor_total')
        if valor in [None, ""]:
            return None

        # Converte para string e remove "R$"
        valor_str = str(valor).replace("R$", "").strip()


        try:
            return Decimal(valor_str)
        except InvalidOperation:
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
        required=False,
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
        required=False,
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
        fields = ['cod_projeto', 'prospeccao', 'empresa_terceira', 'coordenador', 'data_inicio', 'data_fim', 'valor_total', 'status', 'objeto']
        widgets = {
            'cod_projeto': forms.Select(attrs={'class': 'form-select'}),
            'prospeccao': forms.Select(attrs={'class': 'form-select'}),
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
        self.fields['prospeccao'].queryset = (
            SolicitacaoProspeccao.objects.all().exclude(status='Finalizada')
        )


    def clean_valor_total(self):
        valor = self.cleaned_data.get('valor_total')
        if valor in [None, ""]:
            return None

        # Remove prefixo R$ e espaços
        valor_str = str(valor).replace("R$", "").strip()

        try:
            return Decimal(valor_str)
        except InvalidOperation:
            raise forms.ValidationError(f"{valor_str} Informe um valor válido no formato R$ 0,00.")


class SolicitacaoProspeccaoForm(forms.ModelForm):
    valor_provisionado = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Provisionado",
        required=True
    )
    class Meta:
        model = SolicitacaoProspeccao
        fields = ['contrato', 'descricao', 'requisitos','previsto_no_orcamento', 'valor_provisionado', 'cronograma']
        widgets = {
            'valor_provisionado': forms.TextInput(attrs ={
                'class': 'form-control money',
                'placeholder': 'R$ 0,00'
            })
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['descricao'].label = "Escopo de Contratação"
        self.fields['requisitos'].label = "Requisitos Mínimos"

        if user and user.grupo == 'coordenador':
            self.fields['contrato'].queryset = Contrato.objects.filter(coordenador=user)
        elif user and user.grupo == 'financeiro':
            self.fields['contrato'].queryset = Contrato.objects.all()
        elif user and user.grupo == 'gerente':
            self.fields['contrato'].queryset = Contrato.objects.filter(coordenador__centros__in=user.centros.all())
        else:
            self.fields['contrato'].queryset = Contrato.objects.none()

    def clean_valor_provisionado(self):
        valor = self.cleaned_data.get('valor_provisionado')
        if valor:
            try:
                # Remove pontos de milhar e troca vírgula por ponto
                valor = valor.replace('.', '').replace(',', '.')
                return Decimal(valor)
            except (InvalidOperation, AttributeError):
                raise forms.ValidationError("Informe um valor numérico válido (ex: 1.234,56)")
        return valor



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


class DocumentoBMForm(forms.ModelForm):
    class Meta:
        model = DocumentoBM
        fields = ['minuta_boletim', 'assinatura_fornecedor', 'assinatura_gerente']
        widgets = {
            'minuta_boletim': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }


class EventoPrevisaoForm(forms.ModelForm):
    class Meta:
        model = Evento
        fields = ["descricao", "data_prevista", "valor_previsto", "data_prevista_pagamento"]
        widgets = {
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "valor_previsto": forms.NumberInput(attrs={"class": "form-control"}),
            "data_prevista": ISODateInput(attrs={ "class": "form-control"}),
            "data_prevista_pagamento": ISODateInput(attrs={"class": "form-control"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        data_prevista = cleaned_data.get("data_prevista")
        valor_previsto = cleaned_data.get("valor_previsto")
        data_prevista_pagamento = cleaned_data.get("data_prevista_pagamento")

        # Se a data prevista foi preenchida, mas a de pagamento não
        if data_prevista and valor_previsto and not data_prevista_pagamento:
            self.add_error(
                "data_prevista_pagamento",
                "Informe a Data Prevista para o Pagamento quando o Valor previsto e a Data Prevista de Entrega for preenchida."
            )

        return cleaned_data



class EventoEntregaForm(forms.ModelForm):
    class Meta:
        model = Evento
        fields = ["arquivo", "justificativa", "avaliacao", "data_entrega", "realizado", "com_atraso", "valor_pago", "data_pagamento"]
        widgets = {
            "arquivo": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "justificativa": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "avaliacao": forms.Select(attrs={"class": "form-select"}),
            "data_entrega": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "valor_pago": forms.NumberInput(attrs={"class": "form-control"}),
            "data_pagamento": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }


class FiltroPrevisaoForm(forms.Form):
    data_inicial = forms.DateField(
        label="Data inicial (opcional)",
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )

    data_limite = forms.DateField(
        label="Data limite",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )

    coordenador = forms.ModelChoiceField(
        label="Coordenador (opcional)",
        queryset=User.objects.filter(grupo="coordenador").order_by("username"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )
