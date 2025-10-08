from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.utils import timezone
from django.conf import settings


# --------------------
# Usuários com grupos
# --------------------
class User(AbstractUser):
    GRUPOS_CHOICES = [
        ('coordenador', 'Coordenador de Contrato'),
        ('gerente', 'Gerente'),
        ('diretoria', 'Diretoria'),
        ('financeiro', 'Financeiro'),
        ('suprimento', 'Suprimento'),
        ('terceiro', 'Terceiro'),
    ]

    grupo = models.CharField(max_length=20, choices=GRUPOS_CHOICES, blank=True, null=True)

    # Novo campo ManyToMany
    centros = models.ManyToManyField("CentroDeTrabalho", blank=True, related_name="usuarios")

    email = models.EmailField()

    # Evita conflito de acessores reversos com auth.User.*
    groups = models.ManyToManyField(Group, related_name="+", blank=True)
    user_permissions = models.ManyToManyField(Permission, related_name="+", blank=True)

    def __str__(self):
        return self.username


class CentroDeTrabalho(models.Model):
    codigo = models.CharField(max_length=10, unique=True)
    nome = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.nome} ({self.codigo})"


# -----------------
# Cliente
# -----------------
class Cliente(models.Model):
    nome = models.CharField(max_length=200)
    cpf_cnpj = models.CharField(max_length=18, unique=True)
    endereco = models.TextField(blank=True, null=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)

    def __str__(self):
        return self.nome


# -----------------
# Empresa Terceira
# -----------------
class EmpresaTerceira(models.Model):
    nome = models.CharField(max_length=200)
    setor_de_atuacao = models.TextField(blank=True, null=True)
    cpf_cnpj = models.CharField(max_length=18, unique=True)
    endereco = models.TextField(blank=True, null=True)
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

    def __str__(self):
        return self.nome


# ---------
# Proposta (interna)
# ---------
class Proposta(models.Model):
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

    def __str__(self):
        return f"Proposta {self.numero} - {self.cliente}"


# --------------------------
# Contrato com Cliente
# --------------------------
class Contrato(models.Model):
    STATUS_CHOICES = [
        ('em_elaboracao', 'Em elaboração'),
        ('aguardando_assinatura', 'Aguardando assinatura'),
        ('ativo', 'Ativo'),
        ('suspenso', 'Suspenso'),
        ('encerrado', 'Encerrado'),
    ]

    cod_projeto = models.CharField(max_length=50, unique=True)
    proposta = models.OneToOneField(Proposta, on_delete=models.SET_NULL, null=True, blank=True)
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    coordenador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        #limit_choices_to={'grupo': 'Coordenador de Contrato'},
        related_name="contratos_cliente_coordenados"  # evita conflito com contratos_coordenados
    )
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2)
    objeto = models.TextField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='em_elaboracao')

    def __str__(self):
        return f"Contrato {self.cod_projeto} - {self.cliente}"


# ---------------------------------------
# Solicitação de Prospecção de fornecedor
# ---------------------------------------
class SolicitacaoProspeccao(models.Model):
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

    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name='solicitacoes')
    coordenador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    descricao = models.TextField(blank=True, null=True)
    requisitos = models.TextField(blank=True, null=True)
    previsto_no_orcamento = models.BooleanField(default=False)
    valor_provisionado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    valor_vendido = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    data_solicitacao = models.DateTimeField(auto_now_add=True)
    cronograma = models.FileField(
        upload_to='cronograma/',
        verbose_name='Inserir cronograma',
        null=True, blank=True
    )

    aprovado = models.BooleanField(null=True, blank=True)
    data_aprovacao = models.DateTimeField(null=True, blank=True)
    aprovado_por = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="aprovacoes")

    fornecedores_selecionados = models.ManyToManyField(EmpresaTerceira, blank=True)
    triagem_realizada = models.BooleanField(default=False)
    aprovacao_fornecedor_gerente =  models.CharField(max_length=20, choices=APROVACAO_CHOICES, default="pendente")
    aprocacao_fornecedor_gerente_em = models.DateTimeField(null=True, blank=True)

    nenhum_fornecedor_ideal = models.BooleanField(default=False)

    aprovacao_gerencia = models.BooleanField(default=False)
    reprovacao_gerencia = models.BooleanField(default=False)
    aprovacao_diretoria = models.BooleanField(default=False)
    justificativa_gerencia = models.TextField(null=True, blank=True)
    justificativa_diretoria = models.TextField(null=True, blank=True)
    acao_gerencia = models.CharField(max_length=100, null=True, blank=True, choices=ACAO_CHOICES)
    acao_diretoria = models.CharField(max_length=100, null=True, blank=True, choices=ACAO_CHOICES)

    #boletim_flag = models.BooleanField(default=False)


    fornecedor_escolhido = models.ForeignKey(
        EmpresaTerceira,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='escolhido_em'
    )

    status = models.CharField(max_length=100, default='Em análise')
    solicitacao_origem = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="revisoes"
    )

    def __str__(self):
        return f"Solicitação para {self.contrato}"


# ---------------------------------
# Proposta da empresa terceirizada
# ---------------------------------
class PropostaFornecedor(models.Model):
    CONDICOES_CHOICES = [
        ('Conforme Medição Aprovada', 'Conforme Medição Aprovada'),
        ('Conforme Pagamento do Cliente', 'Conforme Pagamento do Cliente'),
        ('A definir', 'A definir'),
    ]

    solicitacao = models.ForeignKey(SolicitacaoProspeccao, on_delete=models.CASCADE, related_name="propostas")
    fornecedor = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE)
    valor_proposta = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    condicao_pagamento = models.CharField(max_length=30, choices=CONDICOES_CHOICES, blank=True, null=True)
    prazo_validade = models.DateField(null=True, blank=True)
    arquivo_proposta = models.FileField(
        upload_to='orcamentos/',
        verbose_name='Inserir Orçamento PDF',
        null=True, blank=True
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = ("solicitacao", "fornecedor")

    def __str__(self):
        return f"Proposta {self.fornecedor} - {self.solicitacao.contrato}"

# --------------------------
# Solicitação de Contratação
# --------------------------
class TriagemFornecedor(models.Model):
    solicitacao = models.ForeignKey(SolicitacaoProspeccao, on_delete=models.CASCADE, related_name="triagens")
    fornecedor = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE)
    selecionado = models.BooleanField(default=False)
# --------------------------
# Solicitação de Contratação
# --------------------------
class SolicitacaoContratacaoTerceiro(models.Model):
    AREA_CHOICES = [
        ('Inovação', 'Inovação'),
        ('Geotecnia', 'Geotecnia'),
        ('Recursos Hídricos', 'Recursos Hídricos'),
        ('Saneamento', 'Saneamento'),
        ('Sustentabilidade', 'Sustentabilidade'),
    ]

    solicitante_nome = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='solicitacoes_contratacao_terceiros'
    )
    area_solicitante = models.CharField(max_length=30, choices=AREA_CHOICES)
    responsavel_sumprimento = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        limit_choices_to={'groups__name': 'Suprimento'},
        related_name='solicitacoes_comerciais'
    )
    empresa_1 = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE)
    numero_proposta_1 = models.ForeignKey(
        PropostaFornecedor,
        on_delete=models.CASCADE,
        related_name="solicitacoes_como_proposta_1"
    )

    empresa_2 = models.ForeignKey(
        EmpresaTerceira,
        on_delete=models.SET_NULL, blank=True, null=True,
        related_name='contratos_empresa_2'
    )
    numero_proposta_2 = models.ForeignKey(
        PropostaFornecedor,
        on_delete=models.SET_NULL, blank=True, null=True,
        related_name="solicitacoes_como_proposta_2"
    )

    empresa_3 = models.ForeignKey(
        EmpresaTerceira,
        on_delete=models.SET_NULL, blank=True, null=True,
        related_name='contratos_empresa_3'
    )
    numero_proposta_3 = models.ForeignKey(
        PropostaFornecedor,
        on_delete=models.SET_NULL, blank=True, null=True,
        related_name="solicitacoes_como_proposta_3"
    )

    justificativa = models.TextField(null=True, blank=True)
    valor_vendido_ao_cliente = models.FloatField()
    cod_projeto = models.ForeignKey(Contrato, on_delete=models.SET_NULL, null=True, blank=True)
    prazo_contratual = models.TextField()
    inicio_contrato = models.DateField()
    termino_contrato = models.DateField()
    indicacao_proposta_vencedora = models.FileField(
        upload_to='proposta_vencedora/',
        verbose_name='Inserir indicação clara da proposta vencedora em PDF'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.solicitante_nome} -> {self.cod_projeto}"


# --------------------------
# Contrato com terceiro
# --------------------------
class ContratoTerceiros(models.Model):
    STATUS_CHOICES = [
        ('em_elaboracao', 'Em elaboração'),
        ('aguardando_assinatura', 'Aguardando assinatura'),
        ('ativo', 'Ativo'),
        ('suspenso', 'Suspenso'),
        ('encerrado', 'Encerrado'),
    ]

    cod_projeto = models.ForeignKey(Contrato, on_delete=models.CASCADE)
    prospeccao = models.OneToOneField(SolicitacaoProspeccao, on_delete=models.SET_NULL, null=True, blank=True)
    empresa_terceira = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE)
    coordenador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name="contratos_coordenados",
        #limit_choices_to={'groups__name': 'Coordenador de Contrato'}
    )
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    objeto = models.TextField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='em_elaboracao')
    #observacao = models.TextField()

    def __str__(self):
        return f"Contrato {self.cod_projeto} - {self.empresa_terceira}"


# ---------------------------
# Indicadores do fornecedor
# ---------------------------
class Evento(models.Model):
    AVALIACAO_CHOICES = [
        ('Aprovado', 'Aprovado'),
        ('Reprovado', 'Reprovado'),
    ]
    empresa_terceira = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE)
    prospeccao = models.ForeignKey(SolicitacaoProspeccao, on_delete=models.CASCADE, null=True, blank=True)
    contrato_terceiro = models.ForeignKey(ContratoTerceiros, on_delete=models.CASCADE, null=True, blank=True)
    arquivo = models.FileField(
        upload_to='produto_do_fornecedor/',
        verbose_name='Inserir arquivo para comprovação de entrega',
        null=True, blank=True
    )
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
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Entrega {self.id} - {self.empresa_terceira}"


class AvaliacaoFornecedor(models.Model):
    empresa_terceira = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE)
    contrato_terceiro = models.ForeignKey(ContratoTerceiros, on_delete=models.CASCADE)
    area_avaliadora = models.CharField(max_length=100)
    nota = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comentario = models.TextField(blank=True, null=True)
    data_avaliacao = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"Avaliação {self.id} - {self.empresa_terceira}"


class Indicadores(models.Model):
    empresa_terceira = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE)

    @property
    def entregas_total(self):
        return EntregaFornecedor.objects.filter(empresa_terceira=self.empresa_terceira).count()

    @property
    def entregas_conformes(self):
        return EntregaFornecedor.objects.filter(
            empresa_terceira=self.empresa_terceira,
            avaliacao='Aprovado'
        ).count()

    @property
    def entregas_nao_conformes(self):
        return EntregaFornecedor.objects.filter(
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
        return EntregaFornecedor.objects.filter(
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
    def IS(self):
        avaliacoes = AvaliacaoFornecedor.objects.filter(
            empresa_terceira=self.empresa_terceira
        )
        total_avaliacoes = avaliacoes.count()
        if total_avaliacoes == 0:
            return 0
        soma_notas = sum(a.nota for a in avaliacoes)
        media = soma_notas / total_avaliacoes
        return (media / 5) * 100  # % da nota máxima


# ---------------------------
# Linha do tempo do contrato (cliente)
# ---------------------------
class ContratoTimeline(models.Model):
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name="timeline")
    etapa = models.CharField(max_length=100)  # Ex: Envio, Assinatura, Execução
    descricao = models.TextField(blank=True, null=True)
    data = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['data']

    def __str__(self):
        return f"{self.etapa} - {self.contrato}"


# ---------------------------
# Linha do tempo do contrato de terceiros
# ---------------------------
class ContratoTimelineTerceiro(models.Model):
    contrato = models.ForeignKey(ContratoTerceiros, on_delete=models.CASCADE, related_name="timeline")
    etapa = models.CharField(max_length=100)  # Ex: Envio, Assinatura, Execução
    descricao = models.TextField(blank=True, null=True)
    data = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['data']

    def __str__(self):
        return f"{self.etapa} - {self.contrato}"


# ---------------------
# Aditivos contratuais (cliente)
# ---------------------
class Aditivo(models.Model):
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
class AditivoTerceiro(models.Model):
    contrato = models.ForeignKey(ContratoTerceiros, on_delete=models.CASCADE, related_name="aditivos")
    descricao = models.TextField()
    motivo = models.TextField(blank=True, null=True)
    valor_adicional = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    nova_data_fim = models.DateField(blank=True, null=True)
    data_registro = models.DateField(default=timezone.now)

    def __str__(self):
        return f"Aditivo - {self.contrato.cod_projeto} - {self.contrato.empresa_terceira}"


# -------------
# Documento BM
# -------------
class DocumentoBM(models.Model):
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('aprovado', 'Aprovado'),
        ('reprovado', 'Reprovado'),
    ]
    solicitacao = models.OneToOneField(SolicitacaoProspeccao, on_delete=models.CASCADE)
    minuta_boletim = models.FileField(
        upload_to='Minuta boletim/',
        blank=True,
        null=True
    )
    assinatura_fornecedor = models.FileField(
        upload_to='Assinaturas/',
        blank=True,
        null=True
    )
    assinatura_gerente = models.FileField(
        upload_to='Assinaturas/',
        blank=True,
        null=True
    )

    status_coordenador = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendente')
    data_aprovacao_coordenador = models.DateTimeField(null=True, blank=True)
    status_gerente = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendente')
    data_aprovacao_gerente = models.DateTimeField(null=True, blank=True)


    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Boletim de Medição - {self.solicitacao.contrato.cod_projeto}"

    @property
    def aprovado_por_ambos(self):
        return self.status_coordenador == "aprovado" and self.status_gerente == "aprovado"

    @property
    def reprovado_por_alguem(self):
        return self.status_coordenador == "reprovado" or self.status_gerente == "reprovado"
# ------
# BM (Boletim de Medição) - contrato de terceiros
# ------
class BM(models.Model):
    contrato = models.ForeignKey(ContratoTerceiros, on_delete=models.CASCADE, related_name="boletins_medicao")
    numero_bm = models.PositiveIntegerField()
    valor_pago = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    parcela_paga = models.PositiveIntegerField()
    data_pagamento = models.DateField(default=timezone.now)
    arquivo_bm = models.FileField(
        upload_to='BM/',
        verbose_name='Inserir arquivo do Boletim de Medição',
        null=True, blank=True
    )

    def __str__(self):
        return f"Parcela {self.parcela_paga} - {self.valor_pago}"

    @property
    def total_pago(self):
        """Calcula o valor total pago do contrato"""
        from django.db.models import Sum
        total = BM.objects.filter(
            contrato=self.contrato
        ).aggregate(Sum('valor_pago'))['valor_pago__sum']
        return total or Decimal('0.00')


# -----------
# Documentos (cliente)
# -----------
class DocumentoContrato(models.Model):
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name="documentos")
    arquivo = models.FileField(upload_to="contratos/documentos/")
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
class DocumentoContratoTerceiro(models.Model):
    solicitacao = models.OneToOneField(SolicitacaoProspeccao, on_delete=models.CASCADE, related_name="contrato_relacionado")
    numero_contrato = models.CharField(max_length=100, unique=True)
    objeto = models.TextField()
    prazo_inicio = models.DateField()
    prazo_fim = models.DateField()
    valor_total = models.DecimalField(max_digits=12, decimal_places=2)
    arquivo_contrato = models.FileField(
        upload_to="contratos/",
        verbose_name="Contrato em PDF",
        null=True, blank=True
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Contrato {self.numero_contrato} - {self.solicitacao.contrato}"


class CalendarioPagamento(models.Model):
    data_pagamento = models.DateField(unique=True)

    def __str__(self):
        return self.data_pagamento.strftime('%d/%m/%Y')
