"""Reprogramação individual sem adoção prévia, somente em bancos sintéticos."""
from datetime import date,datetime
from unittest.mock import patch

from django.core.exceptions import PermissionDenied,ValidationError
from django.db import IntegrityError,transaction
from django.urls import reverse
from django.utils import timezone

from . import models as m,bm_cycles as cycles,payment_services as payments
from . import test_financeiro_fase2 as fixtures
from .financial_audit import financial_audit_context
from .tests import BaseUserTestCase


class ReprogramacaoIndividualBMTests(BaseUserTestCase):
    bm=fixtures.FinanceiroFase2Tests.bm
    nf=fixtures.FinanceiroFase2Tests.nf

    def setUp(self):
        fixtures.FinanceiroFase2Tests.setUp(self)
        self.clock=patch('gestao_contratos.bm_cycles.timezone.localdate',return_value=date(2026,11,21))
        self.clock.start();self.addCleanup(self.clock.stop)
        self.manager=self.create_user('manual_lider','gerente_contrato')
        self.director=self.create_user('manual_diretoria','diretoria')
        self.contracts[0].lider_contrato=self.manager;self.contracts[0].save()
        self.events[0].data_prevista_pagamento=date(2026,11,20);self.events[0].save()
        for day in (date(2026,11,20),date(2026,12,20),date(2027,1,20)):
            m.CalendarioPagamento.objects.create(data_pagamento=day)

    def pending(self,**extra):
        extra.setdefault('data_pagamento',date(2026,11,20))
        return self.bm(value='50000',operational='aprovado',
            data_aprovacao_gerente=timezone.make_aware(datetime(2026,11,15,12)),**extra)

    def url(self,bm):return reverse('reprogramar_bm',args=[bm.pk])

    def payload(self,bm):
        response=self.client.get(self.url(bm))
        self.assertEqual(response.status_code,200,response.content[:300])
        return response.context['form'].initial.copy()

    def current(self,bm):return m.CicloPagamentoBM.objects.get(bm=bm,sucessor__isnull=True)

    def test_opcao_na_linha_sem_ciclo_e_sem_botao_em_lote(self):
        bm=self.pending()
        for actor in (self.finance,self.supply):
            self.client.force_login(actor)
            response=self.client.get(reverse('previsao_pagamentos'),{'data_inicial':'2026-11-01','data_limite':'2026-11-30'})
            self.assertContains(response,self.url(bm))
            self.assertContains(response,'Reprogramar BM para 20/12/2026')
            self.assertNotContains(response,'Atualizar programação dos BMs')
        self.assertFalse(m.CicloPagamentoBM.objects.exists())

    def test_get_confirmacao_nao_registra_ciclo_ou_pagamento(self):
        bm=self.pending();response=self.client.get(self.url(bm))
        self.assertContains(response,'20/11/2026');self.assertContains(response,'20/12/2026')
        self.assertEqual(response.context['plan']['balance_cents'],5000000)
        self.assertFalse(m.CicloPagamentoBM.objects.exists());self.assertFalse(m.PagamentoNF.objects.exists())

    def test_post_sem_ciclo_cria_historico_e_reprograma_na_mesma_acao(self):
        bm=self.pending();before=m.BM.objects.values().get(pk=bm.pk)
        response=self.client.post(self.url(bm),self.payload(bm))
        self.assertEqual(response.status_code,302)
        current=self.current(bm)
        self.assertEqual((current.numero,current.tipo,current.data_prevista,current.saldo_inclusao),(2,'reprogramacao',date(2026,12,20),50000))
        self.assertEqual(m.BM.objects.values().get(pk=bm.pk),before)
        self.assertEqual(m.CicloPagamentoBM.objects.count(),2)
        self.assertFalse(m.DecisaoCicloBM.objects.exists());self.assertFalse(m.NF.objects.exists())
        listing=self.client.get(reverse('previsao_pagamentos'),{'data_inicial':'2026-12-01','data_limite':'2026-12-31'})
        self.assertContains(listing,'fin-bm-reprogramado')
        self.assertEqual([item.pk for item in listing.context['bms']],[bm.pk])

    def test_reutiliza_ciclo_inicial_existente_e_preserva_snapshot(self):
        bm=self.pending();cycles.process_bm(bm.pk,self.finance,today=date(2026,11,20))
        initial=m.CicloPagamentoBM.objects.values().get(bm=bm)
        self.assertEqual(self.client.post(self.url(bm),self.payload(bm)).status_code,302)
        self.assertEqual(m.CicloPagamentoBM.objects.count(),2)
        self.assertEqual(m.CicloPagamentoBM.objects.values().get(pk=initial['id']),initial)

    def test_diretoria_pendente_renova_lider_e_diretoria_e_libera_ledger(self):
        bm=self.pending();nf=self.nf(bm,value='50000')
        self.client.post(self.url(bm),self.payload(bm));current=self.current(bm)
        with self.assertRaises(ValidationError):
            payments.record_payment(nf_id=nf.pk,user=self.finance,valor=1,data_pagamento=date(2026,12,20),key='negado-antes-lider')
        cycles.decide(current.pk,self.manager,'gerencia',True)
        bm.refresh_from_db();self.assertEqual(bm.aprovacao_pagamento,'pendente')
        with self.assertRaises(ValidationError):
            payments.record_payment(nf_id=nf.pk,user=self.finance,valor=1,data_pagamento=date(2026,12,20),key='negado-antes-diretor')
        decision=cycles.decide(current.pk,self.director,'diretoria',True,'Conferido no novo ciclo')
        bm.refresh_from_db()
        self.assertEqual((bm.aprovacao_pagamento,bm.data_aprovacao_diretor),('aprovado',decision.registrado_em))
        self.assertEqual(cycles.cycle_state(cycles.raw_connection(),bm.pk)['stage'],'autorizado')
        audit=m.RegistroAuditoria.objects.get(operacao_financeira='decisao_bm',object_id=bm.pk)
        self.assertEqual((audit.usuario_id,audit.estado_anterior['aprovacao_pagamento'],audit.estado_posterior['ciclo_id']),
            (self.director.pk,'pendente',current.pk))
        self.assertEqual(current.anterior.contexto_inclusao['aprovacoes_iniciais']['aprovacao_pagamento'],'pendente')
        payments.record_payment(nf_id=nf.pk,user=self.finance,valor=50000,data_pagamento=date(2026,12,20),key='autorizado-no-ciclo')
        nf.refresh_from_db();self.assertEqual((nf.total_pago,nf.saldo_pendente,nf.financeiro_autorizou),(50000,0,True))

    def test_parcial_reprograma_somente_saldo_preserva_autorizacao_e_caixa(self):
        bm=self.pending(director='aprovado');nf=self.nf(bm,value='50000')
        first,_=payments.record_payment(nf_id=nf.pk,user=self.finance,valor=30000,data_pagamento=date(2026,11,20),key='primeira-parte')
        old_payment=m.PagamentoNF.objects.values().get(pk=first.pk);old_bm=m.BM.objects.values().get(pk=bm.pk)
        self.assertEqual(self.client.post(self.url(bm),self.payload(bm)).status_code,302)
        current=self.current(bm);self.assertEqual(current.saldo_inclusao,20000)
        cycles.decide(current.pk,self.manager,'gerencia',True);cycles.decide(current.pk,self.director,'diretoria',True)
        self.assertEqual(m.BM.objects.values().get(pk=bm.pk),old_bm)
        self.assertEqual(m.PagamentoNF.objects.values().get(pk=first.pk),old_payment)
        self.assertEqual(nf.movimentos.count(),1)

    def test_dois_envios_da_mesma_confirmacao_nao_duplicam(self):
        bm=self.pending();payload=self.payload(bm)
        self.assertEqual(self.client.post(self.url(bm),payload).status_code,302)
        self.assertEqual(self.client.post(self.url(bm),payload).status_code,409)
        self.assertEqual(m.CicloPagamentoBM.objects.count(),2)

    def test_pagamento_entre_confirmacao_e_post_reavalia_saldo(self):
        bm=self.pending(director='aprovado');nf=self.nf(bm,value='50000');payload=self.payload(bm)
        payments.record_payment(nf_id=nf.pk,user=self.finance,valor=10000,data_pagamento=date(2026,11,21),key='tardio')
        self.assertEqual(self.client.post(self.url(bm),payload).status_code,409)
        self.assertFalse(m.CicloPagamentoBM.objects.exists())
        self.assertEqual(self.client.post(self.url(bm),self.payload(bm)).status_code,302)
        self.assertEqual(self.current(bm).saldo_inclusao,40000)

    def test_mudanca_da_data_no_mesmo_calendario_exige_nova_confirmacao(self):
        bm=self.pending();payload=self.payload(bm)
        m.CalendarioPagamento.objects.filter(pk=payload['calendar_id']).update(data_pagamento=date(2026,12,21))
        self.assertEqual(self.client.post(self.url(bm),payload).status_code,409)
        self.assertFalse(m.CicloPagamentoBM.objects.exists())

    def test_sem_calendario_nao_cria_nem_ciclo_inicial(self):
        bm=self.pending();m.CalendarioPagamento.objects.filter(data_pagamento__gt=date(2026,11,20)).delete()
        response=self.client.get(self.url(bm))
        self.assertContains(response,'Aguardando definição',status_code=409)
        self.assertFalse(m.CicloPagamentoBM.objects.exists())

    def test_pago_integral_e_programacao_futura_nao_oferecem_confirmacao(self):
        bm=self.pending(director='aprovado');self.nf(bm,value='50000',paid=True)
        self.assertEqual(self.client.get(self.url(bm)).status_code,409)
        other=self.pending(data_pagamento=date(2026,11,22))
        self.assertEqual(self.client.get(self.url(other)).status_code,409)
        self.assertFalse(m.CicloPagamentoBM.objects.exists())

    def test_reprovacao_inicial_e_operacional_pendente_continuam_bloqueadas(self):
        for bm in (self.pending(director='reprovado'),self.bm(value='50000')):
            response=self.client.get(self.url(bm))
            self.assertEqual(response.status_code,409)
            self.assertFalse(response.context['plan']['available'])
        self.assertFalse(m.CicloPagamentoBM.objects.exists())

    def test_perfis_sem_competencia_nao_reprogramam(self):
        bm=self.pending()
        for actor in (self.director,self.manager,self.leader,self.create_user('manual_fornecedor','fornecedor')):
            self.client.force_login(actor)
            for method in ('get','post'):
                self.assertEqual(getattr(self.client,method)(self.url(bm),{}).status_code,403)
        self.assertFalse(m.CicloPagamentoBM.objects.exists())

    def test_urls_antigas_nao_criam_lotes_iniciais(self):
        bm=self.pending()
        self.assertEqual(self.client.post(reverse('processar_ciclos_bm')).status_code,302)
        response=self.client.post(reverse('processar_ciclos_bm_individual',args=[bm.pk]))
        self.assertRedirects(response,self.url(bm),fetch_redirect_response=False)
        self.assertFalse(m.CicloPagamentoBM.objects.exists())

    def test_destino_de_retorno_externo_nao_e_aceito(self):
        bm=self.pending();payload=self.payload(bm);payload['next']='https://outside.example/roubar'
        response=self.client.post(self.url(bm),payload)
        self.assertEqual(response.status_code,302)
        self.assertEqual(response.url,reverse('detalhe_bm_financeiro',args=[bm.pk]))

    def test_orm_direto_nao_paga_durante_renovacao(self):
        bm=self.pending();nf=self.nf(bm,value='50000');self.client.post(self.url(bm),self.payload(bm))
        with self.assertRaises(IntegrityError),transaction.atomic(),financial_audit_context(self.finance):
            m.PagamentoNF.objects.create(nf=nf,valor=1,data_pagamento=date(2026,12,20),tipo='pagamento',
                registrado_por=self.finance,chave_idempotencia='tentativa-direta-manual')
        self.assertFalse(nf.movimentos.exists())

    def test_financeiro_nao_projeta_autorizacao_da_diretoria(self):
        bm=self.pending();self.client.post(self.url(bm),self.payload(bm))
        decision=cycles.decide(self.current(bm).pk,self.manager,'gerencia',True)
        with self.assertRaises(PermissionDenied):cycles.record_first_director_authorization(bm,self.finance,decision,'forjada')
        bm.refresh_from_db();self.assertEqual(bm.aprovacao_pagamento,'pendente')

    def test_autorizacao_antiga_da_tela_nao_substitui_decisao_do_ciclo(self):
        bm=self.pending();self.client.post(self.url(bm),self.payload(bm))
        self.client.force_login(self.director)
        page=self.client.get(reverse('detalhe_bm_financeiro',args=[bm.pk]))
        self.assertNotContains(page,'data-bm-payment-action="aprovar_pagamento"')
        response=self.client.post(reverse('avaliar_bm',args=[bm.pk]),{'acao':'aprovar_pagamento'})
        self.assertEqual(response.status_code,409)
        bm.refresh_from_db();self.assertEqual(bm.aprovacao_pagamento,'pendente')
        self.assertFalse(m.DecisaoCicloBM.objects.exists())

    def test_reprogramacao_repetida_preserva_primeira_autorizacao_efetiva(self):
        bm=self.pending();self.client.post(self.url(bm),self.payload(bm));first=self.current(bm)
        cycles.decide(first.pk,self.manager,'gerencia',True)
        authorization=cycles.decide(first.pk,self.director,'diretoria',True)
        with patch('gestao_contratos.bm_cycles.timezone.localdate',return_value=date(2026,12,21)):
            self.assertEqual(self.client.post(self.url(bm),self.payload(bm)).status_code,302)
            self.assertEqual(self.current(bm).data_prevista,date(2027,1,20))
            self.assertEqual(cycles.cycle_state(cycles.raw_connection(),bm.pk)['stage'],'gerencia')
            cycles.decide(self.current(bm).pk,self.manager,'gerencia',True)
            cycles.decide(self.current(bm).pk,self.director,'diretoria',True)
        bm.refresh_from_db();self.assertEqual(bm.data_aprovacao_diretor,authorization.registrado_em)
        self.assertEqual(m.RegistroAuditoria.objects.filter(operacao_financeira='decisao_bm',object_id=bm.pk).count(),1)
        self.assertEqual(m.DecisaoCicloBM.objects.count(),4)

    def test_reprovacao_do_novo_ciclo_exige_revisao_e_nao_autoriza_documento(self):
        bm=self.pending();self.client.post(self.url(bm),self.payload(bm));first=self.current(bm)
        cycles.decide(first.pk,self.manager,'gerencia',True)
        cycles.decide(first.pk,self.director,'diretoria',False,'Documentação ainda insuficiente')
        bm.refresh_from_db();self.assertEqual(bm.aprovacao_pagamento,'pendente')
        with patch('gestao_contratos.bm_cycles.timezone.localdate',return_value=date(2026,12,21)):
            response=self.client.get(self.url(bm));self.assertEqual(response.status_code,409)
        revised=cycles.revise(first.pk,self.supply,'Fornecedor apresentou os documentos pendentes')
        cycles.decide(revised.pk,self.manager,'gerencia',True)
        cycles.decide(revised.pk,self.director,'diretoria',True)
        bm.refresh_from_db();self.assertEqual(bm.aprovacao_pagamento,'aprovado')
        self.assertEqual(m.DecisaoCicloBM.objects.filter(ciclo=first,situacao='reprovado').count(),1)

    def test_bm_compartilhado_conserva_duas_liderancas_ao_autorizar_no_ciclo(self):
        from .test_bm_duas_liderancas import approve_shared_fixture
        bm=self.bm(evento=self.events[1],value='50000')
        approve_shared_fixture(self,bm)
        bm.refresh_from_db()
        old=(bm.aprovador_lider_documental_id,bm.aprovador_lider_financeiro_id,bm.data_lider_documental,bm.data_lider_financeiro)
        self.client.force_login(self.finance)
        self.assertEqual(self.client.post(self.url(bm),self.payload(bm)).status_code,302)
        current=self.current(bm)
        cycles.decide(current.pk,self.other,'gerencia',True)
        cycles.decide(current.pk,self.director,'diretoria',True)
        bm.refresh_from_db()
        self.assertEqual((bm.aprovador_lider_documental_id,bm.aprovador_lider_financeiro_id,bm.data_lider_documental,bm.data_lider_financeiro),old)
        self.assertEqual(cycles.cycle_state(cycles.raw_connection(),bm.pk)['stage'],'autorizado')
