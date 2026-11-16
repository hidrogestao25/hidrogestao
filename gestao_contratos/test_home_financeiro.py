"""Home resumida e página exclusiva; todas as fixtures ficam no banco de teste."""
from datetime import date
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import models as m
from . import test_financeiro_fase2 as fixtures
from .tests import BaseUserTestCase
from .test_auditoria import pdf


class HomeFinanceiroTests(BaseUserTestCase):
    setUp = fixtures.FinanceiroFase2Tests.setUp
    bm = fixtures.FinanceiroFase2Tests.bm
    nf = fixtures.FinanceiroFase2Tests.nf
    data = fixtures.FinanceiroFase2Tests.data

    def counts(self):
        return self.client.get(reverse('home')).context['financial_home_counts']

    def test_home_resumida_sem_componentes_completos(self):
        self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        with patch('gestao_contratos.views.build_financial_dashboard_context',side_effect=AssertionError('Painel não deve ser calculado na home')):
            response=self.client.get(reverse('home'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'data-financial-home')
        self.assertContains(response,'dashboard-card')
        self.assertContains(response,'Abrir Painel Financeiro')
        for marker in ('Pesquisar e filtrar','plotly-graph-div','financeModal','financeiro.js','fin-kpi'):
            self.assertNotContains(response,marker)
        self.assertNotIn('financial_stats',response.context)
        self.assertEqual(len(response.context['financial_home_cards']),6)

    def test_sem_registros_contagens_zero(self):
        counts=self.counts()
        self.assertTrue(all(value==0 for value in counts.values()))
        self.assertContains(self.client.get(reverse('home')),'Nenhum registro nesta situação')

    def test_autorizados_incluem_bms_com_nf_antecipada_e_nf_paga(self):
        self.bm(operational='aprovado',director='aprovado')
        self.nf(self.bm(operational='aprovado',director='aprovado'))
        self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        counts=self.counts()
        self.assertEqual((counts['autorizados'],counts['sem_nf'],counts['pagamento']),(3,1,1))

    def test_lideranca_ou_gerencia_contam_aprovacao_operacional(self):
        self.bm(operational='aprovado')
        self.bm(status_coordenador='aprovado')
        self.bm()
        counts=self.counts()
        self.assertEqual((counts['diretoria'],counts['operacional']),(2,1))

    def test_reprovacoes_nao_sao_aguardando_aprovacao(self):
        self.bm(operational='aprovado',status_coordenador='reprovado',director='aprovado')
        self.bm(operational='aprovado',director='reprovado')
        counts=self.counts()
        self.assertEqual((counts['autorizados'],counts['diretoria'],counts['operacional'],counts['atencao_bm']),(0,0,0,2))

    def test_nf_antecipada_nao_libera_pagamento(self):
        self.nf(self.bm())
        self.assertEqual(self.counts()['pagamento'],0)
        response=self.client.get(reverse('home'))
        self.assertNotContains(response,'Registrar pagamento')
        self.assertNotContains(response,'Aprovar Pagamento')

    def test_autorizacao_invalidada_e_nf_paga_pedem_atencao(self):
        bm=self.bm(operational='aprovado',director='aprovado'); self.nf(bm,paid=True)
        bm.valor_pago=200; bm.save()
        counts=self.counts()
        self.assertEqual((counts['autorizados'],counts['pagamento'],counts['atencao_nf']),(0,0,1))

    def test_origem_inconsistente_e_os_cancelada_fora_dos_cards_validos(self):
        broken=self.bm(operational='aprovado',director='aprovado',os=True)
        # Simula registro legado anterior à 0126, que a migration preserva.
        # A escrita nova é negada pelo gatilho e tem regressão própria em P1.
        with connection.cursor() as cursor:
            ddl = cursor.execute("SELECT sql FROM sqlite_master WHERE name='hidro_bm_os_contract_update'").fetchone()[0]
            cursor.execute("DROP TRIGGER hidro_bm_os_contract_update")
            try:
                m.BM.objects.filter(pk=broken.pk).update(contrato=self.contracts[1])
            finally:
                cursor.execute(ddl)
        self.bm(operational='aprovado',director='aprovado',os=True)
        self.order.status='cancelada'; self.order.save()
        counts=self.counts()
        self.assertEqual((counts['autorizados'],counts['sem_nf'],counts['atencao_bm']),(0,0,2))

    def test_compartilhado_conta_duas_participacoes_sem_deduplicar_arquivo(self):
        bm=self.bm(value='60000',operational='aprovado',director='aprovado',arquivo_bm=pdf())
        self.bm(index=1,value='40000',operational='aprovado',director='aprovado',arquivo_bm=bm.arquivo_bm.name)
        counts=self.counts()
        self.assertEqual((counts['autorizados'],counts['sem_nf']),(2,2))
        self.assertEqual(self.data(historico=True).indicators()['medido'],100000)

    def test_nf_fora_do_periodo_nao_converte_bm_em_sem_nf(self):
        bm=self.bm(operational='aprovado',director='aprovado')
        self.nf(bm,day=date(2024,1,1))
        counts=self.counts()
        self.assertEqual((counts['autorizados'],counts['sem_nf']),(1,0))
        # Home é sempre todo o histórico; filtro pertence ao painel.
        response=self.client.get(reverse('home'),{'data_inicial':'2026-11-01','data_limite':'2026-11-30'})
        self.assertEqual(response.context['financial_home_counts'],counts)

    def test_listas_limitadas_e_links_dos_seis_cards_selecionam_painel(self):
        for i in range(8): self.bm(operational='aprovado',director='aprovado')
        response=self.client.get(reverse('home'))
        for group in response.context['financial_home_lists']:
            self.assertLessEqual(len(group['rows']),5)
        for card in response.context['financial_home_cards']:
            target=urlsplit(card['url'])
            self.assertEqual(target.path,reverse('painel_financeiro'))
            self.assertEqual(parse_qs(target.query)['selecao'],[card['key']])
            result=self.client.get(card['url'])
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.context['financial_selection']['page_obj'].paginator.count,card['count'])

    def test_card_um_selecao_lista_bm_autorizado_que_ja_tem_nf(self):
        bm=self.bm(operational='aprovado',director='aprovado'); self.nf(bm,paid=True)
        card=next(c for c in self.client.get(reverse('home')).context['financial_home_cards'] if c['key']=='autorizados')
        response=self.client.get(card['url'])
        self.assertEqual([r['id'] for r in response.context['financial_selection']['rows']],[bm.pk])
        detail=self.client.get(response.context['financial_selection']['rows'][0]['detail_url'])
        self.assertEqual(detail.context['return_url'],response.wsgi_request.get_full_path())

    def test_painel_exclusivo_componente_completo_preservado(self):
        self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        response=self.client.get(reverse('painel_financeiro'))
        self.assertEqual(response.status_code,200)
        self.assertTemplateUsed(response,'financeiro/painel.html')
        self.assertTemplateUsed(response,'financeiro/_painel_home.html')
        for marker in ('Pesquisar e filtrar','Pagamentos efetivos por mês','financeModal','financeiro.js'):
            self.assertContains(response,marker)
        self.assertEqual(len(response.context['financial_queues']),6)
        self.assertEqual(len(response.context['financial_kpis']),8)

    def test_painel_recusa_demais_perfis_inclusive_superuser(self):
        users=[self.supply,self.leader,self.coord,self.create_user('h_dir','diretoria'),self.create_user('h_gc','gerente_contrato'),self.create_user('h_manager','gerente'),self.create_user('h_ml','gerente_lider'),self.create_user('h_vendor','fornecedor')]
        admin=self.create_user('h_admin','suprimento'); admin.is_superuser=True; admin.is_staff=True; admin.save()
        users.append(admin)
        for user in users:
            self.client.force_login(user)
            with self.subTest(role=user.grupo,admin=user.is_superuser):
                self.assertEqual(self.client.get(reverse('painel_financeiro')).status_code,403)

    def test_anonimo_login_e_post_405(self):
        self.assertEqual(self.client.post(reverse('painel_financeiro')).status_code,405)
        self.client.logout()
        response=self.client.get(reverse('painel_financeiro'))
        self.assertRedirects(response,reverse('login')+'?next='+reverse('painel_financeiro'),fetch_redirect_response=False)

    def test_home_anonima_redireciona_login_antes_de_consultar_ciclos(self):
        self.client.logout()
        for ciclos_ativos in (True, False):
            with self.subTest(ciclos_ativos=ciclos_ativos):
                with patch('gestao_contratos.bm_cycles.enabled', return_value=ciclos_ativos) as enabled:
                    response = self.client.get(reverse('home'))
                    enabled.assert_not_called()
                self.assertRedirects(response, reverse('login')+'?next='+reverse('home'),
                                     fetch_redirect_response=False)
                self.assertEqual(self.client.get(response.url).status_code, 200)

    def test_menu_link_exclusivo_e_homes_dos_outros_perfis(self):
        response=self.client.get(reverse('home'))
        self.assertContains(response,'href="'+reverse('painel_financeiro')+'"')
        for user in (self.supply,self.leader,self.coord,self.create_user('h_director','diretoria'),self.create_user('h_contract','gerente_contrato')):
            self.client.force_login(user)
            response=self.client.get(reverse('home'))
            self.assertEqual(response.status_code,200)
            self.assertContains(response,'dashboard-content')
            self.assertNotContains(response,'data-financial-home')
            self.assertNotContains(response,'href="'+reverse('painel_financeiro')+'"')

    def test_rotas_globais_antigas_continuam_liberadas(self):
        nf=self.nf(self.bm(index=1))
        for user in (self.supply,self.create_user('h_global_dir','diretoria'),self.create_user('h_global_gc','gerente_contrato')):
            self.client.force_login(user)
            for url in (reverse('pendencias_financeiras'),reverse('detalhe_bm_financeiro',args=[nf.bm_id]),reverse('detalhe_nf',args=[nf.pk])):
                self.assertEqual(self.client.get(url).status_code,200)

    def test_selecao_paginada_filtros_e_retorno_seguro(self):
        for i in range(22): self.nf(self.bm(operational='aprovado',director='aprovado'))
        params={'historico':'on','selecao':'pagamento','contrato':self.contracts[0].pk,'page':2}
        response=self.client.get(reverse('painel_financeiro'),params)
        section=response.context['financial_selection']
        self.assertEqual(len(section['rows']),2)
        self.assertIn('contrato=',section['pagination_query'])
        self.assertContains(response,'name="selecao" value="pagamento"')
        detail=self.client.get(section['rows'][0]['detail_url'])
        self.assertEqual(detail.context['return_url'],response.wsgi_request.get_full_path())
        nf=section['rows'][0]['record']
        malicious=self.client.get(reverse('detalhe_nf',args=[nf.pk]),{'next':'https://externo.example/'})
        self.assertEqual(malicious.context['return_url'],reverse('home'))

    def test_atencao_lista_bms_e_nfs_em_abas_separadas(self):
        self.nf(self.bm(operational='reprovado'))
        self.assertEqual(self.counts()['atencao'],2)
        for kind in ('bm','nf'):
            response=self.client.get(reverse('painel_financeiro'),{'historico':'on','selecao':'atencao','registro':kind})
            self.assertEqual(response.context['financial_selection']['page_obj'].paginator.count,1)
        for params in ({'selecao':'inexistente'},{'selecao':'atencao','registro':'inexistente'}):
            self.assertEqual(self.client.get(reverse('painel_financeiro'),params).status_code,400)

    def test_consultas_da_home_nao_crescem_com_registros(self):
        self.bm(operational='aprovado',director='aprovado')
        self.client.get(reverse('home'))
        with CaptureQueriesContext(connection) as one: self.client.get(reverse('home'))
        for i in range(12): self.bm(operational='aprovado',director='aprovado')
        with CaptureQueriesContext(connection) as many: self.client.get(reverse('home'))
        self.assertEqual(len(one),len(many))
        self.assertLess(len(many),25)

    def test_documento_privado_a_partir_da_home(self):
        bm=self.bm(operational='aprovado',director='aprovado',arquivo_bm=pdf())
        response=self.client.get(reverse('home'))
        rows=next(g['rows'] for g in response.context['financial_home_lists'] if g['key']=='autorizados')
        detail=self.client.get(rows[0]['detail_url'])
        self.assertEqual(detail.context['row']['id'],bm.pk)
        download=self.client.get(detail.context['row']['document_url'])
        self.assertEqual(download.status_code,200); download.close()

    def payment_calendar(self):
        for day in (date(2026,10,30),date(2026,11,28),date(2026,12,30)):
            m.CalendarioPagamento.objects.create(data_pagamento=day)

    def test_painel_padrao_filtra_ciclo_atual_de_pagamento(self):
        self.payment_calendar()
        bm=self.bm(operational='aprovado',director='aprovado')
        self.nf(bm,value='20',paid=True,day=date(2026,11,15))
        self.nf(bm,value='30',paid=True,day=date(2026,10,30))
        self.nf(bm,value='40',paid=True,day=date(2026,11,29))
        with patch('gestao_contratos.views.timezone.localdate',return_value=date(2026,11,9)):
            response=self.client.get(reverse('painel_financeiro'))
        form=response.context['financial_form']
        self.assertEqual((form.cleaned_data['data_inicial'],form.cleaned_data['data_limite']),(date(2026,10,31),date(2026,11,28)))
        self.assertFalse(form.cleaned_data['historico'])
        self.assertEqual(response.context['financial_stats']['pago'],20)
        self.assertEqual(response.context['financial_period'],'31/10/2026 a 28/11/2026')
        for queue in response.context['financial_queues']:
            params=parse_qs(urlsplit(queue['url']).query)
            self.assertEqual((params['data_inicial'],params['data_limite']),(['2026-10-31'],['2026-11-28']))

    def test_dia_do_pagamento_fecha_ciclo_e_dia_seguinte_abre_proximo(self):
        self.payment_calendar()
        for today,first,last in ((date(2026,11,28),date(2026,10,31),date(2026,11,28)),(date(2026,11,29),date(2026,11,29),date(2026,12,30))):
            with self.subTest(today=today),patch('gestao_contratos.views.timezone.localdate',return_value=today):
                form=self.client.get(reverse('painel_financeiro')).context['financial_form']
                self.assertEqual((form.cleaned_data['data_inicial'],form.cleaned_data['data_limite']),(first,last))

    def test_intervalo_manual_e_historico_explicitos_preservados(self):
        self.payment_calendar()
        response=self.client.get(reverse('painel_financeiro'),{'data_inicial':'2026-01-01','data_limite':'2026-12-31'})
        form=response.context['financial_form']
        self.assertEqual((form.cleaned_data['data_inicial'],form.cleaned_data['data_limite']),(date(2026,1,1),date(2026,12,31)))
        response=self.client.get(reverse('painel_financeiro'),{'historico':'on'})
        self.assertEqual(response.context['financial_period'],'Todo o histórico')

    def test_calendario_incompleto_usa_mes_corrente_com_aviso(self):
        for days in ([],[date(2028,2,15)],[date(2028,3,15)]):
            m.CalendarioPagamento.objects.all().delete()
            for day in days: m.CalendarioPagamento.objects.create(data_pagamento=day)
            with self.subTest(days=days),patch('gestao_contratos.views.timezone.localdate',return_value=date(2028,2,20)):
                response=self.client.get(reverse('painel_financeiro'))
                form=response.context['financial_form']
                self.assertEqual((form.cleaned_data['data_inicial'],form.cleaned_data['data_limite']),(date(2028,2,1),date(2028,2,29)))
                self.assertContains(response,'O calendário não possui as duas datas')

    def test_ciclo_entre_anos_e_data_manual_invalida_nao_e_substituida(self):
        for day in (date(2026,12,30),date(2027,1,28)):
            m.CalendarioPagamento.objects.create(data_pagamento=day)
        with patch('gestao_contratos.views.timezone.localdate',return_value=date(2027,1,9)):
            form=self.client.get(reverse('painel_financeiro')).context['financial_form']
            self.assertEqual((form.cleaned_data['data_inicial'],form.cleaned_data['data_limite']),(date(2026,12,31),date(2027,1,28)))
            response=self.client.get(reverse('painel_financeiro'),{'data_inicial':'inválida','data_limite':'2027-01-28'})
            self.assertNotIn('financial_stats',response.context)
