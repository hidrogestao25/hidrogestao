from datetime import date
from decimal import Decimal
from django.db import connection,transaction,IntegrityError
from django.db.models.deletion import ProtectedError
from django.core.exceptions import ValidationError,PermissionDenied
from django.urls import reverse
from . import models as m,payment_services as service,payment_queries as pq
from . import test_financeiro_fase2 as fixtures
from .tests import BaseUserTestCase


class FinanceiroFase5Tests(BaseUserTestCase):
    setUp=fixtures.FinanceiroFase2Tests.setUp
    bm=fixtures.FinanceiroFase2Tests.bm
    nf=fixtures.FinanceiroFase2Tests.nf

    def invoice(self,value='50000'):
        return self.nf(self.bm(value=value,operational='aprovado',director='aprovado'),value=value)

    def pay(self,nf,amount,key='primeiro',**kwargs):
        return service.record_payment(nf_id=nf.pk,user=self.finance,valor=amount,data_pagamento=date(2026,11,5),key=key,**kwargs)[0]

    def test_5c_tres_parciais_e_saldo_exato(self):
        nf=self.invoice()
        self.pay(nf,'20000');nf.refresh_from_db()
        self.assertEqual((nf.total_pago,nf.saldo_pendente,nf.financeiro_autorizou,nf.situacao_liquidacao),(20000,30000,False,'Parcialmente paga'))
        self.pay(nf,'10000','segundo');nf.refresh_from_db()
        self.assertEqual((nf.total_pago,nf.saldo_pendente),(30000,20000))
        self.pay(nf,'20000','terceiro');nf.refresh_from_db()
        self.assertEqual((nf.total_pago,nf.saldo_pendente,nf.financeiro_autorizou),(50000,0,True))
        self.assertEqual(nf.movimentos.count(),3)

    def test_5c_autorizacao_cada_nova_parcela_e_negacao_sem_evento(self):
        nf=self.invoice();self.pay(nf,'20000')
        m.BM.objects.filter(pk=nf.bm_id).update(aprovacao_pagamento='pendente')
        count=m.RegistroAuditoria.objects.count()
        with self.assertRaises(ValidationError):self.pay(nf,'10000','indevido')
        self.assertEqual(nf.movimentos.count(),1)
        self.assertEqual(m.RegistroAuditoria.objects.count(),count)

    def test_5c_limites_e_precisao(self):
        nf=self.invoice('1.00')
        for value in ('0','-1','1.001','NaN','2'):
            with self.assertRaises(ValidationError):self.pay(nf,value,value)
        for i in range(10):self.pay(nf,'.10',str(i))
        nf.refresh_from_db();self.assertEqual(nf.total_pago,Decimal('1.00'));self.assertTrue(nf.financeiro_autorizou)

    def test_5c_retry_idempotente_e_payload_divergente(self):
        nf=self.invoice();first=self.pay(nf,'20000')
        self.assertEqual(self.pay(nf,'20000').pk,first.pk)
        with self.assertRaises(ValidationError):self.pay(nf,'10000')
        self.assertEqual(nf.movimentos.count(),1)

    def test_5c_rollback_preserva_ledger_e_auditoria(self):
        nf=self.invoice();count=m.RegistroAuditoria.objects.count()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():self.pay(nf,'20000');raise RuntimeError('falha posterior')
        self.assertFalse(nf.movimentos.exists());self.assertEqual(m.RegistroAuditoria.objects.count(),count)

    def test_5h_estorno_parcial_total_e_financeiro_negado(self):
        nf=self.invoice();p=self.pay(nf,'20000')
        with self.assertRaises(PermissionDenied):service.reverse_payment(movement_id=p.pk,user=self.finance,valor=1,data_estorno=date(2026,11,6),motivo='x',key='negado')
        service.reverse_payment(movement_id=p.pk,user=self.supply,valor=5000,data_estorno=date(2026,11,6),motivo='Correção comprovada',key='e1')
        nf.refresh_from_db();self.assertEqual(nf.total_pago,15000)
        with self.assertRaises(ValidationError):service.reverse_payment(movement_id=p.pk,user=self.supply,valor=15001,data_estorno=date(2026,11,6),motivo='x',key='e2')
        service.reverse_payment(movement_id=p.pk,user=self.supply,valor=15000,data_estorno=date(2026,11,6),motivo='Reversão restante',key='e3')
        nf.refresh_from_db();self.assertEqual(nf.total_pago,0)

    def test_5c_movimento_imutavel_sql_e_queryset(self):
        nf=self.invoice();p=self.pay(nf,'20000')
        for action in (lambda:m.PagamentoNF.objects.filter(pk=p.pk).update(valor=1),lambda:m.PagamentoNF.objects.filter(pk=p.pk).delete()):
            with self.assertRaises(IntegrityError),transaction.atomic():action()
        with self.assertRaises(IntegrityError),transaction.atomic(),connection.cursor() as cursor:cursor.execute('UPDATE gestao_contratos_pagamentonf SET data_pagamento=%s WHERE id=%s',['2000-01-01',p.pk])

    def test_5d_programacao_nao_e_caixa_e_vinculo_explicito(self):
        nf=self.invoice('60000')
        p,_=service.schedule(nf_id=nf.pk,user=self.finance,valor=20000,data_prevista=date(2026,11,10),motivo='Programação acordada',key='p1')
        service.schedule(nf_id=nf.pk,user=self.finance,valor=20000,data_prevista=date(2026,12,10),motivo='Programação acordada',key='p2')
        state=pq.financial_state(nf)
        self.assertEqual((state['paid'],state['scheduled'],state['unscheduled']),(0,40000,20000))
        self.pay(nf,10000,programacao_id=p.pk)
        state=pq.financial_state(m.NF.objects.get(pk=nf.pk))
        self.assertEqual((state['paid'],state['scheduled'],state['unscheduled']),(10000,30000,20000))

    def test_5d_acordos_preservam_vencimento_original_e_sequencia(self):
        nf=self.invoice();nf.vencimento_original=date(2026,11,15);nf.save()
        first,_=service.renegotiate(nf_id=nf.pk,user=self.finance,novo_vencimento=date(2026,12,15),motivo='Acordo já formalizado',responsavel_acordo='Fornecedor e responsável',key='a1')
        second,_=service.renegotiate(nf_id=nf.pk,user=self.finance,novo_vencimento=date(2027,1,15),motivo='Segundo acordo',key='a2')
        self.assertEqual(first.vencimento_anterior,date(2026,11,15));self.assertEqual(second.vencimento_anterior,date(2026,12,15))
        nf.refresh_from_db();self.assertEqual(nf.vencimento_original,date(2026,11,15));self.assertEqual(pq.financial_state(nf)['due'],date(2027,1,15))

    def test_5d_acordo_de_parcela_revisa_sem_apagar(self):
        nf=self.invoice()
        p,_=service.schedule(nf_id=nf.pk,user=self.finance,valor=20000,data_prevista=date(2026,11,10),motivo='Programação inicial',key='p1')
        self.pay(nf,10000,programacao_id=p.pk)
        agreement,_=service.renegotiate(nf_id=nf.pk,user=self.finance,programacao_id=p.pk,novo_vencimento=date(2026,12,10),motivo='Prazo acordado',key='a1')
        new=pq.active_schedules(nf).get()
        self.assertEqual((new.substitui_id,new.liquidado_centavos,new.restante_centavos,new.acordo_id),(p.pk,1000000,1000000,agreement.pk))
        self.assertEqual(nf.programacoes.count(),2)

    def test_5h_cancelamento_reverte_sem_apagar_historia(self):
        nf=self.invoice();self.pay(nf,20000)
        service.cancel_invoice(nf_id=nf.pk,user=self.supply,motivo='Cancelamento autorizado')
        nf.refresh_from_db();self.assertIsNotNone(nf.cancelada_em);self.assertEqual(nf.total_pago,0);self.assertEqual(nf.movimentos.count(),2)
        with self.assertRaises(ValidationError):self.pay(nf,10000,'apos-cancelamento')

    def test_5f_indicadores_bm_contrato_e_saldo_usam_movimentos(self):
        from .financial_queries import FinancialData,financial_bms,eager_bms
        from .financial_reconciliation import with_bm_totals
        nf=self.invoice();self.pay(nf,20000);self.pay(nf,10000,'p2')
        data=FinancialData(self.finance,{'historico':True,'contrato':self.contracts[0]})
        stats=data.indicators()
        self.assertEqual((stats['faturado'],stats['pago'],stats['a_pagar']),(50000,30000,20000))
        self.assertEqual(data.indicators(by_contract=True)[nf.contrato_id]['pago'],30000)
        bm=eager_bms(with_bm_totals(financial_bms())).get(pk=nf.bm_id)
        self.assertEqual((bm.nf_billed,bm.nf_paid),(50000,30000))

    def test_5f_pagamento_em_outro_mes_nao_depende_da_data_nf(self):
        from .financial_queries import FinancialData
        from .financial_operations import monthly_projection
        nf=self.invoice();self.pay(nf,20000)
        service.record_payment(nf_id=nf.pk,user=self.finance,valor=10000,data_pagamento=date(2026,12,5),key='dezembro')
        filters=dict(data_inicial=date(2026,12,1),data_limite=date(2026,12,31))
        self.assertEqual(FinancialData(self.finance,filters).indicators()['pago'],10000)
        projection=monthly_projection(self.finance,filters)
        self.assertEqual(next(r for r in projection['rows'] if r['month']==date(2026,12,1))['paid'],10000)

    def test_5f_acordo_desloca_saldo_sem_alterar_pagamento_ocorrido(self):
        from .financial_operations import monthly_projection
        nf=self.invoice();nf.vencimento_original=date(2026,11,15);nf.save()
        payment=self.pay(nf,20000)
        service.renegotiate(nf_id=nf.pk,user=self.finance,novo_vencimento=date(2026,12,15),motivo='Prorrogação formal',key='acordo')
        rows={r['month']:r for r in monthly_projection(self.finance,{'historico':True})['rows']}
        self.assertEqual(rows[date(2026,12,1)]['authorized_unpaid'],30000)
        self.assertEqual(rows[date(2026,11,1)]['paid'],20000)
        payment.refresh_from_db();self.assertEqual(payment.data_pagamento,date(2026,11,5))

    def test_5e_central_e_detalhe_exibem_dimensoes_independentes(self):
        nf=self.invoice();self.pay(nf,20000)
        response=self.client.get(reverse('contas_a_pagar'),{'liquidacao':'parcial'})
        self.assertEqual(response.status_code,200)
        self.assertEqual([r['id'] for r in response.context['rows']],[nf.pk])
        self.assertContains(response,'Parcialmente paga')
        response=self.client.get(reverse('detalhe_nf',args=[nf.pk]))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Pagamentos e estornos confirmados')
        self.assertContains(response,'30.000,00')

    def test_5e_novo_endpoint_nao_edita_valor_fiscal_e_bloqueia_edicao_nf(self):
        nf=self.invoice()
        response=self.client.post(reverse('pagamento_nf',args=[nf.pk]),dict(valor='20.000,00',data_pagamento='2026-11-05',key='api1'),HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,200,response.content)
        nf.refresh_from_db();self.assertEqual(nf.valor_pago,50000);self.assertEqual(nf.total_pago,20000)
        self.assertEqual(self.client.post(reverse('editar_nf',args=[nf.pk]),{}).status_code,403)
        self.assertEqual(self.client.post(reverse('deletar_nf',args=[nf.pk]),{}).status_code,403)
        response=self.client.post(reverse('pagamento_nf',args=[nf.pk]),dict(valor='10.000,00',data_pagamento='2026-11-15',key='api2'),HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,200,response.content)

    def test_5e_comprovante_por_movimento_privado_e_contextual(self):
        from .test_auditoria import pdf
        nf=self.invoice();p=self.pay(nf,20000,comprovante=pdf())
        response=self.client.get(p.comprovante.url);self.assertEqual(response.status_code,200);response.close()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(p.comprovante.url).status_code,404)
        self.assertEqual(self.client.get(reverse('pagamento_nf',args=[nf.pk])).status_code,403)

    def test_5f_sem_vinculo_nao_abate_parcela_ambiguamente(self):
        from .financial_operations import monthly_projection
        nf=self.invoice()
        service.schedule(nf_id=nf.pk,user=self.finance,valor=50000,data_prevista=date(2026,12,15),motivo='Programação integral',key='prog')
        self.pay(nf,20000)
        state=pq.financial_state(m.NF.objects.get(pk=nf.pk))
        self.assertTrue(state['overprogrammed'])
        projection=monthly_projection(self.finance,{'historico':True})
        self.assertEqual(projection['totals']['review_balance'],30000)
        self.assertEqual(projection['totals']['scheduled'],0)

    def test_5g_concorrencia_arquivo_sqlite_e_conexoes_independentes(self):
        import subprocess,sys
        from pathlib import Path
        root=Path(__file__).resolve().parent.parent
        result=subprocess.run([sys.executable,'-B','-m','gestao_contratos.integration_checks','payments'],cwd=root,capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_5h_financeiro_permanece_bloqueado_apos_estorno_integral(self):
        nf=self.invoice();p=self.pay(nf,20000)
        service.reverse_payment(movement_id=p.pk,user=self.supply,valor=20000,data_estorno=date(2026,11,6),motivo='Correção integral',key='e')
        self.assertEqual(self.client.post(reverse('editar_nf',args=[nf.pk]),{}).status_code,403)
        self.pay(nf,10000,'nova-liquidacao');nf.refresh_from_db();self.assertEqual(nf.total_pago,10000)

    def test_5h_correcao_fiscal_nao_inventa_pagamento(self):
        from .financial_audit import financial_audit_context
        nf=self.invoice();self.pay(nf,50000)
        with financial_audit_context(self.supply,'Correção do valor fiscal'):
            nf.refresh_from_db();nf.valor_pago=60000;nf.save()
        nf.refresh_from_db();self.assertEqual((nf.total_pago,nf.saldo_pendente,nf.financeiro_autorizou),(50000,10000,False))
        with financial_audit_context(self.supply,'Correção insuficiente'),self.assertRaises(IntegrityError),transaction.atomic():
            m.NF.objects.filter(pk=nf.pk).update(valor_pago=40000)

    def test_5h_origem_congelada_e_exclusao_cascata_negada(self):
        from .financial_audit import financial_audit_context
        nf=self.invoice();self.pay(nf,20000)
        for change in ({'contrato_id':self.contracts[1].pk},{'bm_id':self.bm().pk}):
            with financial_audit_context(self.supply,'Correção'),self.assertRaises(IntegrityError),transaction.atomic():
                m.NF.objects.filter(pk=nf.pk).update(**change)
        with self.assertRaises((IntegrityError,ProtectedError)),transaction.atomic():m.NF.objects.filter(pk=nf.pk).delete()
        self.assertEqual(nf.movimentos.count(),1)

    def test_5b_suprimento_tambem_exige_ambas_aprovacoes(self):
        for operational,director in (('pendente','aprovado'),('reprovado','aprovado'),('aprovado','pendente')):
            nf=self.nf(self.bm(operational=operational,director=director))
            with self.assertRaises(ValidationError):service.record_payment(nf_id=nf.pk,user=self.supply,valor=10,data_pagamento=date(2026,11,5),key=str(nf.pk))
            self.assertFalse(nf.movimentos.exists())

    def test_5b_os_cancelada_bloqueia_liquidacao(self):
        nf=self.nf(self.bm(os=True,operational='aprovado',director='aprovado'))
        m.OS.objects.filter(pk=self.order.pk).update(status='cancelada')
        with self.assertRaises(ValidationError):self.pay(nf,10)

    def test_5b_sql_direto_exige_aprovacoes_e_saldo(self):
        from .financial_audit import financial_audit_context
        nf=self.invoice('10');self.pay(nf,6)
        for amount in ('5','0','-1','0.001'):
            with financial_audit_context(self.finance),self.assertRaises(IntegrityError),transaction.atomic():
                m.PagamentoNF.objects.create(nf=nf,valor=amount,tipo='pagamento',data_pagamento=date(2026,11,5),registrado_por=self.finance,chave_idempotencia=amount)
        m.BM.objects.filter(pk=nf.bm_id).update(aprovacao_pagamento='pendente')
        with financial_audit_context(self.finance),self.assertRaises(IntegrityError),transaction.atomic():
            m.PagamentoNF.objects.create(nf=nf,valor=1,tipo='pagamento',data_pagamento=date(2026,11,5),registrado_por=self.finance,chave_idempotencia='unauth')
        self.assertEqual(nf.movimentos.count(),1)

    def test_5d_tres_parcelas_revisao_cancelamento_e_limites(self):
        nf=self.invoice('60000');programs=[]
        for i in range(3):
            programs.append(service.schedule(nf_id=nf.pk,user=self.finance,valor=20000,data_prevista=[date(2026,11,10),date(2026,12,10),date(2027,1,10)][i],motivo='Três parcelas',key=str(i))[0])
        self.assertEqual(pq.financial_state(nf)['scheduled'],60000)
        with self.assertRaises(ValidationError):service.schedule(nf_id=nf.pk,user=self.finance,valor=1,data_prevista=date(2027,1,1),motivo='Excedente',key='excedente')
        old=programs[0]
        revised,_=service.schedule(nf_id=nf.pk,user=self.finance,valor=15000,data_prevista=date(2027,2,1),motivo='Revisão negociada',substitui_id=old.pk,key='revisao')
        with self.assertRaises(ValidationError):self.pay(nf,100,programacao_id=old.pk)
        self.pay(nf,5000,programacao_id=revised.pk)
        with self.assertRaises(ValidationError):service.schedule(nf_id=nf.pk,user=self.finance,valor=4999,data_prevista=date(2027,2,1),motivo='Abaixo do já pago',substitui_id=revised.pk,key='invalid')
        service.schedule(nf_id=nf.pk,user=self.finance,valor=15000,data_prevista=date(2027,2,1),motivo='Cancelada a previsão restante',substitui_id=revised.pk,cancelada=True,key='cancel')
        self.assertEqual(pq.financial_state(m.NF.objects.get(pk=nf.pk))['scheduled'],40000)
        self.assertEqual(nf.programacoes.count(),5)

    def test_5d_programacao_e_acordo_imutaveis_e_idempotentes(self):
        nf=self.invoice()
        values=dict(nf_id=nf.pk,user=self.finance,valor=10000,data_prevista=date(2026,12,15),motivo='Proposta formal',key='p')
        program,created=service.schedule(**values)
        self.assertTrue(created);self.assertEqual(service.schedule(**values),(program,False))
        agreement,_=service.renegotiate(nf_id=nf.pk,user=self.finance,novo_vencimento=date(2027,1,15),motivo='Acordo',key='a')
        for obj in (program,agreement):
            with self.assertRaises(ValidationError):obj.save()
            with self.assertRaises(IntegrityError),transaction.atomic():type(obj).objects.filter(pk=obj.pk).delete()
        self.assertEqual(nf.movimentos.count(),0)

    def test_5d_vencimento_original_desconhecido_e_imutavel(self):
        nf=self.invoice();self.assertIsNone(pq.financial_state(nf)['due'])
        nf.vencimento_original=date(2026,11,15);nf.save()
        with self.assertRaises((IntegrityError,ProtectedError)),transaction.atomic():m.NF.objects.filter(pk=nf.pk).update(vencimento_original=date(2026,12,15))

    def test_5d_acordo_parcial_nao_altera_demais_parcelas(self):
        nf=self.invoice();items=[]
        for i in range(2):items.append(service.schedule(nf_id=nf.pk,user=self.finance,valor=10000,data_prevista=date(2026,11,15),motivo='Inicial',key=str(i))[0])
        service.renegotiate(nf_id=nf.pk,user=self.finance,programacao_id=items[0].pk,novo_vencimento=date(2027,1,15),motivo='Apenas primeira parcela',key='a')
        self.assertEqual(set(pq.active_schedules(nf).values_list('data_prevista',flat=True)),{date(2026,11,15),date(2027,1,15)})
        self.assertIsNone(pq.financial_state(nf)['due'])

    def test_5g_matriz_escrita_endpoints_e_privacidade_acordo(self):
        from .test_auditoria import pdf
        nf=self.invoice();agreement,_=service.renegotiate(nf_id=nf.pk,user=self.finance,novo_vencimento=date(2027,1,15),motivo='Acordo formal',documento=pdf(),key='a')
        response=self.client.get(agreement.documento.url);self.assertEqual(response.status_code,200);response.close()
        for role in ('diretoria','gerente_contrato','lider_contrato','coordenador','gerente','gerente_lider','fornecedor'):
            actor=self.create_user('scope_'+role,role);self.client.force_login(actor)
            for endpoint in ('pagamento_nf','programacao_nf','acordo_nf'):
                for method in ('get','post'):self.assertEqual(getattr(self.client,method)(reverse(endpoint,args=[nf.pk]),{}).status_code,403,(role,endpoint,method))
            if role not in ('diretoria','gerente_contrato'):self.assertEqual(self.client.get(agreement.documento.url).status_code,404)

    def test_5f_relatorios_antigos_usam_datas_dos_movimentos(self):
        from .views import calculate_contract_payment_totals,calculate_annual_contract_execution_totals
        nf=self.invoice();self.pay(nf,20000)
        service.record_payment(nf_id=nf.pk,user=self.finance,valor=10000,data_pagamento=date(2026,12,5),key='dez')
        m.Evento.objects.filter(pk=nf.evento_id).update(valor_pago=999999,data_pagamento=date(2027,1,1))
        self.assertEqual(calculate_contract_payment_totals([nf.contrato])['valor_pago'],30000)
        self.assertEqual(calculate_annual_contract_execution_totals([nf.contrato],2026)['valor_executado'],30000)
        filters=dict(data_inicial='2026-12-01',data_limite='2026-12-31')
        response=self.client.get(reverse('previsao_pagamentos'),filters)
        self.assertEqual(response.status_code,200);self.assertEqual(response.context['total_pago'],10000)
        from io import BytesIO
        from openpyxl import load_workbook
        response=self.client.get(reverse('exportar_previsao_pagamentos_excel'),filters)
        book=load_workbook(BytesIO(response.content))
        self.assertEqual(sum((Decimal(str(row[7] or 0)) for row in book.worksheets[0].iter_rows(min_row=2,values_only=True)),Decimal('0')),10000)

    def test_5f_exportacao_movimentos_e_saldos(self):
        from .financial_exports import export_report
        from .financial_forms import operational_form
        from django.test import RequestFactory
        from io import BytesIO
        from openpyxl import load_workbook
        nf=self.invoice();first=self.pay(nf,20000);self.pay(nf,10000,'p2')
        service.reverse_payment(movement_id=first.pk,user=self.supply,valor=5000,data_estorno=date(2026,11,7),motivo='Correção',key='e')
        request=RequestFactory().get('/',{'historico':'on'});request.user=self.finance
        form=operational_form(request,'contas');self.assertTrue(form.is_valid())
        book=load_workbook(BytesIO(export_report(self.finance,'pagamentos',form)))
        sheet=book['Pagamentos'];self.assertEqual(sheet.max_row,4)
        self.assertEqual({sheet.cell(row,19).value for row in range(2,5)},{p.pk for p in nf.movimentos.all()})
        self.assertEqual(nf.total_pago,25000)

    def test_5g_refresh_descarta_anotacao_de_saldo_obsoleta(self):
        nf=pq.invoice_annotations(m.NF.objects.filter(pk=self.invoice().pk)).get()
        self.assertEqual(nf.total_pago,0);self.pay(nf,20000);nf.refresh_from_db()
        self.assertEqual(nf.total_pago,20000)

    def test_5h_admin_cancela_nf_com_movimentos_sem_exclusao_fisica(self):
        from django.contrib.auth.models import Permission
        nf=self.invoice();self.pay(nf,20000)
        self.supply.is_staff=True;self.supply.save()
        self.supply.user_permissions.add(*Permission.objects.filter(content_type__app_label='gestao_contratos'))
        self.client.force_login(self.supply)
        url=f'/admin/gestao_contratos/nf/{nf.pk}/delete/'
        self.assertContains(self.client.get(url),'cancelamento lógico com estornos')
        response=self.client.post(url,{'post':'yes','justificativa_correcao':'Cancelamento no admin'})
        self.assertEqual(response.status_code,302)
        nf.refresh_from_db();self.assertIsNotNone(nf.cancelada_em);self.assertEqual(nf.total_pago,0);self.assertEqual(nf.movimentos.count(),2)

    def test_5f_painel_grafico_inclui_caixa_mesmo_se_nf_de_outro_mes(self):
        nf=self.invoice();self.pay(nf,20000)
        service.record_payment(nf_id=nf.pk,user=self.finance,valor=10000,data_pagamento=date(2026,12,5),key='dez')
        response=self.client.get(reverse('painel_financeiro'),{'data_inicial':'2026-12-01','data_limite':'2026-12-31'})
        self.assertEqual(response.context['financial_stats']['pago'],10000)
        self.assertIn('10000.0',response.context['financial_chart'])

    def test_5i_migracao_com_comprovante_autoria_e_bm_compartilhado(self):
        import subprocess,sys
        from pathlib import Path
        root=Path(__file__).resolve().parent.parent
        result=subprocess.run([sys.executable,'-B','-m','gestao_contratos.integration_checks','legacy-migration'],cwd=root,capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
