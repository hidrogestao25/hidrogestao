"""Programações e decisões por BM; pagamentos continuam exclusivamente no ledger da NF."""
from django.conf import settings
from django.db import models

from .payment_models import ImmutableFinancialRecord


class JustificativaPagamentoBM(models.Model):
    """Texto atual da Diretoria; decisões e suas justificativas originais são históricas."""
    bm = models.ForeignKey('BM', on_delete=models.CASCADE, related_name='justificativas_pagamento')
    ciclo = models.ForeignKey('CicloPagamentoBM', on_delete=models.PROTECT, null=True, blank=True, related_name='justificativas_atuais')
    versao_material = models.CharField(max_length=64)
    texto = models.TextField(blank=True, default='')
    atualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['bm'], condition=models.Q(ciclo__isnull=True), name='justificativa_bm_inicial_unica'),
            models.UniqueConstraint(fields=['bm', 'ciclo'], condition=models.Q(ciclo__isnull=False), name='justificativa_bm_ciclo_unica'),
        ]


class CicloPagamentoBM(ImmutableFinancialRecord):
    TIPOS = [('inicial', 'Programação inicial'), ('reprogramacao', 'Reprogramação por saldo pendente'), ('revisao', 'Revisão expressa do ciclo')]
    bm = models.ForeignKey('BM', on_delete=models.PROTECT, related_name='ciclos_pagamento')
    numero = models.PositiveIntegerField()
    anterior = models.OneToOneField('self', on_delete=models.PROTECT, null=True, blank=True, related_name='sucessor')
    tipo = models.CharField(max_length=16, choices=TIPOS)
    data_prevista = models.DateField()
    calendario = models.ForeignKey('CalendarioPagamento', on_delete=models.PROTECT, null=True, blank=True, related_name='ciclos_bm')
    saldo_inclusao = models.DecimalField(max_digits=14, decimal_places=2)
    motivo = models.TextField(blank=True, default='')
    contexto_inclusao = models.JSONField()
    versao_material = models.CharField(max_length=64)

    class Meta:
        ordering = ['bm_id', 'numero']
        verbose_name = 'Ciclo de pagamento do BM'
        verbose_name_plural = 'Ciclos de pagamento dos BMs'
        constraints = [
            models.UniqueConstraint(fields=['bm', 'numero'], name='ciclo_bm_numero_unico'),
            models.UniqueConstraint(fields=['bm'], condition=models.Q(anterior__isnull=True), name='ciclo_bm_inicial_unico'),
            models.CheckConstraint(condition=models.Q(saldo_inclusao__gt=0), name='ciclo_bm_saldo_inclusao_positivo'),
        ]
        indexes = [models.Index(fields=['data_prevista', 'bm'], name='ciclo_bm_programacao_idx')]

    def __str__(self):
        return f'BM #{self.bm_id} · ciclo {self.numero} · {self.data_prevista:%d/%m/%Y}'


class DecisaoCicloBM(ImmutableFinancialRecord):
    ciclo = models.ForeignKey(CicloPagamentoBM, on_delete=models.PROTECT, related_name='decisoes')
    etapa = models.CharField(max_length=12, choices=[('gerencia', 'Renovação pelo Líder de Contrato'), ('diretoria', 'Diretoria')])
    situacao = models.CharField(max_length=10, choices=[('aprovado', 'Aprovado'), ('reprovado', 'Reprovado')])
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    saldo_avaliado = models.DecimalField(max_digits=14, decimal_places=2)
    versao_material = models.CharField(max_length=64)
    justificativa = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['registrado_em', 'pk']
        verbose_name = 'Decisão do ciclo de pagamento do BM'
        constraints = [models.UniqueConstraint(fields=['ciclo', 'etapa'], name='decisao_ciclo_bm_etapa_unica')]

    def __str__(self):
        return f'Ciclo #{self.ciclo_id} · {self.get_etapa_display()} · {self.get_situacao_display()}'


class PagamentoCicloBM(models.Model):
    """Somente vínculo histórico; não duplica valor, comprovante ou data de caixa."""
    pagamento = models.OneToOneField('PagamentoNF', on_delete=models.PROTECT, related_name='ciclo_bm')
    ciclo = models.ForeignKey(CicloPagamentoBM, on_delete=models.PROTECT, related_name='pagamentos_vinculados')

    class Meta:
        verbose_name = 'Vínculo do pagamento ao ciclo de BM'

    def __str__(self):
        return f'Pagamento #{self.pagamento_id} · ciclo #{self.ciclo_id}'
