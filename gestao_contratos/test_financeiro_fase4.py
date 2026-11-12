"""Regressões operacionais com NFs/BMs sintéticos; nenhuma base real."""
from datetime import date
from decimal import Decimal
from django.urls import reverse
from django.db import connection
from django.test.utils import CaptureQueriesContext
from . import models as m,financial_operations as fo
from . import test_financeiro_fase2 as fixtures
from .tests import BaseUserTestCase


class FinanceiroFase4Tests(BaseUserTestCase):
    setUp=fixtures.FinanceiroFase2Tests.setUp
    bm=fixtures.FinanceiroFase2Tests.bm
    nf=fixtures.FinanceiroFase2Tests.nf

    def url(self,name='contas_a_pagar'):return reverse(name)

    def test_4a_estados_e_pago_com_autorizacao_invalidada(self):
        waiting=self.nf(self.bm())
        ready=self.nf(self.bm(operational='aprovado',director='aprovado'))
        paid=self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        review=self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        m.BM.objects.filter(pk=review.bm_id).update(aprovacao_pagamento='pendente')
        qs=fo.accounts_query(self.finance,{'historico':True})
        self.assertEqual(dict(qs.values_list('pk','operation_state')),{waiting.pk:'aguardando',ready.pk:'autorizada',paid.pk:'paga',review.pk:'conferencia'})
        response=self.client.get(self.url('pagamentos_financeiros'))
        self.assertEqual(response.context['totals']['paid'],100)
        self.assertContains(response,'Exige conferência')

    def test_4a_os_cancelada_em_conferencia(self):
        nf=self.nf(self.bm(os=True))
        m.OS.objects.filter(pk=self.order.pk).update(status='cancelada')
        response=self.client.get(self.url(),{'situacao':'conferencia'})
        self.assertEqual([r['id'] for r in response.context['rows']],[nf.pk])
        self.assertContains(response,'OS cancelada')

    def test_4a_vazio_sem_vencimento_inventado(self):
        response=self.client.get(self.url())
        self.assertContains(response,'Nenhuma NF encontrada.')
        self.assertEqual(list(response.context['rows']),[])
        self.assertEqual(response.context['totals']['count'],0)

    def test_4a_numero_pesquisa_fornecedor_contrato_projeto(self):
        nf=self.nf(self.bm());nf.numero_nf='000123';nf.save()
        self.nf(self.bm(index=1))
        for filters in ({'numero_nf':'00123'},{'pesquisa':'000123'},{'contrato':self.contracts[0].pk},
            {'projeto':self.projects[0].pk},{'origem':'evento','referencia':self.events[0].pk}):
            response=self.client.get(self.url(),filters)
            self.assertEqual([r['id'] for r in response.context['rows']],[nf.pk],filters)

    def test_4a_periodo_por_data_nf_sem_reinterpretar_como_vencimento(self):
        bm=self.bm();nov=self.nf(bm);self.nf(bm,day=date(2026,12,1))
        response=self.client.get(self.url(),{'data_inicial':'2026-11-01','data_limite':'2026-11-30'})
        self.assertEqual([r['id'] for r in response.context['rows']],[nov.pk])

    def test_4a_filtros_invalidos_nao_ampliam_resultado(self):
        self.nf(self.bm())
        for filters in ({'fornecedor':'invalido'},{'situacao':'inexistente'},{'data_inicial':'2026-12-01','data_limite':'2026-11-01'}):
            response=self.client.get(self.url(),filters)
            self.assertNotIn('rows',response.context)
            self.assertContains(response,'Revise os filtros.')

    def test_4a_paginacao_e_consultas_limitadas(self):
        bm=self.bm();self.nf(bm)
        with CaptureQueriesContext(connection) as small:self.client.get(self.url())
        for _ in range(22):self.nf(bm)
        with CaptureQueriesContext(connection) as large:response=self.client.get(self.url(),{'page':2})
        self.assertEqual(len(response.context['rows']),3)
        self.assertEqual(len(small),len(large))
        self.assertLess(len(large),40)

    def test_4a_bm_compartilhado_60_40_nao_duplica_nf(self):
        from .test_auditoria import pdf
        a=self.bm(value='60000',arquivo_bm=pdf());b=self.bm(index=1,value='40000',arquivo_bm=a.arquivo_bm.name)
        self.nf(a,value='60000');self.nf(b,value='40000')
        self.assertEqual(self.client.get(self.url()).context['totals']['billed'],100000)
        response=self.client.get(self.url(),{'contrato':self.contracts[0].pk})
        self.assertEqual(response.context['totals']['billed'],60000)

    def test_4a_perfis_e_metodos(self):
        for role in ('financeiro','suprimento','diretoria','gerente_contrato'):
            self.client.force_login(self.create_user('op_'+role,role))
            for name in ('contas_a_pagar','pagamentos_financeiros'):
                self.assertEqual(self.client.get(self.url(name)).status_code,200)
                self.assertEqual(self.client.post(self.url(name)).status_code,405)
        for user in (self.leader,self.coord,self.other,self.create_user('op_supplier','fornecedor')):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url(),{'contrato':self.contracts[0].pk}).status_code,403)
        self.client.logout();self.assertEqual(self.client.get(self.url()).status_code,302)

    def test_4a_acao_financeiro_pago_somente_leitura(self):
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        response=self.client.get(self.url())
        self.assertNotContains(response,'data-finance-modal-url=')
        self.assertContains(response,reverse('historico_financeiro')+f'?nf_id={nf.pk}')
        self.client.force_login(self.supply)
        self.assertContains(self.client.get(self.url()),'data-finance-modal-url=')

    def test_4b_contexto_e_confirmacao_pagamento_no_fluxo_existente(self):
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'))
        response=self.client.get(reverse('editar_nf',args=[nf.pk]))
        self.assertContains(response,'data-nf-initial-paid="false"')
        self.assertContains(response,'Valor original: R$ 50,00')
        self.assertContains(response,'Confirmar que o pagamento foi realizado?')
        self.assertContains(self.client.get(self.url()),'js/nf_confirmacao.js')

    def test_4b_pagamento_auditoria_e_correcao_suprimento_preservados(self):
        from .test_auditoria import pdf
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'))
        payload=dict(bm=nf.bm_id,valor_pago='50,00',parcela_paga=1,data_pagamento='2026-11-15',financeiro_autorizou='on',comprovante_pagamento=pdf())
        self.assertTrue(self.client.post(reverse('editar_nf',args=[nf.pk]),payload).json()['success'])
        event=m.RegistroAuditoria.objects.filter(object_id=nf.pk,operacao_financeira='liquidacao').get()
        self.assertEqual(event.usuario,self.finance)
        payload.pop('comprovante_pagamento')
        self.assertEqual(self.client.post(reverse('editar_nf',args=[nf.pk]),payload).status_code,403)
        self.client.force_login(self.supply);payload['justificativa_correcao']='Conferência sintética'
        payload['observacao']='Dado corrigido'
        self.assertTrue(self.client.post(reverse('editar_nf',args=[nf.pk]),payload).json()['success'])
        self.assertEqual(m.RegistroAuditoria.objects.filter(object_id=nf.pk,operacao_financeira='correcao_paga').get().justificativa,'Conferência sintética')

    def test_4c_posicao_reutiliza_totais_sem_multiplicar_participacoes(self):
        a=self.bm(value='60000',operational='aprovado',director='aprovado');b=self.bm(index=1,value='40000')
        self.nf(a,value='20000',paid=True);self.nf(a,value='30000');self.nf(b,value='4000')
        response=self.client.get(self.url('orcamento_financeiro'))
        rows={row['contract'].pk:row['stats'] for row in response.context['rows']}
        self.assertEqual((rows[a.contrato_id]['medido'],rows[a.contrato_id]['faturado'],rows[a.contrato_id]['pago'],rows[a.contrato_id]['unpaid']),(60000,50000,20000,30000))
        self.assertEqual(rows[b.contrato_id]['medido'],40000)

    def test_4c_aditivo_e_acrescimo_nao_valor_absoluto(self):
        self.contracts[0].valor_total=100000;self.contracts[0].save()
        m.AditivoContratoTerceiro.objects.create(contrato=self.contracts[0],motivo='Teste',
            valor_total_anterior=100000,novo_valor_total=25000,arquivo_aditivo_assinado='sintetico.pdf')
        response=self.client.get(self.url('orcamento_financeiro'),{'contrato':self.contracts[0].pk})
        self.assertEqual(response.context['rows'][0]['reference'],125000)

    def test_4c_guarda_chuva_projetos_os_separados_sem_teto_unico(self):
        self.contracts[0].guarda_chuva=True;self.contracts[0].save()
        self.order.cod_projeto=self.projects[1];self.order.save()
        self.bm(os=True,value='2000');self.bm(value='3000')
        response=self.client.get(self.url('orcamento_financeiro'),{'contrato':self.contracts[0].pk,'projeto':self.projects[1].pk})
        self.assertEqual(response.context['rows'][0]['stats']['medido'],2000)
        self.assertEqual(response.context['rows'][0]['stats']['previsto'],350)
        self.assertContains(response,'Guarda-chuva: conferir por OS/projeto')

    def test_4c_centro_m2m_nao_multiplica_medicao_ou_planejamento(self):
        center=m.CentroDeTrabalho.objects.create(codigo='F4',nome='Centro F4')
        other_center=m.CentroDeTrabalho.objects.create(codigo='F4B',nome='Outro centro')
        self.coord.centros.add(center,other_center)
        self.order.coordenador=self.coord;self.order.save()
        self.contracts[0].coordenadores.add(self.coord)
        self.projects[0].coordenadores.add(self.coord)
        self.nf(self.bm(value='1000'))
        self.nf(self.bm(os=True,value='500'))
        response=self.client.get(self.url('orcamento_financeiro'),{'centro':center.pk})
        self.assertEqual(len(response.context['rows']),1)
        self.assertEqual(response.context['rows'][0]['stats']['medido'],1500)
        self.assertEqual(response.context['rows'][0]['stats']['previsto'],60350)
        self.assertEqual(self.client.get(self.url(),{'centro':center.pk}).context['totals']['count'],2)

    def test_4c_posicao_sem_dados_e_limites_informativos(self):
        response=self.client.get(self.url('orcamento_financeiro'))
        self.assertEqual(response.context['rows'][0]['stats']['medido'],0)
        self.assertNotContains(response,'Saldo contratual:')
        self.bm(value='999999')
        self.assertContains(self.client.get(self.url('orcamento_financeiro')),'Medição superior ao planejamento')

    def test_4b_correcao_sem_trocar_comprovante_nao_reabre_arquivo_antigo(self):
        from unittest.mock import patch
        from .test_auditoria import pdf
        from .forms import NFForm
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'))
        nf.comprovante_pagamento=pdf();nf.save();nf.refresh_from_db()
        data=dict(bm=nf.bm_id,valor_pago='50,00',parcela_paga=1,data_pagamento='2026-11-15')
        with patch.object(nf.comprovante_pagamento.storage,'open',wraps=nf.comprovante_pagamento.storage.open) as opened:
            self.assertTrue(NFForm(data,instance=nf,evento=nf.evento,user=self.supply).is_valid())
            opened.assert_not_called()

    def test_4d_central_liga_conferencia_e_detalhes_existentes(self):
        nf=self.nf(self.bm())
        response=self.client.get(self.url())
        row=response.context['rows'][0]
        self.assertContains(response,row['bm_url'])
        self.assertContains(response,row['history_url'])
        self.assertEqual(self.client.get(row['diagnostic_url']).status_code,200)
        self.assertContains(self.client.get(reverse('contrato_fornecedor_detalhe',args=[nf.contrato_id])),'Contas a Pagar deste contrato')

    def test_4d_consultas_nao_corrigem_acumulado_ou_criam_auditoria(self):
        nf=self.nf(self.bm())
        m.Evento.objects.filter(pk=nf.evento_id).update(valor_pago=999)
        count=m.RegistroAuditoria.objects.count()
        for name in ('contas_a_pagar','pagamentos_financeiros','orcamento_financeiro','conferencia_financeira'):
            self.assertEqual(self.client.get(self.url(name)).status_code,200)
        self.assertEqual(m.RegistroAuditoria.objects.count(),count)
        self.assertEqual(m.Evento.objects.get(pk=nf.evento_id).valor_pago,999)

    def test_4e_meses_distintos_nf_paga_sem_somar_acumulado_da_origem(self):
        bm=self.bm(operational='aprovado',director='aprovado')
        self.nf(bm,value='20',paid=True);self.nf(bm,value='30',paid=True,day=date(2026,12,1))
        m.Evento.objects.filter(pk=bm.evento_id).update(valor_pago=999)
        projection=fo.monthly_projection(self.finance,{'historico':True})
        rows={r['month']:r for r in projection['rows']}
        self.assertEqual(rows[date(2026,11,1)]['paid'],20)
        self.assertEqual(rows[date(2026,12,1)]['paid'],30)
        self.assertEqual(projection['totals']['planned'],100350)

    def test_4e_nf_nao_paga_usa_planejamento_origem_nao_data_nf(self):
        self.nf(self.bm(operational='aprovado',director='aprovado'),value='77',day=date(2030,1,1))
        projection=fo.monthly_projection(self.finance,{'historico':True})
        rows={r['month']:r for r in projection['rows']}
        self.assertEqual(rows[None]['authorized_unpaid'],77)
        self.assertNotIn(date(2030,1,1),rows)
        self.assertEqual(projection['totals']['paid'],0)

    def test_4e_data_ausente_explicita_inclusive_com_periodo(self):
        m.Evento.objects.filter(pk=self.events[0].pk).update(data_prevista_pagamento=None)
        self.nf(self.bm(operational='aprovado',director='aprovado'),value='77')
        projection=fo.monthly_projection(self.finance,{'data_inicial':date(2027,1,1),'data_limite':date(2027,12,31)})
        unknown=next(r for r in projection['rows'] if r['month'] is None)
        self.assertEqual(unknown['planned'],60000)
        self.assertEqual(unknown['authorized_unpaid'],77)

    def test_4e_filtro_periodo_e_outro_contrato_nao_vazam_valores(self):
        a=self.bm(operational='aprovado',director='aprovado');b=self.bm(index=1)
        self.nf(a,value='10',paid=True);self.nf(b,value='999',paid=True)
        self.nf(a,value='20',paid=True,day=date(2027,1,1))
        projection=fo.monthly_projection(self.finance,{'contrato':self.contracts[0],'data_inicial':date(2026,11,1),'data_limite':date(2026,11,30)})
        self.assertEqual(projection['totals']['paid'],10)
        self.assertEqual(projection['totals']['planned'],60350)

    def test_4e_pagina_plotly_carregada_uma_vez_e_previsao_antiga_preservada(self):
        from plotly.offline import get_plotlyjs_version
        response=self.client.get(self.url('planejamento_mensal'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.content.count(b'https://cdn.plot.ly/plotly-'),1)
        self.assertContains(response,f'https://cdn.plot.ly/plotly-{get_plotlyjs_version()}.min.js')
        self.assertContains(response,reverse('previsao_pagamentos'))
        self.assertLess(len(response.content),500000)

    def test_4e_sem_dados_nao_cria_grafico_artificial(self):
        m.Evento.objects.all().delete();m.OS.objects.all().delete()
        response=self.client.get(self.url('planejamento_mensal'))
        self.assertContains(response,'Nenhum valor encontrado.')
        self.assertNotContains(response,'https://cdn.plot.ly/plotly-')

    def test_4e_perfis_e_ids_nao_burlam_leitura_global(self):
        for name in ('orcamento_financeiro','planejamento_mensal'):
            self.client.force_login(self.leader)
            self.assertEqual(self.client.get(self.url(name),{'contrato':self.contracts[0].pk}).status_code,403)
            self.client.force_login(self.finance)
            self.assertEqual(self.client.post(self.url(name)).status_code,405)

    def report(self,kind,filters=None):
        from io import BytesIO
        from openpyxl import load_workbook
        response=self.client.get(reverse('relatorio_operacional',args=[kind]),filters or {})
        self.assertEqual(response.status_code,200,response.content[:300])
        return response,load_workbook(BytesIO(response.content))

    def test_4f_contas_exportadas_mesmo_filtro_e_datas_numeros_tipados(self):
        nf=self.nf(self.bm());nf.numero_nf='000123';nf.data_emissao=date(2026,11,1);nf.save()
        self.nf(self.bm(index=1),value='999')
        response,book=self.report('contas',{'contrato':nf.contrato_id})
        sheet=book['Contas a pagar']
        self.assertEqual(sheet.max_row,2)
        self.assertEqual(sheet.cell(2,3).value,'000123')
        self.assertEqual(sheet.cell(2,10).value,50)
        self.assertIn('R$',sheet.cell(2,10).number_format)
        self.assertEqual(sheet.cell(2,11).value.date(),date(2026,11,1))
        self.assertEqual(response['Cache-Control'],'private, no-store')

    def test_4f_pagamentos_incluem_em_revisao_e_autor_confiavel(self):
        from .financial_audit import financial_audit_context
        with financial_audit_context(self.finance):nf=self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        m.BM.objects.filter(pk=nf.bm_id).update(aprovacao_pagamento='pendente')
        self.nf(self.bm())
        _,book=self.report('pagamentos')
        sheet=book['Pagamentos']
        self.assertEqual(sheet.max_row,2)
        self.assertEqual(sheet.cell(2,14).value,'Exige conferência')
        self.assertEqual(sheet.cell(2,17).value,self.finance.get_full_name() or self.finance.username)

    def test_4f_contratos_exportam_mesmas_diferencas(self):
        self.nf(self.bm(value='100'),value='60',paid=True)
        _,book=self.report('contratos',{'contrato':self.contracts[0].pk})
        values=[c.value for c in book['Posição contratual'][2]]
        self.assertEqual(values[5:12],[100,0,60,60,0,40,60250])

    def test_4f_mensal_exporta_totais_fornecedor_projeto(self):
        self.nf(self.bm(operational='aprovado',director='aprovado'),value='25',paid=True)
        _,book=self.report('mensal',{'contrato':self.contracts[0].pk})
        self.assertEqual(book.sheetnames,['Mensal','Fornecedor e projeto','Critérios'])
        self.assertEqual(book['Mensal'].cell(2,3).value,25)
        self.assertEqual(sum(book['Fornecedor e projeto'].cell(r,5).value for r in range(2,book['Fornecedor e projeto'].max_row+1)),25)

    def test_4f_formula_injection_em_todos_relatorios(self):
        self.supplier.nome='  =HYPERLINK("http://invalido")';self.supplier.save()
        self.contracts[0].num_contrato='+2+2';self.contracts[0].save()
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        from .financial_audit import financial_audit_context
        with financial_audit_context(self.supply,'Identificação fiscal sintética'):
            nf.numero_nf='@formula';nf.save()
        for kind in ('contas','pagamentos','contratos','mensal'):
            _,book=self.report(kind)
            dangerous=[]
            for sheet in book:
                for row in sheet:
                    for cell in row:
                        self.assertNotEqual(cell.data_type,'f')
                        if isinstance(cell.value,str) and 'HYPERLINK' in cell.value:dangerous.append(cell.value)
            self.assertTrue(dangerous,kind)
            self.assertTrue(all(value.startswith("'") for value in dangerous))

    def test_4f_limites_nao_entregam_exportacao_parcial(self):
        from unittest.mock import patch
        from .financial_exports import export_report
        from .financial_forms import OperationalFilterForm
        form=OperationalFilterForm({'historico':'on'},user=self.finance);self.assertTrue(form.is_valid())
        with patch('gestao_contratos.financial_exports.fo.accounts_query') as query:
            query.return_value.count.return_value=10001
            with self.assertRaises(fo.ProjectionLimit):export_report(self.finance,'contas',form)
        with patch('gestao_contratos.financial_exports.fo.budget_contracts') as query:
            query.return_value.count.return_value=1001
            with self.assertRaises(fo.ProjectionLimit):export_report(self.finance,'contratos',form)

    def test_4f_exportacoes_invalidas_e_sem_dados_bancarios(self):
        self.nf(self.bm())
        self.assertEqual(self.client.get(reverse('relatorio_operacional',args=['invalido'])).status_code,400)
        self.assertEqual(self.client.get(reverse('relatorio_operacional',args=['contas']),{'situacao':'invalida'}).status_code,400)
        for kind in ('contas','pagamentos','contratos','mensal'):
            _,book=self.report(kind)
            titles=[str(cell.value).lower() for sheet in book for cell in sheet[1]]
            self.assertFalse(any('banco' in title or 'agência' in title or 'pix' in title for title in titles))

    def test_4g_matriz_de_permissoes_paginas_e_relatorios(self):
        pages=[self.url(n) for n in ('contas_a_pagar','pagamentos_financeiros','orcamento_financeiro','planejamento_mensal')]
        pages+=[reverse('relatorio_operacional',args=[kind]) for kind in ('contas','pagamentos','contratos','mensal')]
        for role in ('financeiro','suprimento','diretoria','gerente_contrato'):
            self.client.force_login(self.create_user('final_'+role,role))
            for url in pages:self.assertEqual(self.client.get(url).status_code,200,(role,url))
        for user in (self.leader,self.coord,self.other):
            self.client.force_login(user)
            for url in pages:self.assertEqual(self.client.get(url,{'contrato':self.contracts[0].pk}).status_code,403)
        self.client.logout()
        for url in pages:self.assertEqual(self.client.get(url).status_code,302)

    def test_4g_custo_posicao_constante_com_mais_contratos(self):
        with CaptureQueriesContext(connection) as small:self.client.get(self.url('orcamento_financeiro'))
        for i in range(5):self.create_supplier_contract(cod_projeto=self.projects[0],empresa_terceira=self.supplier,num_contrato=f'EX-{i}')
        with CaptureQueriesContext(connection) as large:self.client.get(self.url('orcamento_financeiro'))
        self.assertEqual(len(small),len(large))
        self.assertLess(len(large),40)
