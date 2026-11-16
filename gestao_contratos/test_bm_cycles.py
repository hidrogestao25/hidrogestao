"""Renovação por programação: caixa real, competências e histórico permanente."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, IntegrityError, transaction
from django.urls import reverse

from . import bm_cycles as cycles, models as m, payment_services as payments
from . import test_financeiro_fase2 as fixtures
from .tests import BaseUserTestCase


class CiclosBMTests(BaseUserTestCase):
    def bm(self, *args, **extra):
        extra.setdefault('data_pagamento',date(2026,11,20))
        return fixtures.FinanceiroFase2Tests.bm(self,*args,**extra)
    nf = fixtures.FinanceiroFase2Tests.nf

    def setUp(self):
        fixtures.FinanceiroFase2Tests.setUp(self)
        self.manager = self.create_user('gestor_ciclo', 'gerente_contrato')
        self.other_manager = self.create_user('gestor_fora_ciclo', 'gerente_contrato')
        self.director = self.create_user('diretor_ciclo', 'diretoria')
        self.events[0].data_prevista_pagamento = date(2026, 11, 20)
        self.events[0].save()
        for day in (date(2026, 11, 20), date(2026, 12, 20), date(2027, 1, 20)):
            m.CalendarioPagamento.objects.create(data_pagamento=day)

    def approved(self, **extra):
        return self.bm(operational='aprovado', director='aprovado', value='50000', **extra)

    def process(self, bm, day=date(2026, 11, 21)):
        with patch('gestao_contratos.bm_cycles.timezone.localdate', return_value=day):
            return cycles.process_bm(bm.pk, self.finance, today=day)

    def assign(self, bm, manager=None):
        # Configura apenas o vínculo de liderança já existente, como na operação.
        leader=manager or self.manager
        if bm.os_id:
            origin=m.OS.objects.get(pk=bm.os_id);origin.lider_contrato=leader;origin.save()
        else:
            origin=m.ContratoTerceiros.objects.get(pk=bm.evento.contrato_terceiro_id)
            if origin.guarda_chuva and origin.cod_projeto_id:
                project=origin.cod_projeto;project.lider_contrato=leader;project.save()
            else:
                origin.lider_contrato=leader;origin.save()
        return origin

    def head(self, bm):
        return m.CicloPagamentoBM.objects.get(bm=bm, sucessor__isnull=True)

    def approve(self, bm):
        cycle = self.head(bm)
        cycles.decide(cycle.pk, self.manager, 'gerencia', True)
        cycles.decide(cycle.pk, self.director, 'diretoria', True)

    def pay(self, nf, amount, key='pagamento'):
        return payments.record_payment(nf_id=nf.pk, user=self.finance, valor=amount,
            data_pagamento=date(2026, 12, 20), key=key)[0]

    def test_01_sem_nf_reaparece_e_exige_novas_decisoes_sem_reescrever_bm(self):
        bm = self.approved()
        before = m.BM.objects.values().get(pk=bm.pk)
        self.assign(bm)
        result = self.process(bm)
        self.assertEqual(len(result['created']), 2)
        current = self.head(bm)
        self.assertEqual((current.numero, current.data_prevista, current.saldo_inclusao), (2, date(2026, 12, 20), Decimal('50000')))
        self.assertEqual(cycles.cycle_state(cycles.raw_connection(), bm.pk)['stage'], 'gerencia')
        self.assertEqual(m.BM.objects.values().get(pk=bm.pk), before)
        self.assertFalse(m.NF.objects.exists())
        self.approve(bm)
        self.assertEqual(cycles.cycle_state(cycles.raw_connection(), bm.pk)['stage'], 'autorizado')
        self.assertEqual(m.BM.objects.values().get(pk=bm.pk), before)
        self.assertEqual(m.DecisaoCicloBM.objects.count(), 2)

    def test_02_nf_nao_paga_preservada_e_pagamento_antigo_nao_libera_ciclo(self):
        bm = self.approved()
        nf = self.nf(bm, value='50000')
        before = m.NF.objects.values().get(pk=nf.pk)
        self.assign(bm)
        self.process(bm)
        with self.assertRaises(ValidationError):
            self.pay(nf, 1)
        self.assertEqual(m.NF.objects.values().get(pk=nf.pk), before)
        self.approve(bm)
        self.pay(nf, 50000)
        self.assertTrue(cycles.financial_state(cycles.raw_connection(), bm.pk)['full'])
        self.assertEqual(m.PagamentoCicloBM.objects.get().ciclo, self.head(bm))

    def test_03_pagamento_parcial_reprograma_so_saldo_e_preserva_caixa(self):
        bm = self.approved()
        nf = self.nf(bm, value='50000')
        first = self.pay(nf, 30000, 'primeiro')
        before = m.PagamentoNF.objects.values().get(pk=first.pk)
        self.assign(bm)
        self.process(bm)
        self.assertEqual(self.head(bm).saldo_inclusao, Decimal('20000'))
        self.approve(bm)
        self.pay(nf, 10000, 'segundo')
        self.pay(nf, 10000, 'terceiro')
        nf.refresh_from_db()
        self.assertEqual((nf.total_pago, nf.saldo_pendente), (50000, 0))
        self.assertEqual(m.PagamentoNF.objects.values().get(pk=first.pk), before)
        self.assertEqual(m.PagamentoCicloBM.objects.count(), 2)
        self.assertEqual(self.process(bm, date(2026, 12, 21))['created'], [])

    def test_04_pago_integral_nao_exige_aprovacao_retroativa(self):
        bm=self.approved();nf=self.nf(bm,value='50000',paid=True)
        before=m.NF.objects.values().get(pk=nf.pk)
        self.assertEqual(self.process(bm)['created'],[])
        self.assertFalse(m.CicloPagamentoBM.objects.exists())
        self.assertEqual(m.NF.objects.values().get(pk=nf.pk),before)

    def test_05_06_ciclos_repetidos_preservam_decisoes_e_nao_reutilizam_autorizacao(self):
        bm=self.approved();nf=self.nf(bm,value='50000');self.assign(bm);self.process(bm);self.approve(bm)
        old=list(m.DecisaoCicloBM.objects.values())
        self.process(bm,date(2026,12,21))
        self.assertEqual(self.head(bm).numero,3)
        self.assertEqual(self.head(bm).data_prevista,date(2027,1,20))
        self.assertEqual(list(m.DecisaoCicloBM.objects.values()),old)
        self.assertEqual(m.BM.objects.count(),1)
        with self.assertRaises(ValidationError):self.pay(nf,1)
        self.approve(bm)
        self.assertEqual(m.DecisaoCicloBM.objects.count(),4)

    def test_07_somente_gerente_do_contrato_projeto_pode_decidir(self):
        bm=self.approved();self.assign(bm);self.process(bm);cycle=self.head(bm)
        for user in (self.other_manager,self.finance,self.supply,self.leader):
            with self.assertRaises(PermissionDenied):cycles.decide(cycle.pk,user,'gerencia',True)
        decision=cycles.decide(cycle.pk,self.manager,'gerencia',True)
        self.assertEqual((decision.registrado_por_id,decision.saldo_avaliado),(self.manager.pk,50000))
        self.assertEqual(decision.responsavel_id,self.manager.pk)

    def test_08_diretoria_somente_depois_do_gerente(self):
        bm=self.approved();nf=self.nf(bm,value='50000');self.assign(bm);self.process(bm);cycle=self.head(bm)
        with self.assertRaises(ValidationError):cycles.decide(cycle.pk,self.director,'diretoria',True)
        cycles.decide(cycle.pk,self.manager,'gerencia',True)
        with self.assertRaises(PermissionDenied):cycles.decide(cycle.pk,self.finance,'diretoria',True)
        cycles.decide(cycle.pk,self.director,'diretoria',True,'Autorizado após conferência')
        self.pay(nf,1)

    def test_09_documento_compartilhado_participacoes_independentes(self):
        from .test_auditoria import pdf
        first=self.approved(arquivo_bm=pdf());second=self.approved(index=1,arquivo_bm=first.arquivo_bm.name)
        nf1=self.nf(first,value='50000');nf2=self.nf(second,value='50000')
        self.pay(nf1,50000,'participacao-1')
        self.assertEqual(self.process(first)['created'],[])
        self.assign(second,self.other_manager);self.process(second)
        self.assertEqual(self.head(second).saldo_inclusao,50000)
        self.assertEqual(nf2.movimentos.count(),0)
        self.assertEqual(m.BM.objects.count(),2)
        self.assertEqual(m.NF.objects.count(),2)

    def test_10_origem_cancelada_nao_reprograma(self):
        bm=self.approved(os=True);self.order.status='cancelada';self.order.save()
        result=self.process(bm)
        self.assertFalse(result['created']);self.assertIn('cancelada',result['reason'])
        self.assertFalse(m.CicloPagamentoBM.objects.exists())

    def test_11_rotina_idempotente_mesma_programacao(self):
        bm=self.approved();self.process(bm)
        self.assertEqual(self.process(bm)['created'],[])
        self.assertEqual(m.CicloPagamentoBM.objects.count(),2)
        self.assertEqual(m.BM.objects.count(),1)

    def test_12_pagamento_tardio_antes_do_novo_ciclo_reavalia_saldo(self):
        bm=self.approved();nf=self.nf(bm,value='50000')
        self.process(bm,date(2026,11,20))
        self.assertEqual(self.head(bm).tipo,'inicial')
        self.pay(nf,50000,'tardio')
        self.assertEqual(self.process(bm)['created'],[])
        self.assertEqual(m.CicloPagamentoBM.objects.count(),1)

    def test_13_estorno_reabre_saldo_e_invalida_decisoes_do_ciclo(self):
        bm=self.approved();nf=self.nf(bm,value='50000');self.assign(bm);self.process(bm);self.approve(bm)
        payment=self.pay(nf,50000,'pago')
        payments.reverse_payment(movement_id=payment.pk,user=self.supply,valor=20000,data_estorno=date(2026,12,20),motivo='Correção documentada',key='estorno')
        state=cycles.cycle_state(cycles.raw_connection(),bm.pk)
        self.assertEqual((state['balance_cents'],state['stage']),(2000000,'revisao'))
        with self.assertRaises(ValidationError):self.pay(nf,1,'sem-nova-decisao')
        self.process(bm,date(2026,12,21));self.assertEqual(self.head(bm).saldo_inclusao,20000)
        self.approve(bm);self.pay(nf,20000,'saldo-reaberto')
        self.assertEqual(nf.movimentos.count(),3)

    def test_14_medicao_caixa_e_previsao_nao_duplicam_em_varios_ciclos(self):
        from .financial_queries import FinancialData
        from .financial_operations import monthly_projection
        bm=self.approved();nf=self.nf(bm,value='50000');self.pay(nf,30000,'parcial-relatorio')
        self.assign(bm);self.process(bm);self.approve(bm)
        self.process(bm,date(2026,12,21));self.approve(bm)
        data=FinancialData(self.finance,{'historico':True})
        stats=data.indicators()
        self.assertEqual((stats['medido'],stats['faturado'],stats['pago'],stats['autorizado']),(50000,50000,30000,20000))
        projection=monthly_projection(self.finance,{'historico':True})
        pending=[r for r in projection['rows'] if r['authorized_unpaid']]
        self.assertEqual([(r['month'].month,r['authorized_unpaid']) for r in pending],[(1,Decimal('20000'))])
        self.assertEqual(projection['totals']['paid'],30000)

    def test_15_fluxo_inicial_nao_muda(self):
        bm=self.approved();nf=self.nf(bm,value='50000')
        self.pay(nf,1,'primeiro-fluxo')
        self.assertFalse(m.CicloPagamentoBM.objects.exists())
        self.assertEqual(nf.movimentos.count(),1)

    def test_reprovacao_exige_motivo_e_nao_desaparece_com_data(self):
        bm=self.approved();self.assign(bm);self.process(bm);cycle=self.head(bm)
        with self.assertRaises(ValidationError):cycles.decide(cycle.pk,self.manager,'gerencia',False,' ')
        rejection=cycles.decide(cycle.pk,self.manager,'gerencia',False,'Documentação incompleta')
        self.assertFalse(self.process(bm,date(2026,12,21))['created'])
        self.assertEqual(self.head(bm),cycle)
        with self.assertRaises(ValidationError):cycles.revise(cycle.pk,self.supply,'')
        new=cycles.revise(cycle.pk,self.supply,'Fornecedor complementou os documentos')
        self.assertEqual((new.anterior_id,new.data_prevista),(cycle.pk,cycle.data_prevista))
        rejection.refresh_from_db();self.assertEqual(rejection.justificativa,'Documentação incompleta')
        self.approve(bm)

    def test_sem_calendario_nao_inventa_data(self):
        m.CalendarioPagamento.objects.filter(data_pagamento__gt=date(2026,11,20)).delete()
        bm=self.approved();result=self.process(bm)
        self.assertEqual(self.head(bm).numero,1)
        self.assertIn('aguardando',result['reason'])

    def test_data_pagamento_bm_define_programacao_sem_previsao_do_evento(self):
        self.events[0].data_prevista_pagamento=None;self.events[0].save()
        bm=self.approved()
        self.assertEqual(len(self.process(bm)['created']),2)
        self.assertEqual(self.head(bm).anterior.data_prevista,date(2026,11,20))

    def test_mudanca_material_invalida_decisoes_e_preserva_historico(self):
        bm=self.approved();nf=self.nf(bm,value='50000');self.assign(bm);self.process(bm);self.approve(bm)
        old=list(m.DecisaoCicloBM.objects.values())
        nf.numero_nf='IDENTIFICACAO-CORRIGIDA';nf.save()
        self.assertEqual(cycles.cycle_state(cycles.raw_connection(),bm.pk)['stage'],'revisao')
        with self.assertRaises(ValidationError):self.pay(nf,1)
        self.assertEqual(list(m.DecisaoCicloBM.objects.values()),old)

    def test_troca_de_gerente_nao_reaproveita_decisao_anterior(self):
        bm=self.approved();self.assign(bm);self.process(bm);self.approve(bm)
        self.assign(bm,self.other_manager)
        state=cycles.cycle_state(cycles.raw_connection(),bm.pk)
        self.assertEqual(state['stage'],'revisao')
        self.assertEqual(m.DecisaoCicloBM.objects.filter(responsavel=self.manager).count(),2)
        self.assertEqual(m.DecisaoCicloBM.objects.count(),2)

    def test_decisoes_e_ciclos_sao_imutaveis_mesmo_bulk_sql(self):
        bm=self.approved();self.assign(bm);self.process(bm);self.approve(bm)
        for model in (m.CicloPagamentoBM,m.DecisaoCicloBM):
            with self.assertRaises(IntegrityError),transaction.atomic():model.objects.update(id=m.models.F('id'))
            with self.assertRaises(IntegrityError),transaction.atomic():
                with connection.cursor() as cursor:cursor.execute('DELETE FROM '+model._meta.db_table)

    def test_pagamento_por_orm_nao_contorna_ciclo(self):
        from .financial_audit import financial_audit_context
        bm=self.approved();nf=self.nf(bm,value='50000');self.assign(bm);self.process(bm)
        with self.assertRaises(IntegrityError),transaction.atomic(),financial_audit_context(self.finance):
            m.PagamentoNF.objects.create(nf=nf,valor=1,data_pagamento=date(2026,12,20),tipo='pagamento',
                registrado_por=self.finance,chave_idempotencia='tentativa-direta')
        self.assertFalse(m.PagamentoNF.objects.exists())

    def test_get_nao_muda_ciclos_e_nao_exibe_cadastro_em_lote(self):
        bm=self.approved()
        response=self.client.get(reverse('previsao_pagamentos'),{'data_inicial':'2026-12-01','data_limite':'2026-12-31'})
        self.assertNotContains(response,'Atualizar programação dos BMs')
        self.assertFalse(m.CicloPagamentoBM.objects.exists())
        self.assertEqual(self.client.get(reverse('processar_ciclos_bm')).status_code,405)
        self.assertFalse(m.CicloPagamentoBM.objects.exists())

    def test_previsao_e_excel_reapresentam_uma_vez_com_historico(self):
        from io import BytesIO
        from openpyxl import load_workbook
        bm=self.approved();self.assign(bm);self.process(bm)
        filters={'data_inicial':'2026-12-01','data_limite':'2026-12-31','ciclo':'reprogramados'}
        response=self.client.get(reverse('previsao_pagamentos'),filters)
        self.assertEqual([b.pk for b in response.context['bms']],[bm.pk])
        self.assertContains(response,'não pago no ciclo anterior')
        export=self.client.get(reverse('exportar_bms_previsao_excel'),filters)
        self.assertEqual(export.status_code,200)
        book=load_workbook(BytesIO(export.content),read_only=True)
        self.assertEqual(len(list(book['Boletins de Medição'].values)),2)
        self.assertEqual(len(list(book['Ciclos de pagamento'].values)),3)
        book.close()

    def test_home_gerente_e_diretor_mostram_apenas_etapa_competente(self):
        bm=self.approved();self.assign(bm);self.process(bm)
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(reverse('home')),'Reaprovar ciclo')
        self.client.force_login(self.other_manager)
        self.assertNotContains(self.client.get(reverse('home')),'Reaprovar ciclo')
        cycles.decide(self.head(bm).pk,self.manager,'gerencia',True)
        self.client.force_login(self.director)
        self.assertContains(self.client.get(reverse('home')),'Autorizar ciclo')

    def test_formulario_diretoria_rejeicao_obrigatoria_aprovacao_opcional(self):
        bm=self.approved();self.assign(bm);self.process(bm);cycle=self.head(bm)
        cycles.decide(cycle.pk,self.manager,'gerencia',True)
        self.client.force_login(self.director)
        url=reverse('decidir_ciclo_bm',args=[cycle.pk,'diretoria'])
        state=cycles.cycle_state(cycles.raw_connection(),bm.pk)
        payload={'versao':state['version'],'responsavel':state['manager']['id'],'acao':'reprovar','justificativa':''}
        self.assertEqual(self.client.post(url,payload).status_code,400)
        payload['acao']='aprovar'
        self.assertEqual(self.client.post(url,payload).status_code,302)

    def test_guarda_chuva_vincula_gerente_ao_projeto_real_da_os(self):
        self.contracts[0].guarda_chuva=True;self.contracts[0].save()
        self.order.cod_projeto=self.projects[1];self.order.save()
        bm=self.approved(os=True);self.assign(bm)
        state=cycles.financial_state(cycles.raw_connection(),bm.pk)
        self.assertEqual(state['project_id'],self.projects[1].pk)
        self.assertEqual(cycles.responsible(cycles.raw_connection(),state)['id'],self.manager.pk)

    def test_sem_vinculo_explicito_nao_libera_qualquer_gerente(self):
        self.contracts[0].lider_contrato=None;self.contracts[0].save()
        bm=self.approved();self.process(bm)
        self.assertEqual(cycles.cycle_state(cycles.raw_connection(),bm.pk)['stage'],'sem_gerente')
        with self.assertRaises(PermissionDenied):cycles.decide(self.head(bm).pk,self.manager,'gerencia',True)

    def test_sem_nf_previsao_mensal_muda_saldo_sem_criar_faturamento(self):
        from .financial_operations import monthly_projection
        bm=self.approved();self.process(bm)
        projection=monthly_projection(self.finance,{'historico':True})
        self.assertEqual(projection['totals']['other_unpaid'],50000)
        self.assertEqual(projection['totals']['paid'],0)
        self.assertEqual([(r['month'].month,r['other_unpaid']) for r in projection['rows'] if r['other_unpaid']],[(12,50000)])

    def test_compartilhado_cruzado_preserva_duas_liderancas_e_gerente_financeiro(self):
        from .test_bm_duas_liderancas import approve_shared_fixture
        bm=self.bm(index=0,evento=self.events[1],value='50000')
        approve_shared_fixture(self,bm)
        self.client.force_login(self.director)
        self.assertEqual(self.client.post(reverse('avaliar_bm',args=[bm.pk]),{'acao':'aprovar_pagamento'}).status_code,200)
        bm.refresh_from_db();before=m.BM.objects.values().get(pk=bm.pk)
        origin=self.assign(bm);self.assertEqual(origin.pk,self.contracts[1].pk)
        self.process(bm);self.approve(bm)
        self.assertEqual(m.BM.objects.values().get(pk=bm.pk),before)
        self.assertEqual(bm.aprovador_lider_documental_id,self.leader.pk)
        self.assertEqual(bm.aprovador_lider_financeiro_id,self.other.pk)

    def test_programacao_nf_futura_nao_e_antecipada_pelo_evento(self):
        bm=self.approved();nf=self.nf(bm,value='50000')
        schedule,_=payments.schedule(nf_id=nf.pk,user=self.finance,valor=50000,data_prevista=date(2026,12,20),motivo='Prazo confirmado',key='futuro')
        self.process(bm)
        self.assertEqual((self.head(bm).numero,self.head(bm).data_prevista),(2,date(2026,12,20)))
        self.assertEqual(self.head(bm).anterior.data_prevista,bm.data_pagamento)
        self.assertEqual(m.ProgramacaoPagamento.objects.get(pk=schedule.pk).data_prevista,date(2026,12,20))

    def test_multiplos_prazos_nf_preservados_para_conferencia(self):
        bm=self.approved();nf=self.nf(bm,value='50000')
        for key,day in [('uma',date(2026,11,20)),('outra',date(2026,12,20))]:
            payments.schedule(nf_id=nf.pk,user=self.finance,valor=25000,data_prevista=day,motivo='Parcelas existentes',key=key)
        self.assertIn('datas diferentes',self.process(bm)['reason'])
        self.assertFalse(m.CicloPagamentoBM.objects.exists())
        self.assertEqual(m.ProgramacaoPagamento.objects.count(),2)

    def test_cancelamento_nf_com_estorno_nao_recria_obrigacao(self):
        bm=self.approved();nf=self.nf(bm,value='50000');self.pay(nf,30000,'antes-cancelar')
        payments.cancel_invoice(nf_id=nf.pk,user=self.supply,motivo='Cancelamento comprovado')
        self.assertIn('canceladas',self.process(bm)['reason'])
        self.assertFalse(m.CicloPagamentoBM.objects.exists())
        self.assertEqual(nf.movimentos.count(),2)

    def test_nao_altera_calendario_ja_usado_por_ciclo(self):
        bm=self.approved();self.process(bm)
        with self.assertRaises(IntegrityError),transaction.atomic():
            m.CalendarioPagamento.objects.filter(pk=self.head(bm).calendario_id).update(data_pagamento=date(2026,12,21))

    def test_command_dry_run_nao_grava_e_operacao_gera_auditoria(self):
        from io import StringIO
        import json
        from django.core.management import call_command
        bm=self.approved();output=StringIO()
        call_command('processar_ciclos_bm',bm_ids=[bm.pk],dry_run=True,stdout=output)
        self.assertTrue(json.loads(output.getvalue())['dry_run'])
        self.assertFalse(m.CicloPagamentoBM.objects.exists())
        self.assign(bm);self.process(bm);self.approve(bm)
        self.assertEqual(m.RegistroAuditoria.objects.filter(operacao_financeira__startswith='ciclo_bm_').count(),4)

    def test_ciclo_com_decisoes_nao_pode_ser_removido_pela_reversao(self):
        from types import SimpleNamespace
        from .bm_cycle_sql import uninstall
        bm=self.approved();self.process(bm)
        with self.assertRaises(RuntimeError):uninstall(None,SimpleNamespace(connection=connection))
        self.assertEqual(m.CicloPagamentoBM.objects.count(),2)

    def test_mudanca_entre_abertura_e_envio_formulario_e_negada(self):
        bm=self.approved();self.assign(bm);self.process(bm);cycle=self.head(bm)
        old=cycles.cycle_state(cycles.raw_connection(),bm.pk)
        self.nf(bm,value='50000')
        with self.assertRaises(ValidationError):
            cycles.decide(cycle.pk,self.manager,'gerencia',True,expected_version=old['version'],expected_responsible=old['manager']['id'])
        self.assertFalse(m.DecisaoCicloBM.objects.exists())

    def test_reprovacao_no_ciclo_vai_para_fila_atencao_bm_e_nf(self):
        from .financial_queries import FinancialData
        bm=self.approved();nf=self.nf(bm,value='50000');self.assign(bm);self.process(bm)
        cycles.decide(self.head(bm).pk,self.manager,'gerencia',False,'Conferir o recebimento')
        data=FinancialData(self.finance,{'historico':True})
        self.assertIn(bm,data.queries['atencao_bm']);self.assertIn(nf,data.queries['atencao_nf'])
        self.assertNotIn(nf,data.queries['autorizacao']);self.assertNotIn(nf,data.queries['pagamento'])
        filtered=FinancialData(self.finance,{'historico':True,'autorizacao':'reprovado'})
        self.assertEqual(list(filtered.nfs),[nf])

    def test_filtro_autorizacao_diretoria_inclui_apenas_ciclo_pendente(self):
        from .financial_queries import FinancialData
        bm=self.approved();self.nf(bm,value='50000');self.assign(bm);self.process(bm)
        cycles.decide(self.head(bm).pk,self.manager,'gerencia',True)
        data=FinancialData(self.finance,{'historico':True,'autorizacao':'diretoria'})
        self.assertEqual(list(data.bms),[bm])
        cycles.decide(self.head(bm).pk,self.director,'diretoria',True)
        self.assertFalse(FinancialData(self.finance,{'historico':True,'autorizacao':'diretoria'}).bms.exists())

    def test_correcao_fiscal_desfeita_nao_restaura_decisao_antiga(self):
        bm=self.approved();nf=self.nf(bm,value='50000');self.assign(bm);self.process(bm);self.approve(bm)
        old=nf.numero_nf
        nf.numero_nf='OUTRA-NUMERACAO';nf.save()
        nf.numero_nf=old;nf.save()
        self.assertEqual(cycles.cycle_state(cycles.raw_connection(),bm.pk)['stage'],'revisao')
        with self.assertRaises(ValidationError):self.pay(nf,1)

    def test_nf_paga_menor_que_medicao_nao_inventa_saldo_liquidavel(self):
        bm=self.approved();self.nf(bm,value='30000',paid=True)
        self.assertIn('valor efetivamente devido',self.process(bm)['reason'])
        self.assertFalse(m.CicloPagamentoBM.objects.exists())

    def test_tres_grupos_de_lideranca_renovam_somente_quando_vinculados(self):
        for index,role in enumerate(('lider_contrato','gerente_lider','gerente_contrato')):
            with self.subTest(role=role):
                actor=self.create_user(f'lider_ciclo_{index}',role)
                bm=self.approved();self.assign(bm,actor);self.process(bm)
                self.client.force_login(actor)
                self.assertContains(self.client.get(reverse('home')),'Reaprovar ciclo')
                cycle=self.head(bm)
                url=reverse('decidir_ciclo_bm',args=[cycle.pk,'gerencia'])
                self.assertEqual(self.client.get(url).status_code,200)
                state=cycles.cycle_state(cycles.raw_connection(),bm.pk)
                response=self.client.post(url,{'acao':'aprovar','versao':state['version'],'responsavel':actor.pk})
                self.assertEqual(response.status_code,302,response.content)
                decision=cycle.decisoes.get(etapa='gerencia')
                self.assertEqual((decision.registrado_por_id,decision.responsavel_id),(actor.pk,actor.pk))
                cycles.decide(cycle.pk,self.director,'diretoria',True)
                self.assertEqual(cycles.cycle_state(cycles.raw_connection(),bm.pk)['stage'],'autorizado')

    def test_lider_contrato_vinculado_renova_os_sem_herdar_outro_projeto(self):
        self.contracts[0].guarda_chuva=True;self.contracts[0].save()
        self.order.cod_projeto=self.projects[1];self.order.lider_contrato=self.other;self.order.save()
        bm=self.approved(os=True);self.process(bm);cycle=self.head(bm)
        with self.assertRaises(PermissionDenied):cycles.decide(cycle.pk,self.leader,'gerencia',True)
        cycles.decide(cycle.pk,self.other,'gerencia',True)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('detalhe_bm_financeiro',args=[bm.pk])).status_code,200)
