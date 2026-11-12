from django import forms
from django.db.models import Q
from .models import Contrato, Cliente, User, Proposta, EmpresaTerceira, ContratoTerceiros, SolicitacaoProspeccao, PropostaFornecedor, DocumentoContratoTerceiro, DocumentoBM, Evento, BM, NF, NFCliente, SolicitacaoOrdemServico, OS, SolicitacaoContrato, AditivoContratoTerceiro
from django.contrib import messages
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
import re
from .permissions import (can_change_nf, payment_registration_error,
                          bm_has_valid_operational_approval, PAID_NF_READ_ONLY_MESSAGE)

def format_decimal_for_br_input(value):
    if value in [None, ""]:
        return ""
    if not isinstance(value, Decimal):
        try:
            value = Decimal(value)
        except (InvalidOperation, TypeError, ValueError):
            return str(value)
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def parse_decimal_from_form_value(value, empty_value=None):
    if value in [None, ""]:
        return empty_value
    if isinstance(value, Decimal):
        return value

    valor = str(value).strip().replace("R$", "").replace(" ", "")
    if not valor:
        return empty_value

    if "," in valor:
        valor = valor.replace(".", "").replace(",", ".")

    try:
        number = Decimal(valor)
        if not number.is_finite():
            raise InvalidOperation
        return number
    except InvalidOperation:
        raise forms.ValidationError("Informe um valor válido no formato 1.234,56")


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

    valor_total = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': '0,00'
        })
    )

    valor_vendido = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Vendido ao Cliente",
        required=False
    )
    class Meta:
        model = Contrato
        fields = ['observacao', 'cod_projeto', 'cliente', 'coordenador', 'coordenadores', 'data_inicio', 'data_fim', 'valor_total', 'status', 'objeto', 'proposta', 'lider_contrato']
        widgets = {
            'cod_projeto': forms.TextInput(attrs={'class': 'form-control'}),
            'proposta': forms.Select(attrs={'class': 'form-select'}),
            'cliente': forms.Select(attrs={'class': 'form-select'}),
            'coordenador': forms.Select(attrs={'class': 'form-select'}),
            'coordenadores': forms.SelectMultiple(attrs={'class': 'form-select'}),
            'lider_contrato': forms.Select(attrs={'class': 'form-select'}),
            #'valor_total': forms.TextInput(attrs={'class': 'form-control money', 'placeholder': '0,00'}),
            'objeto':  forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'observacao':  forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtra apenas usuários que estão no grupo "Coordenador de Contrato"
        self.fields['coordenador'].queryset = (
            User.objects.filter(grupo='coordenador', is_active=True)
        )
        self.fields['coordenadores'].queryset = (
            User.objects.filter(grupo='coordenador', is_active=True)
        )
        self.fields['coordenadores'].required = False
        self.fields['lider_contrato'].queryset = (
            User.objects.filter(grupo__in=['lider_contrato', 'gerente_contrato', 'gerente_lider'], is_active=True)
        )
        self.fields['proposta'].queryset = (
            Proposta.objects.all()
        )
        if self.instance and self.instance.valor_total:
            valor = self.instance.valor_total
            self.initial['valor_total'] = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def clean_valor_total(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_total"), empty_value=None)


class ContratoModalForm(forms.ModelForm):
    class Meta:
        model = Contrato
        fields = ['cod_projeto', 'cliente', 'objeto']


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ['nome', 'razao_social', 'cpf_cnpj', 'endereco', 'complemento', 'telefone', 'email', 'ponto_focal', 'email_focal', 'telefone_focal', 'observacao']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'razao_social': forms.TextInput(attrs={'class': 'form-control'}),
            'cpf_cnpj': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_cpf_cnpj'}),
            'endereco': forms.Textarea(attrs={'class': 'form-control', 'row': 3}),
            'complemento': forms.TextInput(attrs={'class': 'form-control'}),
            'telefone': forms.TextInput(attrs={'class': 'form-control'}),
            'email':  forms.TextInput(attrs={'class': 'form-control'}),
            'ponto_focal':  forms.TextInput(attrs={'class': 'form-control'}),
            'email_focal':  forms.TextInput(attrs={'class': 'form-control'}),
            'telefone_focal':  forms.TextInput(attrs={'class': 'form-control'}),
            'observacao': forms.Textarea(attrs={'class': 'form-control', 'row': 3}),
        }


class FornecedorForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["informacoes_bancarias"].help_text = (
            "A conta bancária do fornecedor deve estar atrelada ao CNPJ."
        )

    valor_vendido = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Vendido ao Cliente",
        required=False
    )
    class Meta:
        model = EmpresaTerceira
        fields = ['nome', 'setor_de_atuacao', 'cpf_cnpj', 'endereco', 'complemento', 'numero', 'bairro', 'municipio', 'estado', 'cep', 'telefone', 'email', 'informacoes_bancarias', 'guarda_chuva', 'ponto_focal', 'email_focal', 'telefone_focal', 'ponto_focal2', 'email_focal2', 'telefone_focal2', 'observacao']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'cpf_cnpj': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_cpf_cnpj'}),
            'endereco': forms.TextInput(attrs={'class': 'form-control'}),
            'complemento': forms.TextInput(attrs={'class': 'form-control'}),
            'numero': forms.TextInput(attrs={'class': 'form-control'}),
            'bairro': forms.TextInput(attrs={'class': 'form-control'}),
            'municipio': forms.TextInput(attrs={'class': 'form-control'}),
            'estado': forms.TextInput(attrs={'class': 'form-control'}),
            'cep': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_cep'}),
            'telefone': forms.TextInput(attrs={'class': 'form-control'}),
            'email':  forms.TextInput(attrs={'class': 'form-control'}),
            'informacoes_bancarias':  forms.Textarea(attrs={'class': 'form-control', 'row': 3}),
            'setor_de_atuacao': forms.TextInput(attrs={'class': 'form-control'}),
            'ponto_focal': forms.TextInput(attrs={'class': 'form-control'}),
            'email_focal':  forms.TextInput(attrs={'class': 'form-control'}),
            'telefone_focal': forms.TextInput(attrs={'class': 'form-control'}),
            'ponto_focal2': forms.TextInput(attrs={'class': 'form-control'}),
            'email_focal2':  forms.TextInput(attrs={'class': 'form-control'}),
            'telefone_focal2': forms.TextInput(attrs={'class': 'form-control'}),
            'observacao': forms.Textarea(attrs={'class': 'form-control', 'row': 3}),
        }


class DadosBancariosFornecedorForm(forms.ModelForm):
    class Meta:
        model = EmpresaTerceira
        fields = ["informacoes_bancarias"]
        labels = {"informacoes_bancarias": "Informações bancárias"}
        widgets = {"informacoes_bancarias": forms.Textarea(attrs={"class": "form-control", "rows": 3})}


class ContratoFornecedorForm(forms.ModelForm):
    preserve_lider_contrato_for_guarda_chuva = False

    valor_total = forms.CharField(required=False, widget=forms.TextInput(
        attrs={'class': 'form-control', 'id': 'id_valor_total'}))

    data_inicio = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                'class': 'form-control datepicker',
                'type': 'text',
                'autocomplete': 'off'
            }
        ),
        input_formats=['%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y']
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
        input_formats=['%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y']
    )

    class Meta:
        model = ContratoTerceiros
        fields = [
            'lider_contrato','condicao_pagamento',
            'num_contrato_arquivo',
            'num_contrato',
            'observacao',
            'cod_projeto',
            'prospeccao',
            'empresa_terceira',
            'coordenador',
            'coordenadores',
            'data_inicio',
            'data_fim',
            'valor_total',
            'status',
            'objeto',
            'guarda_chuva',
            ]

        widgets = {
            'cod_projeto': forms.Select(attrs={'class': 'form-select'}),
            'num_contrato': forms.TextInput(attrs={'class': 'form-control'}),
            'prospeccao': forms.Select(attrs={'class': 'form-select'}),
            'empresa_terceira': forms.Select(attrs={'class': 'form-select'}),
            'coordenador': forms.Select(attrs={'class': 'form-select'}),
            'coordenadores': forms.SelectMultiple(attrs={'class': 'form-select'}),
            'lider_contrato': forms.Select(attrs={'class': 'form-select'}),
            'valor_total': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_valor_total'}),
            'objeto':  forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'observacao':  forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'num_contrato_arquivo': forms.ClearableFileInput(attrs={"class": "form-control"}),
            'condicao_pagamento': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtra apenas usuários que estão no grupo "Coordenador de Contrato"
        self.fields['coordenador'].queryset = (
            User.objects.filter(grupo__in=['coordenador', 'gerente', 'gerente_lider'], is_active=True)
        )
        self.fields['coordenadores'].queryset = (
            User.objects.filter(grupo='coordenador', is_active=True)
        )
        self.fields['coordenadores'].required = False
        self.fields['coordenador'].required = False
        self.fields['lider_contrato'].required = False
        self.fields['lider_contrato'].queryset = (
            User.objects.filter(grupo__in=['lider_contrato','gerente_contrato', 'gerente_lider'], is_active=True)
        )
        self.fields['prospeccao'].queryset = (
            SolicitacaoProspeccao.objects.operacionais().exclude(status='Finalizada')
        )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("guarda_chuva"):
            cleaned_data["coordenador"] = None
            if not self.preserve_lider_contrato_for_guarda_chuva:
                cleaned_data["lider_contrato"] = None
            cleaned_data["coordenadores"] = User.objects.none()
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.preserve_lider_contrato_for_guarda_chuva:
            instance._preserve_lider_contrato_for_guarda_chuva = True
        if commit:
            instance.save()
            self.save_m2m()
        return instance


    def clean_valor_total(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_total"), empty_value=None)


class SolicitacaoContratoForm(forms.ModelForm):
    """valor_provisionado = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Provisionado",
        required=True
    )"""
    valor_disponivel = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Disponível",
        required=False
    )
    valor_vendido = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Vendido ao Cliente",
        required=False
    )
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
        model = SolicitacaoContrato
        fields = [
            'fornecedor_escolhido',
            'contrato',
            'coordenador',
            'descricao',
            'previsto_no_orcamento',
            'justificativa_fornecedor_escolhido',
            'valor_disponivel',
            'valor_vendido',
            'requisitos',
            'data_inicio',
            'data_fim',
            'cronograma',
            'proposta_tecnica',
            'forma_pagamento',
            'justificativa_orcamento',
        ]

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['descricao'].label = "Objeto de contrato"
        self.fields['requisitos'].label = "Observações da Contratação"
        self.fields['previsto_no_orcamento'].label = "Previsto no Planejamento"
        self.fields['justificativa_orcamento'].label = "Justificativa para a contratação dos serviços (sem planejamento)"
        self.fields['proposta_tecnica'].label = "Propostas Técnicas"
        self.fields['proposta_tecnica'].widget.attrs.update({"class": "form-control"})

        if user and user.grupo == 'coordenador':
            self.fields['contrato'].queryset = Contrato.objects.filter(coordenador=user)
        elif user and user.grupo in ['gerente']:
            self.fields['contrato'].queryset = Contrato.objects.filter(
                coordenador__centros__in=user.centros.all()
            )
        elif user and user.grupo in ['gerente_lider']:
            self.fields['contrato'].queryset = Contrato.objects.filter(
                Q(coordenador__centros__in=user.centros.all()) |
                Q(lider_contrato=user)
            ).distinct()
        elif user and user.grupo in ['gerente_contrato', 'lider_contrato', 'suprimento']:
            self.fields['contrato'].queryset = Contrato.objects.all()
        else:
            self.fields['contrato'].queryset = Contrato.objects.none()

        self.fields['coordenador'].queryset = User.objects.filter(
            grupo__in=['coordenador', 'gerente', 'gerente_lider'],
            is_active=True
        )

        self.fields['fornecedor_escolhido'].queryset = EmpresaTerceira.objects.all().order_by('nome')

    def clean_valor_disponivel(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_disponivel"), empty_value=Decimal("0.00"))

    def clean_valor_vendido(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_vendido"), empty_value=None)


class SolicitacaoProspeccaoForm(forms.ModelForm):
    """valor_provisionado = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Provisionado",
        required=False
    )"""
    valor_disponivel = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Disponível",
        required=False
    )
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
    valor_vendido = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Vendido ao Cliente",
        required=False
    )
    class Meta:
        model = SolicitacaoProspeccao
        fields = [
                    'justificativa_orcamento',
                    'forma_pagamento',
                    'valor_disponivel',
                    'valor_vendido',
                    'contrato',
                    'coordenador',
                    'descricao',
                    'requisitos',
                    'previsto_no_orcamento',
                    'cronograma',
                    'justificativa_fornecedor_escolhido',
                    'data_inicio',
                    'data_fim',
                    ]

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['descricao'].label = "Escopo de Contratação"
        self.fields['requisitos'].label = "Requisitos Mínimos"
        self.fields['previsto_no_orcamento'].label = "Previsto no Planejamento"

        if user and user.grupo == 'coordenador':
            self.fields['contrato'].queryset = Contrato.objects.filter(coordenador=user)
        #elif user and user.grupo == 'financeiro':
        #    self.fields['contrato'].queryset = Contrato.objects.all()
        elif user and user.grupo in ['gerente_lider']:
            self.fields['contrato'].queryset = Contrato.objects.filter(
                Q(coordenador__centros__in=user.centros.all()) |
                Q(lider_contrato=user)
            ).distinct()
        elif user and user.grupo in ['lider_contrato', 'gerente_contrato']:
            # A view permite solicitar, mas o formulário antes oferecia zero
            # projetos para estes perfis, inclusive para o líder responsável.
            self.fields['contrato'].queryset = Contrato.objects.filter(lider_contrato=user)
        else:
            self.fields['contrato'].queryset = Contrato.objects.none()
        self.fields['coordenador'].queryset = User.objects.filter(grupo__in=['coordenador','gerente', 'gerente_lider'], is_active=True)

    def clean_valor_disponivel(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_disponivel"), empty_value=Decimal("0.00"))

    """def clean_valor_vendido(self):
        valor = self.cleaned_data.get('valor_vendido')

        if valor:
            try:
                valor = valor.replace('.', '').replace(',', '.')
                return Decimal(valor)
            except (InvalidOperation, AttributeError):
                raise forms.ValidationError(
                    "Informe um valor numérico válido (ex: 1.234,56)"
                )

        return None"""


    def clean_valor_vendido(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_vendido"), empty_value=None)


class SolicitacaoGuardaChuvaForm(forms.ModelForm):
    valor_disponivel = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Disponível",
        required=False
    )
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
    valor_vendido = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Vendido ao Cliente",
        required=False
    )

    class Meta:
        model = SolicitacaoContrato
        fields = [
            'fornecedor_escolhido',
            'coordenador',
            'descricao',
            'previsto_no_orcamento',
            'justificativa_fornecedor_escolhido',
            'valor_disponivel',
            'valor_vendido',
            'requisitos',
            'data_inicio',
            'data_fim',
            'cronograma',
            'proposta_tecnica',
            'forma_pagamento',
            'justificativa_orcamento',
        ]

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['descricao'].label = "Escopo de Contratação"
        self.fields['requisitos'].label = "Observações da Contratação"
        self.fields['previsto_no_orcamento'].label = "Previsto no Planejamento"
        self.fields['proposta_tecnica'].label = "Propostas Técnicas"
        self.fields['proposta_tecnica'].widget.attrs.update({"class": "form-control"})

        self.fields['fornecedor_escolhido'].queryset = EmpresaTerceira.objects.all().order_by('nome')

    def clean_valor_disponivel(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_disponivel"), empty_value=Decimal("0.00"))

    def clean_valor_vendido(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_vendido"), empty_value=None)


class SolicitacaoOrdemServicoForm(forms.ModelForm):
    valor_previsto = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Previsto",
        required=True
    )
    contrato = forms.ModelChoiceField(
        queryset=ContratoTerceiros.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = SolicitacaoOrdemServico
        fields = [
            'contrato',
            'cod_projeto',
            'titulo',
            'descricao',
            'valor_previsto',
            'data_prevista_pagamento',
            'prazo_execucao',
        ]
        widgets = {
            "data_prevista_pagamento": ISODateInput(attrs={"class": "form-control"}),
            "prazo_execucao": ISODateInput(attrs={ "class": "form-control"}),
            'descricao': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        include_contrato = kwargs.pop('include_contrato', False)
        contrato_fixo = kwargs.pop('contrato_fixo', None)
        super().__init__(*args, **kwargs)

        self.fields['cod_projeto'].queryset = Contrato.objects.none()
        self.fields['contrato'].queryset = ContratoTerceiros.objects.none()

        if user and user.grupo == 'lider_contrato':
            contratos_terceiros = ContratoTerceiros.objects.filter(
                guarda_chuva=True,
                cod_projeto__lider_contrato=user,
            ).distinct()
            self.fields['cod_projeto'].queryset = Contrato.objects.filter(
                lider_contrato=user
            ).distinct()
        elif user and user.grupo == 'gerente_contrato':
            contratos_terceiros = ContratoTerceiros.objects.filter(
                guarda_chuva=True,
            ).distinct()
            self.fields['cod_projeto'].queryset = Contrato.objects.all().distinct()
        elif user and user.grupo == 'gerente_lider':
            contratos_terceiros = ContratoTerceiros.objects.filter(
                guarda_chuva=True,
            ).filter(
                Q(cod_projeto__coordenador__centros__in=user.centros.all())
                | Q(cod_projeto__coordenadores__centros__in=user.centros.all())
            ).distinct()
            self.fields['cod_projeto'].queryset = Contrato.objects.filter(
                Q(coordenador__centros__in=user.centros.all())
                | Q(coordenadores__centros__in=user.centros.all())
            ).distinct()
        else:
            contratos_terceiros = ContratoTerceiros.objects.none()

        self.fields['cod_projeto'].widget.attrs.update({'style': 'width:250px;'})
        self.fields['contrato'].queryset = contratos_terceiros

        if include_contrato:
            self.fields['contrato'].required = True
        else:
            self.fields.pop('contrato')

        if contrato_fixo:
            self.initial['contrato'] = contrato_fixo

    def clean_valor_previsto(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_previsto"), empty_value=None)

    def save(self, commit=True):
        instance = super().save(commit=False)
        contrato = self.cleaned_data.get("contrato") or getattr(instance, "contrato", None)
        cod_projeto = self.cleaned_data.get("cod_projeto") or getattr(instance, "cod_projeto", None)

        if contrato is not None:
            instance.contrato = contrato

        if cod_projeto is not None:
            instance.coordenador = cod_projeto.coordenador
        elif contrato is not None and contrato.cod_projeto_id:
            instance.coordenador = contrato.cod_projeto.coordenador

        if commit:
            instance.save()
            self.save_m2m()
        return instance


class UploadContratoOSForm(forms.ModelForm):
    class Meta:
        model = SolicitacaoOrdemServico
        fields = ['arquivo_os']


class SolicitacaoOrdemServicoSemContratoForm(forms.ModelForm):
    valor_previsto = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Previsto",
        required=True
    )
    contrato = forms.ModelChoiceField(
        queryset=ContratoTerceiros.objects.none(),
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Contrato",
    )

    class Meta:
        model = SolicitacaoOrdemServico
        fields = [
            'contrato',
            'cod_projeto',
            'titulo',
            'descricao',
            'valor_previsto',
            'data_prevista_pagamento',
            'prazo_execucao',
        ]
        widgets = {
            'cod_projeto': forms.Select(attrs={'class': 'form-select'}),
            'titulo': forms.TextInput(attrs={'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'data_prevista_pagamento': ISODateInput(attrs={'class': 'form-control'}),
            'prazo_execucao': ISODateInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['cod_projeto'].queryset = Contrato.objects.none()
        self.fields['contrato'].queryset = ContratoTerceiros.objects.none()

        if user and user.grupo == 'lider_contrato':
            self.fields['contrato'].queryset = ContratoTerceiros.objects.filter(
                guarda_chuva=True,
            ).distinct()
            self.fields['cod_projeto'].queryset = Contrato.objects.filter(
                lider_contrato=user
            ).distinct()
        elif user and user.grupo == 'gerente_contrato':
            self.fields['contrato'].queryset = ContratoTerceiros.objects.filter(
                guarda_chuva=True,
            ).distinct()
            self.fields['cod_projeto'].queryset = Contrato.objects.all().distinct()
        elif user and user.grupo == 'gerente_lider':
            self.fields['contrato'].queryset = ContratoTerceiros.objects.filter(
                guarda_chuva=True,
            ).filter(
                Q(cod_projeto__coordenador__centros__in=user.centros.all())
                | Q(cod_projeto__coordenadores__centros__in=user.centros.all())
            ).distinct()
            self.fields['cod_projeto'].queryset = Contrato.objects.filter(
                Q(coordenador__centros__in=user.centros.all())
                | Q(coordenadores__centros__in=user.centros.all())
            ).distinct()

    def clean_valor_previsto(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_previsto"), empty_value=None)

    def save(self, commit=True):
        instance = super().save(commit=False)
        contrato = self.cleaned_data.get("contrato")
        cod_projeto = self.cleaned_data.get("cod_projeto")

        if cod_projeto is not None:
            instance.coordenador = cod_projeto.coordenador
        elif contrato is not None and contrato.cod_projeto_id:
            instance.coordenador = contrato.cod_projeto.coordenador

        if commit:
            instance.save()
            self.save_m2m()
        return instance


class DocumentoContratoTerceiroForm(forms.ModelForm):
    valor_total = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Total",
        required=False)

    class Meta:
        model = DocumentoContratoTerceiro
        fields = ["numero_contrato", "objeto", "arquivo_contrato", "arquivo_contrato_assinado", "observacao", "valor_total"]
        widgets = {
            "arquivo_contrato_assinado": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def clean_valor_total(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_total"), empty_value=Decimal("0.00"))



class PeriodoSolicitacoesForm(forms.Form):
    inicio = forms.DateField(required=False, input_formats=["%Y-%m-%d"])
    fim = forms.DateField(required=False, input_formats=["%Y-%m-%d"])

    def clean(self):
        data = super().clean()
        if data.get("inicio") and data.get("fim") and data["inicio"] > data["fim"]:
            raise forms.ValidationError("A data inicial não pode ser posterior à data final.")
        return data


class OperacaoSolicitacaoForm(forms.Form):
    token = forms.UUIDField(error_messages={"required": "Atualize a página antes de confirmar a operação."})
    motivo = forms.CharField(required=False, max_length=10000, strip=True)
    arquivar = forms.BooleanField(required=False)
    confirmar = forms.BooleanField(error_messages={"required": "Confirme a operação antes de continuar."})

    def __init__(self, *args, operacao, **kwargs):
        super().__init__(*args, **kwargs)
        if operacao == "cancelar":
            self.fields["motivo"].required = True
            self.fields["motivo"].error_messages["required"] = "Informe a justificativa do cancelamento."


class DocumentoBMForm(forms.ModelForm):
    class Meta:
        model = DocumentoBM
        fields = ['minuta_boletim', 'minuta_boletim_assinado']
        widgets = {
            'minuta_boletim': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'minuta_boletim_assinado': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }


class EventoPrevisaoForm(forms.ModelForm):
    valor_previsto = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Previsto",
        required=True
    )
    class Meta:
        model = Evento
        fields = ["descricao", "data_prevista", "valor_previsto", "data_prevista_pagamento", "observacao"]
        widgets = {
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            #"valor_previsto": forms.NumberInput(attrs={"class": "form-control"}),
            "data_prevista": ISODateInput(attrs={ "class": "form-control"}),
            "data_prevista_pagamento": ISODateInput(attrs={"class": "form-control"}),
            "observacao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Se estiver editando (tem instance)
        if self.instance and self.instance.valor_previsto:
            valor = self.instance.valor_previsto
            valor_formatado = f"{valor:,.2f}"
            valor_formatado = valor_formatado.replace(",", "X").replace(".", ",").replace("X", ".")

            self.initial["valor_previsto"] = valor_formatado

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

    def clean_valor_previsto(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_previsto"), empty_value=None)



class EventoEntregaForm(forms.ModelForm):
    valor_pago = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control money", "placeholder": "0,00"})
    )
    data_pagamento = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )

    class Meta:
        model = Evento
        fields = [
            "observacao", "caminho_evidencia", "avaliacao",
            "data_entrega", "realizado", "valor_pago", "data_pagamento",
        ]
        widgets = {
            "caminho_evidencia": forms.Textarea(attrs={"class": "form-control", "rows": 1}),
            "avaliacao": forms.Select(attrs={"class": "form-select"}),
            "data_entrega": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "observacao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            self.initial["valor_pago"] = format_decimal_for_br_input(self.instance.valor_pago)
            self.initial["data_pagamento"] = self.instance.data_pagamento

        if not user or user.grupo != "suprimento":
            self.fields.pop("valor_pago", None)
            self.fields.pop("data_pagamento", None)

    def clean_valor_pago(self):
        if "valor_pago" not in self.fields:
            return self.instance.valor_pago
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_pago"))

    def save(self, commit=True):
        entrega = super().save(commit=False)
        entrega.com_atraso = bool(
            entrega.data_entrega
            and entrega.data_prevista
            and entrega.data_entrega > entrega.data_prevista
        )
        if commit:
            entrega.save()
        return entrega



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
        queryset=User.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        qs = User.objects.filter(grupo="coordenador").order_by("username")

        if user:
            if user.grupo in ["gerente", "gerente_lider"]:
                qs = qs.filter(grupo ="coordenador", centros__in=user.centros.all()).distinct().order_by("username")
            else:
                qs = qs.filter(grupo ="coordenador").distinct().order_by("username")

        self.fields["coordenador"].queryset = qs


class FiltroFinanceiroForm(FiltroPrevisaoForm):
    historico = forms.BooleanField(label="Todo o histórico (ignorar datas)", required=False)
    lider_contrato = forms.ModelChoiceField(label='Líder de Contrato (opcional)', queryset=User.objects.none(), required=False)
    fornecedor = forms.ModelChoiceField(label="Fornecedor", queryset=EmpresaTerceira.objects.none(), required=False)
    contrato = forms.ModelChoiceField(label="Contrato do fornecedor", queryset=ContratoTerceiros.objects.none(), required=False)
    projeto = forms.ModelChoiceField(label="Projeto", queryset=Contrato.objects.none(), required=False)
    origem = forms.ChoiceField(label="Origem", choices=[("", "Eventos e OS"), ("evento", "Evento"), ("os", "OS")], required=False)
    referencia = forms.IntegerField(label="ID do Evento / OS", min_value=1, required=False)
    numero_bm = forms.IntegerField(label="Número do BM", min_value=1, required=False)
    bm_id = forms.IntegerField(widget=forms.HiddenInput, min_value=1, required=False)
    autorizacao = forms.ChoiceField(label="Aprovação / autorização", required=False, choices=[
        ("", "Todas as situações"), ("operacional", "Aguardando aprovação operacional"),
        ("diretoria", "Aguardando Diretoria"), ("autorizado", "Autorizado pela Diretoria"), ("reprovado", "Com reprovação"),
    ])
    pagamento = forms.ChoiceField(label="Pagamento das NFs", required=False,
        choices=[("", "Pagas e não pagas"), ("pago", "Pago"), ("pendente", "Não pago / BM sem NF")])

    def __init__(self, *args, **kwargs):
        self.dynamic_choices = kwargs.pop('dynamic_choices', False)
        super().__init__(*args, **kwargs)
        self.fields['lider_contrato'].queryset = User.objects.filter(
            grupo__in=['lider_contrato', 'gerente_contrato', 'gerente_lider']).order_by('username')
        self.fields["data_limite"].required = False
        self.fields["fornecedor"].queryset = EmpresaTerceira.objects.order_by("nome", "pk")
        self.fields["projeto"].queryset = Contrato.objects.select_related("cliente").order_by("cod_projeto", "pk")
        self.fields["contrato"].queryset = ContratoTerceiros.objects.select_related("empresa_terceira").order_by("num_contrato", "pk")
        self.fields["contrato"].label_from_instance = lambda obj: f"{obj.num_contrato or '#' + str(obj.pk)} · {obj.empresa_terceira.nome}"
        if self.dynamic_choices:
            self.fields.pop('coordenador')
            if self.is_bound and 'coordenador' in self.data:
                # URLs anteriores não podem perder silenciosamente seu filtro.
                data = self.data.copy()
                if 'lider_contrato' not in data:
                    data['lider_contrato'] = data.get('coordenador', '')
                data.pop('coordenador', None)
                self.data = data
            from .financial_queries import financial_filter_choices

            def selected_id(name):
                value = self[name].value()
                if value in (None, ''):
                    return None
                try:
                    number = int(value)
                    return number if 0 < number <= 9223372036854775807 else -1
                except (ValueError, TypeError):
                    return -1

            choices = financial_filter_choices(leader=selected_id('lider_contrato'),
                supplier=selected_id('fornecedor'), project=selected_id('projeto'))
            for name, queryset in choices.items():
                self.fields[name].queryset = queryset
            self.order_fields(['data_inicial', 'data_limite', 'historico', 'lider_contrato',
                'fornecedor', 'projeto', 'contrato', 'origem', 'referencia', 'numero_bm', 'bm_id', 'autorizacao', 'pagamento'])
        for name, field in self.fields.items():
            if name not in {"historico", "bm_id"}:
                field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
        self.fields["historico"].widget.attrs["class"] = "form-check-input"

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("historico"):
            first, last = cleaned.get("data_inicial"), cleaned.get("data_limite")
            if not first or not last:
                raise forms.ValidationError("Informe as duas datas ou selecione Todo o histórico.")
            if first > last:
                raise forms.ValidationError("A data final deve ser igual ou posterior à inicial.")
        return cleaned


class BMForm(forms.ModelForm):
    valor_pago = forms.CharField(
        widget=forms.TextInput(attrs={"class": "form-control money", "placeholder": "0,00"})
    )

    class Meta:
        model = BM
        fields = ["numero_bm", "parcela_paga", "valor_pago", "data_pagamento", "data_inicial_medicao", "data_final_medicao", "observacao", "arquivo_bm"]
        widgets = {
            "numero_bm": forms.NumberInput(attrs={"class": "form-control"}),
            "parcela_paga": forms.TextInput(attrs={"class": "form-control"}),
            "data_inicial_medicao": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "form-control"}
            ),
            "data_final_medicao": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "form-control"}
            ),
            "data_pagamento": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date", "class": "form-control"}
            ),
            "observacao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "arquivo_bm": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # garante que o valor inicial seja respeitado se já existir
        if "initial" in kwargs and "data_pagamento" in kwargs["initial"]:
            self.fields["data_pagamento"].initial = kwargs["initial"]["data_pagamento"]
        if self.instance and self.instance.valor_pago is not None:
            self.initial["valor_pago"] = format_decimal_for_br_input(self.instance.valor_pago)

    def clean_valor_pago(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_pago"), empty_value=None)


class NFForm(forms.ModelForm):
    justificativa_correcao = forms.CharField(label='Justificativa da correção de NF paga',
        required=False, max_length=4000, widget=forms.Textarea(attrs={'class':'form-control','rows':2}))
    valor_pago = forms.CharField(
        widget=forms.TextInput(attrs={"class": "form-control money", "placeholder": "0,00"})
    )

    class Meta:
        model = NF
        fields = [
            "bm",
            "numero_nf", "serie", "tipo_documento", "data_emissao", "chave_acesso",
            "valor_pago",
            "parcela_paga",
            "data_pagamento",
            "arquivo_nf",
            "observacao",
            "financeiro_autorizou",
            "nf_dentro_prazo",
            "comprovante_pagamento", "justificativa_correcao",
            "vencimento_original",
        ]

        widgets = {
            "data_emissao": forms.DateInput(format='%Y-%m-%d',attrs={'type':'date','class':'form-control'}),
            "bm": forms.Select(attrs={"class": "form-control"}),
            "parcela_paga": forms.NumberInput(attrs={"class": "form-control"}),
            "data_pagamento": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "arquivo_nf": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "observacao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    # 🔥 FILTRANDO OS BMs PELO EVENTO
    def __init__(self, *args, **kwargs):
        evento = kwargs.pop("evento", None)
        os_obj = kwargs.pop("os", None)
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.was_paid = bool(self.instance.pk and self.instance.possui_pagamentos)
        self.fields['vencimento_original'].widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date','class':'form-control'})
        if self.instance.vencimento_original:self.fields['vencimento_original'].disabled=True
        for name in ('numero_nf','serie','tipo_documento','chave_acesso','comprovante_pagamento'):
            self.fields[name].widget.attrs['class']='form-control'
        self.read_only = bool(self.instance.pk and self.user
                              and self.user.grupo == "financeiro" and not can_change_nf(self.user, self.instance))

        if evento:
            self.instance.evento = evento
            self.instance.os = None
            self.instance.contrato = evento.contrato_terceiro
        elif os_obj:
            self.instance.os = os_obj
            self.instance.evento = None
            self.instance.contrato = os_obj.contrato

        if evento:
            self.fields["bm"].queryset = BM.objects.filter(evento=evento)
        elif os_obj:
            self.fields["bm"].queryset = BM.objects.filter(os=os_obj)
        else:
            self.fields["bm"].queryset = BM.objects.none()
        self.fields["bm"].required = True
        self.fields["bm"].error_messages["required"] = "Selecione o BM da mesma origem financeira da NF."
        self.fields["bm"].label_from_instance = lambda bm: (
            f"BM {bm.numero_bm} — participação #{bm.pk} — Parcela {bm.parcela_paga} — "
            f"{'Aprovação operacional pendente ou reprovada' if not bm_has_valid_operational_approval(bm) else 'Autorizado pela Diretoria' if bm.aprovacao_pagamento == 'aprovado' else 'Pagamento ainda não autorizado pela Diretoria'}"
        )
        self.fields["valor_pago"].label = "Valor da NF"
        if self.instance and self.instance.valor_pago is not None:
            self.initial["valor_pago"] = format_decimal_for_br_input(self.instance.valor_pago)
        self.fields["financeiro_autorizou"].label = "Pagamento realizado ao fornecedor"
        self.fields["financeiro_autorizou"].required = False
        self.fields["nf_dentro_prazo"].required = False
        self.payment_options = {
            str(bm.pk): {"allowed": not payment_registration_error(self.user, bm, evento or os_obj),
                         "message": ("Suprimento pode corrigir o registro financeiro, inclusive uma NF já paga."
                                     if self.user and self.user.grupo == "suprimento" else
                                     payment_registration_error(self.user, bm, evento or os_obj)
                                     or "Pagamento autorizado. Registre somente após a realização do pagamento.")}
            for bm in self.fields["bm"].queryset
        }
        selected = str(self.data.get(self.add_prefix("bm"), "") if self.is_bound else self.initial.get("bm") or "")
        option = self.payment_options.get(selected)
        self.payment_notice = (option["message"] if option else
                               "Selecione o BM. A NF pode ser cadastrada antes das aprovações; o pagamento exige liberação.")
        if self.user and self.user.grupo == "financeiro" and not (option and option["allowed"]):
            # Só o widget é desabilitado. O valor forjado no POST ainda passa
            # pela validação abaixo, em vez de ser silenciosamente descartado.
            self.fields["financeiro_autorizou"].widget.attrs["disabled"] = True
        if self.read_only:
            self.payment_notice = PAID_NF_READ_ONLY_MESSAGE
            for field in self.fields.values():
                field.disabled = True

    def clean(self):
        cleaned = super().clean()
        if self.read_only and self.is_bound:
            raise forms.ValidationError(PAID_NF_READ_ONLY_MESSAGE)
        if self.was_paid and not cleaned.get('justificativa_correcao'):
            self.add_error('justificativa_correcao','Informe o motivo da correção da NF paga.')
        if (self.user and self.user.grupo=='financeiro' and 'comprovante_pagamento' in self.changed_data
                and not cleaned.get('financeiro_autorizou')):
            self.add_error('comprovante_pagamento','Anexe o comprovante no momento de registrar o pagamento.')
        if cleaned.get("financeiro_autorizou"):
            from types import SimpleNamespace
            actor=SimpleNamespace(grupo='financeiro') if not self.instance.financeiro_autorizou else self.user
            error = payment_registration_error(actor, cleaned.get("bm"), self.instance.evento or self.instance.os)
            if error:
                self.add_error("financeiro_autorizou", error)
        return cleaned

    def save(self, commit=True):
        self.instance._audit_user=self.user
        self.instance._audit_reason=self.cleaned_data.get('justificativa_correcao','')
        return super().save(commit=commit)

    def clean_valor_pago(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_pago"), empty_value=None)


class NFClienteForm(forms.ModelForm):
    valor_pago = forms.CharField(
        widget=forms.TextInput(attrs={"class": "form-control money", "placeholder": "0,00"})
    )

    class Meta:
        model = NFCliente
        fields = [
            "valor_pago",
            "parcela_paga",
            "data_emissao",
            "data_pagamento",
            "arquivo_nf",
            "observacao",
        ]
        widgets = {
            "parcela_paga": forms.NumberInput(attrs={"class": "form-control"}),
            "data_emissao": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "data_pagamento": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "arquivo_nf": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "observacao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.valor_pago is not None:
            self.initial["valor_pago"] = format_decimal_for_br_input(self.instance.valor_pago)
        if user and user.grupo != "suprimento":
            self.fields.pop("valor_pago", None)
            self.fields.pop("data_pagamento", None)

    def clean_valor_pago(self):
        if "valor_pago" not in self.fields:
            return self.instance.valor_pago
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_pago"))


class RegistroEntregaOSForm(forms.ModelForm):
    valor_pago = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control money", "placeholder": "0,00"}),
    )
    data_pagamento = forms.DateField(
        required=False,
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
    )

    class Meta:
        model = OS
        fields = [
            "caminho_evidencia",
            "avaliacao",
            "data_entrega",
            "realizado",
            "valor_pago",
            "data_pagamento",
            "observacao",
        ]
        widgets = {
            "caminho_evidencia": forms.Textarea(attrs={"class": "form-control", "rows": 1}),
            "avaliacao": forms.Select(attrs={"class": "form-select"}),
            "data_entrega": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "observacao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial["data_entrega"] = self.instance.data_entrega
            self.initial["data_pagamento"] = self.instance.data_pagamento
        if self.instance and self.instance.valor_pago is not None:
            self.initial["valor_pago"] = format_decimal_for_br_input(self.instance.valor_pago)
        if user and user.grupo != "suprimento":
            self.fields.pop("valor_pago", None)
            self.fields.pop("data_pagamento", None)

    def clean_valor_pago(self):
        if "valor_pago" not in self.fields:
            return self.instance.valor_pago
        return parse_decimal_from_form_value(self.cleaned_data.get("valor_pago"))

    def save(self, commit=True):
        entrega = super().save(commit=False)
        entrega.com_atraso = bool(
            entrega.data_entrega
            and entrega.prazo_execucao
            and entrega.data_entrega > entrega.prazo_execucao
        )
        if commit:
            entrega.save()
        return entrega


class OrdemServicoForm(forms.ModelForm):
    valor = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control money", "placeholder": "0,00"}),
    )

    class Meta:
        model = OS
        fields = [
            'contrato',
            'solicitacao',
            'cod_projeto',
            'coordenador',
            'lider_contrato',
            'titulo',
            'descricao',
            'valor',
            'data_prevista_pagamento',
            'prazo_execucao',
            'status',
            'arquivo_os'
        ]
        widgets = {
            "data_prevista_pagamento": ISODateInput(attrs={"class": "form-control"}),
            "prazo_execucao": ISODateInput(attrs={ "class": "form-control"}),
            'descricao': forms.Textarea(attrs={"class": "form-control", 'rows': 4}),
            'titulo': forms.Textarea(attrs={"class": "form-control", "rows": 1}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'arquivo_os':forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        def include_instance_value(field_name):
            instance_value = getattr(self.instance, field_name, None)
            if not instance_value:
                return

            field = self.fields[field_name]
            if field.queryset.filter(pk=instance_value.pk).exists():
                return

            current_ids = list(field.queryset.values_list("pk", flat=True))
            current_ids.append(instance_value.pk)
            field.queryset = field.queryset.model.objects.filter(pk__in=current_ids).distinct()

        self.fields['coordenador'].queryset = User.objects.filter(grupo__in=['gerente', 'coordenador'], is_active=True)
        self.fields['coordenador'].required = False
        self.fields['contrato'].queryset = ContratoTerceiros.objects.filter(guarda_chuva=True)
        self.fields['solicitacao'].queryset = SolicitacaoOrdemServico.objects.filter(status__in=['solicitacao_os', 'pendente_lider', 'pendente_gerente', 'pendente_suprimento', 'aprovada'])
        self.fields['lider_contrato'].queryset = User.objects.filter(grupo__in=['gerente_contrato', 'lider_contrato', 'gerente_lider'], is_active=True)
        self.fields['lider_contrato'].required = False
        self.fields['cod_projeto'].queryset = Contrato.objects.filter(status='ativo')
        include_instance_value('contrato')
        include_instance_value('solicitacao')
        include_instance_value('cod_projeto')
        include_instance_value('coordenador')
        include_instance_value('lider_contrato')
        if self.instance and self.instance.valor is not None:
            self.initial["valor"] = format_decimal_for_br_input(self.instance.valor)

    def clean_valor(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("valor"), empty_value=None)


class RenegociacaoValorForm(forms.Form):
    valor_proposta = forms.CharField(label="Novo valor da proposta", widget=forms.TextInput(attrs={"class": "form-control", "inputmode": "decimal"}))

    def clean_valor_proposta(self):
        amount = parse_decimal_from_form_value(self.cleaned_data["valor_proposta"])
        return forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0")).clean(amount)


class RenegociacaoPrazoForm(forms.ModelForm):
    class Meta:
        model = DocumentoContratoTerceiro
        fields = ["prazo_inicio", "prazo_fim"]
        widgets = {field: ISODateInput(attrs={"class": "form-control"}) for field in fields}


class RevisaoProspeccaoForm(forms.ModelForm):
    class Meta:
        model = SolicitacaoProspeccao
        fields = ["descricao", "requisitos", "previsto_no_orcamento", "justificativa_orcamento", "forma_pagamento",
                  "valor_disponivel", "valor_vendido", "data_inicio", "data_fim"]
        widgets = {"data_inicio": ISODateInput(), "data_fim": ISODateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["descricao"].required = True
        self.fields["descricao"].label = "Escopo da nova prospecção"


class SolicitacaoAditivoContratoTerceiroForm(forms.ModelForm):
    novo_valor_total = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control money",
                "placeholder": "0,00",
            }
        ),
    )

    class Meta:
        model = AditivoContratoTerceiro
        fields = ["motivo", "novo_valor_total", "nova_data_fim"]
        widgets = {
            "motivo": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "nova_data_fim": ISODateInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.novo_valor_total is not None:
            valor = self.instance.novo_valor_total
            self.initial["novo_valor_total"] = (
                f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            )
        elif self.initial.get("novo_valor_total") is not None:
            valor = self.initial["novo_valor_total"]
            if isinstance(valor, Decimal):
                self.initial["novo_valor_total"] = (
                    f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                )

    def clean_novo_valor_total(self):
        return parse_decimal_from_form_value(self.cleaned_data.get("novo_valor_total"), empty_value=None)


class DocumentoAditivoContratoTerceiroForm(forms.ModelForm):
    class Meta:
        model = AditivoContratoTerceiro
        fields = ["arquivo_aditivo"]
        widgets = {
            "arquivo_aditivo": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }


class DocumentoAditivoAssinadoContratoTerceiroForm(forms.ModelForm):
    arquivo_aditivo_assinado = forms.FileField(required=True)
    class Meta:
        model = AditivoContratoTerceiro
        fields = ["arquivo_aditivo_assinado"]
        widgets = {
            "arquivo_aditivo_assinado": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }
