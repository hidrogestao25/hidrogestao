import os
import uuid
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.utils.deconstruct import deconstructible
from django.conf import settings

from datetime import date
from django.core.exceptions import ValidationError
from .validation import BusinessValidationMixin, validate_upload


def _uppercase_model_fields(instance, field_names):
    for field_name in field_names:
        value = getattr(instance, field_name, None)
        if isinstance(value, str):
            setattr(instance, field_name, value.upper())


def _short_label(value, max_length=80):
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3].rstrip()}..."


def _solicitacao_label(instance):
    if getattr(instance, "contrato_id", None) and getattr(instance, "contrato", None):
        return f"Solicitação para {instance.contrato}"

    fornecedor = getattr(instance, "fornecedor_escolhido", None)
    if fornecedor:
        tipo = "Solicitação guarda-chuva" if getattr(instance, "guarda_chuva", False) else "Solicitação"
        return f"{tipo} para {fornecedor}"

    descricao = _short_label(getattr(instance, "descricao", None))
    if descricao:
        prefixo = "Solicitação guarda-chuva" if getattr(instance, "guarda_chuva", False) else "Solicitação"
        identificador = f" #{instance.pk}" if instance.pk else ""
        return f"{prefixo}{identificador} - {descricao}"

    identificador = f" #{instance.pk}" if instance.pk else ""
    if getattr(instance, "guarda_chuva", False):
        return f"Solicitação guarda-chuva{identificador}"
    return f"Solicitação{identificador}"


def _forma_pagamento_label(instance):
    value = getattr(instance, "forma_pagamento", None)
    if value in (None, ""):
        return "Não informado"

    labels = dict(getattr(instance, "FORMA_PAGAMENTO_CHOICES", []))
    normalized = str(value).strip()
    numeric_days = {"30", "60", "90"}

    if normalized not in numeric_days:
        try:
            decimal_value = Decimal(normalized)
        except Exception:
            decimal_value = None
        if decimal_value is not None and decimal_value == decimal_value.to_integral_value():
            normalized = str(int(decimal_value))

    return labels.get(value) or labels.get(normalized) or (
        f"{normalized} dias" if normalized in numeric_days else normalized
    )


@deconstructible
class ShortenedUploadPath:
    def __init__(self, directory, fallback_name="arquivo"):
        self.directory = directory.strip("/\\")
        self.fallback_name = fallback_name

    def __call__(self, instance, filename):
        base_name = os.path.basename(filename or "")
        stem, extension = os.path.splitext(base_name)
        safe_stem = "".join(
            char for char in stem if char.isalnum() or char in {"_", "-", "."}
        ).strip("._-")
        if not safe_stem:
            safe_stem = self.fallback_name

        safe_extension = "".join(
            char for char in extension.lower() if char.isalnum() or char == "."
        )[:15]
        if safe_extension and not safe_extension.startswith("."):
            safe_extension = f".{safe_extension}"

        suffix = f"_{uuid.uuid4().hex[:8]}"
        max_stem_length = 255 - len(self.directory) - 1 - len(suffix) - len(safe_extension)
        safe_stem = safe_stem[: max(1, max_stem_length)].rstrip("._-") or self.fallback_name
        return f"{self.directory}/{safe_stem}{suffix}{safe_extension}"


CRONOGRAMA_UPLOAD_PATH = ShortenedUploadPath("cronograma", "cronograma")
PROPOSTA_TECNICA_UPLOAD_PATH = ShortenedUploadPath("propostas_tecnicas", "proposta_tecnica")
ORCAMENTO_UPLOAD_PATH = ShortenedUploadPath("orcamentos", "orcamento")
CONTRACT_SUPPLIER_UPLOAD_PATH = ShortenedUploadPath("contrato_do_fornecedor", "contrato_fornecedor")
SOLICITACAO_OS_UPLOAD_PATH = ShortenedUploadPath("OS", "solicitacao_os")
OS_UPLOAD_PATH = ShortenedUploadPath("OS", "ordem_servico")
EVENTO_EVIDENCIA_UPLOAD_PATH = ShortenedUploadPath("produto_do_fornecedor", "evidencia_evento")
MINUTA_BM_UPLOAD_PATH = ShortenedUploadPath("Minuta boletim", "minuta_bm")
MINUTA_BM_ASSINADO_UPLOAD_PATH = ShortenedUploadPath("Minuta boletim/assinados", "minuta_bm_assinado")
BM_UPLOAD_PATH = ShortenedUploadPath("BM", "boletim_medicao")
NF_FORNECEDOR_UPLOAD_PATH = ShortenedUploadPath("NF/Fornecedor", "nf_fornecedor")
NF_CLIENTE_UPLOAD_PATH = ShortenedUploadPath("NF/Cliente", "nf_cliente")
DOCUMENTO_CONTRATO_UPLOAD_PATH = ShortenedUploadPath("contratos/documentos", "documento_contrato")
MINUTA_CONTRATO_UPLOAD_PATH = ShortenedUploadPath("contratos", "minuta_contrato")
CONTRATO_ASSINADO_UPLOAD_PATH = ShortenedUploadPath("contratos/assinados", "contrato_assinado")
ADITIVO_UPLOAD_PATH = ShortenedUploadPath("aditivos_fornecedor", "aditivo")
ADITIVO_ASSINADO_UPLOAD_PATH = ShortenedUploadPath("aditivos_fornecedor_assinados", "aditivo_assinado")


# --------------------
# Usuários com grupos
# --------------------
class User(AbstractUser):
    GRUPOS_CHOICES = [
        ('coordenador', 'Coordenador de Contrato'),
        ('lider_contrato','Lider de Contratos'),
        ('gerente', 'Gerente'),
        ('gerente_lider', 'Gerente e Lider de Contratos'),
        ('gerente_contrato', 'Gerente de Contratos'),
        ('diretoria', 'Diretoria'),
        ('financeiro', 'Financeiro'),
        ('suprimento', 'Suprimento'),
        ('fornecedor', 'Fornecedor'),
    ]

    grupo = models.CharField(max_length=50, choices=GRUPOS_CHOICES, blank=True, null=True)
    gerente_contrato_ausente = models.BooleanField(default=False)

    # Novo campo ManyToMany
    centros = models.ManyToManyField("CentroDeTrabalho", blank=True, related_name="usuarios")

    email = models.EmailField()

    # Evita conflito de acessores reversos com auth.User.*
    groups = models.ManyToManyField(Group, related_name="+", blank=True)
    user_permissions = models.ManyToManyField(Permission, related_name="+", blank=True)

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def atua_como_gerente_contrato(self):
        if self.grupo == "gerente_contrato":
            return True
        if self.grupo != "diretoria":
            return False
        return User.objects.filter(
            grupo="gerente_contrato",
            is_active=True,
            gerente_contrato_ausente=True,
        ).exists()


class CentroDeTrabalho(BusinessValidationMixin, models.Model):
    codigo = models.CharField(max_length=10, unique=True)
    nome = models.CharField(max_length=100)

    observacao = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.nome} ({self.codigo})"


# -----------------
# Cliente
# -----------------
class Cliente(BusinessValidationMixin, models.Model):
    nome = models.CharField(max_length=200)
    razao_social = models.CharField(max_length=200, blank=True, null=True)
    cpf_cnpj = models.CharField(max_length=18, unique=True)
    endereco = models.TextField(blank=True, null=True)
    complemento = models.TextField(blank=True, null=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)

    ponto_focal = models.CharField(max_length=200, null=True, blank=True)
    email_focal = models.EmailField(blank=True, null=True)
    telefone_focal =models.CharField(max_length=20, blank=True, null=True)

    """ponto_focal2 = models.CharField(max_length=200, null=True, blank=True)
    email_focal2 = models.EmailField(blank=True, null=True)
    telefone_focal2 =models.CharField(max_length=20, blank=True, null=True)"""

    observacao = models.TextField(null=True, blank=True)

    def save(self, *args, **kwargs):
        _uppercase_model_fields(
            self,
            [
                "nome",
                "razao_social",
                "endereco",
                "ponto_focal",
                "observacao",
            ],
        )
        super().save(*args, **kwargs)

    def __str__(self):
        if self.razao_social == None:
            return self.nome
        else:
            return f"{self.nome} ({self.razao_social})"


# -----------------
# Empresa Terceira
# -----------------
class EmpresaTerceira(BusinessValidationMixin, models.Model):
    nome = models.CharField(max_length=200)
    setor_de_atuacao = models.TextField(blank=True, null=True)
    cpf_cnpj = models.CharField(max_length=18, unique=True)
    endereco = models.TextField(blank=True, null=True)
    complemento = models.TextField(blank=True, null=True)
    numero = models.TextField(blank=True, null=True)
    bairro = models.TextField(blank=True, null=True)
    municipio = models.TextField(blank=True, null=True)
    estado = models.TextField(blank=True, null=True)
    cep = models.TextField(blank=True, null=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    informacoes_bancarias = models.TextField(max_length=200)
    guarda_chuva = models.BooleanField(default=False)

    ponto_focal = models.CharField(max_length=200, null=True, blank=True)
    email_focal = models.EmailField(blank=True, null=True)
    telefone_focal =models.CharField(max_length=20, blank=True, null=True)

    ponto_focal2 = models.CharField(max_length=200, null=True, blank=True)
    email_focal2 = models.EmailField(blank=True, null=True)
    telefone_focal2 =models.CharField(max_length=20, blank=True, null=True)

    observacao = models.TextField(null=True, blank=True)

    def save(self, *args, **kwargs):
        _uppercase_model_fields(
            self,
            [
                "nome",
                "setor_de_atuacao",
                "endereco",
                "numero",
                "bairro",
                "municipio",
                "estado",
                "cep",
                "informacoes_bancarias",
                "ponto_focal",
                "ponto_focal2",
                "observacao",
            ],
        )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome


# ---------
# Proposta (interna)
# ---------
class Proposta(BusinessValidationMixin, models.Model):
    STATUS_CHOICES = [
        ('analise', 'Em análise'),
        ('aprovada', 'Aprovada'),
        ('reprovada', 'Reprovada'),
    ]

    numero = models.CharField(max_length=50, unique=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    responsavel_sumprimento = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        limit_choices_to={'groups__name': 'Suprimento'},
        related_name="propostas_comerciais"
    )
    responsavel_tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="propostas_tecnicas"
    )
    descricao = models.TextField()
    valor_total = models.DecimalField(max_digits=12, decimal_places=2)
    data_envio = models.DateField(default=timezone.now)
    prazo_validade = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='analise')
    observacao = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Proposta {self.numero} - {self.cliente}"


# --------------------------
# Contrato com Cliente
# --------------------------
class Contrato(BusinessValidationMixin, models.Model):
    STATUS_CHOICES = [
        ('em_elaboracao', 'Em elaboração'),
        ('aguardando_assinatura', 'Aguardando assinatura'),
        ('ativo', 'Ativo'),
        ('suspenso', 'Suspenso'),
        ('encerrado', 'Encerrado'),
    ]

    cod_projeto = models.CharField(max_length=50, unique=True)
    proposta = models.OneToOneField(Proposta, on_delete=models.SET_NULL, null=True, blank=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="contratos")
    coordenador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        #limit_choices_to={'grupo': 'Coordenador de Contrato'},
        related_name="contratos_cliente_coordenados"  # evita conflito com contratos_coordenados
    )
    coordenadores = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="contratos_cliente_como_coordenador",
        limit_choices_to={"grupo": "coordenador"},
    )
    lider_contrato = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"grupo__in": ["lider_contrato", "gerente_contrato", "gerente_lider"]},
        related_name="contratos_liderados"
    )
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    objeto = models.TextField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='em_elaboracao', null=True, blank=True)
    observacao = models.TextField(null=True, blank=True)

    def save(self, *args, **kwargs):
        _uppercase_model_fields(self, ["cod_projeto"])
        super().save(*args, **kwargs)
        if self.coordenador_id:
            self.coordenadores.add(self.coordenador_id)

    @property
    def todos_coordenadores(self):
        coordenadores = list(self.coordenadores.all())
        if self.coordenador and self.coordenador not in coordenadores:
            coordenadores.insert(0, self.coordenador)
        return coordenadores

    @property
    def coordenadores_display(self):
        nomes = [
            coordenador.get_full_name() or coordenador.username
            for coordenador in self.todos_coordenadores
        ]
        return ", ".join(nomes)

    def __str__(self):
        return f"{self.cod_projeto} - {self.cliente}"


# ---------------------------------------
# Solicitação de Contratação de fornecedor
# ---------------------------------------
class SolicitacaoQuerySet(models.QuerySet):
    def operacionais(self):
        queryset = self.filter(arquivada=False, cancelada_em__isnull=True)
        if any(field.name == "status" for field in self.model._meta.fields):
            queryset = queryset.exclude(status__in=["Cancelada", "cancelada"])
        return queryset

    def em_visualizacao(self, visualizacao):
        if visualizacao == "todas":
            return self.all()
        queryset = self.filter(arquivada=visualizacao == "arquivadas")
        if self.model._meta.model_name in {"solicitacaoprospeccao", "solicitacaocontrato"}:
            queryset = queryset.exclude(status="Onboarding")
        return queryset


class EstadoSolicitacao(models.Model):
    """Visibilidade e encerramento são estados independentes do fluxo de aprovação."""
    arquivada = models.BooleanField(default=False, db_index=True, editable=False)
    arquivada_em = models.DateTimeField(null=True, blank=True, editable=False)
    arquivada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="+", editable=False)
    motivo_arquivamento = models.TextField(blank=True, default="", editable=False)
    cancelada_em = models.DateTimeField(null=True, blank=True, editable=False)
    cancelada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="+", editable=False)
    motivo_cancelamento = models.TextField(blank=True, default="", editable=False)

    objects = SolicitacaoQuerySet.as_manager()

    class Meta:
        abstract = True

    @property
    def cancelada(self):
        return bool(self.cancelada_em or self.status in {"Cancelada", "cancelada"})


class SolicitacaoContrato(BusinessValidationMixin, EstadoSolicitacao):
    class Meta:
        permissions = [
            ("arquivar_solicitacaocontrato", "Pode arquivar e desarquivar contratações"),
            ("cancelar_solicitacaocontrato", "Pode cancelar contratações"),
        ]

    ACAO_CHOICES = [
        ('renegociar_valor', 'Renegociar Valor'),
        ('renegociar_prazo', 'Renegociar Prazo'),
        ('alterar_fornecedor', 'Selecionar outro Fornecedor'),
    ]
    APROVACAO_CHOICES = [
        ("pendente", "Pendente"),
        ("aprovado", "Aprovado"),
        ("reprovado", "Reprovado")
    ]
    FORMA_PAGAMENTO_CHOICES = [
        ("conforme_pagamento_cliente", "Conforme Pagamento do Cliente"),
        ("conforme_medicao_aprovada", "Conforme Medição Aprovada"),
        ("30", "30 dias"),
        ("60", "60 dias"),
        ("90", "90 dias"),
    ]

    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name='solicitacoes_contratos', blank=True, null=True)
    coordenador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    lider_contrato = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"grupo__in": ["lider_contrato", "gerente_contrato", "gerente_lider"]},
        related_name="solicitacoes_lideradas_contratos",
    )
    descricao = models.TextField(blank=True, null=True)
    requisitos = models.TextField(blank=True, null=True)
    previsto_no_orcamento = models.BooleanField(default=False)
    justificativa_orcamento = models.TextField(blank=True, null=True)
    forma_pagamento = models.CharField(max_length=40, choices=FORMA_PAGAMENTO_CHOICES, null=True, blank=True, verbose_name="Forma de Pagamento")
    valor_disponivel = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    valor_provisionado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    valor_vendido = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    data_solicitacao = models.DateTimeField(auto_now_add=True)
    guarda_chuva = models.BooleanField(default=False, null=True, blank=True)
    justificativa_solicitacao = models.TextField(null=True, blank=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    cronograma = models.FileField(
        upload_to=CRONOGRAMA_UPLOAD_PATH,
        verbose_name='Inserir cronograma',
        null=True, blank=True,
        max_length=255,
    )
    proposta_tecnica = models.FileField(
        upload_to=PROPOSTA_TECNICA_UPLOAD_PATH,
        verbose_name='Inserir propostas técnicas',
        null=True,
        blank=True,
        max_length=255,
    )

    aprovacao_fornecedor_gerente =  models.CharField(max_length=20, choices=APROVACAO_CHOICES, default="pendente")
    aprocacao_fornecedor_gerente_em = models.DateTimeField(null=True, blank=True)
    aprovacao_fornecedor_diretor =  models.CharField(max_length=20, choices=APROVACAO_CHOICES, default="pendente")
    aprocacao_fornecedor_diretor_em = models.DateTimeField(null=True, blank=True)

    aprovacao_gerencia = models.BooleanField(default=False)
    reprovacao_gerencia = models.BooleanField(default=False)
    aprovacao_diretoria = models.BooleanField(default=False)
    reprovacao_diretoria = models.BooleanField(default=False)
    justificativa_gerencia = models.TextField(null=True, blank=True)
    justificativa_diretoria = models.TextField(null=True, blank=True)
    acao_gerencia = models.CharField(max_length=100, null=True, blank=True, choices=ACAO_CHOICES)
    acao_diretoria = models.CharField(max_length=100, null=True, blank=True, choices=ACAO_CHOICES)

    #boletim_flag = models.BooleanField(default=False)
    observacao = models.TextField(null=True, blank=True)

    fornecedor_escolhido = models.ForeignKey(
        EmpresaTerceira,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='escolhido_contrato'
    )
    justificativa_fornecedor_escolhido = models.TextField(null=True, blank=True)

    status = models.CharField(max_length=100, default='Em análise')

    solicitante = models.CharField(max_length=50, null=True, blank=True)

    @property
    def forma_pagamento_label(self):
        return _forma_pagamento_label(self)

    def __str__(self):
        return _solicitacao_label(self)


# ---------------------------------------
# Solicitação de Prospecção de fornecedor
# ---------------------------------------
class SolicitacaoProspeccao(BusinessValidationMixin, EstadoSolicitacao):
    class Meta:
        permissions = [
            ("arquivar_solicitacaoprospeccao", "Pode arquivar e desarquivar prospecções"),
            ("cancelar_solicitacaoprospeccao", "Pode cancelar prospecções"),
        ]

    ACAO_CHOICES = [
        ('renegociar_valor', 'Renegociar Valor'),
        ('renegociar_prazo', 'Renegociar Prazo'),
        ('alterar_fornecedor', 'Selecionar outro Fornecedor'),
    ]
    APROVACAO_CHOICES = [
        ("pendente", "Pendente"),
        ("aprovado", "Aprovado"),
        ("reprovado", "Reprovado")
    ]
    FORMA_PAGAMENTO_CHOICES = [
        ("conforme_pagamento_cliente", "Conforme Pagamento do Cliente"),
        ("conforme_medicao_aprovada", "Conforme Medição Aprovada"),
        ("30", "30 dias"),
        ("60", "60 dias"),
        ("90", "90 dias"),
    ]

    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name='solicitacoes')
    coordenador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    lider_contrato = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"grupo__in": ["lider_contrato", "gerente_contrato", "gerente_lider"]},
        related_name="solicitacoes_lideradas",
    )
    descricao = models.TextField(blank=True, null=True)
    requisitos = models.TextField(blank=True, null=True)
    previsto_no_orcamento = models.BooleanField(default=False)
    justificativa_orcamento = models.TextField(blank=True, null=True)
    forma_pagamento = models.CharField(max_length=40, choices=FORMA_PAGAMENTO_CHOICES, null=True, blank=True, verbose_name="Forma de Pagamento")
    valor_disponivel = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    valor_provisionado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    valor_vendido = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    data_solicitacao = models.DateTimeField(auto_now_add=True)
    guarda_chuva = models.BooleanField(default=False, null=True, blank=True)
    justificativa_solicitacao = models.TextField(null=True, blank=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    cronograma = models.FileField(
        upload_to=CRONOGRAMA_UPLOAD_PATH,
        verbose_name='Inserir cronograma',
        null=True, blank=True,
        max_length=255,
    )

    aprovado = models.BooleanField(null=True, blank=True)
    data_aprovacao = models.DateTimeField(null=True, blank=True)
    aprovado_por = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="aprovacoes")

    fornecedores_selecionados = models.ManyToManyField(EmpresaTerceira, blank=True)
    triagem_realizada = models.BooleanField(default=False)
    aprovacao_fornecedor_gerente =  models.CharField(max_length=20, choices=APROVACAO_CHOICES, default="pendente")
    aprocacao_fornecedor_gerente_em = models.DateTimeField(null=True, blank=True)
    aprovacao_fornecedor_diretor =  models.CharField(max_length=20, choices=APROVACAO_CHOICES, default="pendente")
    aprocacao_fornecedor_diretor_em = models.DateTimeField(null=True, blank=True)

    nenhum_fornecedor_ideal = models.BooleanField(default=False)

    aprovacao_gerencia = models.BooleanField(default=False)
    reprovacao_gerencia = models.BooleanField(default=False)
    aprovacao_diretoria = models.BooleanField(default=False)
    justificativa_gerencia = models.TextField(null=True, blank=True)
    justificativa_diretoria = models.TextField(null=True, blank=True)
    acao_gerencia = models.CharField(max_length=100, null=True, blank=True, choices=ACAO_CHOICES)
    acao_diretoria = models.CharField(max_length=100, null=True, blank=True, choices=ACAO_CHOICES)

    #boletim_flag = models.BooleanField(default=False)
    observacao = models.TextField(null=True, blank=True)

    fornecedor_escolhido = models.ForeignKey(
        EmpresaTerceira,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='escolhido_em'
    )
    justificativa_fornecedor_escolhido = models.TextField(null=True, blank=True)

    status = models.CharField(max_length=100, default='Em análise')
    solicitacao_origem = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="revisoes"
    )
    solicitante = models.CharField(max_length=50, null=True, blank=True)

    @property
    def forma_pagamento_label(self):
        return _forma_pagamento_label(self)

    def __str__(self):
        return _solicitacao_label(self)


# ---------------------------------
# Proposta da empresa terceirizada
# ---------------------------------
class PropostaFornecedor(BusinessValidationMixin, models.Model):
    CONDICOES_CHOICES = [
        ('Conforme Medição Aprovada', 'Conforme Medição Aprovada'),
        ('Conforme Pagamento do Cliente', 'Conforme Pagamento do Cliente'),
        ('A definir', 'A definir'),
    ]

    solicitacao = models.ForeignKey(SolicitacaoProspeccao, on_delete=models.CASCADE, related_name="propostas", null=True, blank=True)
    solicitacao_contrato = models.ForeignKey(SolicitacaoContrato, on_delete=models.CASCADE, related_name="proposta", null=True, blank=True)
    fornecedor = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE)
    valor_proposta = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    condicao_pagamento = models.CharField(max_length=30, choices=CONDICOES_CHOICES, blank=True, null=True)
    prazo_validade = models.DateField(null=True, blank=True)
    arquivo_proposta = models.FileField(
        upload_to=ORCAMENTO_UPLOAD_PATH,
        verbose_name='Inserir Orçamento PDF',
        null=True, blank=True,
        max_length=255,
    )
    observacao = models.TextField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = ("solicitacao", "fornecedor")

    def __str__(self):
        if self.solicitacao is not None:
            return f"Proposta {self.fornecedor} - {self.solicitacao.contrato}"
        if self.solicitacao_contrato is not None:
            return f"Proposta {self.fornecedor} - {self.solicitacao_contrato.contrato}"


# --------------------------
# Solicitação de Contratação
# --------------------------
class TriagemFornecedor(BusinessValidationMixin, models.Model):
    solicitacao = models.ForeignKey(SolicitacaoProspeccao, on_delete=models.CASCADE, related_name="triagens")
    fornecedor = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE)
    selecionado = models.BooleanField(default=False)


# --------------------------
# Contrato com terceiro
# --------------------------
class ContratoTerceiros(BusinessValidationMixin, models.Model):
    STATUS_CHOICES = [
        ('em_elaboracao', 'Em elaboração'),
        ('aguardando_assinatura', 'Aguardando assinatura'),
        ('ativo', 'Ativo'),
        ('suspenso', 'Suspenso'),
        ('encerrado', 'Encerrado'),
    ]

    cod_projeto = models.ForeignKey(Contrato, on_delete=models.CASCADE, null=True, blank=True)
    num_contrato = models.CharField(max_length=30, null=True, blank=True)
    prospeccao = models.OneToOneField(SolicitacaoProspeccao, on_delete=models.SET_NULL, null=True, blank=True)
    solicitacao = models.OneToOneField(SolicitacaoContrato, on_delete=models.SET_NULL, null=True, blank=True)
    empresa_terceira = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE, related_name='contratos')
    coordenador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name="contratos_coordenados",
    )
    coordenadores = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="contratos_fornecedor_como_coordenador",
        limit_choices_to={"grupo": "coordenador"},
    )
    lider_contrato = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"grupo__in": ["lider_contrato", "gerente_contrato", "gerente_lider"]},
        related_name="contratos_liderados_terceiros"
    )
    guarda_chuva = models.BooleanField(default=False, null=True, blank=True)
    condicao_pagamento = models.CharField(max_length=80, null=True, blank=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    objeto = models.TextField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='em_elaboracao')
    ocultar_home_contrato_vencido = models.BooleanField(default=False)
    observacao = models.TextField(null=True, blank=True)

    num_contrato_arquivo = models.FileField(
        upload_to=CONTRACT_SUPPLIER_UPLOAD_PATH,
        verbose_name='Inserir arquivo do contrato com fornecedor',
        null=True, blank=True,
        max_length=255,
    )

    @property
    def referencia_coordenador(self):
        if self.guarda_chuva and self.cod_projeto:
            return self.cod_projeto.coordenador
        return self.coordenador

    @property
    def referencia_lider_contrato(self):
        if self.guarda_chuva and self.cod_projeto:
            return self.cod_projeto.lider_contrato
        return self.lider_contrato

    @property
    def referencia_todos_coordenadores(self):
        if self.guarda_chuva and self.cod_projeto:
            if hasattr(self.cod_projeto, "todos_coordenadores"):
                return self.cod_projeto.todos_coordenadores
            coordenadores = []
            if self.cod_projeto.coordenador:
                coordenadores.append(self.cod_projeto.coordenador)
            return coordenadores
        return self.todos_coordenadores

    @property
    def referencia_coordenadores_display(self):
        nomes = [
            coordenador.get_full_name() or coordenador.username
            for coordenador in self.referencia_todos_coordenadores
        ]
        return ", ".join(nomes)

    @property
    def dias_para_vencer(self):
        data_vencimento = getattr(self, "data_vencimento_home", None) or self.data_fim
        if data_vencimento:
            return (data_vencimento - timezone.localdate()).days
        return None

    @property
    def dias_vencido(self):
        if self.dias_para_vencer is not None and self.dias_para_vencer < 0:
            return abs(self.dias_para_vencer)
        return 0

    def save(self, *args, **kwargs):
        if self.guarda_chuva:
            self.coordenador = None
            if not getattr(self, "_preserve_lider_contrato_for_guarda_chuva", False):
                self.lider_contrato = None
        super().save(*args, **kwargs)
        if self.guarda_chuva:
            self.coordenadores.clear()
        elif self.coordenador_id:
            self.coordenadores.add(self.coordenador_id)

    @property
    def todos_coordenadores(self):
        coordenadores = list(self.coordenadores.all())
        if self.coordenador and self.coordenador not in coordenadores:
            coordenadores.insert(0, self.coordenador)
        return coordenadores

    @property
    def coordenadores_display(self):
        nomes = [
            coordenador.get_full_name() or coordenador.username
            for coordenador in self.todos_coordenadores
        ]
        return ", ".join(nomes)

    def __str__(self):
        if self.guarda_chuva:
            return f"{self.empresa_terceira}"
        else:
            return f"{self.cod_projeto} - {self.empresa_terceira}"

    @property
    def eventos(self):
        return Evento.objects.filter(contrato_terceiro=self)

    @property
    def entregas_total(self):
        return self.eventos.filter(realizado=True).count()

    @property
    def entregas_conformes(self):
        return self.eventos.filter(avaliacao="Aprovado").count()

    @property
    def entregas_nao_conformes(self):
        return self.eventos.filter(avaliacao="Reprovado").count()

    @property
    def IQ(self):
        """Índice de Qualidade"""
        total = self.entregas_total
        conformes = self.entregas_conformes
        return (conformes / total * 100) if total > 0 else 0

    @property
    def entregas_pontuais(self):
        return self.eventos.filter(
            data_prevista__isnull=False,
            data_entrega__lte=models.F("data_prevista")
        ).count()

    @property
    def IP(self):
        """Índice de Pontualidade"""
        total = self.entregas_total
        pontuais = self.entregas_pontuais
        return (pontuais / total * 100) if total > 0 else 0

    @property
    def INC(self):
        """Índice de Entregas Não Conformes"""
        total = self.entregas_total
        nao_conformes = self.entregas_nao_conformes
        return (nao_conformes / total * 100) if total > 0 else 0

    @property
    def IS_gestao(self):
        average = AvaliacaoFornecedor.objects.filter(contrato_terceiro=self).aggregate(average=models.Avg("nota_gestao"))["average"]
        return (average / 5) * 100 if average is not None else 0

    @property
    def IS_tecnica(self):
        average = AvaliacaoFornecedor.objects.filter(contrato_terceiro=self).aggregate(average=models.Avg("nota_tecnica"))["average"]
        return (average / 5) * 100 if average is not None else 0

    @property
    def IS_entrega(self):
        average = AvaliacaoFornecedor.objects.filter(contrato_terceiro=self).aggregate(average=models.Avg("nota_entrega"))["average"]
        return (average / 5) * 100 if average is not None else 0


# ---------------------------
# Solicitação de Ordens de Serviços para Contratos Guarda-chuvas
# ---------------------------
class SolicitacaoOrdemServico(BusinessValidationMixin, EstadoSolicitacao):
    class Meta:
        permissions = [
            ("arquivar_solicitacaoordemservico", "Pode arquivar e desarquivar solicitações de OS"),
            ("cancelar_solicitacaoordemservico", "Pode cancelar solicitações de OS"),
        ]

    STATUS_CHOICES = [
        ('solicitacao_os', 'Solicitação de OS'),
        ('pendente_lider', 'Pendente Líder'),
        ('pendente_gerente', 'Pendente Gerente'),
        ('pendente_diretoria', 'Pendente Diretoria'),
        ('pendente_minuta_gerente', 'Pendente Avaliação da Minuta'),
        ('pendente_suprimento', 'Pendente Suprimento'),
        ('aprovada', 'Aprovada'),
        ('reprovada', 'Reprovada'),
        ('finalizada', 'Finalizada'),
        ('cancelada', 'Cancelada'),
    ]

    contrato = models.ForeignKey(
        ContratoTerceiros,
        on_delete=models.CASCADE,
        related_name='ordens_servico',
        limit_choices_to={'guarda_chuva': True}
    )
    cod_projeto = models.ForeignKey(Contrato, on_delete=models.CASCADE, null=True, blank=True)
    solicitante = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ordens_solicitantes")
    lider_contrato = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"grupo__in": ["lider_contrato", "gerente_lider", "gerente_contrato"]},
        related_name="ordens_liderados_terceiros"
    )
    coordenador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="os_coordenados",
    )
    titulo = models.CharField(max_length=200)
    descricao = models.TextField()
    valor_previsto = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    data_prevista_pagamento = models.DateField(null=True, blank=True)
    prazo_execucao = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='solicitacao_os')
    criado_em = models.DateTimeField(auto_now_add=True)

    aprovacao_lider = models.CharField(max_length=100, null=True, blank=True)
    aprovado_lider_em =models.DateTimeField(null=True, blank=True)
    justificativa_reprovacao_lider = models.TextField(null=True, blank=True)

    arquivo_os = models.FileField(
        upload_to=SOLICITACAO_OS_UPLOAD_PATH,
        verbose_name='Inserir arquivo da Ordem de Serviço',
        null=True, blank=True,
        max_length=255,
    )
    aprovacao_gerente = models.CharField(max_length=100, null=True, blank=True)
    aprovado_gerente_em =models.DateTimeField(null=True, blank=True)
    justificativa_reprovacao_gerente = models.TextField(null=True, blank=True)

    aprovacao_diretor = models.CharField(max_length=100, null=True, blank=True)
    aprovado_diretor_em =models.DateTimeField(null=True, blank=True)
    justificativa_reprovacao_diretor = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Solicitação {self.id} - {self.titulo} - {self.contrato.empresa_terceira}"


# ---------------------------
# ordem de Serviço
# ---------------------------
class OS(BusinessValidationMixin, models.Model):
    def clean(self):
        super().clean()
        from .os_integrity import validate_os_identity
        validate_os_identity(self)

    def save(self, *args, **kwargs):
        from .os_integrity import validate_os_identity, os_identity_transaction
        with os_identity_transaction(self, using=kwargs.get("using")):
            validate_os_identity(self, using=kwargs.get("using"), update_fields=kwargs.get("update_fields"))
            return super().save(*args, **kwargs)

    @property
    def nf_paid(self):
        return Decimal(getattr(self,'nf_paid_centavos',0))/100
    STATUS_CHOICES = [
        ('em_execucao', "Em Execução"),
        ('paralizada', "Paralizada"),
        ('cancelada', "Cancelada"),
        ('finalizada', "Finalizada")
    ]
    AVALIACAO_CHOICES = [
        ('Aprovado', 'Aprovado'),
        ('Reprovado', 'Reprovado'),
    ]

    contrato = models.ForeignKey(
        ContratoTerceiros,
        on_delete=models.CASCADE,
        related_name='os_cadastrada',
        limit_choices_to={'guarda_chuva': True}
    )
    solicitacao = models.ForeignKey(SolicitacaoOrdemServico, on_delete=models.CASCADE, null=True, blank=True)
    cod_projeto = models.ForeignKey(Contrato, on_delete=models.CASCADE)
    coordenador = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ordens_coordenador",
    )
    lider_contrato = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"grupo__in": ["lider_contrato", "gerente_contrato", "gerente_lider"]},
        related_name="ordens"
    )
    titulo = models.CharField(max_length=200)
    descricao = models.TextField()
    valor = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    data_prevista_pagamento = models.DateField(null=True, blank=True)
    prazo_execucao = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='em_execucao')
    criado_em = models.DateTimeField(auto_now_add=True)
    arquivo_os = models.FileField(
        upload_to=OS_UPLOAD_PATH,
        verbose_name='Inserir arquivo da Ordem de Serviço',
        null=True, blank=True,
        max_length=255,
    )

    # registro da entrega
    caminho_evidencia = models.CharField(max_length=260, null=True, blank=True)
    avaliacao = models.CharField(max_length=30, choices=AVALIACAO_CHOICES, null=True, blank=True)
    data_entrega = models.DateField(null=True, blank=True)
    realizado = models.BooleanField(default=False)
    com_atraso = models.BooleanField(default=False)
    valor_pago = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    data_pagamento = models.DateField(null=True, blank=True)
    observacao = models.TextField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["solicitacao"], condition=models.Q(solicitacao__isnull=False),
            name="unique_os_por_solicitacao",
        )]

    @property
    def dias_atraso(self):
        if self.prazo_execucao and self.prazo_execucao < timezone.localdate():
            return (timezone.localdate() - self.prazo_execucao).days
        return 0
    def __str__(self):
        return f"OS {self.id} - {self.titulo} - {self.contrato.empresa_terceira}"


# ---------------------------
# Indicadores do fornecedor
# ---------------------------
class Evento(BusinessValidationMixin, models.Model):
    @property
    def nf_paid(self):
        return Decimal(getattr(self,'nf_paid_centavos',0))/100
    AVALIACAO_CHOICES = [
        ('Aprovado', 'Aprovado'),
        ('Reprovado', 'Reprovado'),
    ]
    empresa_terceira = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE, null=True, blank=True)
    prospeccao = models.ForeignKey(SolicitacaoProspeccao, on_delete=models.CASCADE, null=True, blank=True)
    solicitacao_contrato = models.ForeignKey(SolicitacaoContrato, on_delete=models.CASCADE, null=True, blank=True)
    contrato_terceiro = models.ForeignKey(ContratoTerceiros, on_delete=models.CASCADE, null=True, blank=True)
    aditivo = models.ForeignKey("AditivoContratoTerceiro", on_delete=models.CASCADE, null=True, blank=True, related_name="eventos")
    arquivo = models.FileField(
        upload_to=EVENTO_EVIDENCIA_UPLOAD_PATH,
        verbose_name='Inserir arquivo para comprovação de entrega',
        null=True, blank=True,
        max_length=255,
    )
    caminho_evidencia = models.CharField(max_length=260, null=True, blank=True)
    descricao = models.TextField()
    justificativa = models.TextField(null=True, blank=True)
    avaliacao = models.CharField(max_length=30, choices=AVALIACAO_CHOICES, null=True, blank=True)
    data_prevista = models.DateField(null=True, blank=True)  # limite para entrega
    data_entrega = models.DateField(null=True, blank=True)       # data real da entrega
    realizado = models.BooleanField(default=False)
    com_atraso = models.BooleanField(default=False)
    valor_previsto = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    valor_pago = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    data_prevista_pagamento = models.DateField(null=True, blank=True)
    data_pagamento = models.DateField(null=True, blank=True)
    observacao = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def dias_atraso(self):
        if self.data_prevista and not self.data_entrega:
            return (timezone.localdate() - self.data_prevista).days
        return 0

    @property
    def dias_para_entrega(self):
        if self.data_prevista:
            return (self.data_prevista - timezone.localdate()).days
        return None

    @property
    def dias_sem_avaliacao(self):
        if self.data_entrega:
            return (timezone.localdate() - self.data_entrega).days
        return 0

    @property
    def fornecedor_display(self):
        fornecedor = (
            self.empresa_terceira
            or getattr(self.contrato_terceiro, "empresa_terceira", None)
            or getattr(self.prospeccao, "fornecedor_escolhido", None)
            or getattr(self.solicitacao_contrato, "fornecedor_escolhido", None)
        )
        return str(fornecedor) if fornecedor else "-"

    def __str__(self):
        return f"Entrega {self.id} - {self.contrato_terceiro or '-'} - {self.fornecedor_display}"


class AvaliacaoFornecedor(BusinessValidationMixin, models.Model):
    empresa_terceira = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE)
    contrato_terceiro = models.ForeignKey(ContratoTerceiros, on_delete=models.CASCADE)
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, blank=True, null=True, related_name="avaliacoes")
    os = models.ForeignKey(OS, on_delete=models.CASCADE, blank=True, null=True, related_name="avaliacoes")
    area_avaliadora = models.CharField(max_length=100)
    avaliador = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    nota_gestao = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], null=True, blank=True)
    nota_tecnica = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], null=True, blank=True)
    nota_entrega = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], null=True, blank=True)
    comentario = models.TextField(blank=True, null=True)
    data_avaliacao = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"Avaliação {self.id} - {self.empresa_terceira}"


class Indicadores(BusinessValidationMixin, models.Model):
    empresa_terceira = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.empresa_terceira}"

    @property
    def entregas_total(self):
        return Evento.objects.filter(empresa_terceira=self.empresa_terceira,realizado=True).count()

    @property
    def entregas_conformes(self):
        return Evento.objects.filter(
            empresa_terceira=self.empresa_terceira,
            avaliacao='Aprovado'
        ).count()

    @property
    def entregas_nao_conformes(self):
        return Evento.objects.filter(
            empresa_terceira=self.empresa_terceira,
            avaliacao='Reprovado'
        ).count()

    @property
    def IQ(self):
        total = self.entregas_total
        conformes = self.entregas_conformes
        return (conformes / total) * 100 if total > 0 else 0

    @property
    def entregas_pontuais(self):
        return Evento.objects.filter(
            empresa_terceira=self.empresa_terceira,
            data_prevista__isnull=False,
            data_entrega__lte=models.F('data_prevista')
        ).count()

    @property
    def IP(self):
        total = self.entregas_total
        pontuais = self.entregas_pontuais
        return (pontuais / total) * 100 if total > 0 else 0

    @property
    def INC(self):
        nao_conforme = self.entregas_nao_conformes
        total = self.entregas_total
        return (nao_conforme / total) * 100 if total > 0 else 0

    @property
    def IS_gestao(self):
        average = AvaliacaoFornecedor.objects.filter(empresa_terceira=self.empresa_terceira).aggregate(average=models.Avg("nota_gestao"))["average"]
        return (average / 5) * 100 if average is not None else 0

    @property
    def IS_tecnica(self):
        average = AvaliacaoFornecedor.objects.filter(empresa_terceira=self.empresa_terceira).aggregate(average=models.Avg("nota_tecnica"))["average"]
        return (average / 5) * 100 if average is not None else 0

    @property
    def IS_entrega(self):
        average = AvaliacaoFornecedor.objects.filter(empresa_terceira=self.empresa_terceira).aggregate(average=models.Avg("nota_entrega"))["average"]
        return (average / 5) * 100 if average is not None else 0


"""# ---------------------
# Aditivos contratuais (cliente)
# ---------------------
class Aditivo(BusinessValidationMixin, models.Model):
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name="aditivos")
    descricao = models.TextField()
    motivo = models.TextField(blank=True, null=True)
    valor_adicional = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    nova_data_fim = models.DateField(blank=True, null=True)
    data_registro = models.DateField(default=timezone.now)

    def __str__(self):
        return f"Aditivo - {self.contrato.cod_projeto}"


# ----------------------------------
# Aditivos contratuais de terceiros
# ----------------------------------
class AditivoTerceiro(BusinessValidationMixin, models.Model):
    contrato = models.ForeignKey(ContratoTerceiros, on_delete=models.CASCADE, related_name="aditivos")
    descricao = models.TextField()
    motivo = models.TextField(blank=True, null=True)
    valor_adicional = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    nova_data_fim = models.DateField(blank=True, null=True)
    data_registro = models.DateField(default=timezone.now)

    def __str__(self):
        return f"Aditivo - {self.contrato.cod_projeto} - {self.contrato.empresa_terceira}"

"""
# -------------
# Documento BM
# -------------
class DocumentoBM(BusinessValidationMixin, models.Model):
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('aprovado', 'Aprovado'),
        ('reprovado', 'Reprovado'),
    ]
    solicitacao = models.OneToOneField(SolicitacaoProspeccao, on_delete=models.CASCADE, related_name="minuta_boletins_medicao", null=True, blank=True)
    solicitacao_contrato = models.OneToOneField(SolicitacaoContrato, on_delete=models.CASCADE, related_name="minuta_boletins_medicao_contrato", null=True, blank=True)
    minuta_boletim = models.FileField(
        upload_to=MINUTA_BM_UPLOAD_PATH,
        blank=True,
        null=True,
        max_length=255,
    )
    minuta_boletim_assinado = models.FileField(
        upload_to=MINUTA_BM_ASSINADO_UPLOAD_PATH,
        blank=True,
        null=True,
        max_length=255,
    )

    status_coordenador = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendente')
    data_aprovacao_coordenador = models.DateTimeField(null=True, blank=True)
    status_gerente = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendente')
    data_aprovacao_gerente = models.DateTimeField(null=True, blank=True)

    observacao = models.TextField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.solicitacao and self.solicitacao.contrato:
            return f"Boletim de Medição - {self.solicitacao.contrato.cod_projeto}"

        if self.solicitacao_contrato and self.solicitacao_contrato.contrato:
            return f"Boletim de Medição - {self.solicitacao_contrato.contrato.cod_projeto}"

        return "Boletim de Medição"

    @property
    def aprovado_por_ambos(self):
        return self.status_coordenador == "aprovado" and self.status_gerente == "aprovado"

    @property
    def aprovado_gerente(self):
        return self.status_gerente == "aprovado"

    @property
    def status_avaliacao(self):
        if self.status_gerente != "pendente":
            return self.status_gerente
        return self.status_coordenador

    @property
    def aprovado(self):
        return self.status_avaliacao == "aprovado"

    @property
    def reprovado_por_alguem(self):
        return self.status_coordenador == "reprovado" or self.status_gerente == "reprovado"
# ------
# BM (Boletim de Medição) - contrato de terceiros
# ------
class BM(BusinessValidationMixin, models.Model):
    @property
    def nf_paid(self):
        return Decimal(getattr(self,'nf_paid_centavos',0))/100
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('aprovado', 'Aprovado'),
        ('reprovado', 'Reprovado'),
    ]
    status_lider_documental=models.CharField(max_length=20,choices=STATUS_CHOICES,null=True,blank=True,editable=False)
    aprovador_lider_documental=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+',db_index=False,editable=False)
    data_lider_documental=models.DateTimeField(null=True,blank=True,editable=False)
    justificativa_lider_documental=models.TextField(null=True,blank=True,editable=False)
    status_lider_financeiro=models.CharField(max_length=20,choices=STATUS_CHOICES,null=True,blank=True,editable=False)
    aprovador_lider_financeiro=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+',db_index=False,editable=False)
    data_lider_financeiro=models.DateTimeField(null=True,blank=True,editable=False)
    justificativa_lider_financeiro=models.TextField(null=True,blank=True,editable=False)

    @property
    def aprovacoes_contratos(self):
        from .bm_approvals import rows
        return rows(self)

    @property
    def compartilhado_entre_contratos(self):
        from .bm_approvals import shared
        return shared(self)

    @property
    def aprovacao_operacional_completa(self):
        from .permissions import bm_has_valid_operational_approval
        return bm_has_valid_operational_approval(self)

    @property
    def versao_aprovacao(self):
        from .bm_approvals import version
        return version(self)
    contrato = models.ForeignKey(ContratoTerceiros, on_delete=models.PROTECT, related_name="boletins_medicao")
    evento = models.ForeignKey(Evento, on_delete=models.PROTECT, related_name='boletins_medicao', null=True, blank=True)
    os = models.ForeignKey(OS, on_delete=models.PROTECT, related_name='boletins_medicao', null=True, blank=True)
    numero_bm = models.PositiveIntegerField()
    valor_pago = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    parcela_paga = models.PositiveIntegerField()
    data_pagamento = models.DateField(default=timezone.now)
    data_inicial_medicao  = models.DateTimeField(null=True, blank=True)
    data_final_medicao = models.DateTimeField(null=True, blank=True)

    status_coordenador = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendente')
    data_aprovacao_coordenador = models.DateTimeField(null=True, blank=True)
    status_gerente = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendente')
    data_aprovacao_gerente = models.DateTimeField(null=True, blank=True)

    aprovacao_pagamento = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendente')
    data_aprovacao_diretor = models.DateTimeField(null=True, blank=True)

    justificativa_aprovacao_diretor = models.TextField(
        'Justificativa da aprovação de pagamento pela Diretoria',null=True,blank=True)

    justificativa_reprovacao_coordenador = models.TextField(
        null=True, blank=True,
        verbose_name="Justificativa da Reprovação do Coordenador"
    )
    justificativa_reprovacao_gerente = models.TextField(
        null=True, blank=True,
        verbose_name="Justificativa da Reprovação do Gerente"
    )

    justificativa_reprovacao_diretor = models.TextField(
        null=True, blank=True,
        verbose_name="Justificativa da Reprovação da Direção"
    )

    arquivo_bm = models.FileField(
        upload_to=BM_UPLOAD_PATH,
        verbose_name='Inserir arquivo do Boletim de Medição',
        null=True, blank=True,
        max_length=255,
    )
    observacao = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Parcela {self.parcela_paga} - {self.valor_pago}"

    @property
    def contrato_financeiro(self):
        """O Evento (ou OS) define a participação; contrato é o vínculo documental."""
        if self.evento_id:
            return self.evento.contrato_terceiro
        if self.os_id:
            return self.os.contrato
        return self.contrato

    @property
    def total_pago(self):
        """Soma as participações medidas do contrato financeiro, sem deduplicar arquivo."""
        from django.db.models import Sum
        contract = self.contrato_financeiro
        if contract is None:
            return Decimal('0.00')
        total = BM.objects.filter(
            models.Q(evento__contrato_terceiro=contract)
            | models.Q(os__contrato=contract)
            | models.Q(evento__isnull=True, os__isnull=True, contrato=contract)
        ).aggregate(Sum('valor_pago'))['valor_pago__sum']
        return total or Decimal('0.00')

    def clean(self):
        super().clean()
        if self.evento_id and self.os_id:
            raise ValidationError("Um BM deve referenciar evento ou OS, nunca ambos.")
        # Um BM pode documentar mais de um contrato. No vínculo cruzado,
        # a participação financeira continua pertencendo ao Evento.
        if self.os_id and self.os.contrato_id != self.contrato_id:
            raise ValidationError("A OS deve pertencer ao contrato do BM.")

    def save(self, *args, **kwargs):
        # DateField com default timezone.now começa como datetime em memória.
        # Normalize antes de comparar para não invalidar uma aprovação por tipo.
        self.data_pagamento = self._meta.get_field("data_pagamento").to_python(self.data_pagamento)
        self.clean()
        relevant = ["contrato_id", "evento_id", "os_id", "numero_bm", "parcela_paga",
                    "valor_pago", "data_pagamento", "data_inicial_medicao",
                    "data_final_medicao", "arquivo_bm"]
        if self.pk:
            old = BM.objects.filter(pk=self.pk).first()
            def comparable(instance, key):
                value = getattr(instance, key)
                return (value.name or "") if key == "arquivo_bm" else value
            if old and any(comparable(old, key) != comparable(self, key) for key in relevant):
                reset = []
                from .bm_approvals import FIELDS
                for field in FIELDS:
                    setattr(self,field,None)
                    reset.append(field)
                for field in ["status_coordenador", "status_gerente", "aprovacao_pagamento"]:
                    setattr(self, field, "pendente")
                    reset.append(field)
                for field in ["data_aprovacao_coordenador", "data_aprovacao_gerente",
                              "data_aprovacao_diretor", "justificativa_reprovacao_coordenador",
                              "justificativa_reprovacao_gerente", "justificativa_reprovacao_diretor",
                              "justificativa_aprovacao_diretor"]:
                    setattr(self, field, None)
                    reset.append(field)
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | set(reset)
        super().save(*args, **kwargs)


class MedicaoRecebimentoBM(models.Model):
    """Informação do Financeiro, independente da medição e de suas aprovações."""
    bm = models.OneToOneField(BM, on_delete=models.CASCADE, related_name='medicao_recebimento')
    sobre_medicao = models.TextField('Sobre medição', max_length=4000)
    sobre_medicao_recebimento = models.TextField('Sobre medição e recebimento', max_length=4000)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+', editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+', editable=False)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Medição e recebimento do BM'
        verbose_name_plural = 'Informações de medição e recebimento dos BMs'
        constraints = [models.CheckConstraint(
            condition=~models.Q(sobre_medicao='') & ~models.Q(sobre_medicao_recebimento=''),
            name='bm_medicao_recebimento_textos_preenchidos')]

    def __str__(self):
        return f'Medição e recebimento do BM #{self.bm_id}'

    @staticmethod
    def identificar(usuario):
        return f'{usuario.get_full_name() or usuario.username} (@{usuario.username})'

    @property
    def identificacao_criador(self):
        return self.identificar(self.criado_por)

    @property
    def identificacao_editor(self):
        return self.identificar(self.atualizado_por)

    @property
    def texto_exportacao(self):
        return '\n'.join([
            f'Sobre medição: {self.sobre_medicao}',
            f'Sobre medição e recebimento: {self.sobre_medicao_recebimento}',
        ])


class NF(BusinessValidationMixin, models.Model):
    vencimento_original=models.DateField(null=True,blank=True)
    cancelada_em=models.DateTimeField(null=True,blank=True,editable=False)
    cancelada_por=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+',editable=False)
    motivo_cancelamento=models.TextField(blank=True,default='',editable=False)
    numero_nf = models.CharField('Número da NF', max_length=64, null=True, blank=True, db_index=True)
    serie = models.CharField('Série', max_length=32, null=True, blank=True)
    data_emissao = models.DateField('Data de emissão', null=True, blank=True)
    chave_acesso = models.CharField('Chave de acesso (quando aplicável)', max_length=120, null=True, blank=True, db_index=True)
    tipo_documento = models.CharField('Tipo de documento fiscal', max_length=40, null=True, blank=True)
    comprovante_pagamento = models.FileField('Comprovante de pagamento',
        upload_to=ShortenedUploadPath('NF/Comprovantes', 'comprovante'), null=True, blank=True,
        max_length=255, validators=[validate_upload])
    contrato = models.ForeignKey(ContratoTerceiros, on_delete=models.PROTECT, related_name="nota_fiscal")
    evento = models.ForeignKey(Evento, on_delete=models.PROTECT, related_name='nota_fiscal', null=True, blank=True)
    os = models.ForeignKey(OS, on_delete=models.PROTECT, related_name='nota_fiscal', null=True, blank=True)
    bm = models.ForeignKey(BM, on_delete=models.PROTECT, related_name='nota_fiscal', blank=True, null=True)
    valor_pago = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    parcela_paga = models.PositiveIntegerField()
    data_pagamento = models.DateField(default=timezone.now)
    arquivo_nf = models.FileField(
        upload_to=NF_FORNECEDOR_UPLOAD_PATH,
        verbose_name='Inserir arquivo da Nota Fiscal',
        null=True, blank=True,
        max_length=255,
    )
    observacao = models.TextField(null=True, blank=True)
    financeiro_autorizou = models.BooleanField(default=False)
    nf_dentro_prazo = models.BooleanField(default=False)

    def clean(self):
        super().clean()
        # O schema permanece nullable para compatibilidade com históricos.
        from .payment_queries import cents
        try:cents(self.valor_pago)
        except (ValueError,ArithmeticError) as error:raise ValidationError({'valor_pago':str(error)}) from error
        if self.comprovante_pagamento and not self.comprovante_pagamento._committed:
            validate_upload(self.comprovante_pagamento.file)
        # Novos registros e edições exigem o vínculo, inclusive fora dos forms.
        if not self.bm_id:
            raise ValidationError({"bm": "Toda NF de fornecedor deve estar vinculada a um BM."})
        if self.evento_id and self.os_id:
            raise ValidationError("Uma NF deve referenciar evento ou OS, nunca ambos.")
        if self.evento_id and self.evento.contrato_terceiro_id != self.contrato_id:
            raise ValidationError("O evento deve pertencer ao contrato da NF.")
        if self.os_id and self.os.contrato_id != self.contrato_id:
            raise ValidationError("A OS deve pertencer ao contrato da NF.")
        if self.bm_id and (self.bm.contrato_financeiro is None
                           or self.bm.contrato_financeiro.pk != self.contrato_id
                           or self.bm.evento_id != self.evento_id or self.bm.os_id != self.os_id):
            raise ValidationError("O BM deve pertencer à mesma origem e contrato da NF.")

    def save(self, *args, **kwargs):
        self.clean()
        from .financial_audit import financial_audit_context, validate_nf_save
        from .middleware import get_current_user, get_current_request
        request = get_current_request()
        if request is None and not hasattr(self, '_audit_user') and not hasattr(self, '_audit_reason'):
            validate_nf_save(self)
            return super().save(*args, **kwargs)
        user = getattr(self, '_audit_user', None) or get_current_user()
        reason = getattr(self, '_audit_reason', None)
        if reason is None:
            reason = request.POST.get('justificativa_correcao', '') if request else ''
        with financial_audit_context(user, reason):
            validate_nf_save(self)
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from .financial_audit import financial_audit_context
        from .middleware import get_current_user, get_current_request
        request = get_current_request()
        if self.movimentos.exists() or self.programacoes.exists() or self.reprogramacoes.exists():
            from .payment_services import cancel_invoice
            import json
            from .financial_audit import metadata
            info=json.loads(metadata())
            user=getattr(self,'_audit_user',None) or get_current_user() or (User.objects.filter(pk=info.get('usuario_id')).first() if info.get('usuario_id') else None)
            reason=getattr(self,'_audit_reason',None) or info.get('justificativa','')
            cancel_invoice(nf_id=self.pk,user=user,motivo=reason)
            self.refresh_from_db()
            return 0,{}
        if request is None and not hasattr(self, '_audit_user') and not hasattr(self, '_audit_reason'):
            return super().delete(*args, **kwargs)
        user = getattr(self, '_audit_user', None) or get_current_user()
        reason = getattr(self, '_audit_reason', None)
        if reason is None:
            reason = request.POST.get('justificativa_correcao', '') if request else ''
        with financial_audit_context(user, reason):
            return super().delete(*args, **kwargs)

    def __str__(self):
        referencia = None
        if self.evento:
            referencia = f"{self.evento.descricao} (id - {self.evento.id})"
        elif self.os:
            referencia = f"{self.os.titulo} (OS - {self.os.id})"
        else:
            referencia = "Sem referência"
        return f"Nota Fiscal {self.id} - {referencia}"

    @property
    def total_pago(self):
        from .payment_queries import invoice_paid_cents,money
        return money(invoice_paid_cents(self))

    def refresh_from_db(self,*args,**kwargs):
        for key in list(self.__dict__):
            if key.startswith('ledger_'):self.__dict__.pop(key,None)
        return super().refresh_from_db(*args,**kwargs)

    @property
    def saldo_pendente(self):
        return Decimal('0') if self.cancelada_em else self.valor_pago-self.total_pago

    @property
    def possui_pagamentos(self):
        return getattr(self,'ledger_has_payments',None) if hasattr(self,'ledger_has_payments') else self.movimentos.exists()

    @property
    def possui_historico_financeiro(self):
        return self.possui_pagamentos or (self.ledger_has_program_history if hasattr(self,'ledger_has_program_history') else self.programacoes.exists()) or (self.ledger_renegotiated if hasattr(self,'ledger_renegotiated') else self.reprogramacoes.exists())

    @property
    def situacao_liquidacao(self):
        paid=self.total_pago
        return 'Integralmente paga' if paid>0 and paid==self.valor_pago else 'Parcialmente paga' if paid>0 else 'Não paga'


# -------------
# Nota Fiscal para o Cliente
#--------------
class NFCliente(BusinessValidationMixin, models.Model):
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, related_name="nota_fiscal")
    valor_pago = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    parcela_paga = models.PositiveIntegerField()
    data_emissao = models.DateField(default=timezone.now)
    data_pagamento = models.DateField(default=timezone.now)
    arquivo_nf = models.FileField(
        upload_to=NF_CLIENTE_UPLOAD_PATH,
        verbose_name='Inserir arquivo da Nota Fiscal',
        null=True, blank=True,
        max_length=255,
    )
    observacao = models.TextField(null=True, blank=True)
    inserido_por = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True)

    def __str__(self):
        return f"Nota Fiscal {self.id} - Parcela {self.parcela_paga} - {self.contrato}"


# -----------
# Documentos (cliente)
# -----------
class DocumentoContrato(BusinessValidationMixin, models.Model):
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name="documentos")
    arquivo = models.FileField(upload_to=DOCUMENTO_CONTRATO_UPLOAD_PATH, max_length=255)
    descricao = models.CharField(max_length=200, blank=True, null=True)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name='documentos_contrato_enviados'
    )
    data_envio = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Documento {self.id} - {self.contrato.cod_projeto}"


# -----------
# Documentos (terceiros)
# -----------
class DocumentoContratoTerceiro(BusinessValidationMixin, models.Model):
    solicitacao = models.OneToOneField(SolicitacaoProspeccao, on_delete=models.CASCADE, related_name="contrato_relacionado", null=True, blank=True)
    solicitacao_contrato = models.OneToOneField(SolicitacaoContrato, on_delete=models.CASCADE, related_name="minuta_contrato", null=True, blank=True)
    numero_contrato = models.CharField(max_length=100, unique=True)
    objeto = models.TextField()
    prazo_inicio = models.DateField()
    prazo_fim = models.DateField()
    valor_total = models.DecimalField(max_digits=12, decimal_places=2)
    arquivo_contrato = models.FileField(
        upload_to=MINUTA_CONTRATO_UPLOAD_PATH,
        verbose_name="Contrato em PDF",
        null=True, blank=True,
        max_length=255,
    )
    arquivo_contrato_assinado = models.FileField(
        upload_to=CONTRATO_ASSINADO_UPLOAD_PATH,
        verbose_name="Contrato assinado em PDF",
        null=True, blank=True,
        max_length=255,
    )
    observacao = models.TextField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.solicitacao and self.solicitacao.contrato:
            return f"Contrato {self.numero_contrato} - {self.solicitacao.contrato}"

        if self.solicitacao_contrato and self.solicitacao_contrato.contrato:
            return f"Contrato {self.numero_contrato} - {self.solicitacao_contrato.contrato}"

        return f"Contrato {self.numero_contrato}"



class CalendarioPagamento(BusinessValidationMixin, models.Model):
    data_pagamento = models.DateField(unique=True)
    observacao = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.data_pagamento.strftime('%d/%m/%Y')


class RegistroAuditoria(BusinessValidationMixin, models.Model):
    operacao_financeira = models.CharField(max_length=40, null=True, blank=True, db_index=True)
    estado_anterior = models.JSONField(null=True, blank=True)
    estado_posterior = models.JSONField(null=True, blank=True)
    justificativa = models.TextField(null=True, blank=True)
    autor_nome = models.CharField(max_length=255, null=True, blank=True)
    autor_grupo = models.CharField(max_length=50, null=True, blank=True)
    ACAO_CHOICES = [
        ("criado", "Criado"),
        ("atualizado", "Atualizado"),
    ]

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    acao = models.CharField(max_length=20, choices=ACAO_CHOICES)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registros_auditoria",
    )
    modelo = models.CharField(max_length=100)
    representacao_objeto = models.CharField(max_length=255)
    detalhes = models.TextField(blank=True, null=True)
    data_hora = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-data_hora"]
        indexes = [models.Index(fields=['content_type','object_id','-data_hora'],name='financial_object_history_idx')]

    def __str__(self):
        return f"{self.get_acao_display()} - {self.modelo} #{self.object_id}"


class ConfiguracaoSLA(BusinessValidationMixin, models.Model):
    TIPO_FLUXO_CHOICES = [
        ("prospeccao", "Prospeccao"),
        ("contratacao", "Contratacao"),
        ("aditivo", "Aditivo"),
        ("os", "Ordem de Servico"),
        ("bm", "Boletim de Medicao"),
    ]

    tipo_fluxo = models.CharField(max_length=30, choices=TIPO_FLUXO_CHOICES)
    etapa = models.CharField(max_length=100)
    nome_etapa = models.CharField(max_length=150)
    ordem = models.PositiveIntegerField(default=1)
    prazo_dias_uteis = models.PositiveIntegerField(default=1)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["tipo_fluxo", "ordem", "nome_etapa"]
        unique_together = ("tipo_fluxo", "etapa")
        verbose_name = "Configuracao de SLA"
        verbose_name_plural = "Configuracoes de SLA"

    def __str__(self):
        return f"{self.get_tipo_fluxo_display()} - {self.nome_etapa} ({self.prazo_dias_uteis} dias uteis)"


class Feriado(BusinessValidationMixin, models.Model):
    nome = models.CharField(max_length=150)
    data = models.DateField(unique=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["data", "nome"]
        verbose_name = "Feriado"
        verbose_name_plural = "Feriados"

    def __str__(self):
        return f"{self.nome} - {self.data.strftime('%d/%m/%Y')}"


class ChaveIdempotencia(models.Model):
    """Somente hashes técnicos; não armazena conteúdo de requisições."""
    chave = models.CharField(max_length=64, primary_key=True)
    expira_em = models.DateTimeField(db_index=True)


class AditivoContratoTerceiro(BusinessValidationMixin, EstadoSolicitacao):
    STATUS_CHOICES = [
        ("pendente", "Pendente"),
        ("aprovado", "Aprovado"),
        ("reprovado", "Reprovado"),
    ]

    contrato = models.ForeignKey(ContratoTerceiros, on_delete=models.CASCADE, related_name="aditivos")
    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="aditivos_solicitados_terceiros",
    )
    motivo = models.TextField()
    valor_total_anterior = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    novo_valor_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    data_fim_anterior = models.DateField(null=True, blank=True)
    nova_data_fim = models.DateField(null=True, blank=True)
    arquivo_aditivo = models.FileField(upload_to=ADITIVO_UPLOAD_PATH, null=True, blank=True, max_length=255)
    arquivo_aditivo_assinado = models.FileField(upload_to=ADITIVO_ASSINADO_UPLOAD_PATH, null=True, blank=True, max_length=255)
    documento_enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="aditivos_enviados_terceiros",
    )
    documento_enviado_em = models.DateTimeField(null=True, blank=True)
    documento_assinado_enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="aditivos_assinados_enviados_terceiros",
    )
    documento_assinado_enviado_em = models.DateTimeField(null=True, blank=True)
    status_lider = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pendente")
    data_aprovacao_lider = models.DateTimeField(null=True, blank=True)
    justificativa_reprovacao_lider = models.TextField(null=True, blank=True)
    status_gerente = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pendente")
    data_aprovacao_gerente = models.DateTimeField(null=True, blank=True)
    justificativa_reprovacao_gerente = models.TextField(null=True, blank=True)
    status_diretoria = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pendente")
    data_aprovacao_diretoria = models.DateTimeField(null=True, blank=True)
    justificativa_reprovacao_diretoria = models.TextField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em"]
        permissions = [
            ("arquivar_aditivocontratoterceiro", "Pode arquivar e desarquivar solicitações de aditivo"),
            ("cancelar_aditivocontratoterceiro", "Pode cancelar solicitações de aditivo"),
        ]

    @property
    def cancelada(self):
        return bool(self.cancelada_em)

    @property
    def status(self):
        """Rótulo derivado; as aprovações existentes continuam sendo a fonte da etapa."""
        return self.etapa_atual

    def __str__(self):
        return f"Aditivo {self.id} - {self.contrato.num_contrato or self.contrato.id}"

    @property
    def tem_documento(self):
        return bool(self.arquivo_aditivo)

    @property
    def tem_documento_assinado(self):
        return bool(self.arquivo_aditivo_assinado)

    @property
    def solicitacao_aprovada_totalmente(self):
        return self.status_gerente == "aprovado" and self.status_diretoria == "aprovado"

    @property
    def solicitacao_reprovada_por_alguem(self):
        return self.status_gerente == "reprovado" or self.status_diretoria == "reprovado"

    @property
    def minuta_aprovada(self):
        return self.status_lider == "aprovado" and self.tem_documento

    @property
    def minuta_reprovada(self):
        return self.status_lider == "reprovado"

    @property
    def reprovado_por_alguem(self):
        return self.solicitacao_reprovada_por_alguem or self.minuta_reprovada

    @property
    def aprovado_totalmente(self):
        return self.tem_documento_assinado

    @property
    def etapa_atual(self):
        if self.cancelada:
            return "Cancelada"
        if self.aprovado_totalmente:
            return "Concluido"
        if self.minuta_aprovada:
            return "Aguardando Documento Assinado"
        if self.tem_documento:
            if self.minuta_reprovada:
                return "Minuta Reprovada"
            return "Aguardando Aprovacao da Minuta"
        if self.solicitacao_aprovada_totalmente:
            return "Aguardando Minuta do Aditivo"
        if self.solicitacao_reprovada_por_alguem:
            return "Solicitacao Reprovada"
        return "Aguardando Aprovacao da Solicitacao"


# Entidades financeiras registradas no mesmo app, sem duplicar NF ou BM.
from .payment_models import PagamentoNF,ProgramacaoPagamento,ReprogramacaoPagamento
