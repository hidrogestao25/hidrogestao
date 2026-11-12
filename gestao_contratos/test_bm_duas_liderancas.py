"""Contrato documental e contrato do Evento exigem decisões separadas."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4
from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction,IntegrityError,connection
from django.test import RequestFactory
from django.urls import reverse
from . import models as m,financial_queries as fq,payment_services as payments,bm_approvals
from . import test_financeiro_fase2 as fixtures
from .financial_audit import financial_audit_context
from .permissions import bm_has_valid_operational_approval,can_view_object
from .tests import BaseUserTestCase

def approve_shared_fixture(case,bm,instant=None):
    """Relatórios só recebem fixture aprovada depois das duas decisões reais."""
    if not bm.evento.avaliacoes.exists():
        m.AvaliacaoFornecedor.objects.create(empresa_terceira=bm.evento.contrato_terceiro.empresa_terceira,
            contrato_terceiro=bm.evento.contrato_terceiro,evento=bm.evento,
            avaliador=bm.evento.contrato_terceiro.referencia_lider_contrato,area_avaliadora='lider_contrato',nota_gestao=5)
    from contextlib import nullcontext
    clock=patch('gestao_contratos.views.timezone.now',return_value=instant) if instant else nullcontext()
    with clock:
        actors={c.referencia_lider_contrato.pk:c.referencia_lider_contrato for c in bm_approvals.contracts(bm).values()}
        for actor in actors.values():
            case.client.force_login(actor)
            response=case.client.post(reverse('avaliar_bm',args=[bm.pk]),{'acao':'aprovar'})
            case.assertEqual(response.status_code,200,response.content)
    bm.refresh_from_db();case.assertTrue(bm_has_valid_operational_approval(bm))

class DuasLiderancasBMTests(BaseUserTestCase):
    setUp=fixtures.FinanceiroFase2Tests.setUp
    nf=fixtures.FinanceiroFase2Tests.nf

    def shared(self,**extra):
        defaults=dict(contrato=self.contracts[0],evento=self.events[1],numero_bm=20,parcela_paga=1,valor_pago=100)
        defaults.update(extra)
        return m.BM.objects.create(**defaults)

    def evaluate(self,bm):
        return m.AvaliacaoFornecedor.objects.create(empresa_terceira=self.supplier,contrato_terceiro=self.contracts[1],
            evento=bm.evento,area_avaliadora=self.other.grupo,avaliador=self.other,nota_gestao=5)

    def decide(self,user,bm,action='aprovar',reason=''):
        self.client.force_login(user)
        return self.client.post(reverse('avaliar_bm',args=[bm.pk]),{'acao':action,'justificativa':reason})

    def director(self):return self.create_user('dual_director_'+uuid4().hex[:8],'diretoria')

    def test_duas_ordens_exigem_ambos_e_guardam_contrato_autor_data(self):
        for first,second in [(self.leader,self.other),(self.other,self.leader)]:
            bm=self.shared()
            if not bm.evento.avaliacoes.exists():self.evaluate(bm)
            self.assertEqual(self.decide(first,bm).status_code,200)
            bm.refresh_from_db();self.assertFalse(bm_has_valid_operational_approval(bm))
            self.assertFalse(fq.financial_bms().filter(fq.operational_query(),pk=bm.pk).exists())
            self.assertEqual(self.decide(self.director(),bm,'aprovar_pagamento').status_code,400)
            self.assertEqual(self.decide(second,bm).status_code,200)
            bm.refresh_from_db();self.assertTrue(bm_has_valid_operational_approval(bm))
            self.assertEqual((bm.aprovador_lider_documental_id,bm.aprovador_lider_financeiro_id),(self.leader.pk,self.other.pk))
            self.assertIsNotNone(bm.data_lider_documental);self.assertIsNotNone(bm.data_lider_financeiro)
            self.assertTrue(fq.financial_bms().filter(fq.operational_query(),pk=bm.pk).exists())
            self.assertEqual(bm.contrato_financeiro_id if hasattr(bm,'contrato_financeiro_id') else bm.contrato_financeiro.pk,self.contracts[1].pk)
            history=m.RegistroAuditoria.objects.filter(content_type=ContentType.objects.get_for_model(m.BM),object_id=bm.pk,operacao_financeira='decisao_bm')
            self.assertEqual(set(history.values_list('usuario_id',flat=True)),{self.leader.pk,self.other.pk})
            self.assertEqual(history.count(),2)

    def test_evento_avaliado_uma_vez_e_repeticao_nao_sobrescreve_decisao(self):
        bm=self.shared()
        for user in (self.leader,self.other):self.assertEqual(self.decide(user,bm).status_code,400)
        evaluation=self.evaluate(bm)
        self.assertEqual(self.decide(self.leader,bm).status_code,200)
        bm.refresh_from_db();instant=bm.data_lider_documental
        self.assertEqual(self.decide(self.leader,bm,'reprovar','Tentar mudar decisão').status_code,403)
        bm.refresh_from_db();self.assertEqual(bm.data_lider_documental,instant)
        self.assertEqual(bm.status_lider_documental,'aprovado')
        self.assertEqual(self.decide(self.other,bm).status_code,200)
        self.assertEqual(list(bm.evento.avaliacoes.values_list('pk',flat=True)),[evaluation.pk])

    def test_gerencia_terceiros_coordenador_e_cobertura_diretoria_nao_substituem_lideres(self):
        bm=self.shared();self.evaluate(bm)
        manager=self.create_user('dual_manager','gerente_contrato')
        manager.gerente_contrato_ausente=True;manager.save()
        outsider=self.create_user('dual_outsider','lider_contrato')
        for user in (manager,outsider,self.coord):
            self.assertIn(self.decide(user,bm).status_code,(302,403))
        self.assertEqual(self.decide(self.director(),bm,'aprovar_pagamento').status_code,400)
        bm.refresh_from_db();self.assertIsNone(bm.status_lider_documental);self.assertIsNone(bm.status_lider_financeiro)

    def test_reprovacao_exige_motivo_bloqueia_outro_lider_e_revisao_reabre_ambos(self):
        bm=self.shared();self.evaluate(bm)
        self.assertEqual(self.decide(self.leader,bm,'reprovar').status_code,400)
        self.assertEqual(self.decide(self.leader,bm,'reprovar','Corrigir medição').status_code,200)
        self.assertEqual(self.decide(self.other,bm).status_code,403)
        bm.refresh_from_db();self.assertEqual(bm.justificativa_lider_documental,'Corrigir medição')
        self.assertFalse(bm_has_valid_operational_approval(bm))
        bm.valor_pago=101;bm.save();bm.refresh_from_db()
        self.assertTrue(all(getattr(bm,f) is None for f in bm_approvals.FIELDS))
        for user in (self.leader,self.other):self.assertEqual(self.decide(user,bm).status_code,200)

    def test_mesmo_responsavel_em_ambos_e_contrato_sem_lider(self):
        self.contracts[1].lider_contrato=self.leader;self.contracts[1].save()
        bm=self.shared();self.evaluate(bm)
        self.assertEqual(self.decide(self.leader,bm).status_code,200)
        bm.refresh_from_db();self.assertTrue(bm_has_valid_operational_approval(bm))
        self.assertEqual(bm.aprovador_lider_documental_id,bm.aprovador_lider_financeiro_id)
        self.contracts[1].lider_contrato=None;self.contracts[1].save()
        other=self.shared();self.assertEqual(self.decide(self.leader,other).status_code,200)
        other.refresh_from_db();self.assertFalse(bm_has_valid_operational_approval(other))

    def test_pagamento_apenas_apos_duas_aprovacoes_e_diretoria(self):
        bm=self.shared();self.evaluate(bm);nf=self.nf(bm,value='100')
        director=self.director()
        self.assertEqual(self.decide(self.leader,bm).status_code,200)
        with self.assertRaises(ValidationError):payments.record_payment(nf_id=nf.pk,user=self.finance,valor=10,data_pagamento=date.today(),key=str(uuid4()))
        self.assertEqual(self.decide(self.other,bm).status_code,200)
        self.assertEqual(self.decide(director,bm,'aprovar_pagamento').status_code,200)
        payments.record_payment(nf_id=nf.pk,user=self.finance,valor=10,data_pagamento=date.today(),key=str(uuid4()))
        nf.refresh_from_db();self.assertEqual((nf.total_pago,nf.saldo_pendente),(10,90))
        self.assertEqual(nf.contrato_id,self.contracts[1].pk)

    def test_sql_forjado_nao_cria_segunda_aprovacao_e_revisao_sql_limpa_ambas(self):
        bm=self.shared();self.evaluate(bm)
        with self.assertRaises(IntegrityError),transaction.atomic():
            m.BM.objects.filter(pk=bm.pk).update(status_lider_financeiro='aprovado',aprovador_lider_financeiro=self.other,data_lider_financeiro=m.timezone.now())
        for user in (self.leader,self.other):self.assertEqual(self.decide(user,bm).status_code,200)
        with self.assertRaises(IntegrityError),transaction.atomic(),financial_audit_context(self.other):
            m.BM.objects.filter(pk=bm.pk).update(justificativa_lider_financeiro='Reescrever história')
        m.BM.objects.filter(pk=bm.pk).update(numero_bm=21)
        bm.refresh_from_db();self.assertTrue(all(getattr(bm,f) is None for f in bm_approvals.FIELDS))
        self.assertEqual(bm.aprovacao_pagamento,'pendente')

    def test_aprovacao_legada_nao_inventa_assinaturas_e_sql_diretoria_nao_contorna(self):
        bm=self.shared(status_gerente='aprovado',aprovacao_pagamento='aprovado')
        self.assertFalse(bm_has_valid_operational_approval(bm))
        nf=self.nf(bm,value='100')
        with self.assertRaises(IntegrityError),transaction.atomic(),financial_audit_context(self.finance):
            m.PagamentoNF.objects.create(nf=nf,valor=10,tipo='pagamento',data_pagamento=date.today(),
                registrado_por=self.finance,chave_idempotencia='tentativa_sql_sem_dupla',origem_registro='normal')
        with self.assertRaises((ValidationError,IntegrityError)):
            payments.record_payment(nf_id=nf.pk,user=self.supply,valor=10,data_pagamento=date.today(),key=str(uuid4()))
        m.BM.objects.filter(pk=bm.pk).update(aprovacao_pagamento='pendente')
        with self.assertRaises(IntegrityError),transaction.atomic():m.BM.objects.filter(pk=bm.pk).update(aprovacao_pagamento='aprovado')

    def test_tela_e_home_dos_dois_lideres_sem_liberar_nf_ao_lider_documental(self):
        bm=self.shared();self.evaluate(bm);nf=self.nf(bm,value='100')
        for user in (self.leader,self.other):
            self.client.force_login(user)
            response=self.client.get(reverse('detalhe_bm_financeiro',args=[bm.pk]))
            self.assertContains(response,'Aprovação dos dois contratos')
            self.assertContains(response,'Aprovar minha participação')
            home=self.client.get(reverse('home'))
            self.assertIn(bm.pk,[b.pk for b in home.context['bms_pendentes']])
        self.client.force_login(self.leader)
        self.assertEqual(self.client.get(reverse('detalhe_nf',args=[nf.pk])).status_code,404)
        response=self.client.get(reverse('detalhe_bm_financeiro',args=[bm.pk]))
        self.assertEqual(list(response.context['page_obj']),[])

    def test_admin_e_formularios_nao_editam_campos_de_decisao(self):
        from .forms import BMForm
        bm=self.shared();request=RequestFactory().get('/');request.user=self.supply
        request.user.is_superuser=request.user.is_staff=True
        form=admin.site._registry[m.BM].get_form(request,bm)
        for field in ('status_lider_documental','aprovador_lider_documental','status_lider_financeiro','aprovador_lider_financeiro'):
            self.assertNotIn(field,form.base_fields);self.assertNotIn(field,BMForm().fields)

    def test_formulario_aberto_antes_de_revisar_valor_nao_aprova_nova_medicao(self):
        bm=self.shared();self.evaluate(bm);version=bm.versao_aprovacao
        self.client.force_login(self.leader)
        unchanged=self.client.post(reverse('avaliar_bm',args=[bm.pk]),{'acao':'aprovar','versao_bm':version})
        self.assertEqual(unchanged.status_code,200,unchanged.content)
        bm.valor_pago=101;bm.save()
        self.client.force_login(self.leader)
        response=self.client.post(reverse('avaliar_bm',args=[bm.pk]),{'acao':'aprovar','versao_bm':version})
        self.assertEqual(response.status_code,409)
        bm.refresh_from_db();self.assertIsNone(bm.status_lider_documental)

    def test_reverter_migration_com_decisao_e_recusado(self):
        from importlib import import_module
        from types import SimpleNamespace
        bm=self.shared();self.evaluate(bm);self.decide(self.leader,bm)
        migration=import_module('gestao_contratos.migrations.0127_bm_aprovacao_duas_liderancas')
        with self.assertRaisesRegex(RuntimeError,'decisões'):
            migration.remove(None,SimpleNamespace(connection=connection))
