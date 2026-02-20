from django import forms
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
        fields = ['observacao', 'cod_projeto', 'cliente', 'coordenador', 'data_inicio', 'data_fim', 'valor_total', 'status', 'objeto', 'proposta', 'lider_contrato']
        widgets = {
            'cod_projeto': forms.TextInput(attrs={'class': 'form-control'}),
            'proposta': forms.Select(attrs={'class': 'form-select'}),
            'cliente': forms.Select(attrs={'class': 'form-select'}),
            'coordenador': forms.Select(attrs={'class': 'form-select'}),
            'lider_contrato': forms.Select(attrs={'class': 'form-select'}),
            'valor_total': forms.TextInput(attrs={'class': 'form-control', 'id': 'id_valor_total'}),
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
        fields = ['lider_contrato','condicao_pagamento', 'num_contrato_arquivo', 'num_contrato', 'observacao', 'cod_projeto', 'prospeccao', 'empresa_terceira', 'coordenador', 'data_inicio', 'data_fim', 'valor_total', 'status', 'objeto', 'guarda_chuva']
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
            User.objects.filter(grupo='coordenador', is_active=True)
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


from decimal import Decimal
from django import forms

class SolicitacaoContratoForm(forms.ModelForm):
    valor_provisionado = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control money',
            'placeholder': 'R$ 0,00'
        }),
        label="Valor Provisionado",
        required=True
    )

    class Meta:
        model = SolicitacaoContrato
        fields = [
            'fornecedor_escolhido',
            'contrato',
            'lider_contrato',
            'descricao',
            'requisitos',
            'previsto_no_orcamento',
            'valor_provisionado',
            'cronograma'
        ]

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['descricao'].label = "Escopo de Contratação"
        self.fields['requisitos'].label = "Requisitos Mínimos"

        if user and user.grupo == 'coordenador':
            self.fields['contrato'].queryset = Contrato.objects.filter(coordenador=user)
        elif user and user.grupo == 'gerente':
            self.fields['contrato'].queryset = Contrato.objects.filter(
                coordenador__centros__in=user.centros.all()
            )
        else:
            self.fields['contrato'].queryset = Contrato.objects.none()

        self.fields['lider_contrato'].queryset = User.objects.filter(
            grupo__in=['gerente_contrato', 'lider_contrato'],
            is_active=True
        )

        self.fields['fornecedor_escolhido'].queryset = EmpresaTerceira.objects.all().order_by('nome')

    def clean_valor_provisionado(self):
        valor = self.cleaned_data.get('valor_provisionado')

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
        fields = ['contrato', 'lider_contrato', 'descricao', 'requisitos','previsto_no_orcamento', 'valor_provisionado', 'cronograma']
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
        #elif user and user.grupo == 'financeiro':
        #    self.fields['contrato'].queryset = Contrato.objects.all()
        elif user and user.grupo == 'gerente':
            self.fields['contrato'].queryset = Contrato.objects.filter(coordenador__centros__in=user.centros.all())
        else:
            self.fields['contrato'].queryset = Contrato.objects.none()
        self.fields['lider_contrato'].queryset = User.objects.filter(grupo__in=['gerente_contrato', 'lider_contrato'], is_active=True)

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


class SolicitacaoOrdemServicoForm(forms.ModelForm):
    class Meta:
        model = SolicitacaoOrdemServico
        fields = [
            'contrato',
            'cod_projeto',
            'titulo',
            'descricao',
            'valor_previsto',
            'prazo_execucao',
            'lider_contrato'
        ]
        widgets = {
            "prazo_execucao": ISODateInput(attrs={ "class": "form-control"}),
            'descricao': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['contrato'].queryset = ContratoTerceiros.objects.filter(guarda_chuva=True)
        self.fields['lider_contrato'].queryset = User.objects.filter(grupo__in=['gerente_contrato', 'lider_contrato'], is_active=True)
        if user.grupo == 'coordenador':
            self.fields['cod_projeto'].queryset = Contrato.objects.filter(coordenador=user)
        elif user.grupo == 'gerente':
            self.fields['cod_projeto'].queryset = Contrato.objects.filter(coordenador__centros__in=user.centros.all())

class UploadContratoOSForm(forms.ModelForm):
    class Meta:
        model = SolicitacaoOrdemServico
        fields = ['arquivo_os']


class DocumentoContratoTerceiroForm(forms.ModelForm):
    valor_total = forms.CharField(required=True)  # força como texto primeiro

    class Meta:
        model = DocumentoContratoTerceiro
        fields = ["numero_contrato", "objeto", "prazo_inicio", "prazo_fim", "valor_total", "arquivo_contrato", "observacao"]

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
        fields = ["descricao", "data_prevista", "valor_previsto", "data_prevista_pagamento", "observacao"]
        widgets = {
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "valor_previsto": forms.NumberInput(attrs={"class": "form-control"}),
            "data_prevista": ISODateInput(attrs={ "class": "form-control"}),
            "data_prevista_pagamento": ISODateInput(attrs={"class": "form-control"}),
            "observacao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
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
        queryset=User.objects.filter(grupo="coordenador").order_by("username"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )


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
