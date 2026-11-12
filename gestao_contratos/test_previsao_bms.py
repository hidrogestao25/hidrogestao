"""Ciclo automático pelo calendário de pagamentos e Excel da tabela de BMs."""
from datetime import date,datetime
from decimal import Decimal
from io import BytesIO
import zipfile
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook
from . import models as m,payment_services as payments
from . import test_financeiro_fase2 as fixtures
from .tests import BaseUserTestCase
from .test_auditoria import pdf


class PrevisaoBMsTests(BaseUserTestCase):
    setUp=fixtures.FinanceiroFase2Tests.setUp
    bm=fixtures.FinanceiroFase2Tests.bm
    nf=fixtures.FinanceiroFase2Tests.nf

    def approved(self,day=date(2026,9,10),**extra):
        return self.bm(operational='aprovado',director='aprovado',
            data_aprovacao_gerente=timezone.make_aware(datetime.combine(day,datetime.min.time()).replace(hour=12)),**extra)

    def excel(self,**filters):
        response=self.client.get(reverse('exportar_bms_previsao_excel'),filters or {'data_limite':'2026-09-30'})
        self.assertEqual(response.status_code,200,response.content[:200])
        self.assertEqual(response['Cache-Control'],'private, no-store')
        return load_workbook(BytesIO(response.content))

    def test_apenas_limite_usa_pagamento_anterior_mais_um_inclusive(self):
        for day in (date(2026,9,15),date(2026,9,30),date(2026,10,15)):
            m.CalendarioPagamento.objects.create(data_pagamento=day)
        self.approved();self.approved(date(2026,9,15))
        first=self.approved(date(2026,9,16));edge=self.approved(date(2026,9,30));self.approved(date(2026,10,1))
        self.bm();self.bm(operational='reprovado',data_aprovacao_gerente=timezone.now())
        response=self.client.get(reverse('previsao_pagamentos'),{'data_limite':'2026-09-30'})
        self.assertEqual(response.status_code,200)
        self.assertEqual({bm.pk for bm in response.context['bms']},{first.pk,edge.pk})
        self.assertIn('data_inicial=2026-09-16',response.context['bm_export_query'])
        self.assertIn('data_inicial=2026-09-16',response.context['export_query'])
        self.assertContains(response,'16/09/2026 a 30/09/2026')
        self.assertContains(response,reverse('exportar_bms_previsao_excel'))
        self.assertNotContains(response,'value="None"')
        self.assertEqual(self.excel()['Boletins de Medição'].max_row,3)

    def test_inicio_explicito_mantem_intervalo(self):
        m.CalendarioPagamento.objects.create(data_pagamento=date(2026,9,25))
        self.approved();included=self.approved(date(2026,9,20))
        response=self.client.get(reverse('previsao_pagamentos'),{'data_inicial':'2026-09-15','data_limite':'2026-09-30'})
        self.assertEqual([bm.pk for bm in response.context['bms']],[included.pk])
        self.assertIn('data_inicial=2026-09-15',response.context['bm_export_query'])

    def test_periodo_medicao_sem_inicio_na_pagina_e_excel(self):
        m.CalendarioPagamento.objects.create(data_pagamento=date(2026,8,31))
        bm=self.approved(data_inicial_medicao=timezone.make_aware(datetime(2026,9,1,12)),data_final_medicao=timezone.make_aware(datetime(2026,9,1,12)))
        self.approved(data_inicial_medicao=timezone.make_aware(datetime(2026,8,31,12)),data_final_medicao=timezone.make_aware(datetime(2026,9,1,12)))
        self.approved(data_inicial_medicao=timezone.make_aware(datetime(2026,9,1,12)),data_final_medicao=timezone.make_aware(datetime(2026,10,1,12)))
        filters={'data_limite':'2026-09-30','filtro_bm':'medicao'}
        response=self.client.get(reverse('previsao_pagamentos'),filters)
        self.assertEqual([row.pk for row in response.context['bms']],[bm.pk])
        self.assertEqual(self.excel(**filters)['Boletins de Medição'].max_row,2)

    def test_zip_sem_inicio_usa_mesmo_corte_da_tabela(self):
        m.CalendarioPagamento.objects.create(data_pagamento=date(2026,9,15))
        self.approved(date(2026,9,20),arquivo_bm=pdf('passado.pdf'))
        self.approved(date(2026,10,1),arquivo_bm=pdf('futuro.pdf'))
        response=self.client.get(reverse('download_bms_aprovados'),{'data_limite':'2026-09-30'})
        self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(BytesIO(response.content)) as archive:self.assertEqual(len(archive.namelist()),1)

    def test_calendario_sem_anterior_usa_mes_do_limite_e_avisa(self):
        m.CalendarioPagamento.objects.create(data_pagamento=date(2026,9,30))
        self.approved(date(2026,8,31));included=self.approved(date(2026,9,1))
        response=self.client.get(reverse('previsao_pagamentos'),{'data_limite':'2026-09-30'})
        self.assertEqual([bm.pk for bm in response.context['bms']],[included.pk])
        self.assertContains(response,'O calendário não possui data de pagamento anterior')
        self.assertEqual(response.context['forecast_start'],date(2026,9,1))
        criteria=dict(self.excel()['Critérios'].iter_rows(min_row=2,values_only=True))
        self.assertEqual(criteria['Data inicial'].date(),date(2026,9,1))

    def test_ciclo_pode_cruzar_mes_e_ano(self):
        from .views import forecast_period_start
        m.CalendarioPagamento.objects.create(data_pagamento=date(2025,12,15))
        m.CalendarioPagamento.objects.create(data_pagamento=date(2026,1,15))
        self.assertEqual(forecast_period_start(None,date(2026,1,15)),(date(2025,12,16),''))
        self.assertEqual(forecast_period_start(date(2026,1,1),date(2026,1,15)),(date(2026,1,1),''))

    def test_planejamento_e_seu_excel_usam_o_mesmo_inicio_automatico(self):
        m.CalendarioPagamento.objects.create(data_pagamento=date(2026,9,15))
        m.Evento.objects.filter(pk=self.events[0].pk).update(data_prevista_pagamento=date(2026,9,16))
        m.Evento.objects.filter(pk=self.events[1].pk).update(data_prevista_pagamento=date(2026,9,15))
        filters={'data_limite':'2026-09-30'}
        response=self.client.get(reverse('previsao_pagamentos'),filters)
        self.assertEqual(response.context['total_previsto'],60000)
        response=self.client.get(reverse('exportar_previsao_pagamentos_excel'),filters)
        book=load_workbook(BytesIO(response.content))
        self.assertEqual(sum(Decimal(str(row[5] or 0)) for row in book.active.iter_rows(min_row=2,values_only=True)),60000)

    def test_excel_colunas_valores_e_datas_reais_de_pagamentos_parciais(self):
        from .bm_forecast_exports import HEADERS
        bm=self.approved(observacao='Observação específica do BM')
        nf=self.nf(bm,value='100')
        payments.record_payment(nf_id=nf.pk,user=self.finance,valor=20,data_pagamento=date(2026,9,12),key='p1')
        payments.record_payment(nf_id=nf.pk,user=self.finance,valor=10,data_pagamento=date(2026,10,5),key='p2')
        sheet=self.excel()['Boletins de Medição']
        self.assertEqual([c.value for c in sheet[1]],HEADERS)
        row=[c.value for c in sheet[2]]
        self.assertEqual(row[:5],[self.supplier.nome,self.events[0].descricao,'Observação específica do BM',self.projects[0].cod_projeto,self.leader.get_full_name()])
        self.assertEqual(row[5:7],[60000,100])
        self.assertEqual(row[7].date(),date(2026,11,15))
        self.assertIn('Gerência: Aprovado',row[8]);self.assertIn('Aprovado',row[9])
        self.assertEqual(row[10:12],['Sim','12/09/2026\n05/10/2026'])
        self.assertEqual(sheet.cell(2,6).data_type,'n');self.assertEqual(sheet.cell(2,8).number_format,'dd/mm/yyyy')

    def test_data_pagamento_em_branco_sem_movimento_e_sem_estorno_integral(self):
        bm=self.approved();nf=self.nf(bm,value='100')
        self.assertIsNone(self.excel()['Boletins de Medição'].cell(2,12).value)
        p,_=payments.record_payment(nf_id=nf.pk,user=self.finance,valor=20,data_pagamento=date(2026,9,12),key='p1')
        payments.reverse_payment(movement_id=p.pk,user=self.supply,valor=20,data_estorno=date(2026,9,13),motivo='Correção',key='e1')
        self.assertIsNone(self.excel()['Boletins de Medição'].cell(2,12).value)

    def test_excel_filtro_coordenador_e_contrato_financeiro_bm_compartilhado(self):
        self.approved(index=1,evento=self.events[0],arquivo_bm='BM/compartilhado.pdf')
        self.approved(index=1,arquivo_bm='BM/compartilhado.pdf')
        sheet=self.excel(data_limite='2026-09-30',coordenador=self.coord.pk)['Boletins de Medição']
        self.assertEqual(sheet.max_row,2)
        self.assertEqual(sheet.cell(2,4).value,self.projects[0].cod_projeto)
        self.assertEqual(sheet.cell(2,5).value,self.leader.get_full_name())

    def test_excel_escopo_restrito_e_rejeicao_perfis_externos(self):
        self.approved();self.approved(index=1)
        manager=self.create_user('export_manager','gerente_lider')
        center=self.create_center('EXP','Exportação');manager.centros.add(center);self.coord.centros.add(center)
        self.client.force_login(manager)
        sheet=self.excel()['Boletins de Medição'];self.assertEqual(sheet.max_row,2)
        self.assertEqual(sheet.cell(2,4).value,self.projects[0].cod_projeto)
        self.client.force_login(self.create_user('export_external','fornecedor'))
        self.assertEqual(self.client.get(reverse('exportar_bms_previsao_excel'),{'data_limite':'2026-09-30'}).status_code,403)

    def test_excel_validacao_e_formula_nao_executavel(self):
        self.approved(observacao=' =HYPERLINK("https://example.com")')
        sheet=self.excel()['Boletins de Medição']
        self.assertEqual(sheet.cell(2,3).data_type,'s');self.assertTrue(sheet.cell(2,3).value.startswith("'"))
        url=reverse('exportar_bms_previsao_excel')
        for params in ({},{'data_limite':'inválida'},{'data_inicial':'2026-10-01','data_limite':'2026-09-30'}):
            self.assertEqual(self.client.get(url,params).status_code,400)
        self.assertEqual(self.client.post(url,{'data_limite':'2026-09-30'}).status_code,405)
