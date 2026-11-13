"""Decisão da Diretoria, justificativas, exportação e ciclo até a liquidação."""
from datetime import date
from io import BytesIO
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import transaction,IntegrityError
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook
from . import models as m,payment_services as payments
from . import test_financeiro_fase2 as fixtures
from .tests import BaseUserTestCase


class DecisaoPagamentoBMTests(BaseUserTestCase):
    bm=fixtures.FinanceiroFase2Tests.bm
    nf=fixtures.FinanceiroFase2Tests.nf

    def setUp(self):
        fixtures.FinanceiroFase2Tests.setUp(self)
        self.director=self.create_user('decision_director','diretoria')
        self.manager=self.create_user('decision_manager','gerente_contrato')

    def decide(self,bm,action='aprovar_pagamento',reason=None,user=None):
        self.client.force_login(user or self.director)
        data={'acao':action}
        if reason is not None:data['justificativa']=reason
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('avaliar_bm',args=[bm.pk]),data)

    def history(self,bm):
        return m.RegistroAuditoria.objects.filter(content_type=ContentType.objects.get_for_model(m.BM),object_id=bm.pk,operacao_financeira='decisao_bm')

    def test_aprovacao_opcional_em_evento_e_os_e_historico_imutavel(self):
        for is_os in (False,True):
            for reason in (None,'','   ','  Acordo conferido com a gerência.  '):
                bm=self.bm(os=is_os,operational='aprovado')
                response=self.decide(bm,reason=reason)
                self.assertEqual(response.status_code,200,response.content)
                bm.refresh_from_db()
                self.assertEqual(bm.aprovacao_pagamento,'aprovado')
                self.assertEqual(bm.justificativa_aprovacao_diretor,(reason or '').strip() or None)
                self.assertIsNone(bm.justificativa_reprovacao_diretor)
                event=self.history(bm).get()
                self.assertEqual(event.usuario,self.director)
                self.assertEqual(event.estado_anterior['aprovacao_pagamento'],'pendente')
                self.assertEqual(event.estado_posterior['justificativa_aprovacao_diretor'],bm.justificativa_aprovacao_diretor)
                with self.assertRaises(IntegrityError),transaction.atomic():self.history(bm).update(justificativa='reescrita')

    def test_reprovacao_sem_justificativa_nao_muda_estado_nao_notifica(self):
        for is_os in (False,True):
            bm=self.bm(os=is_os,operational='aprovado')
            for reason in (None,'','  \n '):
                count=m.RegistroAuditoria.objects.count();sent=len(mail.outbox)
                response=self.decide(bm,'reprovar_pagamento',reason)
                self.assertEqual(response.status_code,400,response.content)
                bm.refresh_from_db();self.assertEqual(bm.aprovacao_pagamento,'pendente')
                self.assertIsNone(bm.data_aprovacao_diretor)
                self.assertEqual(m.RegistroAuditoria.objects.count(),count);self.assertEqual(len(mail.outbox),sent)

    def test_reprovacao_justificada_bloqueia_nova_liquidacao(self):
        bm=self.bm(operational='aprovado');nf=self.nf(bm)
        self.assertEqual(self.decide(bm,'reprovar_pagamento','Ajustar os valores.').status_code,200)
        bm.refresh_from_db();self.assertEqual(bm.justificativa_reprovacao_diretor,'Ajustar os valores.')
        self.assertIsNone(bm.justificativa_aprovacao_diretor)
        with self.assertRaises(ValidationError):payments.record_payment(nf_id=nf.pk,user=self.finance,valor=10,data_pagamento=date(2026,11,10),key='denied')
        self.assertFalse(nf.movimentos.exists())

    def test_repeticao_da_decisao_nao_altera_autoria_nem_duplica_notificacao(self):
        bm=self.bm(operational='aprovado')
        self.assertEqual(self.decide(bm,reason='Primeira decisão').status_code,200)
        bm.refresh_from_db();instant=bm.data_aprovacao_diretor;sent=len(mail.outbox)
        for action in ('aprovar_pagamento','reprovar_pagamento'):
            self.assertEqual(self.decide(bm,action,'Tentativa posterior').status_code,409)
        bm.refresh_from_db();self.assertEqual(bm.data_aprovacao_diretor,instant)
        self.assertEqual(bm.justificativa_aprovacao_diretor,'Primeira decisão')
        self.assertEqual(self.history(bm).count(),1);self.assertEqual(len(mail.outbox),sent)

    def test_sem_aprovacao_operacional_e_perfis_sem_competencia(self):
        bm=self.bm()
        self.assertEqual(self.decide(bm).status_code,400)
        for user in (self.finance,self.supply,self.leader,self.coord,self.manager,self.create_user('decision_external','fornecedor')):
            response=self.decide(bm,user=user)
            self.assertIn(response.status_code,(302,400,403))
            bm.refresh_from_db();self.assertEqual(bm.aprovacao_pagamento,'pendente')
        self.assertFalse(self.history(bm).exists())

    def test_cobertura_gerente_ausente_preserva_as_duas_etapas(self):
        self.manager.gerente_contrato_ausente=True;self.manager.save()
        for action,reason,status in (('aprovar_pagamento','Análise conjunta','aprovado'),('reprovar_pagamento','Revisar medição','reprovado')):
            bm=self.bm()
            self.assertEqual(self.decide(bm,action,reason).status_code,200)
            bm.refresh_from_db();self.assertEqual((bm.status_gerente,bm.aprovacao_pagamento),(status,status))
            self.assertEqual(bm.data_aprovacao_diretor,bm.data_aprovacao_gerente)

    def test_revisao_financeira_reabre_autorizacao_limpa_nota_e_preserva_historico(self):
        bm=self.bm(operational='aprovado')
        self.decide(bm,reason='Aprovação original')
        event=self.history(bm).get()
        bm.refresh_from_db();bm.valor_pago=200;bm.save(update_fields=['valor_pago'])
        bm.refresh_from_db()
        self.assertEqual((bm.status_gerente,bm.aprovacao_pagamento),('pendente','pendente'))
        self.assertIsNone(bm.justificativa_aprovacao_diretor)
        event.refresh_from_db();self.assertEqual(event.estado_posterior['justificativa_aprovacao_diretor'],'Aprovação original')

    def test_fluxo_completo_gerencia_diretoria_nf_parciais_e_saldo(self):
        for is_os in (False,True):
            bm=self.bm(os=is_os,value='100')
            if not is_os:
                m.AvaliacaoFornecedor.objects.create(empresa_terceira=self.supplier,contrato_terceiro=self.contracts[0],evento=bm.evento,avaliador=self.manager,area_avaliadora='Gerência')
            self.assertEqual(self.decide(bm,'aprovar',user=self.manager).status_code,200)
            self.assertEqual(self.decide(bm,reason='Medição conferida').status_code,200)
            nf=self.nf(bm,value='100')
            for amount,key in ((20,'primeiro'),(30,'segundo'),(50,'terceiro')):
                payments.record_payment(nf_id=nf.pk,user=self.finance,valor=amount,data_pagamento=date(2026,11,10),key=key)
            nf.refresh_from_db();self.assertEqual((nf.total_pago,nf.saldo_pendente,nf.financeiro_autorizou),(100,0,True))
            self.assertEqual(nf.movimentos.count(),3)

    def test_rollback_nao_envia_notificacao_de_decisao_nao_confirmada(self):
        bm=self.bm(operational='aprovado');self.client.force_login(self.director)
        count=m.RegistroAuditoria.objects.count();sent=len(mail.outbox)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            try:
                with transaction.atomic():
                    self.assertEqual(self.client.post(reverse('avaliar_bm',args=[bm.pk]),{'acao':'aprovar_pagamento','justificativa':'Será revertida'}).status_code,200)
                    self.assertEqual(len(mail.outbox),sent)
                    raise RuntimeError('Rollback externo')
            except RuntimeError:pass
        self.assertEqual(callbacks,[]);self.assertEqual(len(mail.outbox),sent)
        self.assertEqual(m.RegistroAuditoria.objects.count(),count)
        bm.refresh_from_db();self.assertEqual(bm.aprovacao_pagamento,'pendente')

    def test_bm_documental_compartilhado_notifica_contrato_financeiro(self):
        bm=self.bm(index=1,evento=self.events[0])
        m.AvaliacaoFornecedor.objects.create(empresa_terceira=self.supplier,contrato_terceiro=self.contracts[0],
            evento=self.events[0],area_avaliadora=self.leader.grupo,avaliador=self.leader,nota_gestao=5)
        for user in (self.other,self.leader):
            self.assertEqual(self.decide(bm,action='aprovar',user=user).status_code,200)
        self.assertEqual(self.decide(bm,reason='Participação conferida').status_code,200)
        self.assertIn(self.contracts[0].num_contrato,mail.outbox[-1].body)
        self.assertEqual(self.history(bm).count(),3)
        self.assertEqual(self.history(bm).get(usuario=self.director).estado_posterior['contrato_id'],self.contracts[0].pk)

    def test_excel_gerencia_e_justificativa_opcional_da_diretoria(self):
        bm=self.bm(operational='aprovado',data_aprovacao_gerente=timezone.now(),justificativa_reprovacao_gerente=' =Texto gerencial legado')
        self.decide(bm,reason='Justificativa opcional da Diretoria')
        response=self.client.get(reverse('exportar_bms_previsao_excel'),{'data_inicial':'2026-01-01','data_limite':'2026-12-31'})
        self.assertEqual(response.status_code,200)
        sheet=load_workbook(BytesIO(response.content))['Boletins de Medição']
        self.assertEqual(sheet.max_column,14)
        self.assertEqual(sheet.cell(1,14).value,'Justificativa da gerência')
        self.assertEqual(sheet.cell(2,14).value,"' =Texto gerencial legado")
        self.assertIn('Justificativa opcional da Diretoria',sheet.cell(2,11).value)

    def test_telas_de_evento_os_e_consulta_financeira_compartilham_modal(self):
        event=self.bm(operational='aprovado');order=self.bm(os=True,operational='aprovado')
        self.client.force_login(self.director)
        for name,key in (('detalhes_entrega',self.events[0].pk),('detalhes_os',self.order.pk),('detalhe_bm_financeiro',event.pk)):
            response=self.client.get(reverse(name,args=[key]))
            self.assertEqual(response.status_code,200,(name,response.status_code))
            self.assertContains(response,'data-bm-payment-action="aprovar_pagamento"')
            self.assertContains(response,'data-bm-payment-form')
            self.assertContains(response,'js/decisao_pagamento_bm.js')
        self.decide(order,reason='Nota exibida na OS')
        self.assertContains(self.client.get(reverse('detalhes_os',args=[self.order.pk])),'Nota exibida na OS')

    def test_justificativa_excessiva_negada_sem_salvar(self):
        bm=self.bm(operational='aprovado')
        self.assertEqual(self.decide(bm,reason='a'*4001).status_code,400)
        self.assertFalse(self.history(bm).exists())

    def test_duas_decisoes_simultaneas_confirmam_apenas_uma(self):
        import subprocess,sys
        from pathlib import Path
        root=Path(__file__).resolve().parent.parent
        result=subprocess.run([sys.executable,'-B','-m','gestao_contratos.integration_checks','bm-decisions'],cwd=root,capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_admin_nao_contorna_decisao_nem_justificativa_da_diretoria(self):
        from django.contrib.auth.models import Permission
        bm=self.bm()
        self.supply.is_staff=True;self.supply.save()
        self.supply.user_permissions.add(*Permission.objects.filter(content_type__app_label='gestao_contratos'))
        self.client.force_login(self.supply)
        response=self.client.post(f'/admin/gestao_contratos/bm/{bm.pk}/change/',dict(
            contrato=bm.contrato_id,evento=bm.evento_id,numero_bm=bm.numero_bm,parcela_paga=1,valor_pago='100',data_pagamento='2026-11-15',
            status_gerente='aprovado',aprovacao_pagamento='aprovado',justificativa_aprovacao_diretor='Forjada pelo admin',_save='Salvar'))
        self.assertEqual(response.status_code,302)
        bm.refresh_from_db();self.assertEqual((bm.status_gerente,bm.aprovacao_pagamento),('pendente','pendente'))
        self.assertIsNone(bm.justificativa_aprovacao_diretor)
