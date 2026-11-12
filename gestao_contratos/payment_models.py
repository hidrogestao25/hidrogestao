"""Liquidações e programação imutáveis; centavos gerados pelo banco."""
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Cast,Round
from .validation import validate_upload
from .models import ShortenedUploadPath


def cents_field(source):
    return models.GeneratedField(expression=Cast(Round(models.F(source)*100),models.BigIntegerField()),
        output_field=models.BigIntegerField(),db_persist=True)


class ImmutableFinancialRecord(models.Model):
    registrado_em=models.DateTimeField(auto_now_add=True)
    registrado_por=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='+')
    class Meta:abstract=True
    def save(self,*args,**kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Registro financeiro confirmado é imutável; acrescente correção auditada.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):
        raise ValidationError('Registro financeiro permanente não pode ser excluído.')


class PagamentoNF(ImmutableFinancialRecord):
    nf=models.ForeignKey('NF',on_delete=models.PROTECT,related_name='movimentos')
    valor=models.DecimalField(max_digits=12,decimal_places=2)
    centavos=cents_field('valor')
    data_pagamento=models.DateField(null=True,blank=True)
    tipo=models.CharField(max_length=12,choices=[('pagamento','Pagamento'),('estorno','Estorno')])
    referencia_estorno=models.ForeignKey('self',on_delete=models.PROTECT,null=True,blank=True,related_name='estornos')
    programacao=models.ForeignKey('ProgramacaoPagamento',on_delete=models.PROTECT,null=True,blank=True,related_name='movimentos')
    justificativa=models.TextField(blank=True,default='')
    observacao=models.TextField(blank=True,default='')
    comprovante=models.FileField(upload_to=ShortenedUploadPath('NF/Pagamentos','comprovante'),null=True,blank=True,max_length=255,validators=[validate_upload])
    chave_idempotencia=models.CharField(max_length=64,unique=True)
    payload_hash=models.CharField(max_length=64,blank=True,default='')
    origem_registro=models.CharField(max_length=32,default='normal',choices=[('normal','Normal'),('legado_nf_integral','Abertura legada integral')])
    class Meta:
        ordering=['data_pagamento','pk']
        constraints=[models.CheckConstraint(condition=models.Q(valor__gt=0),name='pagamento_nf_valor_positivo'),
            models.UniqueConstraint(fields=['nf'],condition=models.Q(origem_registro='legado_nf_integral'),name='uma_abertura_legada_por_nf')]
        indexes=[models.Index(fields=['nf','tipo'],name='pag_nf_tipo_idx'),models.Index(fields=['data_pagamento'],name='pag_nf_data_idx')]
    def __str__(self):return f'{self.get_tipo_display()} #{self.pk} · NF #{self.nf_id}'


class ReprogramacaoPagamento(ImmutableFinancialRecord):
    nf=models.ForeignKey('NF',on_delete=models.PROTECT,related_name='reprogramacoes')
    programacao=models.ForeignKey('ProgramacaoPagamento',on_delete=models.PROTECT,null=True,blank=True,related_name='acordos')
    vencimento_anterior=models.DateField(null=True,blank=True)
    novo_vencimento=models.DateField()
    motivo=models.TextField()
    responsavel_acordo=models.CharField(max_length=255,blank=True,default='')
    documento=models.FileField(upload_to=ShortenedUploadPath('NF/Acordos','acordo'),null=True,blank=True,max_length=255,validators=[validate_upload])
    observacao=models.TextField(blank=True,default='')
    chave_idempotencia=models.CharField(max_length=64,unique=True)
    class Meta:ordering=['registrado_em','pk']
    def __str__(self):return f'Acordo #{self.pk} · NF #{self.nf_id}'


class ProgramacaoPagamento(ImmutableFinancialRecord):
    nf=models.ForeignKey('NF',on_delete=models.PROTECT,related_name='programacoes')
    grupo=models.UUIDField(default=uuid.uuid4,db_index=True,editable=False)
    substitui=models.OneToOneField('self',on_delete=models.PROTECT,null=True,blank=True,related_name='sucessora')
    acordo=models.ForeignKey(ReprogramacaoPagamento,on_delete=models.PROTECT,null=True,blank=True,related_name='programacoes')
    valor_previsto=models.DecimalField(max_digits=12,decimal_places=2)
    centavos=cents_field('valor_previsto')
    data_prevista=models.DateField()
    cancelada=models.BooleanField(default=False)
    justificativa=models.TextField()
    observacao=models.TextField(blank=True,default='')
    chave_idempotencia=models.CharField(max_length=64,unique=True)
    class Meta:
        ordering=['data_prevista','pk']
        constraints=[models.CheckConstraint(condition=models.Q(valor_previsto__gt=0),name='programacao_nf_valor_positivo')]
    def __str__(self):return f'Programação #{self.pk} · NF #{self.nf_id}'
    @property
    def valor_restante(self):
        from .payment_queries import money
        return money(getattr(self,'restante_centavos',self.centavos))
