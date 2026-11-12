from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.db import connection, IntegrityError, transaction
from django.urls import reverse
from django.core.exceptions import ValidationError

from . import models as m
from . import test_financeiro_fase2 as fixtures
from .tests import BaseUserTestCase
from .financial_audit import financial_audit_context


class FinanceiroFase3Tests(BaseUserTestCase):
    setUp = fixtures.FinanceiroFase2Tests.setUp
    bm = fixtures.FinanceiroFase2Tests.bm
    nf = fixtures.FinanceiroFase2Tests.nf

    def history(self,nf_id):
        return m.RegistroAuditoria.objects.filter(content_type=ContentType.objects.get_for_model(m.NF),
            object_id=nf_id,operacao_financeira__isnull=False).order_by('pk')

    def payload(self,bm,paid=False,**extra):
        return dict(bm=bm.pk,valor_pago='50,00',parcela_paga=1,data_pagamento='2026-11-15',
            **({'financeiro_autorizou':'on'} if paid else {}),**extra)

    def test_3a_criacao_e_pagamento_identificam_ator_estados_e_bm(self):
        bm=self.bm(operational='aprovado',director='aprovado')
        with financial_audit_context(self.finance): nf=self.nf(bm)
        with financial_audit_context(self.finance):
            m.NF.objects.filter(pk=nf.pk).update(financeiro_autorizou=True)
        events=list(self.history(nf.pk))
        self.assertEqual([e.operacao_financeira for e in events],['criacao','liquidacao'])
        event=events[-1]
        self.assertEqual(event.usuario,self.finance)
        self.assertEqual(event.estado_anterior['financeiro_autorizou'],False)
        self.assertEqual(event.estado_posterior['financeiro_autorizou'],True)
        self.assertEqual(event.estado_posterior['bm_id'],bm.pk)
        self.assertEqual(event.estado_posterior['bm_diretoria'],'aprovado')

    def test_3a_update_e_sql_direto_na_conexao_django_nao_escapam_da_trilha(self):
        nf=self.nf(self.bm())
        with financial_audit_context(self.supply):
            m.NF.objects.filter(pk=nf.pk).update(numero_nf='001')
            with connection.cursor() as cursor:
                cursor.execute('UPDATE gestao_contratos_nf SET serie=%s WHERE id=%s',['A',nf.pk])
        self.assertEqual(self.history(nf.pk).count(),3)
        self.assertEqual(self.history(nf.pk).last().estado_posterior['serie'],'A')

    def test_3a_correcao_e_desmarcacao_exigem_justificativa_e_preservam_autoria(self):
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        with self.assertRaises(IntegrityError),transaction.atomic(),financial_audit_context(self.supply):
            m.NF.objects.filter(pk=nf.pk).update(valor_pago=70)
        with financial_audit_context(self.supply,'Correção conferida com documento'):
            m.NF.objects.filter(pk=nf.pk).update(valor_pago=70)
            from .payment_services import reverse_payment
            reverse_payment(movement_id=nf.movimentos.get().pk,user=self.supply,valor=50,data_estorno=date(2026,11,15),motivo='Correção conferida com documento',key='teste-reversao')
        events=list(self.history(nf.pk))
        self.assertEqual([e.operacao_financeira for e in events],['criacao','correcao_paga','estorno'])
        self.assertEqual(events[1].justificativa,'Correção conferida com documento')
        self.assertEqual(events[1].autor_grupo,'suprimento')

    def test_3a_exclusao_preserva_estados_e_registro_sem_fk_para_nf(self):
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True); pk=nf.pk
        with financial_audit_context(self.supply,'Documento cadastrado em duplicidade'):
            nf.delete()
        event=self.history(pk).last()
        self.assertEqual(event.operacao_financeira,'cancelamento')
        self.assertEqual(event.estado_anterior['valor_pago'],50)
        self.assertIsNotNone(event.estado_posterior['cancelada_em'])
        self.assertEqual(event.content_object.pk,pk)
        self.assertEqual(m.NF.objects.get(pk=pk).total_pago,0)

    def test_3a_auditoria_imutavel_inclusive_queryset_sql_e_autoria(self):
        nf=self.nf(self.bm()); event=self.history(nf.pk).first()
        for action in (
            lambda:m.RegistroAuditoria.objects.filter(pk=event.pk).update(usuario=self.supply),
            lambda:m.RegistroAuditoria.objects.filter(pk=event.pk).delete(),
            lambda:m.RegistroAuditoria.objects.filter(pk=event.pk).update(estado_posterior={}),
        ):
            with self.assertRaises(IntegrityError),transaction.atomic(): action()
        with self.assertRaises(IntegrityError),transaction.atomic(),connection.cursor() as cursor:
            cursor.execute('DELETE FROM gestao_contratos_registroauditoria WHERE id=%s',[event.pk])

    def test_3a_transacao_desfeita_nao_deixa_evento_falso(self):
        count=m.RegistroAuditoria.objects.filter(operacao_financeira__isnull=False).count()
        try:
            with transaction.atomic():
                self.nf(self.bm()); raise RuntimeError('Simula falha posterior')
        except RuntimeError: pass
        self.assertEqual(m.RegistroAuditoria.objects.filter(operacao_financeira__isnull=False).count(),count)

    def test_3a_script_sem_usuario_nao_inventa_responsavel(self):
        nf=self.nf(self.bm())
        event=self.history(nf.pk).first()
        self.assertIsNone(event.usuario_id); self.assertIsNone(event.autor_nome)

    def test_3b_dados_fiscais_opcionais_e_identificadores_sem_formato_unico(self):
        nf=self.nf(self.bm())
        response=self.client.post(reverse('editar_nf',args=[nf.pk]),self.payload(nf.bm,
            numero_nf='000123',serie='A',tipo_documento='NFS-e',data_emissao='2026-10-02',chave_acesso='codigo-municipal-123'))
        self.assertTrue(response.json()['success'],response.content)
        nf.refresh_from_db()
        self.assertEqual(nf.numero_nf,'000123'); self.assertEqual(nf.data_emissao,date(2026,10,2))
        self.assertEqual(self.history(nf.pk).last().estado_posterior['chave_acesso'],'codigo-municipal-123')

    def test_3b_comprovante_privado_no_pagamento_e_imutavel_para_financeiro(self):
        from .test_auditoria import pdf
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'))
        response=self.client.post(reverse('editar_nf',args=[nf.pk]),self.payload(nf.bm,paid=True,comprovante_pagamento=pdf()))
        self.assertTrue(response.json()['success'],response.content)
        nf.refresh_from_db(); self.assertTrue(nf.comprovante_pagamento)
        download=self.client.get(nf.comprovante_pagamento.url); self.assertEqual(download.status_code,200); download.close()
        response=self.client.post(reverse('editar_nf',args=[nf.pk]),self.payload(nf.bm,paid=True,comprovante_pagamento=pdf()))
        self.assertEqual(response.status_code,403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(nf.comprovante_pagamento.url).status_code,404)

    def test_3b_comprovante_invalido_e_excessivo_recusados(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from .test_auditoria import pdf
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'))
        response=self.client.post(reverse('editar_nf',args=[nf.pk]),self.payload(nf.bm,paid=True,
            comprovante_pagamento=SimpleUploadedFile('falso.pdf',b'conteudo invalido')))
        self.assertEqual(response.status_code,400)
        with override_settings(MAX_UPLOAD_BYTES=4):
            self.assertEqual(self.client.post(reverse('editar_nf',args=[nf.pk]),self.payload(nf.bm,paid=True,comprovante_pagamento=pdf())).status_code,400)
        nf.refresh_from_db(); self.assertFalse(nf.financeiro_autorizou)

    def test_3b_suprimento_corrige_paga_so_com_justificativa(self):
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        self.client.force_login(self.supply)
        response=self.client.post(reverse('editar_nf',args=[nf.pk]),self.payload(nf.bm))
        self.assertFalse(response.json()['success'])
        self.assertEqual(self.history(nf.pk).count(),1)
        response=self.client.post(reverse('editar_nf',args=[nf.pk]),self.payload(nf.bm,
            justificativa_correcao='Pagamento revertido após conferência'))
        self.assertTrue(response.json()['success'],response.content)
        self.assertEqual(self.history(nf.pk).last().operacao_financeira,'estorno')

    def test_3b_exclusao_paga_requer_motivo_na_view(self):
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True); pk=nf.pk
        self.client.force_login(self.supply)
        self.assertEqual(self.client.post(reverse('deletar_nf',args=[pk])).status_code,400)
        self.assertTrue(m.NF.objects.filter(pk=pk).exists())
        self.assertEqual(self.client.post(reverse('deletar_nf',args=[pk]),{'justificativa_correcao':'NF equivocada'}).status_code,302)
        self.assertEqual(self.history(pk).last().justificativa,'NF equivocada')

    def test_3c_multiplas_nfs_conferidas_sem_multiplicar_medicao(self):
        from .financial_reconciliation import bm_totals,with_bm_totals
        bm=self.bm(value='100000',operational='aprovado',director='aprovado')
        self.nf(bm,value='20000',paid=True); self.nf(bm,value='30000',paid=True);self.nf(bm,value='50000')
        totals=bm_totals(bm,m.NF.objects.filter(bm=bm))
        self.assertEqual((totals['measured'],totals['billed'],totals['paid'],totals['unpaid']),(100000,100000,50000,50000))
        from .financial_queries import financial_bms
        annotated=with_bm_totals(financial_bms()).get(pk=bm.pk)
        self.assertEqual((annotated.nf_billed,annotated.nf_paid),(100000,50000))

    def test_3c_compartilhado_concilia_participacoes_independentes(self):
        from .financial_reconciliation import with_bm_totals
        from .financial_queries import financial_bms
        from .test_auditoria import pdf
        a=self.bm(value='60000',arquivo_bm=pdf());b=self.bm(index=1,value='40000',arquivo_bm=a.arquivo_bm.name)
        self.nf(a,value='5000');self.nf(b,value='3000')
        rows=list(with_bm_totals(financial_bms()).order_by('pk'))
        self.assertEqual(sum(r.valor_pago for r in rows),100000)
        self.assertEqual([r.nf_billed for r in rows],[5000,3000])

    def test_3c_excedente_apenas_sinaliza_sem_bloquear_nf(self):
        bm=self.bm(value='10000'); self.nf(bm,value='8000');self.nf(bm,value='5000')
        response=self.client.get(reverse('conferencia_financeira'),{'historico':'on','bm_id':bm.pk})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Valor faturado superior ao valor medido')
        self.assertEqual(response.context['rows'][0]['difference'],-3000)

    def test_3c_origigens_historicas_diferentes_de_nf_paga_sao_diagnosticadas(self):
        from .financial_reconciliation import legacy_origins
        m.Evento.objects.filter(pk=self.events[0].pk).update(valor_pago=999,data_pagamento=date(2026,11,15))
        self.assertEqual(list(legacy_origins('evento').values_list('pk',flat=True)),[self.events[0].pk])
        response=self.client.get(reverse('conferencia_financeira'),{'historico':'on','visao':'evento'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['origins'][0]['record'].origin_paid,999)
        self.events[0].refresh_from_db(); self.assertEqual(self.events[0].valor_pago,999)

    def test_3d_duplicidade_fiscal_nao_usa_numero_bm_ou_arquivo(self):
        from .financial_reconciliation import possible_duplicates
        a=self.nf(self.bm());b=self.nf(self.bm())
        self.assertFalse(possible_duplicates(a).exists())
        for nf in (a,b):
            nf.numero_nf='000123';nf.serie='A';nf.tipo_documento='NFS-e';nf.data_emissao=date(2026,11,1);nf.save()
        self.assertEqual(list(possible_duplicates(a)),[b])

    def test_3d_datas_emissao_antecipada_permitida_e_pagamento_anterior_sinalizado(self):
        from .financial_reconciliation import nf_diagnostic_reasons
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        with financial_audit_context(self.supply,'Correção fiscal sintética'):
            nf.data_emissao=date(2026,11,20);nf.save()
        self.assertTrue(any('anterior à emissão' in reason for reason in nf_diagnostic_reasons(nf)))
        nf.refresh_from_db();self.assertTrue(nf.financeiro_autorizou)

    def test_3e_historico_de_excluida_e_documento_anterior_acessiveis_com_escopo(self):
        from .test_auditoria import pdf
        nf=self.nf(self.bm());nf.arquivo_nf=pdf();nf.save();pk=nf.pk
        nf.delete()
        event=self.history(pk).last()
        response=self.client.get(reverse('historico_financeiro'),{'nf_id':pk})
        self.assertContains(response,'Exclusão da NF')
        url=reverse('documento_historico_nf',args=[event.pk,'anterior','arquivo_nf'])
        response=self.client.get(url);self.assertEqual(response.status_code,200);response.close()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code,404)

    def test_3e_historico_de_mudanca_de_contrato_nao_expoe_outro_contexto(self):
        from .financial_reconciliation import can_view_audit
        nf=self.nf(self.bm())
        m.NF.objects.filter(pk=nf.pk).update(contrato=self.contracts[1],evento=self.events[1])
        event=self.history(nf.pk).last()
        self.assertFalse(can_view_audit(self.leader,event));self.assertFalse(can_view_audit(self.other,event))
        self.assertTrue(can_view_audit(self.finance,event))

    def test_3e_paginas_e_exportacao_novas_so_leitura_global(self):
        urls=[reverse(name) for name in ('conferencia_financeira','historico_financeiro','exportar_conferencia_financeira')]
        for role in ('financeiro','suprimento','diretoria','gerente_contrato'):
            self.client.force_login(self.create_user('f3_'+role,role))
            for url in urls:
                self.assertEqual(self.client.get(url,{'historico':'on'}).status_code,200)
                self.assertEqual(self.client.post(url).status_code,405)
        for user in (self.leader,self.coord,self.other):
            self.client.force_login(user)
            for url in urls:self.assertEqual(self.client.get(url).status_code,403)

    def test_3e_detalhes_existentes_integram_historico_fiscal_e_conciliacao(self):
        nf=self.nf(self.bm())
        response=self.client.get(reverse('detalhe_nf',args=[nf.pk]))
        self.assertContains(response,'Identificação fiscal');self.assertContains(response,'Histórico financeiro')
        response=self.client.get(reverse('detalhe_bm_financeiro',args=[nf.bm_id]))
        self.assertContains(response,'Conferência desta participação')

    def test_3e_exportacao_conferencia_protege_formulas(self):
        from openpyxl import load_workbook
        from io import BytesIO
        self.contracts[0].num_contrato='=2+2';self.contracts[0].save()
        self.bm()
        response=self.client.get(reverse('exportar_conferencia_financeira'),{'historico':'on'})
        book=load_workbook(BytesIO(response.content));cell=book.active.cell(row=2,column=3)
        self.assertEqual(cell.data_type,'s');self.assertTrue(cell.value.startswith("'="))

    def test_3e_guarda_chuva_nao_aplica_teto_uniforme(self):
        self.contracts[0].guarda_chuva=True;self.contracts[0].save()
        self.bm(value='999999')
        response=self.client.get(reverse('conferencia_financeira'),{'historico':'on','contrato':self.contracts[0].pk})
        self.assertContains(response,'Guarda-chuva: conferir por OS/projeto')
        self.assertNotContains(response,'supera o valor contratual vigente')

    def test_3a_bulk_create_gera_um_evento_por_nf(self):
        bm=self.bm()
        with financial_audit_context(self.finance):
            rows=m.NF.objects.bulk_create([m.NF(contrato=self.contracts[0],evento=self.events[0],bm=bm,
                valor_pago=10,parcela_paga=1,data_pagamento=date(2026,11,15)) for _ in range(2)])
        for row in rows:
            self.assertEqual(self.history(row.pk).count(),1)
            self.assertEqual(self.history(row.pk).first().usuario,self.finance)

    def test_3a_sql_pagamento_sem_autorizacao_e_alteracao_financeiro_paga_negados(self):
        nf=self.nf(self.bm())
        with self.assertRaises(IntegrityError),transaction.atomic(),financial_audit_context(self.finance):
            m.NF.objects.filter(pk=nf.pk).update(financeiro_autorizou=True)
        self.assertEqual(self.history(nf.pk).count(),1)
        m.BM.objects.filter(pk=nf.bm_id).update(status_gerente='aprovado',aprovacao_pagamento='aprovado')
        with financial_audit_context(self.finance): m.NF.objects.filter(pk=nf.pk).update(financeiro_autorizou=True)
        with self.assertRaises(IntegrityError),transaction.atomic(),financial_audit_context(self.finance,'Motivo não concede permissão'):
            m.NF.objects.filter(pk=nf.pk).update(numero_nf='NEGADA')
        self.assertEqual(self.history(nf.pk).count(),2)

    def test_3a_trigger_ausente_bloqueia_gravacao_sem_perder_trilha(self):
        from django.db import DatabaseError
        nf=self.nf(self.bm())
        with connection.cursor() as cursor:
            ddl=cursor.execute("SELECT sql FROM sqlite_master WHERE name='hidro_nf_audit_update'").fetchone()[0]
            cursor.execute('DROP TRIGGER hidro_nf_audit_update')
        try:
            with self.assertRaises(DatabaseError),transaction.atomic():
                m.NF.objects.filter(pk=nf.pk).update(numero_nf='SEM-TRILHA')
        finally:
            with connection.cursor() as cursor: cursor.execute(ddl)
        nf.refresh_from_db(); self.assertIsNone(nf.numero_nf)
        self.assertEqual(self.history(nf.pk).count(),1)

    def test_3b_financeiro_nao_anexa_comprovante_em_nf_nao_paga(self):
        from .test_auditoria import pdf
        nf=self.nf(self.bm())
        response=self.client.post(reverse('editar_nf',args=[nf.pk]),self.payload(nf.bm,comprovante_pagamento=pdf()))
        self.assertFalse(response.json()['success'])
        nf.refresh_from_db();self.assertFalse(nf.comprovante_pagamento)
        self.assertEqual(self.history(nf.pk).count(),1)

    def test_3b_substituicao_suprimento_preserva_comprovante_anterior(self):
        from .test_auditoria import pdf
        nf=self.nf(self.bm(operational='aprovado',director='aprovado'))
        self.client.post(reverse('editar_nf',args=[nf.pk]),self.payload(nf.bm,paid=True,comprovante_pagamento=pdf()))
        nf.refresh_from_db();previous=nf.comprovante_pagamento.name
        self.client.force_login(self.supply)
        response=self.client.post(reverse('editar_nf',args=[nf.pk]),self.payload(nf.bm,paid=True,
            comprovante_pagamento=pdf(),justificativa_correcao='Comprovante corrigido'))
        self.assertTrue(response.json()['success'],response.content)
        nf.refresh_from_db();event=self.history(nf.pk).last()
        self.assertNotEqual(previous,nf.comprovante_pagamento.name)
        self.assertEqual(event.estado_anterior['comprovante_pagamento'],previous)
        self.assertTrue(nf.comprovante_pagamento.storage.exists(previous))
        response=self.client.get(reverse('documento_historico_nf',args=[event.pk,'anterior','comprovante_pagamento']))
        self.assertEqual(response.status_code,200);response.close()

    def test_3d_bm_alterado_apos_pagamento_aparece_no_diagnostico(self):
        from .financial_reconciliation import diagnostic_nfs,nf_diagnostic_reasons
        with financial_audit_context(self.finance):
            nf=self.nf(self.bm(operational='aprovado',director='aprovado'),paid=True)
        m.BM.objects.filter(pk=nf.bm_id).update(valor_pago=999)
        nf.refresh_from_db()
        self.assertIn(nf.pk,list(diagnostic_nfs(m.NF.objects.all()).values_list('pk',flat=True)))
        self.assertTrue(any('alterado após' in text for text in nf_diagnostic_reasons(nf)))
        self.assertTrue(nf.financeiro_autorizou)

    def test_3d_autorizacao_invalidada_e_os_cancelada_apenas_sinalizadas(self):
        from .financial_reconciliation import nf_diagnostic_reasons
        nf=self.nf(self.bm(os=True,operational='aprovado',director='aprovado'),paid=True)
        m.BM.objects.filter(pk=nf.bm_id).update(aprovacao_pagamento='pendente')
        m.OS.objects.filter(pk=self.order.pk).update(status='cancelada')
        nf.refresh_from_db();reasons=nf_diagnostic_reasons(nf)
        self.assertTrue(any('autorização atual' in x for x in reasons))
        self.assertTrue(any('OS cancelada' in x for x in reasons))
        self.assertTrue(nf.financeiro_autorizou)

    def test_3d_limite_planejado_por_origem_e_datas_informativos(self):
        from django.utils import timezone
        from .financial_reconciliation import bm_reconciliation_row,with_bm_totals,nf_diagnostic_reasons
        from .financial_queries import eager_bms,financial_bms
        bm=self.bm(os=True,value='1000',operational='aprovado',director='aprovado',data_final_medicao=timezone.now())
        row=bm_reconciliation_row(eager_bms(with_bm_totals(financial_bms())).get(pk=bm.pk),self.finance)
        self.assertTrue(any('valor planejado do Evento/OS' in x for x in row['reasons']))
        nf=self.nf(bm,paid=True,day=date(2020,1,1))
        self.assertTrue(any('conclusão da medição' in x for x in nf_diagnostic_reasons(nf)))
