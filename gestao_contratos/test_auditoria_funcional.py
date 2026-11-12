"""Regressões funcionais comprovadas; somente fixtures e serviços de teste."""
from decimal import Decimal
from django.urls import reverse
from . import models as m
from .forms import ContratoFornecedorForm
from . import test_financeiro_fase2 as fixtures
from .tests import BaseUserTestCase


class AuditoriaFuncionalTests(BaseUserTestCase):
    setUp = fixtures.FinanceiroFase2Tests.setUp

    def prospect(self):
        source = m.SolicitacaoProspeccao.objects.create(contrato=self.projects[0],
            lider_contrato=self.leader, coordenador=self.coord, descricao='Auditoria sintética',status='Em análise')
        source.fornecedores_selecionados.add(self.supplier)
        return source

    def test_endpoints_ajax_rejeitam_get_sem_gravar(self):
        self.client.force_login(self.supply)
        for route,model in [('add_contrato',m.Contrato),('cadastrar_fornecedor',m.EmpresaTerceira)]:
            with self.subTest(route=route):
                before=list(model.objects.values())
                response=self.client.get(reverse(route))
                self.assertEqual(response.status_code,405)
                self.assertEqual(list(model.objects.values()),before)

    def test_valor_contrato_ptbr_e_canonico_preservam_centavos(self):
        for value,expected in [('1.234,56','1234.56'),('1234.56','1234.56'),('0,00','0'),('','0')]:
            with self.subTest(value=value):
                form=ContratoFornecedorForm(dict(cod_projeto=self.projects[0].pk,
                    empresa_terceira=self.supplier.pk,objeto='Sintético',status='ativo',valor_total=value))
                self.assertTrue(form.is_valid(),form.errors)
                self.assertEqual(form.cleaned_data['valor_total'],None if value=='' else Decimal(expected))
        for value in ['inválido','NaN','Infinity','1234567890123,00','-1,00','0,001']:
            with self.subTest(invalid=value):
                form=ContratoFornecedorForm(dict(cod_projeto=self.projects[0].pk,
                    empresa_terceira=self.supplier.pk,objeto='Sintético',status='ativo',valor_total=value))
                self.assertFalse(form.is_valid())

    def test_propostas_get_renderiza_sem_criar_registros(self):
        source=self.prospect(); self.client.force_login(self.supply)
        response=self.client.get(reverse('propostas_fornecedores',args=[source.pk]))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'form-TOTAL_FORMS')
        self.assertContains(response,self.supplier.nome,html=False)
        self.assertEqual(m.PropostaFornecedor.objects.filter(solicitacao=source).count(),0)

    def test_propostas_post_persiste_valores_e_identidade_e_reenvio(self):
        source=self.prospect(); self.client.force_login(self.supply)
        url=reverse('propostas_fornecedores',args=[source.pk])
        response=self.client.get(url)
        formset=response.context['formset']
        payload={f'form-{key}':value for key,value in formset.management_form.initial.items()}
        for i,form in enumerate(formset.forms):
            for key in form.fields:
                value=form.initial.get(key,'')
                payload[f'form-{i}-{key}']=getattr(value,'pk',value) or ''
            payload[f'form-{i}-valor_proposta']='123.45'
            payload[f'form-{i}-condicao_pagamento']='A definir'
            payload[f'form-{i}-fornecedor_identidade']=form.instance.fornecedor_id
        response=self.client.post(url,payload)
        self.assertEqual(response.status_code,302)
        proposal=m.PropostaFornecedor.objects.get(solicitacao=source)
        self.assertEqual(proposal.fornecedor_id,self.supplier.pk)
        self.assertEqual(proposal.valor_proposta,Decimal('123.45'))
        self.client.post(url,payload)
        self.assertEqual(m.PropostaFornecedor.objects.filter(solicitacao=source).count(),1)
        response=self.client.get(url)
        existing=response.context['formset']
        payload={f'form-{key}':value for key,value in existing.management_form.initial.items()}
        payload.update({'form-0-id':proposal.pk,'form-0-solicitacao':source.pk,
            'form-0-fornecedor_identidade':self.supplier.pk,'form-0-valor_proposta':'234.56',
            'form-0-condicao_pagamento':'A definir'})
        self.assertEqual(self.client.post(url,payload).status_code,302)
        proposal.refresh_from_db()
        self.assertEqual((proposal.solicitacao_id,proposal.fornecedor_id,proposal.valor_proposta),
            (source.pk,self.supplier.pk,Decimal('234.56')))

    def test_duplicar_os_reenvio_nao_repete_e_nova_intencao_permite(self):
        self.client.force_login(self.supply)
        detail=reverse('detalhes_os',args=[self.order.pk])
        url=reverse('duplicar_os_cadastrada',args=[self.order.pk])
        response=self.client.get(detail)
        payload={'submission_token':response.context['duplicate_submission_token']}
        before=m.OS.objects.count()
        for _ in range(2):self.client.post(url,payload)
        self.assertEqual(m.OS.objects.count(),before+1)
        response=self.client.get(detail)
        self.client.post(url,{'submission_token':response.context['duplicate_submission_token']})
        self.assertEqual(m.OS.objects.count(),before+2)

    def test_propostas_financeiro_e_lider_de_outro_projeto_nao_gravam(self):
        source=self.prospect()
        for user in [self.finance,self.other]:
            self.client.force_login(user)
            response=self.client.post(reverse('propostas_fornecedores',args=[source.pk]),{})
            self.assertIn(response.status_code,[302,403,404])
            self.assertFalse(m.PropostaFornecedor.objects.filter(solicitacao=source).exists())

    def test_propostas_post_invalido_nao_cria_placeholder(self):
        source=self.prospect(); self.client.force_login(self.supply)
        response=self.client.post(reverse('propostas_fornecedores',args=[source.pk]),{
            'form-TOTAL_FORMS':1,'form-INITIAL_FORMS':0,'form-0-valor_proposta':'inválido',
            'form-0-fornecedor_identidade':self.supplier.pk})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.context['formset'].errors)
        self.assertFalse(m.PropostaFornecedor.objects.filter(solicitacao=source).exists())

    def test_propostas_id_forjado_nao_altera_outra_solicitacao(self):
        source=self.prospect(); other=self.prospect()
        own=m.PropostaFornecedor.objects.create(solicitacao=source,fornecedor=self.supplier,valor_proposta=10)
        foreign=m.PropostaFornecedor.objects.create(solicitacao=other,fornecedor=self.supplier,valor_proposta=20)
        self.client.force_login(self.supply)
        self.client.post(reverse('propostas_fornecedores',args=[source.pk]),{
            'form-TOTAL_FORMS':1,'form-INITIAL_FORMS':1,'form-0-id':foreign.pk,
            'form-0-solicitacao':other.pk,'form-0-valor_proposta':'999'})
        own.refresh_from_db();foreign.refresh_from_db()
        self.assertEqual((own.valor_proposta,foreign.valor_proposta),(10,20))

    def test_propostas_formulario_antigo_nao_transfere_valor_para_outro_fornecedor(self):
        source=self.prospect(); other=self.create_supplier(nome='Outro fornecedor sintético')
        self.client.force_login(self.supply)
        url=reverse('propostas_fornecedores',args=[source.pk])
        self.client.get(url)
        source.fornecedores_selecionados.set([other])
        response=self.client.post(url,{'form-TOTAL_FORMS':1,'form-INITIAL_FORMS':0,
            'form-0-valor_proposta':'123.45','form-0-fornecedor_identidade':self.supplier.pk})
        self.assertEqual(response.status_code,409)
        self.assertFalse(m.PropostaFornecedor.objects.filter(solicitacao=source).exists())

    def test_elaboracao_contrato_nao_expoe_propostas_ao_fornecedor_ou_outro_projeto(self):
        sources=[]
        for project,leader in zip(self.projects,[self.leader,self.other]):
            sources.append(m.SolicitacaoProspeccao.objects.create(contrato=project,
                lider_contrato=leader,fornecedor_escolhido=self.supplier,
                aprovacao_fornecedor_gerente='aprovado',status='Fornecedor aprovado',descricao='Confidencial sintético'))
            m.PropostaFornecedor.objects.create(solicitacao=sources[-1],fornecedor=self.supplier,valor_proposta='8765.43')
        external=self.create_user('audit_supplier_external','fornecedor')
        url=reverse('elaboracao_contrato')
        self.client.force_login(external)
        response=self.client.get(url)
        with self.subTest(role='fornecedor'):
            self.assertEqual(response.status_code,403)
            self.assertNotContains(response,'8.765,43',status_code=403)
        admin=self.create_user('audit_scope_admin','');admin.is_superuser=True;admin.save()
        for user,expected in [(self.leader,[sources[0].pk]),(self.coord,[sources[0].pk]),(self.other,[sources[1].pk]),
            (self.supply,[s.pk for s in sources]),(self.finance,[s.pk for s in sources]),(admin,[s.pk for s in sources])]:
            with self.subTest(role=user.grupo,user=user.pk):
                self.client.force_login(user)
                response=self.client.get(url)
                self.assertEqual([item['solicitacao'].pk for item in response.context['lista_solicitacoes']],expected)
