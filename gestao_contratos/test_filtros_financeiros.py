"""Dependências do painel, com dados sintéticos e API exclusiva do Financeiro."""
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import models as m
from . import test_financeiro_fase2 as fixtures
from .forms import FiltroFinanceiroForm
from .tests import BaseUserTestCase


class FiltrosFinanceirosTests(BaseUserTestCase):
    bm = fixtures.FinanceiroFase2Tests.bm
    nf = fixtures.FinanceiroFase2Tests.nf
    def setUp(self):
        fixtures.FinanceiroFase2Tests.setUp(self)
        self.coord2=self.create_user('filtros_coord2','coordenador')
        self.supplier2=self.create_supplier(nome='Fornecedor do segundo coordenador')
        self.projects[1].coordenador=self.coord2; self.projects[1].save()
        self.contracts[1].coordenador=self.coord2
        self.contracts[1].empresa_terceira=self.supplier2; self.contracts[1].save()
        self.leader2=self.create_user('filtros_lider2','gerente_contrato')
        self.projects[1].lider_contrato=self.leader2; self.projects[1].save()
        self.contracts[1].lider_contrato=self.leader2; self.contracts[1].save()
        self.url=reverse('opcoes_filtros_financeiros')

    def ids(self,response,key):
        self.assertEqual(response.status_code,200,response.content)
        return [int(option['value']) for option in response.json()['options'][key]]

    def test_sem_selecao_mostra_opcoes_globais(self):
        response=self.client.get(self.url)
        self.assertCountEqual(self.ids(response,'fornecedor'),[self.supplier.pk,self.supplier2.pk])
        self.assertCountEqual(self.ids(response,'projeto'),[p.pk for p in self.projects])
        self.assertCountEqual(self.ids(response,'contrato'),[c.pk for c in self.contracts])

    def test_lider_restringe_fornecedor_projeto_e_contrato_sem_exigir_bm_nf(self):
        response=self.client.get(self.url,{'lider_contrato':self.leader.pk})
        self.assertEqual(self.ids(response,'fornecedor'),[self.supplier.pk])
        self.assertEqual(self.ids(response,'projeto'),[self.projects[0].pk])
        self.assertEqual(self.ids(response,'contrato'),[self.contracts[0].pk])
        self.assertFalse(m.BM.objects.exists()); self.assertFalse(m.NF.objects.exists())

    def test_fornecedor_restringe_projetos_e_contratos(self):
        response=self.client.get(self.url,{'fornecedor':self.supplier2.pk})
        self.assertEqual(self.ids(response,'projeto'),[self.projects[1].pk])
        self.assertEqual(self.ids(response,'contrato'),[self.contracts[1].pk])

    def test_projeto_restringe_contratos(self):
        response=self.client.get(self.url,{'projeto':self.projects[0].pk})
        self.assertEqual(self.ids(response,'contrato'),[self.contracts[0].pk])

    def test_coordenador_m2m_legado_nao_duplica_opcoes(self):
        from .financial_queries import financial_filter_choices
        self.contracts[1].coordenadores.add(self.coord,self.coord2)
        self.projects[1].coordenadores.add(self.coord,self.coord2)
        choices=financial_filter_choices(coordinator=self.coord.pk)
        self.assertCountEqual(list(choices['fornecedor']),[self.supplier,self.supplier2])
        self.assertEqual(choices['contrato'].count(),2)
        self.contracts[1].coordenadores.remove(self.coord)
        choices=financial_filter_choices(coordinator=self.coord.pk)
        self.assertIn(self.supplier2,choices['fornecedor'])

    def test_lider_da_os_e_projeto_da_os_seguem_escopo_financeiro(self):
        leader=self.create_user('filtros_os_lider','gerente_lider')
        self.order.lider_contrato=leader; self.order.cod_projeto=self.projects[1]; self.order.save()
        response=self.client.get(self.url,{'lider_contrato':leader.pk})
        self.assertEqual(self.ids(response,'fornecedor'),[self.supplier.pk])
        self.assertEqual(self.ids(response,'projeto'),[self.projects[1].pk])
        self.assertEqual(self.ids(response,'contrato'),[self.contracts[0].pk])
        response=self.client.get(self.url,{'lider_contrato':leader.pk,'projeto':self.projects[1].pk,'contrato':self.contracts[0].pk})
        self.assertEqual(response.status_code,200)

    def test_lider_sem_vinculos_tem_opcoes_vazias(self):
        leader=self.create_user('filtros_sem_vinculo','gerente_lider')
        response=self.client.get(self.url,{'lider_contrato':leader.pk})
        for key in ('fornecedor','projeto','contrato'): self.assertEqual(self.ids(response,key),[])

    def test_combinacoes_incompativeis_sao_recusadas_na_api_e_no_painel(self):
        for params,field in (({'lider_contrato':self.leader.pk,'fornecedor':self.supplier2.pk},'fornecedor'),
            ({'fornecedor':self.supplier.pk,'projeto':self.projects[1].pk},'projeto'),
            ({'projeto':self.projects[0].pk,'contrato':self.contracts[1].pk},'contrato')):
            with self.subTest(params=params):
                response=self.client.get(self.url,params)
                self.assertEqual(response.status_code,400); self.assertIn(field,response.json()['errors'])
                response=self.client.get(reverse('painel_financeiro'),params | {'historico':'on'})
                self.assertEqual(response.status_code,200)
                self.assertNotIn('financial_stats',response.context)
                self.assertIn(field,response.context['financial_form'].errors)

    def test_ids_invalidos_nao_causam_erro_de_servidor(self):
        for value in ('inválido','-1','99999999999999999999999999999999999999'):
            for key in ('lider_contrato','fornecedor','projeto','contrato'):
                with self.subTest(value=value,key=key): self.assertEqual(self.client.get(self.url,{key:value}).status_code,400)

    def test_formulario_renderizado_e_recarregado_mantem_selecao_compativel(self):
        params={'historico':'on','lider_contrato':self.leader.pk,'fornecedor':self.supplier.pk,'projeto':self.projects[0].pk,'contrato':self.contracts[0].pk}
        response=self.client.get(reverse('painel_financeiro'),params)
        form=response.context['financial_form']
        self.assertFalse(form.errors)
        self.assertEqual(form.cleaned_data['contrato'],self.contracts[0])
        self.assertEqual(list(form.fields['fornecedor'].queryset),[self.supplier])
        self.assertContains(response,'data-financial-filters-url="'+self.url+'"')
        self.assertContains(response,'filtros_financeiro.js')
        self.assertEqual(str(form['projeto'].value()),str(self.projects[0].pk))

    def test_endpoint_exclusivo_anonimo_e_metodos(self):
        self.assertEqual(self.client.post(self.url).status_code,405)
        for user in (self.supply,self.leader,self.coord,self.create_user('filtros_dir','diretoria'),self.create_user('filtros_gc','gerente_contrato')):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code,403)
        self.supply.is_superuser=True; self.supply.save(); self.client.force_login(self.supply)
        self.assertEqual(self.client.get(self.url).status_code,403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code,302)

    def test_pendencias_de_outros_perfis_preservam_formulario_anterior(self):
        self.client.force_login(self.supply)
        response=self.client.get(reverse('pendencias_financeiras'),{'historico':'on'})
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'data-financial-filters-url=')
        self.assertFalse(response.context['financial_form'].dynamic_choices)

    def test_numero_consultas_constante_ao_aumentar_opcoes(self):
        self.client.get(self.url)
        with CaptureQueriesContext(connection) as initial: self.client.get(self.url,{'lider_contrato':self.leader.pk})
        for i in range(8):
            project=self.create_contract(codigo='FD-'+str(i),coordenador=self.coord,lider_contrato=self.leader)
            self.create_supplier_contract(cod_projeto=project,empresa_terceira=self.supplier,coordenador=self.coord,lider_contrato=self.leader,num_contrato='FD-C'+str(i))
        with CaptureQueriesContext(connection) as many: self.client.get(self.url,{'lider_contrato':self.leader.pk})
        self.assertEqual(len(initial),len(many)); self.assertLess(len(many),12)

    def test_opcoes_nao_calculam_painel_nem_gravam_dados(self):
        before=list(m.ContratoTerceiros.objects.order_by('pk').values())
        with patch('gestao_contratos.views.build_financial_dashboard_context',side_effect=AssertionError('API somente de opções')):
            self.assertEqual(self.client.get(self.url,{'lider_contrato':self.leader.pk}).status_code,200)
        self.assertEqual(before,list(m.ContratoTerceiros.objects.order_by('pk').values()))

    def test_titulo_e_opcoes_apenas_dos_tres_grupos_de_lideranca(self):
        combined=self.create_user('filtros_gerente_lider','gerente_lider')
        response=self.client.get(reverse('painel_financeiro'),{'historico':'on'})
        form=response.context['financial_form']
        self.assertEqual(form.fields['lider_contrato'].label,'Líder de Contrato (opcional)')
        self.assertNotIn('coordenador',form.fields)
        allowed=set(m.User.objects.filter(grupo__in=['lider_contrato','gerente_contrato','gerente_lider']).values_list('pk',flat=True))
        self.assertSetEqual(set(form.fields['lider_contrato'].queryset.values_list('pk',flat=True)),allowed)
        for user in (self.leader,self.leader2,combined):
            self.assertEqual(self.client.get(self.url,{'lider_contrato':user.pk}).status_code,200)
        self.assertNotIn(self.coord.pk,allowed)

    def test_grupos_nao_permitidos_recusados_mesmo_em_requisicao_manual(self):
        for user in (self.coord,self.finance,self.supply,self.create_user('filtros_gerente_simples','gerente'),self.create_user('filtros_fornecedor','fornecedor')):
            with self.subTest(group=user.grupo):
                self.assertEqual(self.client.get(self.url,{'lider_contrato':user.pk}).status_code,400)
                response=self.client.get(reverse('painel_financeiro'),{'historico':'on','lider_contrato':user.pk})
                self.assertIn('lider_contrato',response.context['financial_form'].errors)
                self.assertNotIn('financial_stats',response.context)

    def test_links_antigos_nao_perdem_filtro_silenciosamente(self):
        invalid=self.client.get(reverse('painel_financeiro'),{'historico':'on','coordenador':self.coord.pk})
        self.assertIn('lider_contrato',invalid.context['financial_form'].errors)
        self.assertNotIn('financial_stats',invalid.context)
        response=self.client.get(reverse('painel_financeiro'),{'historico':'on','coordenador':self.leader.pk})
        self.assertEqual(response.context['financial_form'].cleaned_data['lider_contrato'],self.leader)
        for queue in response.context['financial_queues']:
            self.assertIn('lider_contrato=',queue['url']); self.assertNotIn('coordenador=',queue['url'])

    def test_valores_e_filas_filtram_lideranca_sem_misturar_outro_lider(self):
        self.nf(self.bm(value='1000'),value='50')
        self.nf(self.bm(index=1,value='2000'),value='90')
        response=self.client.get(reverse('painel_financeiro'),{'historico':'on','lider_contrato':self.leader.pk})
        stats=response.context['financial_stats']
        self.assertEqual((stats['medido'],stats['faturado'],stats['previsto']),(1000,50,60350))
        queue=next(q for q in response.context['financial_queues'] if q['key']=='autorizacao')
        follow=self.client.get(queue['url'])
        self.assertEqual(follow.status_code,200)
        self.assertEqual(follow.context['financial_stats']['faturado'],50)
        self.assertEqual(follow.context['financial_form'].cleaned_data['lider_contrato'],self.leader)

    def test_lider_do_projeto_do_contrato_mantem_vinculo(self):
        self.contracts[0].lider_contrato=None; self.contracts[0].save()
        response=self.client.get(self.url,{'lider_contrato':self.leader.pk})
        self.assertEqual(self.ids(response,'fornecedor'),[self.supplier.pk])
        self.assertEqual(self.ids(response,'contrato'),[self.contracts[0].pk])

    def test_lider_do_projeto_da_os_filtra_opcoes_e_valores_da_os(self):
        leader=self.create_user('filtros_lider_projeto_os','gerente_lider')
        project=self.create_contract(codigo='FD-OS',lider_contrato=leader)
        self.order.lider_contrato=None; self.order.cod_projeto=project; self.order.save()
        self.nf(self.bm(os=True,value='25'),value='25')
        response=self.client.get(self.url,{'lider_contrato':leader.pk})
        self.assertEqual(self.ids(response,'fornecedor'),[self.supplier.pk])
        self.assertEqual(self.ids(response,'projeto'),[project.pk])
        response=self.client.get(reverse('painel_financeiro'),{'historico':'on','lider_contrato':leader.pk})
        stats=response.context['financial_stats']
        self.assertEqual((stats['previsto'],stats['medido'],stats['faturado']),(350,25,25))
