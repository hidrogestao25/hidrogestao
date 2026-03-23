from django import forms
from django.db.models import Q
from .models import Contrato, Cliente, User, Proposta, EmpresaTerceira, ContratoTerceiros, SolicitacaoProspeccao, PropostaFornecedor, DocumentoContratoTerceiro, DocumentoBM, Evento, BM, NF, NFCliente, SolicitacaoOrdemServico, OS, SolicitacaoContrato
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

    class Meta:
        model = Contrato
        fields = ['observacao', 'cod_projeto', 'cliente', 'coordenador', 'data_inicio', 'data_fim', 'valor_total', 'status', 'objeto', 'proposta', 'lider_contrato']
        widgets = {
            'cod_projeto': forms.TextInput(attrs={'class': 'form-control'}),
            'proposta': forms.Select(attrs={'class': 'form-select'}),
            'cliente': forms.Select(attrs={'class': 'form-select'}),
            'coordenador': forms.Select(attrs={'class': 'form-select'}),
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
        self.fields['lider_contrato'].queryset = (
            User.objects.filter(grupo__in=['lider_contrato', 'gerente_contrato'], is_active=True)
        )
        self.fields['proposta'].queryset = (
            Proposta.objects.all()
        )
        if self.instance and self.instance.valor_total:
            valor = self.instance.valor_total
            self.initial['valor_total'] = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def clean_valor_total(self):
        valor = self.cleaned_data.get('valor_total')
        if valor in [None, ""]:
            return None

        valor = valor.replace(".", "").replace(",", ".")

        try:
            return Decimal(valor)
        except InvalidOperation:
            raise forms.ValidationError("Informe um valor válido no formato R$ 0,00.")


class ContratoModalForm(forms.ModelForm):
    class Meta:
        model = Contrato
        fields = ['cod_projeto', 'cliente', 'objeto']


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = '__all__'
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'razao_social': forms.TextInput(attrs={'class': 'form-control'}),
            'cpf_cnpj': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_cpf_cnpj'}),
            'endereco': forms.Textarea(attrs={'class': 'form-control', 'row': 3}),
            'telefone': forms.TextInput(attrs={'class': 'form-control'}),
            'email':  forms.TextInput(attrs={'class': 'form-control'}),
            'ponto_focal':  forms.TextInput(attrs={'class': 'form-control'}),
            'email_focal':  forms.TextInput(attrs={'class': 'form-control'}),
            'telefone_focal':  forms.TextInput(attrs={'class': 'form-control'}),
            'observacao': forms.Textarea(attrs={'class': 'form-control', 'row': 3}),
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
            'ponto_focal2': forms.TextInput(attrs={'class': 'form-control'}),
            'email_focal2':  forms.TextInput(attrs={'class': 'form-control'}),
            'telefone_focal2': forms.TextInput(attrs={'class': 'form-control'}),
            'observacao': forms.Textarea(attrs={'class': 'form-control', 'row': 3}),
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
        fields = ['lider_contrato','condicao_pagamento', 'num_contrato_arquivo', 'num_contrato', 'observacao', 'cod_projeto', 'prospeccao', 'empresa_terceira', 'coordenador', 'data_inicio', 'data_fim', 'valor_total', 'status', 'objeto']
        widgets = {
            'cod_projeto': forms.Select(attrs={'class': 'form-select'}),
            'num_contrato': forms.TextInput(attrs={'class': 'form-control'}),
            'prospeccao': forms.Select(attrs={'class': 'form-select'}),
            'empresa_terceira': forms.Select(attrs={'class': 'form-select'}),
            'coordenador': forms.Select(attrs={'class': 'form-select'}),
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
            User.objects.filter(grupo__in=['coordenador', 'gerente', 'lider_contrato'], is_active=True)
        )
        self.fields['lider_contrato'].queryset = (
            User.objects.filter(grupo__in=['lider_contrato','gerente_contrato'], is_active=True)
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
            'requisitos',
            'previsto_no_orcamento',
            'justificativa_fornecedor_escolhido',
            'valor_disponivel',
            'data_inicio',
            'data_fim',
            'cronograma',
            'forma_pagamento',
            'justificativa_orcamento',
        ]

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['descricao'].label = "Escopo de Contratação"
        self.fields['requisitos'].label = "Requisitos Mínimos"

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
        elif user and user.grupo in ['gerente_contrato', 'lider_contrato']:
            self.fields['contrato'].queryset = Contrato.objects.all()
        else:
            self.fields['contrato'].queryset = Contrato.objects.none()

        self.fields['coordenador'].queryset = User.objects.filter(
            grupo__in=['coordenador', 'gerente', 'gerente_lider'],
            is_active=True
        )

        self.fields['fornecedor_escolhido'].queryset = EmpresaTerceira.objects.all().order_by('nome')

    def clean_valor_disponivel(self):
        valor = self.cleaned_data.get('valor_disponivel')

        if valor:
            valor = (
                valor.replace('R$', '')
                     .replace('.', '')
                     .replace(',', '.')
                     .strip()
            )
            try:
                return Decimal(valor)
            except:
                raise forms.ValidationError("Informe um valor monetário válido.")

        return valor

    """def clean_valor_vendido(self):
        valor = self.cleaned_data.get('valor_vendido')

        if valor:
            valor = (
                valor.replace('R$', '')
                     .replace('.', '')
                     .replace(',', '.')
                     .strip()
            )
            try:
                return Decimal(valor)
            except:
                raise forms.ValidationError("Informe um valor monetário válido.")

        return valor"""


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
    class Meta:
        model = SolicitacaoProspeccao
        fields = ['justificativa_orcamento','forma_pagamento','valor_disponivel','contrato', 'coordenador', 'descricao', 'requisitos','previsto_no_orcamento', 'cronograma']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['descricao'].label = "Escopo de Contratação"
        self.fields['requisitos'].label = "Requisitos Mínimos"

        if user and user.grupo == 'coordenador':
            self.fields['contrato'].queryset = Contrato.objects.filter(coordenador=user)
        #elif user and user.grupo == 'financeiro':
        #    self.fields['contrato'].queryset = Contrato.objects.all()
        elif user and user.grupo in ['gerente_lider']:
            self.fields['contrato'].queryset = Contrato.objects.filter(coordenador__centros__in=user.centros.all())
        else:
            self.fields['contrato'].queryset = Contrato.objects.none()
        self.fields['coordenador'].queryset = User.objects.filter(grupo__in=['coordenador','gerente', 'gerente_lider'], is_active=True)

    def clean_valor_disponivel(self):
        valor = self.cleaned_data.get('valor_disponivel')
        if valor:
            try:
                # Remove pontos de milhar e troca vírgula por ponto
                valor = valor.replace('.', '').replace(',', '.')
                return Decimal(valor)
            except (InvalidOperation, AttributeError):
                raise forms.ValidationError("Informe um valor numérico válido (ex: 1.234,56)")
        return valor

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


class SolicitacaoOrdemServicoForm(forms.ModelForm):
    valor_previsto = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Previsto",
        required=True
    )
    class Meta:
        model = SolicitacaoOrdemServico
        fields = [
            'cod_projeto',
            'titulo',
            'descricao',
            'valor_previsto',
            'prazo_execucao'
        ]
        widgets = {
            "prazo_execucao": ISODateInput(attrs={ "class": "form-control"}),
            'descricao': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user.grupo == 'coordenador':
            self.fields['cod_projeto'].queryset = Contrato.objects.filter(coordenador=user)
        elif user.grupo == 'gerente':
            self.fields['cod_projeto'].queryset = Contrato.objects.filter(coordenador__centros__in=user.centros.all())
        self.fields['cod_projeto'].widget.attrs.update({'style': 'width:250px;'})


class UploadContratoOSForm(forms.ModelForm):
    class Meta:
        model = SolicitacaoOrdemServico
        fields = ['arquivo_os']


class DocumentoContratoTerceiroForm(forms.ModelForm):
    """valor_total = forms.CharField(required=True)"""

    class Meta:
        model = DocumentoContratoTerceiro
        fields = ["numero_contrato", "objeto", "arquivo_contrato", "observacao"]

    """def clean_valor_total(self):
        valor = self.cleaned_data.get("valor_total")

        if valor:
            # remove pontos de milhar e troca vírgula por ponto
            valor = valor.replace(".", "").replace(",", ".")
            try:
                return Decimal(valor)
            except InvalidOperation:
                raise forms.ValidationError("Informe um valor válido no formato 1.234,56")
        return None"""


class DocumentoBMForm(forms.ModelForm):
    class Meta:
        model = DocumentoBM
        fields = ['minuta_boletim']
        widgets = {
            'minuta_boletim': forms.ClearableFileInput(attrs={'class': 'form-control'}),
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
        valor = self.cleaned_data.get("valor_previsto")

        if valor:
            # remove pontos de milhar e troca vírgula por ponto
            valor = valor.replace(".", "").replace(",", ".")
            try:
                return Decimal(valor)
            except InvalidOperation:
                raise forms.ValidationError("Informe um valor válido no formato 1.234,56")
        return None



class EventoEntregaForm(forms.ModelForm):
    class Meta:
        model = Evento
        fields = [
            "observacao", "caminho_evidencia", "justificativa", "avaliacao",
            "data_entrega", "realizado", "com_atraso",
            "valor_pago", "data_pagamento"
        ]
        widgets = {
            "caminho_evidencia": forms.Textarea(attrs={"class": "form-control", "rows": 1}),
            "justificativa": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "avaliacao": forms.Select(attrs={"class": "form-select"}),
            "data_entrega": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "valor_pago": forms.NumberInput(attrs={"class": "form-control"}),
            "data_pagamento": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "observacao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.data_pagamento:
            self.initial['data_pagamento'] = self.instance.data_pagamento.strftime('%Y-%m-%d')



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


class BMForm(forms.ModelForm):
    class Meta:
        model = BM
        fields = ["numero_bm", "parcela_paga", "valor_pago", "data_pagamento", "data_inicial_medicao", "data_final_medicao", "observacao", "arquivo_bm"]
        widgets = {
            "numero_bm": forms.NumberInput(attrs={"class": "form-control"}),
            "parcela_paga": forms.TextInput(attrs={"class": "form-control"}),
            "valor_pago": forms.NumberInput(attrs={"class": "form-control"}),
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


class NFForm(forms.ModelForm):
    class Meta:
        model = NF
        fields = [
            "bm",
            "valor_pago",
            "parcela_paga",
            "data_pagamento",
            "arquivo_nf",
            "observacao",
            "financeiro_autorizou",
            "nf_dentro_prazo",
        ]

        widgets = {
            "bm": forms.Select(attrs={"class": "form-control"}),
            "valor_pago": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "parcela_paga": forms.NumberInput(attrs={"class": "form-control"}),
            "data_pagamento": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "arquivo_nf": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "observacao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    # 🔥 FILTRANDO OS BMs PELO EVENTO
    def __init__(self, *args, **kwargs):
        evento = kwargs.pop("evento", None)   # recebe o evento da view
        super().__init__(*args, **kwargs)

        # Se veio um evento, filtra os BMs desse evento
        if evento:
            self.fields["bm"].queryset = BM.objects.filter(evento=evento)
        else:
            self.fields["bm"].queryset = BM.objects.none()


class NFClienteForm(forms.ModelForm):
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
            "data_emissao": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "data_pagamento": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "arquivo_nf": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "observacao": forms.Textarea(attrs={"rows": 3}),
        }


class RegistroEntregaOSForm(forms.ModelForm):
    class Meta:
        model = OS
        fields = [
            "caminho_evidencia",
            "avaliacao",
            "data_entrega",
            "realizado",
            "com_atraso",
            "valor_pago",
            "data_pagamento",
            "observacao",
        ]
        widgets = {
            "data_entrega": forms.DateInput(attrs={"type": "date"}),
            "data_pagamento": forms.DateInput(attrs={"type": "date"}),
            "observacao": forms.Textarea(attrs={"rows": 3}),
        }


class OrdemServicoForm(forms.ModelForm):
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
            'prazo_execucao',
            'status',
            'arquivo_os'
        ]
        widgets = {
            "prazo_execucao": ISODateInput(attrs={ "class": "form-control"}),
            'descricao': forms.Textarea(attrs={"class": "form-control", 'rows': 4}),
            'titulo': forms.Textarea(attrs={"class": "form-control", "rows": 1}),
            'valor': forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'arquivo_os':forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['coordenador'].queryset = User.objects.filter(grupo__in=['gerente', 'coordenador'], is_active=True)
        self.fields['contrato'].queryset = ContratoTerceiros.objects.filter(guarda_chuva=True)
        self.fields['solicitacao'].queryset = SolicitacaoOrdemServico.objects.filter(status__in=['solicitacao_os', 'pendente_lider', 'pendente_gerente', 'pendente_suprimento', 'aprovada'])
        self.fields['lider_contrato'].queryset = User.objects.filter(grupo__in=['gerente_contrato', 'lider_contrato'], is_active=True)
        self.fields['cod_projeto'].queryset = Contrato.objects.filter(status='ativo')
