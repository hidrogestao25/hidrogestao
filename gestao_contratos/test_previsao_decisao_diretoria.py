"""Ações da Diretoria na previsão, com bancos e anexos sintéticos."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import Client
from django.urls import reverse

from . import models as m, bm_cycles as cycles, bm_payment_views as payment
from . import test_financeiro_fase2 as fixtures
from .tests import BaseUserTestCase


class PrevisaoDiretoriaTests(BaseUserTestCase):
    bm = fixtures.FinanceiroFase2Tests.bm
    nf = fixtures.FinanceiroFase2Tests.nf

    def setUp(self):
        fixtures.FinanceiroFase2Tests.setUp(self)
        self.director = self.create_user('previsao_diretor', 'diretoria')
        self.client.force_login(self.director)
        for target in ('gestao_contratos.views.plot', 'plotly.basedatatypes.BaseFigure.to_html'):
            mock = patch(target, return_value='<div>Gráfico</div>');mock.start();self.addCleanup(mock.stop)

    def current(self, bm):
        return payment.payment_info(m.BM.objects.get(pk=bm.pk), self.director)

    def post(self, bm, action, text='', token=None):
        return self.client.post(reverse('acao_pagamento_bm_previsao', args=[bm.pk]), {
            'acao': action, 'justificativa': text, 'token': token or self.current(bm)['token']})

    def forecast(self):
        return self.client.get(reverse('previsao_pagamentos'), {'data_inicial':'2026-01-01', 'data_limite':'2027-12-31','filtro_bm':'medicao'})

    def test_diretoria_nao_processa_graficos_e_preserva_totais_tabelas_e_acoes(self):
        from . import payment_services
        bm=self.bm(operational='aprovado',director='aprovado',data_aprovacao_gerente='2026-11-01T12:00:00Z')
        nf=self.nf(bm,value='50',paid=True)
        payment_services.reverse_payment(movement_id=nf.movimentos.get().pk,user=self.supply,valor=10,
            data_estorno=date(2026,11,16),motivo='Teste de total líquido',key='sem-graficos-estorno')
        for target in ('gestao_contratos.views.go.Figure','gestao_contratos.views.plot',
                       'gestao_contratos.views.nf_monthly_chart','gestao_contratos.views.fq.monthly_paid_series',
                       'gestao_contratos.views.get_plotlyjs_version'):
            mock=patch(target,side_effect=AssertionError('Gráficos não devem ser processados para a Diretoria'))
            mock.start();self.addCleanup(mock.stop)
        response=self.client.get(reverse('previsao_pagamentos'),{'data_inicial':'2026-11-01','data_limite':'2026-11-30'})
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.context['show_forecast_charts'])
        self.assertEqual(response.context['nf_paid_total'],40)
        self.assertEqual(response.context['total_pago'],40)
        self.assertEqual(response.context['total_previsto'],Decimal('100350'))
        self.assertEqual([item.pk for item in response.context['bms']],[bm.pk])
        self.assertNotContains(response,'cdn.plot.ly')
        self.assertNotContains(response,'plotly-graph-div')
        self.assertNotContains(response,'Nenhuma NF paga neste período.')
        self.assertContains(response,'Ver Detalhes')
        self.assertContains(response,'data-bm-forecast-action="salvar_justificativa"')

    def test_financeiro_e_suprimento_continuam_com_graficos(self):
        with patch('gestao_contratos.views.nf_monthly_chart',return_value='<div>Gráfico NF</div>') as chart:
            for actor in (self.finance,self.supply):
                with self.subTest(grupo=actor.grupo):
                    self.client.force_login(actor)
                    response=self.client.get(reverse('previsao_pagamentos'),{'data_inicial':'2026-11-01','data_limite':'2026-11-30'})
                    self.assertTrue(response.context['show_forecast_charts'])
                    self.assertContains(response,'cdn.plot.ly')
                    self.assertContains(response,'Gráfico NF')
                    self.assertTrue(response.context['grafico_barras'])
            self.assertEqual(chart.call_count,2)

    def test_botoes_acima_do_detalhe_e_coluna_justificativa(self):
        bm=self.bm(operational='aprovado',data_aprovacao_gerente='2026-11-01T12:00:00Z')
        response=self.client.get(reverse('previsao_pagamentos'),{'data_inicial':'2026-01-01','data_limite':'2026-12-31'})
        self.assertContains(response,'<th>Justificativa</th>',html=True)
        self.assertContains(response,'data-bm-forecast-action="aprovar_pagamento"')
        self.assertContains(response,'data-bm-forecast-action="reprovar_pagamento"')
        self.assertContains(response,'Adicionar justificativa')
        self.assertContains(response,'Ver Detalhes')
        html=response.content.decode()
        self.assertLess(html.index('data-bm-forecast-action="aprovar_pagamento"'),html.index('Ver Detalhes'))
        self.assertContains(response,'data-bm-payment-form')

    def test_aprovar_sem_justificativa_mesma_decisao_do_detalhe_e_tag(self):
        bm=self.bm(operational='aprovado')
        self.assertEqual(self.post(bm,'aprovar_pagamento').status_code,200)
        bm.refresh_from_db();self.assertEqual(bm.aprovacao_pagamento,'aprovado')
        self.assertFalse(self.current(bm)['can_decide'])
        self.assertEqual(self.current(bm)['status'],'aprovado')
        self.assertEqual(m.RegistroAuditoria.objects.filter(object_id=bm.pk,operacao_financeira='decisao_bm').count(),1)

    def test_reprovar_sem_motivo_nao_persiste_e_com_motivo_bloqueia(self):
        bm=self.bm(operational='aprovado')
        self.assertEqual(self.post(bm,'reprovar_pagamento').status_code,400)
        bm.refresh_from_db();self.assertEqual(bm.aprovacao_pagamento,'pendente')
        self.assertEqual(self.post(bm,'reprovar_pagamento','Revisar os valores.').status_code,200)
        bm.refresh_from_db();self.assertEqual(bm.justificativa_reprovacao_diretor,'Revisar os valores.')
        self.assertEqual(self.current(bm)['status'],'reprovado')

    def test_adicionar_editar_excluir_nao_decide_e_preserva_autoria(self):
        bm=self.bm(operational='aprovado')
        for action,text,expected in (('salvar_justificativa','Conferir','Conferir'),('salvar_justificativa','Conferido','Conferido'),('excluir_justificativa','','')):
            self.assertEqual(self.post(bm,action,text).status_code,200)
            bm.refresh_from_db();self.assertEqual(bm.aprovacao_pagamento,'pendente')
            self.assertEqual(self.current(bm)['text'],expected)
        history=m.RegistroAuditoria.objects.filter(object_id=bm.pk,operacao_financeira='justificativa_bm').order_by('pk')
        self.assertEqual(history.count(),3)
        self.assertTrue(all(item.usuario_id==self.director.pk for item in history))
        self.assertEqual(history.last().estado_anterior['justificativa'],'Conferido')

    def test_justificativa_existente_usada_na_reprovacao(self):
        bm=self.bm(operational='aprovado')
        self.post(bm,'salvar_justificativa','Documento incompleto')
        text=self.current(bm)['text']
        self.assertEqual(self.post(bm,'reprovar_pagamento',text).status_code,200)
        bm.refresh_from_db();self.assertEqual(bm.justificativa_reprovacao_diretor,text)

    def test_alterar_excluir_apos_decisao_preserva_estado_data_e_historico(self):
        bm=self.bm(operational='aprovado')
        self.post(bm,'reprovar_pagamento','Razão original')
        bm.refresh_from_db();instant=bm.data_aprovacao_diretor
        for action,text in (('salvar_justificativa','Razão atualizada'),('excluir_justificativa','')):
            self.assertEqual(self.post(bm,action,text).status_code,200)
        bm.refresh_from_db()
        self.assertEqual((bm.aprovacao_pagamento,bm.data_aprovacao_diretor),('reprovado',instant))
        audit=m.RegistroAuditoria.objects.get(object_id=bm.pk,operacao_financeira='decisao_bm')
        self.assertEqual(audit.estado_posterior['justificativa_reprovacao_diretor'],'Razão original')

    def test_post_repetido_ou_token_antigo_nao_sobrescreve(self):
        bm=self.bm(operational='aprovado');token=self.current(bm)['token']
        self.assertEqual(self.post(bm,'salvar_justificativa','Primeiro',token).status_code,200)
        self.assertEqual(self.post(bm,'salvar_justificativa','Segundo',token).status_code,409)
        self.assertEqual(self.current(bm)['text'],'Primeiro')
        token=self.current(bm)['token']
        self.assertEqual(self.post(bm,'aprovar_pagamento','Primeiro',token).status_code,200)
        self.assertEqual(self.post(bm,'reprovar_pagamento','Forjado',token).status_code,409)

    def test_perfis_indevidos_get_csrf(self):
        bm=self.bm(operational='aprovado');url=reverse('acao_pagamento_bm_previsao',args=[bm.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        for actor in (self.finance,self.supply,self.leader,self.coord):
            self.client.force_login(actor)
            self.assertEqual(self.post(bm,'salvar_justificativa','Indevido').status_code,403)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.director)
        self.assertEqual(csrf.post(url,{'acao':'aprovar_pagamento','token':self.current(bm)['token']}).status_code,403)
        self.assertFalse(m.JustificativaPagamentoBM.objects.exists())

    def test_limite_branco_escape_e_mudanca_material(self):
        bm=self.bm(operational='aprovado')
        self.assertEqual(self.post(bm,'salvar_justificativa','  ').status_code,400)
        self.assertEqual(self.post(bm,'salvar_justificativa','a'*4001).status_code,400)
        self.post(bm,'salvar_justificativa','<script>alert(1)</script>')
        token=self.current(bm)['token'];bm.valor_pago=200;bm.save()
        self.assertEqual(self.current(bm)['text'],'')
        self.assertEqual(self.post(bm,'aprovar_pagamento','',token).status_code,409)

    def test_os_tambem_usa_mesmo_fluxo(self):
        bm=self.bm(os=True,operational='aprovado')
        self.assertEqual(self.post(bm,'aprovar_pagamento','OS conferida').status_code,200)
        bm.refresh_from_db();self.assertEqual(bm.justificativa_aprovacao_diretor,'OS conferida')

    def test_tags_substituem_botoes_apos_decisao_e_outros_perfis_so_consultam(self):
        bm=self.bm(operational='aprovado',data_aprovacao_gerente='2026-11-01T12:00:00Z')
        self.post(bm,'reprovar_pagamento','Motivo visível')
        params={'data_inicial':'2026-01-01','data_limite':'2026-12-31'}
        response=self.client.get(reverse('previsao_pagamentos'),params)
        self.assertContains(response,'<span class="badge bg-danger">Reprovado</span>',html=True)
        self.assertNotContains(response,'data-bm-forecast-action="aprovar_pagamento"')
        self.assertContains(response,'Motivo visível')
        self.client.force_login(self.finance)
        response=self.client.get(reverse('previsao_pagamentos'),params)
        self.assertContains(response,'Motivo visível')
        self.assertNotContains(response,'data-bm-forecast-action=')

    def test_justificativa_pendente_no_evento_e_escape_html(self):
        bm=self.bm(operational='aprovado')
        text='<script>alert(1)</script>'
        self.post(bm,'salvar_justificativa',text)
        for name,key in (('detalhes_entrega',bm.evento_id),('detalhe_bm_financeiro',bm.pk)):
            response=self.client.get(reverse(name,args=[key]))
            self.assertContains(response,'&lt;script&gt;alert(1)&lt;/script&gt;')
            self.assertNotContains(response,text)

    def test_ciclo_reprogramado_exige_lider_e_mantem_decisao_original_imutavel(self):
        bm=self.bm(operational='aprovado',director='aprovado',data_pagamento=date(2026,10,24))
        m.CalendarioPagamento.objects.create(data_pagamento=date(2026,11,24))
        cycles.process_bm(bm.pk,self.finance,today=date(2026,11,16),reprogram_only=True)
        self.assertFalse(self.current(bm)['can_decide'])
        self.assertEqual(self.post(bm,'aprovar_pagamento').status_code,409)
        cycle=m.CicloPagamentoBM.objects.get(bm=bm,sucessor__isnull=True)
        cycles.decide(cycle.pk,self.leader,'gerencia',True)
        self.assertTrue(self.current(bm)['can_decide'])
        self.assertEqual(self.post(bm,'reprovar_pagamento','Rever NF no ciclo').status_code,200)
        original=m.DecisaoCicloBM.objects.values().get(ciclo=cycle,etapa='diretoria')
        self.assertEqual(self.post(bm,'salvar_justificativa','Anotação corrigida').status_code,200)
        self.assertEqual(self.post(bm,'excluir_justificativa').status_code,200)
        self.assertEqual(m.DecisaoCicloBM.objects.values().get(ciclo=cycle,etapa='diretoria'),original)
        self.assertEqual(self.current(bm)['text'],'')
        self.assertEqual(self.current(bm)['status'],'reprovado')
