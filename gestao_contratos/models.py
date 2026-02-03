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
        ('lider_contrato','Lider de Contratos'),
        ('gerente', 'Gerente'),
        ('gerente_contrato', 'Gerente de Contratos'),
        ('diretoria', 'Diretoria'),
        ('financeiro', 'Financeiro'),
        ('suprimento', 'Suprimento'),
        ('fornecedor', 'Fornecedor'),
    ]

    grupo = models.CharField(max_length=20, choices=GRUPOS_CHOICES, blank=True, null=True)

    # Novo campo ManyToMany
    centros = models.ManyToManyField("CentroDeTrabalho", blank=True, related_name="usuarios")

    email = models.EmailField()

    # Evita conflito de acessores reversos com auth.User.*
    groups = models.ManyToManyField(Group, related_name="+", blank=True)
    user_permissions = models.ManyToManyField(Permission, related_name="+", blank=True)

    def __str__(self):
        return self.get_full_name() or self.username


class CentroDeTrabalho(models.Model):
    codigo = models.CharField(max_length=10, unique=True)
    nome = models.CharField(max_length=100)

    observacao = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.nome} ({self.codigo})"


# -----------------
# Cliente
# -----------------
class Cliente(models.Model):
    nome = models.CharField(max_length=200)
    razao_social = models.CharField(max_length=200, blank=True, null=True)
    cpf_cnpj = models.CharField(max_length=18, unique=True)
    endereco = models.TextField(blank=True, null=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)

    ponto_focal = models.CharField(max_length=200, null=True, blank=True)
    email_focal = models.EmailField(blank=True, null=True)
    telefone_focal =models.CharField(max_length=20, blank=True, null=True)

    """ponto_focal2 = models.CharField(max_length=200, null=True, blank=True)
    email_focal2 = models.EmailField(blank=True, null=True)
    telefone_focal2 =models.CharField(max_length=20, blank=True, null=True)"""

    observacao = models.TextField(null=True, blank=True)

    def __str__(self):
        if self.razao_social == None:
            return self.nome
        else:
            return f"{self.nome} ({self.razao_social})"


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

    ponto_focal2 = models.CharField(max_length=200, null=True, blank=True)
    email_focal2 = models.EmailField(blank=True, null=True)
    telefone_focal2 =models.CharField(max_length=20, blank=True, null=True)

    observacao = models.TextField(null=True, blank=True)

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
    observacao = models.TextField(null=True, blank=True)

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
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="contratos")
    coordenador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        #limit_choices_to={'grupo': 'Coordenador de Contrato'},
        related_name="contratos_cliente_coordenados"  # evita conflito com contratos_coordenados
    )
    lider_contrato = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"grupo": "lider_contrato"},
        related_name="contratos_liderados"
    )
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2)
    objeto = models.TextField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='Em elaboracao')
    observacao = models.TextField(null=True, blank=True)

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
    lider_contrato = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"grupo": "lider_contrato"},
        related_name="solicitacoes_lideradas",
    )
    descricao = models.TextField(blank=True, null=True)
    requisitos = models.TextField(blank=True, null=True)
    previsto_no_orcamento = models.BooleanField(default=False)
    valor_provisionado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    valor_vendido = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    data_solicitacao = models.DateTimeField(auto_now_add=True)
    guarda_chuva = models.BooleanField(default=False, null=True, blank=True)
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
    observacao = models.TextField(null=True, blank=True)
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
    num_contrato = models.CharField(max_length=30, null=True, blank=True)
    prospeccao = models.OneToOneField(SolicitacaoProspeccao, on_delete=models.SET_NULL, null=True, blank=True)
    empresa_terceira = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE, related_name='contratos')
    coordenador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True,
        related_name="contratos_coordenados",
    )
    lider_contrato = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"grupo": "lider_contrato"},
        related_name="contratos_liderados_terceiros"
    )
    guarda_chuva = models.BooleanField(default=False, null=True, blank=True)
    condicao_pagamento = models.CharField(max_length=80, null=True, blank=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    objeto = models.TextField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='Em elaboracao')
    observacao = models.TextField(null=True, blank=True)

    num_contrato_arquivo = models.FileField(
        upload_to='contrato_do_fornecedor/',
        verbose_name='Inserir arquivo do contrato com fornecedor',
        null=True, blank=True
    )

    def __str__(self):
        return f"Contrato {self.num_contrato} - {self.cod_projeto} - {self.empresa_terceira}"

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
        """Índice de Satisfação - Gestão (avaliado apenas neste contrato)"""
        avaliacoes = AvaliacaoFornecedor.objects.filter(
            contrato_terceiro=self
        )
        total_avaliacoes = avaliacoes.count()
        if total_avaliacoes == 0:
            return 0
        soma_notas = sum(a.nota_gestao for a in avaliacoes if a.nota_gestao)
        media = soma_notas / total_avaliacoes
        return (media / 5) * 100

    @property
    def IS_tecnica(self):
        """Índice de Satisfação - Técnica (avaliado apenas neste contrato)"""
        avaliacoes = AvaliacaoFornecedor.objects.filter(
            contrato_terceiro=self
        )
        total_avaliacoes = avaliacoes.count()
        if total_avaliacoes == 0:
            return 0
        soma_notas = sum(a.nota_tecnica for a in avaliacoes if a.nota_tecnica)
        media = soma_notas / total_avaliacoes
        return (media / 5) * 100

    @property
    def IS_entrega(self):
        """Índice de Satisfação - Entrega (avaliado apenas neste contrato)"""
        avaliacoes = AvaliacaoFornecedor.objects.filter(
            contrato_terceiro=self
        )
        total_avaliacoes = avaliacoes.count()
        if total_avaliacoes == 0:
            return 0
        soma_notas = sum(a.nota_entrega for a in avaliacoes if a.nota_entrega)
        media = soma_notas / total_avaliacoes
        return (media / 5) * 100


# ---------------------------
# Solicitação de Ordens de Serviços para Contratos Guarda-chuvas
# ---------------------------
class SolicitacaoOrdemServico(models.Model):
    STATUS_CHOICES = [
        ('solicitacao_os', 'Solicitação de OS'),
        ('pendente_lider', 'Pendente Líder'),
        ('pendente_gerente', 'Pendente Gerente'),
        ('pendente_suprimento', 'Pendente Suprimento'),
        ('aprovada', 'Aprovada'),
        ('reprovada', 'Reprovada'),
        ('finalizada', 'Finalizada'),
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
        limit_choices_to={"grupo": "lider_contrato"},
        related_name="ordens_liderados_terceiros"
    )
    titulo = models.CharField(max_length=200)
    descricao = models.TextField()
    valor_previsto = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    prazo_execucao = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='solicitacao_os')
    criado_em = models.DateTimeField(auto_now_add=True)

    aprovacao_lider = models.CharField(max_length=100, null=True, blank=True)
    aprovado_lider_em =models.DateTimeField(null=True, blank=True)
    justificativa_reprovacao_lider = models.TextField(null=True, blank=True)

    arquivo_os = models.FileField(
        upload_to='OS/',
        verbose_name='Inserir arquivo da Ordem de Serviço',
        null=True, blank=True
    )
    aprovacao_gerente = models.CharField(max_length=100, null=True, blank=True)
    aprovado_gerente_em =models.DateTimeField(null=True, blank=True)
    justificativa_reprovacao_gerente = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Solicitação {self.id} - {self.titulo} - {self.contrato.empresa_terceira}"


# ---------------------------
# ordem de Serviço
# ---------------------------
class OS(models.Model):
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
    coordenador = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ordens_coordenador")
    lider_contrato = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"grupo": "lider_contrato"},
        related_name="ordens"
    )
    titulo = models.CharField(max_length=200)
    descricao = models.TextField()
    valor = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    prazo_execucao = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='em_execucao')
    criado_em = models.DateTimeField(auto_now_add=True)
    arquivo_os = models.FileField(
        upload_to='OS/',
        verbose_name='Inserir arquivo da Ordem de Serviço',
        null=True, blank=True
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

    def __str__(self):
        return f"OS {self.id} - {self.titulo} - {self.contrato.empresa_terceira}"


# ---------------------------
# Indicadores do fornecedor
# ---------------------------
class Evento(models.Model):
    AVALIACAO_CHOICES = [
        ('Aprovado', 'Aprovado'),
        ('Reprovado', 'Reprovado'),
    ]
    empresa_terceira = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE, null=True, blank=True)
    prospeccao = models.ForeignKey(SolicitacaoProspeccao, on_delete=models.CASCADE, null=True, blank=True)
    contrato_terceiro = models.ForeignKey(ContratoTerceiros, on_delete=models.CASCADE, null=True, blank=True)
    arquivo = models.FileField(
        upload_to='produto_do_fornecedor/',
        verbose_name='Inserir arquivo para comprovação de entrega',
        null=True, blank=True
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

    def __str__(self):
        try:
            empresa = self.empresa_terceira or "Sem empresa vinculada"
        except Exception:
            empresa = "Sem empresa vinculada"
        return f"Entrega {self.id} - {self.contrato_terceiro} - {empresa}"


class AvaliacaoFornecedor(models.Model):
    empresa_terceira = models.ForeignKey(EmpresaTerceira, on_delete=models.CASCADE)
    contrato_terceiro = models.ForeignKey(ContratoTerceiros, on_delete=models.CASCADE)
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, blank=True, null=True, related_name="avaliacoes")
    area_avaliadora = models.CharField(max_length=100)
    avaliador = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    nota_gestao = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], null=True, blank=True)
    nota_tecnica = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], null=True, blank=True)
    nota_entrega = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], null=True, blank=True)
    comentario = models.TextField(blank=True, null=True)
    data_avaliacao = models.DateField(auto_now_add=True)

    def __str__(self):
        return f"Avaliação {self.id} - {self.empresa_terceira}"


class Indicadores(models.Model):
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
        avaliacoes = AvaliacaoFornecedor.objects.filter(
            empresa_terceira=self.empresa_terceira
        )
        total_avaliacoes = avaliacoes.count()
        if total_avaliacoes == 0:
            return 0
        soma_notas = sum(a.nota_gestao for a in avaliacoes)
        media = soma_notas / total_avaliacoes
        return (media / 5) * 100

    @property
    def IS_tecnica(self):
        avaliacoes = AvaliacaoFornecedor.objects.filter(
            empresa_terceira=self.empresa_terceira
        )
        total_avaliacoes = avaliacoes.count()
        if total_avaliacoes == 0:
            return 0
        soma_notas = sum(a.nota_tecnica for a in avaliacoes)
        media = soma_notas / total_avaliacoes
        return (media / 5) * 100

    @property
    def IS_entrega(self):
        avaliacoes = AvaliacaoFornecedor.objects.filter(
            empresa_terceira=self.empresa_terceira
        )
        total_avaliacoes = avaliacoes.count()
        if total_avaliacoes == 0:
            return 0
        soma_notas = sum(a.nota_entrega for a in avaliacoes)
        media = soma_notas / total_avaliacoes
        return (media / 5) * 100


"""# ---------------------
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

"""
# -------------
# Documento BM
# -------------
class DocumentoBM(models.Model):
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('aprovado', 'Aprovado'),
        ('reprovado', 'Reprovado'),
    ]
    solicitacao = models.OneToOneField(SolicitacaoProspeccao, on_delete=models.CASCADE, related_name="minuta_boletins_medicao")
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

    observacao = models.TextField(null=True, blank=True)
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
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('aprovado', 'Aprovado'),
        ('reprovado', 'Reprovado'),
    ]
    contrato = models.ForeignKey(ContratoTerceiros, on_delete=models.CASCADE, related_name="boletins_medicao")
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='boletins_medicao', null=True, blank=True)
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
        upload_to='BM/',
        verbose_name='Inserir arquivo do Boletim de Medição',
        null=True, blank=True
    )
    observacao = models.TextField(null=True, blank=True)

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

    def save(self, *args, **kwargs):
        """Se o arquivo for atualizado, reinicia as aprovações"""
        if self.pk:
            old = BM.objects.filter(pk=self.pk).first()
            if old and old.arquivo_bm != self.arquivo_bm:
                self.status_coordenador = 'pendente'
                self.status_gerente = 'pendente'
                self.data_aprovacao_coordenador = None
                self.data_aprovacao_gerente = None
        super().save(*args, **kwargs)


# -------------
# Nota Fiscal
#--------------
class NF(models.Model):
    contrato = models.ForeignKey(ContratoTerceiros, on_delete=models.CASCADE, related_name="nota_fiscal")
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='nota_fiscal')
    bm = models.ForeignKey(BM, on_delete=models.CASCADE, related_name='nota_fiscal', blank=True, null=True)
    valor_pago = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    parcela_paga = models.PositiveIntegerField()
    data_pagamento = models.DateField(default=timezone.now)
    arquivo_nf = models.FileField(
        upload_to='NF/Fornecedor/',
        verbose_name='Inserir arquivo da Nota Fiscal',
        null=True, blank=True
    )
    observacao = models.TextField(null=True, blank=True)
    financeiro_autorizou = models.BooleanField(default=False)
    nf_dentro_prazo = models.BooleanField(default=False)

    def __str__(self):
        return f"Nota Fiscal {self.id} - {self.evento.descricao} (id - {self.evento.id})"


# -------------
# Nota Fiscal para o Cliente
#--------------
class NFCliente(models.Model):
    contrato = models.ForeignKey(Contrato, on_delete=models.CASCADE, related_name="nota_fiscal")
    valor_pago = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    parcela_paga = models.PositiveIntegerField()
    data_emissao = models.DateField(default=timezone.now)
    data_pagamento = models.DateField(default=timezone.now)
    arquivo_nf = models.FileField(
        upload_to='NF/Cliente/',
        verbose_name='Inserir arquivo da Nota Fiscal',
        null=True, blank=True
    )
    observacao = models.TextField(null=True, blank=True)
    inserido_por = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f"Nota Fiscal {self.id} - Parcela {self.parcela_paga} - {self.contrato}"


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
    observacao = models.TextField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Contrato {self.numero_contrato} - {self.solicitacao.contrato}"


class CalendarioPagamento(models.Model):
    data_pagamento = models.DateField(unique=True)
    observacao = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.data_pagamento.strftime('%d/%m/%Y')
