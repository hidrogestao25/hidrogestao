"""Indicadores e interface financeira: bancos e documentos exclusivamente sintéticos."""
from datetime import date
from decimal import Decimal
import tempfile

from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import models as m
from .financial_queries import FinancialData, eager_bms, eager_nfs, bm_row, nf_rows, monthly_paid_series
from .forms import FiltroFinanceiroForm
from .test_auditoria import pdf
from .tests import BaseUserTestCase


class FinanceiroFase2Tests(BaseUserTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        settings = override_settings(MEDIA_ROOT=temp.name, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
        settings.enable(); self.addCleanup(settings.disable)
        self.finance = self.create_user("f2_fin", "financeiro")
        self.supply = self.create_user("f2_supply", "suprimento")
        self.leader = self.create_user("f2_leader", "lider_contrato")
        self.coord = self.create_user("f2_coord", "coordenador")
        self.other = self.create_user("f2_other", "lider_contrato")
        self.supplier = self.create_supplier()
        self.projects = [self.create_contract(codigo=f"F2-{i}", lider_contrato=self.leader if i == 0 else self.other,
            coordenador=self.coord if i == 0 else None) for i in range(2)]
        self.contracts = [self.create_supplier_contract(cod_projeto=p, empresa_terceira=self.supplier,
            lider_contrato=p.lider_contrato, coordenador=p.coordenador, num_contrato=f"F2-C{i}") for i,p in enumerate(self.projects)]
        self.events = [self.create_event(contrato=c) for c in self.contracts]
        for event, amount in zip(self.events, ("60000", "40000")):
            event.valor_previsto = Decimal(amount); event.data_prevista_pagamento = date(2026, 11, 15); event.save()
        self.order = self.create_os(contrato=self.contracts[0], data_prevista_pagamento=date(2026, 11, 20))
        self.filters = {"data_inicial": date(2026, 11, 1), "data_limite": date(2026, 11, 30)}
        self.client.force_login(self.finance)

    def bm(self, index=0, value="100", operational="pendente", director="pendente", os=False, **extra):
        data = dict(contrato=self.contracts[index], numero_bm=15, parcela_paga=1, valor_pago=Decimal(value),
            data_pagamento=date(2026, 11, 15), status_gerente=operational, aprovacao_pagamento=director,
            **({"os": self.order} if os else {"evento": self.events[index]}))
        data.update(extra)
        return m.BM.objects.create(**data)

    def nf(self, bm, value="50", paid=False, day=date(2026, 11, 15)):
        from .payment_context import ledger_context
        # Estado histórico sintético; pagamentos novos são testados pelos serviços.
        with ledger_context(legacy=paid):
            return m.NF.objects.create(contrato=bm.contrato_financeiro, evento=bm.evento, os=bm.os,
                bm=bm, valor_pago=Decimal(value), parcela_paga=1, financeiro_autorizou=paid, data_pagamento=day)

    def data(self, **filters):
        return FinancialData(self.finance, self.filters | filters)

    def test_2a_indicadores_vazios(self):
        stats = self.data().indicators()
        self.assertEqual(stats["previsto"], Decimal("100350"))
        for name in ("medido", "autorizado", "faturado", "pago", "a_pagar", "nao_autorizado", "em_revisao"):
            self.assertEqual(stats[name], 0, name)

    def test_2a_participacoes_compartilhadas_somam_100_mil(self):
        a = self.bm(value="60000", operational="aprovado", director="aprovado", arquivo_bm=pdf())
        self.bm(index=1, value="40000", operational="aprovado", director="aprovado", arquivo_bm=a.arquivo_bm.name)
        stats = self.data().indicators()
        self.assertEqual(stats["medido"], Decimal("100000"))
        self.assertEqual(stats["autorizado"], Decimal("100000"))
        self.assertEqual(stats["sem_nf_count"], 2)

    def test_2a_documental_cruzado_segue_financeiro_do_evento(self):
        bm = self.bm(index=1, value="60", evento=self.events[0])
        self.assertEqual(list(self.data(contrato=self.contracts[0]).bms), [bm])
        self.assertFalse(self.data(contrato=self.contracts[1]).bms.exists())
        self.assertEqual(self.data(projeto=self.projects[0]).indicators()["medido"], 60)

    def test_2a_nfs_multiplas_nao_multiplicam_medicao(self):
        bm = self.bm(value="100", operational="aprovado", director="aprovado")
        self.nf(bm, value="20", paid=True); self.nf(bm, value="30"); self.nf(bm, value="10")
        stats = self.data().indicators()
        self.assertEqual((stats["medido"], stats["faturado"], stats["pago"], stats["a_pagar"]), (100,60,20,40))
        self.assertEqual((stats["sem_nf_count"], stats["pagamento_count"], stats["pagos_count"]), (0,2,1))

    def test_2a_pago_usa_data_de_cada_nf_e_nao_ultima_data_da_origem(self):
        bm = self.bm(operational="aprovado", director="aprovado")
        self.nf(bm, value="20", paid=True); self.nf(bm, value="30", paid=True, day=date(2026, 12, 10))
        self.events[0].valor_pago = 999; self.events[0].data_pagamento = date(2026, 12, 10); self.events[0].save()
        self.assertEqual(self.data().indicators()["pago"], 20)
        series = monthly_paid_series(self.data(historico=True).nfs)
        self.assertEqual([(x["month"].month, x["total"]) for x in series], [(11,20),(12,30)])

    def test_2a_previsto_nao_repetido_por_bm_ou_nf(self):
        for _ in range(3): self.nf(self.bm())
        self.assertEqual(self.data().indicators()["previsto"], Decimal("100350"))

    def test_2a_filas_bm_e_nf_disjuntas(self):
        pending = self.bm()
        operational = self.bm(operational="aprovado")
        without_nf = self.bm(operational="aprovado", director="aprovado")
        waiting = self.nf(pending)
        ready = self.nf(self.bm(operational="aprovado", director="aprovado"))
        paid = self.nf(self.bm(operational="aprovado", director="aprovado"), paid=True)
        q = self.data().queries
        self.assertSetEqual(set(q["aprovacao"].values_list("pk",flat=True)), {pending.pk,operational.pk})
        self.assertEqual(list(q["sem_nf"]), [without_nf])
        self.assertEqual(list(q["autorizacao"]), [waiting]); self.assertEqual(list(q["pagamento"]), [ready]); self.assertEqual(list(q["pagos"]), [paid])
        sets = [set(q[key].values_list("pk",flat=True)) for key in ("autorizacao","pagamento","pagos","atencao_nf")]
        self.assertEqual(sum(map(len,sets)), len(set().union(*sets)))

    def test_2a_reprovacoes_e_autorizacao_incoerente_exigem_atencao(self):
        for operational, director in (("reprovado","pendente"),("aprovado","reprovado"),("pendente","aprovado")):
            bm=self.bm(operational=operational,director=director); nf=self.nf(bm)
            self.assertIn(bm,self.data().queries["atencao_bm"])
            self.assertIn(nf,self.data().queries["atencao_nf"])
            self.assertNotIn(nf,self.data().queries["pagamento"])

    def test_2a_pagamento_com_autorizacao_invalidada_nao_desaparece_do_total(self):
        bm=self.bm(operational="aprovado",director="aprovado"); nf=self.nf(bm,paid=True)
        bm.valor_pago=200; bm.save()
        data=self.data()
        self.assertIn(nf,data.queries["atencao_nf"]); self.assertNotIn(nf,data.queries["pagos"])
        self.assertEqual(data.indicators()["pago"],50)

    def test_2a_os_cancelada_preserva_valor_e_encaminha_revisao(self):
        bm=self.bm(os=True,operational="aprovado",director="aprovado"); nf=self.nf(bm,paid=True)
        self.order.status="cancelada"; self.order.save()
        data=self.data(); self.assertIn(nf,data.queries["atencao_nf"]); self.assertIn(bm,data.queries["atencao_bm"])
        self.assertEqual(data.indicators()["pago"],50)
        self.assertEqual(data.indicators()["autorizado"],0)

    def test_2a_legado_sem_bm_e_vinculo_incompativel_so_sinalizados(self):
        a,b=self.bm(),self.bm(index=1)
        legacy=self.nf(a); cross=self.nf(b)
        m.NF.objects.filter(pk=legacy.pk).update(bm=None)
        m.NF.objects.filter(pk=cross.pk).update(bm=a)
        before=list(m.NF.objects.order_by("pk").values())
        self.assertSetEqual(set(self.data().queries["atencao_nf"].values_list("pk",flat=True)),{legacy.pk,cross.pk})
        self.data().indicators()
        self.assertEqual(before,list(m.NF.objects.order_by("pk").values()))

    def test_2a_filtros_por_fornecedor_contrato_projeto_origem_bm_e_status(self):
        a=self.bm(operational="aprovado",director="aprovado"); b=self.bm(index=1); self.bm(os=True)
        nf=self.nf(a,paid=True)
        self.assertEqual(list(self.data(contrato=self.contracts[1]).bms),[b])
        self.assertEqual(self.data(origem="os").bms.count(),1)
        self.assertEqual(list(self.data(autorizacao="autorizado",pagamento="pago").nfs),[nf])
        self.assertEqual(list(self.data(bm_id=a.pk).bms),[a])
        self.assertEqual(self.data(numero_bm=15).bms.count(),3)
        self.assertEqual(list(self.data(projeto=self.projects[1]).bms),[b])

    def test_2a_coordenadores_multiplos_nao_multiplicam_totais(self):
        self.contracts[0].coordenadores.add(self.coord)
        self.projects[0].coordenadores.add(self.coord)
        self.bm(value="100"); self.nf(self.bm(value="200"),value="30")
        stats=self.data(coordenador=self.coord).indicators()
        self.assertEqual((stats["medido"],stats["faturado"]),(300,30))

    def test_2a_formulario_rejeita_intervalo_invertido(self):
        form=FiltroFinanceiroForm({"data_inicial":"2026-12-01","data_limite":"2026-11-01"},user=self.finance)
        self.assertFalse(form.is_valid())
        self.assertTrue(FiltroFinanceiroForm({"historico":"on"},user=self.finance).is_valid())

    def test_2a_helpers_negam_painel_a_perfis_restritos(self):
        for user in (self.leader,self.coord,self.other,self.create_user("f2_vendor","fornecedor")):
            with self.subTest(role=user.grupo),self.assertRaises(PermissionDenied): FinancialData(user,self.filters)

    def test_2b_painel_renderiza_indicadores_e_seis_filas(self):
        bm=self.bm(operational='aprovado',director='aprovado'); self.nf(bm)
        response=self.client.get(reverse('painel_financeiro'),{'historico':'on'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['financial_stats']['a_pagar'],50)
        self.assertEqual(len(response.context['financial_queues']),6)
        self.assertContains(response,'Painel do Financeiro')
        self.assertContains(response,'Registrar pagamento')
        self.assertContains(response,'financeiro.js')

    def test_2b_painel_previa_limitada_e_fila_paginada(self):
        for i in range(23): self.nf(self.bm(operational='aprovado',director='aprovado'))
        response=self.client.get(reverse('painel_financeiro'),{'historico':'on'})
        queue=next(q for q in response.context['financial_queues'] if q['key']=='pagamento')
        self.assertEqual((queue['count'],len(queue['rows'])),(23,5))
        response=self.client.get(reverse('pendencias_financeiras'),{'fila':'pagamento','historico':'on','page':2,'contrato':self.contracts[0].pk})
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.context['rows']),3)
        self.assertEqual(response.context['page_obj'].paginator.count,23)
        self.assertIn('contrato=',response.context['pagination_query'])

    def test_2b_filas_e_detalhes_somente_get(self):
        nf=self.nf(self.bm())
        for url in (reverse('pendencias_financeiras'),reverse('detalhe_nf',args=[nf.pk]),reverse('detalhe_bm_financeiro',args=[nf.bm_id])):
            self.assertEqual(self.client.post(url).status_code,405)

    def test_2b_filtros_invalidos_nao_retornam_todos_registros(self):
        self.nf(self.bm())
        for url in (reverse('painel_financeiro'),reverse('pendencias_financeiras')):
            response=self.client.get(url,{'data_inicial':'2026-12-01','data_limite':'2026-11-01'})
            self.assertEqual(response.status_code,200)
            self.assertNotIn('financial_stats',response.context)
            self.assertContains(response,'Revise os filtros')
        self.assertEqual(self.client.get(reverse('pendencias_financeiras'),{'fila':'inexistente'}).status_code,400)

    def test_2b_atencao_separa_tipos_e_preserva_criterios(self):
        bm=self.bm(operational='reprovado'); nf=self.nf(bm)
        for kind,record in (('nf',nf),('bm',bm)):
            response=self.client.get(reverse('pendencias_financeiras'),{'fila':'atencao','registro':kind,'historico':'on'})
            self.assertEqual(response.status_code,200)
            self.assertEqual([r['record'] for r in response.context['rows']],[record])
            self.assertContains(response,'Nenhum lançamento é corrigido automaticamente')

    def test_2b_custo_consultas_independe_de_quantidade_de_linhas(self):
        self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        # Aquece ContentType/session para comparar o mesmo caminho.
        url=reverse('pendencias_financeiras')+'?fila=pagos&historico=on'
        self.client.get(url)
        with CaptureQueriesContext(connection) as first: self.client.get(url)
        for i in range(12): self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        with CaptureQueriesContext(connection) as many: self.client.get(url)
        self.assertEqual(len(first),len(many))
        self.assertLess(len(many),35)

    def test_2c_globais_consultam_filas_e_detalhes(self):
        nf=self.nf(self.bm(index=1))
        users=[self.finance,self.supply,self.create_user('f2_dir','diretoria'),self.create_user('f2_gc','gerente_contrato')]
        for user in users:
            self.client.force_login(user)
            for url in (reverse('pendencias_financeiras'),reverse('detalhe_nf',args=[nf.pk]),reverse('detalhe_bm_financeiro',args=[nf.bm_id])):
                with self.subTest(role=user.grupo,url=url): self.assertEqual(self.client.get(url).status_code,200)

    def test_2c_restritos_so_consultam_detalhes_proprios(self):
        own=self.nf(self.bm()); foreign=self.nf(self.bm(index=1))
        for user in (self.leader,self.coord):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('pendencias_financeiras')).status_code,403)
            for name,own_id,foreign_id in (('detalhe_nf',own.pk,foreign.pk),('detalhe_bm_financeiro',own.bm_id,foreign.bm_id)):
                self.assertEqual(self.client.get(reverse(name,args=[own_id])).status_code,200)
                self.assertEqual(self.client.get(reverse(name,args=[foreign_id])).status_code,404)

    def test_2c_anonimo_exige_login(self):
        nf=self.nf(self.bm()); self.client.logout()
        for url in (reverse('pendencias_financeiras'),reverse('detalhe_nf',args=[nf.pk]),reverse('detalhe_bm_financeiro',args=[nf.bm_id])):
            self.assertEqual(self.client.get(url).status_code,302)

    def test_2c_nf_paga_financeiro_consulta_suprimento_corrige(self):
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        url=reverse('detalhe_nf',args=[nf.pk])
        response=self.client.get(url)
        self.assertContains(response,'Movimentos confirmados são permanentes')
        self.assertNotContains(response,'data-finance-modal-url=')
        self.assertNotContains(response,'Excluir NF')
        self.client.force_login(self.supply)
        response=self.client.get(url)
        self.assertContains(response,'Editar NF'); self.assertContains(response,'Cancelar NF com estornos')

    def test_2c_contexto_navega_todos_os_niveis(self):
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'))
        response=self.client.get(reverse('detalhe_nf',args=[nf.pk]))
        for name,key in (('detalhe_bm_financeiro',nf.bm_id),('detalhes_entrega',nf.evento_id),('contrato_fornecedor_detalhe',nf.contrato_id),('fornecedor_detalhe',self.supplier.pk)):
            self.assertContains(response,reverse(name,args=[key]))
        self.assertContains(response,'Registrar pagamento')
        bm_response=self.client.get(reverse('detalhe_bm_financeiro',args=[nf.bm_id]))
        self.assertContains(bm_response,reverse('detalhe_nf',args=[nf.pk]))

    def test_2c_os_aponta_consulta_acessivel_ao_financeiro(self):
        nf=self.nf(self.bm(os=True))
        response=self.client.get(reverse('detalhe_nf',args=[nf.pk]))
        self.assertContains(response,reverse('detalhes_os',args=[self.order.pk]))
        self.assertEqual(self.client.get(reverse('detalhes_os',args=[self.order.pk])).status_code,200)

    def test_2c_retorno_preserva_filtros_e_recusa_host_externo(self):
        nf=self.nf(self.bm()); url=reverse('detalhe_nf',args=[nf.pk])
        back=reverse('pendencias_financeiras')+'?fila=autorizacao&historico=on'
        self.assertEqual(self.client.get(url,{'next':back}).context['return_url'],back)
        self.assertEqual(self.client.get(url,{'next':'https://externo.example/'}).context['return_url'],reverse('home'))
        response=self.client.post(reverse('deletar_nf',args=[nf.pk]),{'next':back})
        self.assertRedirects(response,back,fetch_redirect_response=False)

    def test_2c_bm_inicial_cadastro_nf_reutiliza_formulario(self):
        for is_os in (False,True):
            bm=self.bm(os=is_os)
            url=reverse('cadastrar_nf_os' if is_os else 'cadastrar_nf',args=[self.order.pk if is_os else bm.evento_id])
            response=self.client.get(url,{'bm':bm.pk})
            self.assertEqual(str(response.context['form']['bm'].value()),str(bm.pk))
            self.assertContains(response,'submission_token')

    def test_2c_bm_restrito_nao_expoe_nf_de_outro_contrato(self):
        own=self.bm(); foreign=self.nf(self.bm(index=1))
        m.NF.objects.filter(pk=foreign.pk).update(bm=own)
        self.client.force_login(self.leader)
        response=self.client.get(reverse('detalhe_bm_financeiro',args=[own.pk]))
        self.assertEqual(response.context['rows'],[])
        self.assertEqual(self.client.get(reverse('detalhe_nf',args=[foreign.pk])).status_code,404)

    def test_2c_documentos_sao_links_privados_com_escopo(self):
        bm=self.bm(arquivo_bm=pdf()); row=bm_row(bm,self.finance)
        self.assertTrue(row['document_url'].startswith('/arquivos/'))
        response=self.client.get(row['document_url'])
        self.assertEqual(response.status_code,200)
        response.close()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(row['document_url']).status_code,404)

    def test_2d_previsao_nf_por_mes_preserva_acumulado_da_origem(self):
        bm=self.bm(operational='aprovado',director='aprovado')
        self.nf(bm,value='20',paid=True); self.nf(bm,value='30',paid=True,day=date(2026,12,10))
        m.Evento.objects.filter(pk=bm.evento_id).update(valor_pago=Decimal('50'),data_pagamento=date(2026,12,10))
        response=self.client.get(reverse('previsao_pagamentos'),{'data_inicial':'2026-11-01','data_limite':'2026-12-31'})
        self.assertEqual(response.status_code,200)
        self.assertEqual([(r['month'].month,r['total']) for r in response.context['nf_paid_series']],[(11,20),(12,30)])
        self.assertEqual(response.context['nf_paid_total'],50)
        self.assertEqual(response.context['total_pago'],50)
        self.assertContains(response,'datas efetivas de cada movimento')
        self.assertContains(response,'Pagamentos efetivos por NF')
        self.assertEqual(response.content.count(b'src="https://cdn.plot.ly/plotly-'),1)
        self.assertLess(len(response.content),500000)
        november=self.client.get(reverse('previsao_pagamentos'),{'data_inicial':'2026-11-01','data_limite':'2026-11-30'})
        self.assertEqual(november.context['nf_paid_total'],20)
        self.assertEqual(november.context['total_pago'],20)

    def test_2d_serie_complementar_respeita_escopo_restrito(self):
        for index,value in ((0,'20'),(1,'90')): self.nf(self.bm(index=index,operational='aprovado',director='aprovado'),value=value,paid=True)
        manager=self.create_user('f2_center_manager','gerente_lider')
        center=self.create_center('F2'); manager.centros.add(center); self.coord.centros.add(center)
        self.client.force_login(manager)
        response=self.client.get(reverse('previsao_pagamentos'),{'data_inicial':'2026-11-01','data_limite':'2026-11-30'})
        self.assertEqual(response.context['nf_paid_total'],20)

    def test_2d_serie_filtro_coordenador(self):
        for index,value in ((0,'20'),(1,'90')): self.nf(self.bm(index=index,operational='aprovado',director='aprovado'),value=value,paid=True)
        response=self.client.get(reverse('previsao_pagamentos'),{'data_inicial':'2026-11-01','data_limite':'2026-11-30','coordenador':self.coord.pk})
        self.assertEqual(response.context['nf_paid_total'],20)
        self.assertIn('coordenador=',response.context['export_query'])

    def test_2d_exportacoes_preservadas(self):
        from io import BytesIO
        import zipfile
        import openpyxl
        from django.utils import timezone
        self.bm(operational='aprovado',arquivo_bm=pdf(),data_aprovacao_gerente=timezone.now())
        params={'data_inicial':'2026-01-01','data_limite':'2026-12-31'}
        response=self.client.get(reverse('exportar_previsao_pagamentos_excel'),params)
        self.assertEqual(response.status_code,200)
        workbook=openpyxl.load_workbook(BytesIO(response.content))
        self.assertEqual(len(workbook.sheetnames),4)
        response=self.client.get(reverse('download_bms_aprovados'),params)
        self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(BytesIO(response.content)) as archive: self.assertEqual(len(archive.namelist()),1)

    def test_2d_estado_vazio_e_exportacoes_sem_filtro(self):
        response=self.client.get(reverse('previsao_pagamentos'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Selecione as datas para habilitar as exportações')
        response=self.client.get(reverse('previsao_pagamentos'),{'data_inicial':'2026-11-01','data_limite':'2026-11-30'})
        self.assertContains(response,'Nenhuma NF paga neste período')

    def test_2e_nf_cliente_nao_compoe_faturamento_fornecedor(self):
        m.NFCliente.objects.create(contrato=self.projects[0],valor_pago=900,parcela_paga=1,data_emissao=date(2026,11,15),data_pagamento=date(2026,11,15))
        stats=self.data().indicators()
        self.assertEqual((stats['faturado'],stats['pago']),(0,0))

    def test_2e_pagamento_via_formulario_existente_atualiza_filas(self):
        bm=self.bm(operational='aprovado',director='aprovado'); nf=self.nf(bm)
        response=self.client.post(reverse('editar_nf',args=[nf.pk]),{'bm':bm.pk,'valor_pago':'50,00','parcela_paga':1,'data_pagamento':'2026-11-15','financeiro_autorizou':'on'})
        self.assertTrue(response.json()['success'],response.content)
        nf.refresh_from_db(); self.assertTrue(nf.financeiro_autorizou)
        self.assertEqual((self.data().indicators()['pagamento_count'],self.data().indicators()['pagos_count']),(0,1))
        row=nf_rows([nf],self.finance)[0]
        self.assertEqual(row['payment_actor'],self.finance.get_full_name() or self.finance.username)
        self.assertFalse(row['can_edit'])

    def test_2e_cadastro_pago_sem_trilha_de_transicao_nao_inventa_ator(self):
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        self.assertEqual(nf_rows([nf],self.finance)[0]['payment_actor'],'Responsável não identificado no histórico disponível.')

    def test_2e_nf_propria_com_bm_estrangeiro_nao_expoe_contexto(self):
        nf=self.nf(self.bm()); foreign=self.bm(index=1)
        m.NF.objects.filter(pk=nf.pk).update(bm=foreign)
        self.client.force_login(self.leader)
        self.assertEqual(self.client.get(reverse('detalhe_nf',args=[nf.pk])).status_code,404)

    def test_2e_gerente_contrato_preserva_previsao_e_nfs_globais(self):
        manager=self.create_user('f2_global_manager','gerente_contrato')
        for index in (0,1): self.nf(self.bm(index=index,operational='aprovado',director='aprovado'),paid=True)
        self.client.force_login(manager)
        response=self.client.get(reverse('previsao_pagamentos'),{'data_inicial':'2026-11-01','data_limite':'2026-11-30'})
        self.assertEqual(response.context['total_previsto'],Decimal('100350'))
        self.assertEqual(response.context['nf_paid_total'],100)
