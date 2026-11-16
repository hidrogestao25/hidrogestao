"""Programação original pelo BM, com histórico preservado e calendário nos sucessores."""
from datetime import date,datetime
from io import BytesIO
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from . import bm_cycles as cycles,models as m,payment_services as payments
from . import test_financeiro_fase2 as fixtures
from .bm_cycle_views import info
from .tests import BaseUserTestCase


class ProgramacaoDataBMTests(BaseUserTestCase):
    nf=fixtures.FinanceiroFase2Tests.nf

    def setUp(self):
        fixtures.FinanceiroFase2Tests.setUp(self)
        clock=patch('gestao_contratos.bm_cycles.timezone.localdate',return_value=date(2026,11,13))
        clock.start();self.addCleanup(clock.stop)
        self.events[0].data_prevista_pagamento=date(2026,9,20);self.events[0].save()
        self.order.data_prevista_pagamento=date(2026,9,20);self.order.save()
        for day in (date(2026,10,27),date(2026,11,24),date(2026,12,21)):
            m.CalendarioPagamento.objects.create(data_pagamento=day)

    def bm(self,day=date(2026,11,24),**extra):
        return fixtures.FinanceiroFase2Tests.bm(self,value='50000',operational='aprovado',
            data_pagamento=day,data_aprovacao_gerente=timezone.make_aware(datetime(2026,11,13,12)),**extra)

    def current(self,bm):return m.CicloPagamentoBM.objects.get(bm=bm,sucessor__isnull=True)

    def legacy_initial(self,bm_day,stored_day):
        # Simula um registro antigo preservado e uma data atual diferente no BM.
        bm=self.bm(stored_day)
        cycles.process_bm(bm.pk,self.finance,today=min(stored_day,date(2026,11,13)))
        initial=m.CicloPagamentoBM.objects.values().get(bm=bm)
        bm.data_pagamento=bm_day;bm.save()
        m.BM.objects.filter(pk=bm.pk).update(status_gerente='aprovado')
        bm.refresh_from_db()
        return bm,initial

    def test_evento_programacao_usa_bm_24_novembro_e_nao_evento_setembro(self):
        bm=self.bm();state=cycles.financial_state(cycles.raw_connection(),bm.pk)
        self.assertEqual(state['reference'],date(2026,11,24))
        self.assertEqual(info(bm,self.finance)['scheduled_date'],date(2026,11,24))
        plan=cycles.reprogramming_plan(cycles.raw_connection(),bm.pk)
        self.assertEqual(plan['previous_date'],date(2026,11,24));self.assertFalse(plan['available'])
        self.assertFalse(m.CicloPagamentoBM.objects.exists())

    def test_os_tambem_usa_a_data_do_bm(self):
        bm=self.bm(os=True)
        self.assertEqual(info(bm,self.finance)['scheduled_date'],date(2026,11,24))
        self.assertEqual(bm.os.data_prevista_pagamento,date(2026,9,20))

    def test_previsao_futura_do_evento_nao_substitui_programacao_do_bm(self):
        self.events[0].data_prevista_pagamento=date(2026,12,21);self.events[0].save()
        bm=self.bm(date(2026,11,10))
        plan=cycles.reprogramming_plan(cycles.raw_connection(),bm.pk)
        self.assertTrue(plan['available']);self.assertEqual(plan['next_date'],date(2026,11,24))
        cycles.process_bm(bm.pk,self.finance,reprogram_only=True)
        self.assertEqual(self.current(bm).anterior.data_prevista,date(2026,11,10))
        self.assertEqual(self.current(bm).data_prevista,date(2026,11,24))

    def test_inicial_antigo_de_setembro_nao_libera_reprogramacao_antes_do_dia_do_bm(self):
        bm,initial=self.legacy_initial(date(2026,11,24),date(2026,9,20))
        state=info(bm,self.finance)
        self.assertEqual(state['scheduled_date'],date(2026,11,24))
        self.assertEqual(state['reprogramming']['previous_date'],date(2026,11,24))
        self.assertFalse(state['reprogramming']['available'])
        self.assertEqual(m.CicloPagamentoBM.objects.values().get(pk=initial['id']),initial)

    def test_inicial_antigo_futuro_nao_sobrepoe_data_de_pagamento_do_bm(self):
        bm,initial=self.legacy_initial(date(2026,11,10),date(2026,12,21))
        plan=cycles.reprogramming_plan(cycles.raw_connection(),bm.pk)
        self.assertTrue(plan['available']);self.assertEqual(plan['previous_date'],date(2026,11,10))
        cycles.process_bm(bm.pk,self.finance,reprogram_only=True)
        self.assertEqual(self.current(bm).data_prevista,date(2026,11,24))
        self.assertEqual(info(bm,self.finance)['previous_date'],date(2026,11,10))
        self.assertEqual(m.CicloPagamentoBM.objects.values().get(pk=initial['id']),initial)

    def test_confirmacao_exibe_data_do_bm_e_preserva_registro_inicial(self):
        bm,initial=self.legacy_initial(date(2026,11,10),date(2026,9,20))
        response=self.client.get(reverse('reprogramar_bm',args=[bm.pk]))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['plan']['previous_date'],date(2026,11,10))
        payload=response.context['form'].initial.copy()
        self.assertEqual(self.client.post(reverse('reprogramar_bm',args=[bm.pk]),payload).status_code,302)
        self.assertEqual(self.current(bm).contexto_inclusao['data_programacao_anterior'],'2026-11-10')
        self.assertEqual(m.CicloPagamentoBM.objects.values().get(pk=initial['id']),initial)

    def test_sem_previsao_no_evento_tem_programacao_pelo_bm(self):
        self.events[0].data_prevista_pagamento=None;self.events[0].save()
        bm=self.bm()
        self.assertEqual(info(bm,self.finance)['scheduled_date'],date(2026,11,24))

    def test_alterar_previsao_evento_nao_troca_a_data_programada_do_bm(self):
        bm=self.bm()
        self.events[0].data_prevista_pagamento=date(2027,1,15);self.events[0].save()
        self.assertEqual(info(bm,self.finance)['scheduled_date'],date(2026,11,24))

    def test_reprogramacao_mantem_nova_data_do_ciclo_e_data_anterior_confirmada(self):
        bm=self.bm(date(2026,11,10));cycles.process_bm(bm.pk,self.finance,reprogram_only=True)
        current=self.current(bm)
        bm.data_pagamento=date(2026,11,12);bm.save()
        state=info(bm,self.finance)
        self.assertEqual(state['scheduled_date'],date(2026,11,24))
        self.assertEqual(state['previous_date'],date(2026,11,10))
        current.refresh_from_db();self.assertEqual(current.data_prevista,date(2026,11,24))

    def test_parcela_nf_futura_e_preservada_sem_virar_programacao_original(self):
        bm=self.bm(date(2026,11,10));nf=self.nf(bm,value='50000')
        schedule,_=payments.schedule(nf_id=nf.pk,user=self.finance,valor=50000,data_prevista=date(2026,12,21),motivo='Prazo explícito da NF',key='prazo')
        state=cycles.financial_state(cycles.raw_connection(),bm.pk)
        self.assertEqual((state['reference'],state['not_before']),(date(2026,11,10),date(2026,12,21)))
        cycles.process_bm(bm.pk,self.finance,reprogram_only=True)
        self.assertEqual(self.current(bm).anterior.data_prevista,date(2026,11,10))
        self.assertEqual(self.current(bm).data_prevista,date(2026,12,21))
        schedule.refresh_from_db();self.assertEqual(schedule.data_prevista,date(2026,12,21))

    def test_excel_preserva_historico_e_exporta_data_anterior_confirmada(self):
        bm,initial=self.legacy_initial(date(2026,11,10),date(2026,12,21))
        cycles.process_bm(bm.pk,self.finance,reprogram_only=True)
        response=self.client.get(reverse('exportar_bms_previsao_excel'),{'data_inicial':'2026-11-01','data_limite':'2026-11-30'})
        self.assertEqual(response.status_code,200)
        book=load_workbook(BytesIO(response.content),read_only=True)
        rows=list(book['Ciclos de pagamento'].values)
        self.assertEqual(rows[1][8].date(),date(2026,12,21))
        self.assertEqual(rows[2][7].date(),date(2026,11,10))
        self.assertEqual(rows[2][8].date(),date(2026,11,24))
        book.close()
        self.assertEqual(m.CicloPagamentoBM.objects.values().get(pk=initial['id']),initial)

    def test_revisao_de_inicial_considera_data_atual_do_bm_sem_reescrever_ciclo(self):
        bm,initial=self.legacy_initial(date(2026,11,24),date(2026,9,20))
        new=cycles.revise(initial['id'],self.supply,'Conferência expressa da programação do BM')
        self.assertEqual(new.data_prevista,date(2026,11,24))
        self.assertEqual(new.calendario.data_pagamento,date(2026,11,24))
        self.assertEqual(m.CicloPagamentoBM.objects.values().get(pk=initial['id']),initial)

    def test_faturamento_parcial_na_mesma_data_do_bm_nao_cria_divergencia_de_prazos(self):
        bm=self.bm();self.nf(bm,value='25000')
        state=cycles.financial_state(cycles.raw_connection(),bm.pk)
        self.assertEqual(state['reference'],date(2026,11,24))
        self.assertEqual(state['errors'],[])
        plan=cycles.reprogramming_plan(cycles.raw_connection(),bm.pk,state=state)
        self.assertFalse(plan['available'])
        self.assertIn('ainda não passou',plan['reason'])
