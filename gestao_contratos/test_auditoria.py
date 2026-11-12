"""Regressões de acesso, integridade e fluxos identificados na auditoria."""
from datetime import date
from contextlib import closing
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, override_settings
from django.test import RequestFactory
from django.contrib import admin
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from .tests import BaseUserTestCase
from .models import (AditivoContratoTerceiro, AvaliacaoFornecedor, BM, ContratoTerceiros,
                     DocumentoBM, DocumentoContratoTerceiro, Evento, Indicadores, NF,
                     NFCliente, OS, SolicitacaoContrato, SolicitacaoProspeccao)
from .forms import BMForm, EventoPrevisaoForm, NFForm, SolicitacaoAditivoContratoTerceiroForm
from .views import criar_contrato_se_aprovado_minuta, send_mail
from .workflows import claim_once


def pdf(name="documento.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4\nconteudo de teste", content_type="application/pdf")


class AuditRegressionTests(BaseUserTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = override_settings(MEDIA_ROOT=directory.name)
        override.enable()
        self.addCleanup(override.disable)
        self.supply = self.create_user("audit_supply", "suprimento")
        self.finance = self.create_user("audit_finance", "financeiro")
        self.leader = self.create_user("audit_leader", "lider_contrato")
        self.outsider = self.create_user("audit_outside", "lider_contrato")
        self.vendor = self.create_user("audit_vendor", "fornecedor")
        self.manager = self.create_user("audit_manager", "gerente_contrato")
        self.director = self.create_user("audit_director", "diretoria")
        self.project = self.create_contract(lider_contrato=self.leader)
        self.contract = self.create_supplier_contract(cod_projeto=self.project, lider_contrato=self.leader)
        self.contract.valor_total = Decimal("1000.00")
        self.contract.data_fim = date(2026, 12, 31)
        self.contract.save()
        self.event = self.create_event(contrato=self.contract)

    def bm(self, **kwargs):
        values = dict(contrato=self.contract, evento=self.event, numero_bm=1,
                      parcela_paga=1, valor_pago=Decimal("100.00"),
                      status_gerente="aprovado", aprovacao_pagamento="aprovado")
        values.update(kwargs)
        return BM.objects.create(**values)

    def addendum(self, **kwargs):
        values = dict(contrato=self.contract, solicitado_por=self.leader, motivo="Escopo adicional",
                      valor_total_anterior=self.contract.valor_total,
                      data_fim_anterior=self.contract.data_fim,
                      novo_valor_total=Decimal("200.00"), nova_data_fim=date(2027, 1, 31),
                      status_gerente="aprovado", status_diretoria="aprovado", status_lider="aprovado",
                      arquivo_aditivo="aditivos_fornecedor/minuta.pdf")
        values.update(kwargs)
        return AditivoContratoTerceiro.objects.create(**values)

    def test_foreign_contract_ids_do_not_grant_access(self):
        for user in (self.outsider, self.vendor):
            self.client.force_login(user)
            for name, key in (("contrato_fornecedor_detalhe", self.contract.pk),
                              ("contrato_cliente_detalhe", self.project.pk),
                              ("editar_evento", self.event.pk)):
                with self.subTest(user=user.grupo, route=name):
                    response = self.client.get(reverse(name, args=[key]))
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response.url, reverse("home"))

    def test_own_contract_remains_accessible(self):
        self.client.force_login(self.leader)
        self.assertEqual(self.client.get(reverse("contrato_fornecedor_detalhe", args=[self.contract.pk])).status_code, 200)

    def test_foreign_event_post_and_duplicate_are_denied(self):
        self.client.force_login(self.outsider)
        count = Evento.objects.count()
        for route in ("editar_evento", "duplicar_evento", "excluir_evento"):
            self.client.post(reverse(route, args=[self.event.pk]), {"descricao": "fraude"})
        self.event.refresh_from_db()
        self.assertEqual(self.event.descricao, "Entrega prevista")
        self.assertEqual(Evento.objects.count(), count)

    def test_supplier_cannot_duplicate_event(self):
        self.client.force_login(self.vendor)
        count = Evento.objects.count()
        self.client.post(reverse("duplicar_evento", args=[self.event.pk]))
        self.assertEqual(Evento.objects.count(), count)

    def test_duplicate_does_not_copy_delivery_evidence(self):
        self.event.realizado = True
        self.event.data_entrega = date(2026, 4, 20)
        self.event.avaliacao = "Aprovado"
        self.event.caminho_evidencia = "evidencia antiga"
        self.event.save()
        self.client.force_login(self.supply)
        self.client.post(reverse("duplicar_evento", args=[self.event.pk]))
        new = Evento.objects.exclude(pk=self.event.pk).get()
        self.assertFalse(new.realizado)
        self.assertIsNone(new.data_entrega)
        self.assertIsNone(new.avaliacao)
        self.assertFalse(new.caminho_evidencia)

    def test_destructive_get_is_rejected_without_mutation(self):
        bm = self.bm()
        nf = NF.objects.create(contrato=self.contract, evento=self.event, bm=bm, parcela_paga=1)
        client_nf = NFCliente.objects.create(contrato=self.project, parcela_paga=1)
        self.client.force_login(self.finance)
        for route, obj in (("deletar_bm", bm), ("deletar_nf", nf), ("excluir_nf_cliente", client_nf)):
            with self.subTest(route=route):
                response = self.client.get(reverse(route, args=[obj.pk]))
                self.assertEqual(response.status_code, 405)
                self.assertTrue(type(obj).objects.filter(pk=obj.pk).exists())

    def test_approval_get_is_rejected_without_state_change(self):
        request = self.create_os_request(contrato=self.contract, solicitante=self.leader)
        for user, route in ((self.manager, "aprovar_os_gerente_contrato"), (self.director, "aprovar_os_diretoria")):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse(route, args=[request.pk, "aprovar"])).status_code, 405)
        request.refresh_from_db()
        self.assertEqual(request.status, "pendente_gerente")

    def test_csrf_is_required_for_deletion(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.finance)
        bm = self.bm()
        self.assertEqual(client.post(reverse("deletar_bm", args=[bm.pk])).status_code, 403)
        self.assertTrue(BM.objects.filter(pk=bm.pk).exists())

    def test_private_download_requires_authentication_and_scope(self):
        self.contract.num_contrato_arquivo = pdf()
        self.contract.save()
        url = self.contract.num_contrato_arquivo.url
        self.assertTrue(url.startswith("/arquivos/"))
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.leader)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        response.close()

    def test_legacy_media_url_is_also_private(self):
        self.contract.num_contrato_arquivo = pdf()
        self.contract.save()
        self.assertEqual(self.client.get("/media/" + self.contract.num_contrato_arquivo.name).status_code, 302)

    def test_unregistered_file_and_path_traversal_are_not_served(self):
        self.client.force_login(self.supply)
        for name in ("../.env", "modelos_word/Modelo Contrato.docm", "inexistente.pdf"):
            self.assertEqual(self.client.get(reverse("private_download", args=[name])).status_code, 404)

    def test_changing_bm_amount_invalidates_all_approvals(self):
        bm = self.bm()
        bm.data_aprovacao_diretor = timezone.now()
        bm.save()
        bm.valor_pago = Decimal("200.00")
        bm.save(update_fields=["valor_pago"])
        bm.refresh_from_db()
        self.assertEqual(bm.status_gerente, "pendente")
        self.assertEqual(bm.aprovacao_pagamento, "pendente")
        self.assertIsNone(bm.data_aprovacao_diretor)

    def test_changing_bm_file_invalidates_director_approval(self):
        bm = self.bm()
        bm.arquivo_bm = pdf()
        bm.save()
        self.assertEqual(bm.aprovacao_pagamento, "pendente")

    def test_shared_bm_can_reference_another_contract_event(self):
        other = self.create_supplier_contract(cod_projeto=self.project, num_contrato="OUTRO")
        bm = self.bm(contrato=other)
        self.assertEqual(bm.contrato_financeiro, self.contract)

    def test_bm_create_allows_explicit_shared_contract_and_event(self):
        other = self.create_supplier_contract(cod_projeto=self.project, num_contrato="OUTRO")
        self.client.force_login(self.supply)
        response = self.client.post(reverse("cadastrar_bm", args=[other.pk, self.event.pk]), {
            "numero_bm": 1, "parcela_paga": 1, "valor_pago": "100,00", "data_pagamento": "2026-10-23",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(BM.objects.get().contrato_financeiro, self.contract)

    def test_nf_cannot_reference_foreign_bm(self):
        bm = self.bm()
        other = self.create_event(contrato=self.contract)
        with self.assertRaises(ValidationError):
            NF.objects.create(contrato=self.contract, evento=other, bm=bm, parcela_paga=1)

    def test_financial_parents_are_protected_from_cascade(self):
        bm = self.bm()
        nf = NF.objects.create(contrato=self.contract, evento=self.event, bm=bm, parcela_paga=1)
        for obj in (self.event, self.contract, self.project, bm):
            with self.subTest(model=type(obj).__name__), self.assertRaises(ProtectedError):
                obj.delete()
        self.assertTrue(NF.objects.filter(pk=nf.pk).exists())

    def test_event_delete_view_reports_protected_history(self):
        bm = self.bm()
        self.client.force_login(self.supply)
        response = self.client.post(reverse("excluir_evento_contrato", args=[self.event.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(BM.objects.filter(pk=bm.pk).exists())

    def test_multiple_paid_nfs_are_summed_and_unchecking_recalculates(self):
        bm = self.bm()
        self.client.force_login(self.finance)
        url = reverse("cadastrar_nf", args=[self.event.pk])
        for amount in ("100,10", "200,20"):
            response = self.client.post(url, {"bm": bm.pk, "valor_pago": amount, "parcela_paga": 1,
                "data_pagamento": "2026-10-23", "financeiro_autorizou": "on"})
            self.assertTrue(response.json()["success"], response.content)
        self.event.refresh_from_db()
        self.assertEqual(self.event.valor_pago, Decimal("300.30"))
        nf = NF.objects.order_by("pk").last()
        # Correção de pagamento já registrado é atribuição de Suprimento.
        self.client.force_login(self.supply)
        response = self.client.post(reverse("editar_nf", args=[nf.pk]), {
            "bm": bm.pk, "valor_pago": "200,20", "parcela_paga": 1, "data_pagamento": "2026-10-23", "justificativa_correcao":"Correção sintética conferida",
        })
        self.assertTrue(response.json()["success"], response.content)
        self.event.refresh_from_db()
        self.assertEqual(self.event.valor_pago, Decimal("100.10"))

    def test_deleting_last_paid_nf_clears_total_and_payment_date(self):
        bm = self.bm()
        self.client.force_login(self.finance)
        self.client.post(reverse("cadastrar_nf", args=[self.event.pk]), {
            "bm": bm.pk, "valor_pago": "100,00", "parcela_paga": 1, "data_pagamento": "2026-10-23", "financeiro_autorizou": "on",
        })
        nf = NF.objects.get()
        self.client.force_login(self.supply)
        self.client.post(reverse("deletar_nf", args=[nf.pk]), {"justificativa_correcao":"Exclusão sintética conferida"})
        self.event.refresh_from_db()
        self.assertEqual(self.event.valor_pago, Decimal("0.00"))
        self.assertIsNone(self.event.data_pagamento)

    def test_finance_cannot_finalize_os_by_manual_post(self):
        os = self.create_os(contrato=self.contract, lider_contrato=self.leader)
        self.client.force_login(self.finance)
        response = self.client.post(reverse("registrar_entrega_os", args=[os.pk]), {"realizado": "on", "data_entrega": "2026-10-23"})
        self.assertEqual(response.status_code, 403)
        os.refresh_from_db()
        self.assertFalse(os.realizado)
        self.assertEqual(os.status, "em_execucao")

    def test_signed_addendum_is_applied_once(self):
        ad = self.addendum()
        self.client.force_login(self.supply)
        self.client.post(reverse("enviar_aditivo_assinado_contrato", args=[ad.pk]), {"arquivo_aditivo_assinado": pdf()})
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.valor_total, Decimal("1200.00"))
        self.contract.valor_total = Decimal("1500.00")
        self.contract.save()
        self.client.post(reverse("enviar_aditivo_assinado_contrato", args=[ad.pk]), {"arquivo_aditivo_assinado": pdf()})
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.valor_total, Decimal("1500.00"))

    def test_signed_addendum_rolls_back_on_contract_save_failure(self):
        ad = self.addendum()
        self.client.force_login(self.supply)
        with patch.object(ContratoTerceiros, "save", side_effect=RuntimeError("falha simulada")):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse("enviar_aditivo_assinado_contrato", args=[ad.pk]), {"arquivo_aditivo_assinado": pdf()})
        ad.refresh_from_db()
        self.contract.refresh_from_db()
        self.assertFalse(ad.aprovado_totalmente)
        self.assertEqual(self.contract.valor_total, Decimal("1000.00"))

    def test_stale_addendum_snapshot_is_rejected(self):
        ad = self.addendum()
        self.contract.valor_total = Decimal("2000.00")
        self.contract.save()
        self.client.force_login(self.supply)
        self.client.post(reverse("enviar_aditivo_assinado_contrato", args=[ad.pk]), {"arquivo_aditivo_assinado": pdf()})
        ad.refresh_from_db()
        self.assertFalse(ad.aprovado_totalmente)

    def test_unsigned_addendum_cannot_finish_without_request_approval(self):
        ad = self.addendum(status_gerente="reprovado")
        self.client.force_login(self.supply)
        self.client.post(reverse("enviar_aditivo_assinado_contrato", args=[ad.pk]), {"arquivo_aditivo_assinado": pdf()})
        ad.refresh_from_db()
        self.assertFalse(ad.aprovado_totalmente)

    def test_closed_contract_cannot_start_addendum(self):
        self.contract.status = "encerrado"
        self.contract.save()
        self.client.force_login(self.leader)
        self.client.post(reverse("solicitar_aditivo_contrato", args=[self.contract.pk]), {"motivo": "não permitido"})
        self.assertFalse(AditivoContratoTerceiro.objects.exists())

    def test_one_os_per_request_is_enforced_by_database(self):
        request = self.create_os_request(contrato=self.contract, solicitante=self.leader)
        self.create_os(contrato=self.contract, solicitacao=request)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_os(contrato=self.contract, solicitacao=request)

    def test_idempotency_claim_survives_clearing_worker_cache(self):
        self.assertTrue(claim_once("audit:submission", 60))
        cache.clear()
        self.assertFalse(claim_once("audit:submission", 60))

    def test_failed_transaction_does_not_consume_idempotency_claim(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.assertTrue(claim_once("audit:rollback", 60))
                raise RuntimeError("falha simulada")
        self.assertTrue(claim_once("audit:rollback", 60))

    def test_expired_idempotency_claim_can_be_used_again(self):
        from .models import ChaveIdempotencia
        self.assertTrue(claim_once("audit:expiry", 60))
        ChaveIdempotencia.objects.update(expira_em=timezone.now())
        self.assertTrue(claim_once("audit:expiry", 60))

    def test_contract_creation_rolls_back_when_source_update_fails(self):
        request = SolicitacaoContrato.objects.create(
            contrato=self.project, fornecedor_escolhido=self.contract.empresa_terceira,
            status="Aprovação Final", aprovacao_gerencia=True,
        )
        DocumentoBM.objects.create(solicitacao_contrato=request, status_gerente="aprovado")
        DocumentoContratoTerceiro.objects.create(
            solicitacao_contrato=request, numero_contrato="AUDIT-ROLLBACK", objeto="Objeto",
            prazo_inicio=date(2026, 10, 1), prazo_fim=date(2026, 12, 31),
            valor_total=Decimal("1000.00"), arquivo_contrato_assinado=pdf(),
        )
        event = Evento.objects.create(solicitacao_contrato=request, descricao="Planejamento")
        with patch.object(SolicitacaoContrato, "save", side_effect=RuntimeError("falha simulada")):
            with self.assertRaises(RuntimeError):
                criar_contrato_se_aprovado_minuta(request)
        self.assertFalse(ContratoTerceiros.objects.filter(solicitacao=request).exists())
        event.refresh_from_db()
        self.assertIsNone(event.contrato_terceiro_id)

    def test_triage_rejects_negative_proposal_without_partial_updates(self):
        request = SolicitacaoProspeccao.objects.create(
            contrato=self.project, lider_contrato=self.leader, aprovado=True,
            status="Aprovada pelo suprimento",
        )
        supplier = self.contract.empresa_terceira
        self.client.force_login(self.supply)
        self.client.post(reverse("triagem_fornecedores", args=[request.pk]), {
            "fornecedores": [supplier.pk], f"valor_{supplier.pk}": "-100,00",
        })
        request.refresh_from_db()
        self.assertFalse(request.triagem_realizada)
        self.assertEqual(request.status, "Aprovada pelo suprimento")
        self.assertFalse(request.fornecedores_selecionados.exists())

    def test_negative_amounts_and_inverted_measurement_are_invalid(self):
        for data in ({"valor_pago": "-10,00"}, {"data_inicial_medicao": "2026-10-24", "data_final_medicao": "2026-10-23"}):
            payload = {"numero_bm": 1, "parcela_paga": 1, "valor_pago": "100,00", "data_pagamento": "2026-10-23", **data}
            form = BMForm(payload)
            self.assertFalse(form.is_valid(), form.errors)

    def test_decimal_dot_and_comma_have_same_meaning(self):
        for value in ("1500.00", "1.500,00"):
            form = SolicitacaoAditivoContratoTerceiroForm({"motivo": "teste", "novo_valor_total": value})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data["novo_valor_total"], Decimal("1500.00"))

    def test_upload_rejects_disguised_html(self):
        self.client.force_login(self.supply)
        request = SolicitacaoContrato.objects.create(contrato=self.project, fornecedor_escolhido=self.contract.empresa_terceira)
        response = self.client.post(reverse("cadastrar_minuta_contrato", args=[request.pk]), {
            "arquivo_contrato": SimpleUploadedFile("falso.pdf", b"<script>alert(1)</script>", content_type="application/pdf"),
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(DocumentoContratoTerceiro.objects.exists())

    @override_settings(MAX_UPLOAD_BYTES=8)
    def test_upload_size_limit_is_enforced(self):
        self.client.force_login(self.supply)
        response = self.client.post(reverse("novo_fornecedor"), {"arquivo": pdf()})
        self.assertEqual(response.status_code, 400)

    def test_anonymous_minute_view_redirects_to_login(self):
        response = self.client.get(reverse("cadastrar_minuta_contrato", args=[123]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("login")))

    def test_excel_exports_untrusted_names_as_text(self):
        supplier = self.contract.empresa_terceira
        supplier.nome = '=HYPERLINK("https://example.invalid","teste")'
        supplier.save()
        self.event.data_prevista_pagamento = date(2026, 10, 23)
        self.event.save()
        self.client.force_login(self.finance)
        response = self.client.get(reverse("exportar_previsao_pagamentos_excel"), {"data_inicial": "2026-10-01", "data_limite": "2026-10-31"})
        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(response.content), data_only=False)
        cell = workbook.worksheets[0]["D2"]
        self.assertTrue(cell.value.startswith("="))
        self.assertEqual(cell.data_type, "s")

    def test_partial_supplier_evaluation_does_not_crash_indicators(self):
        AvaliacaoFornecedor.objects.create(empresa_terceira=self.contract.empresa_terceira, contrato_terceiro=self.contract, nota_gestao=5)
        indicator = Indicadores(empresa_terceira=self.contract.empresa_terceira)
        self.assertEqual(indicator.IS_gestao, 100)
        self.assertEqual(indicator.IS_tecnica, 0)

    def test_smtp_failure_does_not_raise_or_expose_payload(self):
        with patch("gestao_contratos.views.django_send_mail", side_effect=OSError("segredo-smtp")):
            self.assertEqual(send_mail("teste", "conteúdo", "origem@example.com", [self.leader.email]), 0)

    def test_initial_request_cannot_skip_supplier_approval_by_uploading_draft(self):
        request = SolicitacaoContrato.objects.create(
            contrato=self.project, lider_contrato=self.leader,
            fornecedor_escolhido=self.contract.empresa_terceira, status="Solicitação de contratação",
            data_inicio=date(2026, 10, 1), data_fim=date(2026, 12, 31),
        )
        self.client.force_login(self.supply)
        self.client.post(reverse("cadastrar_minuta_contrato", args=[request.pk]), {
            "numero_contrato": "PULO", "objeto": "Não pode pular", "valor_total": "100,00", "arquivo_contrato": pdf(),
        })
        self.assertFalse(DocumentoContratoTerceiro.objects.filter(solicitacao_contrato=request).exists())
        self.client.post(reverse("inserir_minuta_bm_contrato", args=[request.pk]), {"minuta_boletim": pdf()})
        self.assertFalse(DocumentoBM.objects.filter(solicitacao_contrato=request).exists())

    def test_signed_upload_is_not_authorized_by_a_hidden_button(self):
        request = SolicitacaoContrato.objects.create(
            contrato=self.project, fornecedor_escolhido=self.contract.empresa_terceira,
            status="Planejamento do Contrato", data_inicio=date(2026, 10, 1), data_fim=date(2026, 12, 31),
        )
        self.client.force_login(self.supply)
        self.client.post(reverse("cadastrar_minuta_contrato", args=[request.pk]), {
            "numero_contrato": "ASS-SPOOF", "objeto": "Não aprovado", "valor_total": "100,00", "arquivo_contrato_assinado": pdf(),
        })
        self.assertFalse(ContratoTerceiros.objects.filter(solicitacao=request).exists())
        self.assertFalse(DocumentoContratoTerceiro.objects.filter(solicitacao_contrato=request).exists())

    def test_supplier_choice_must_belong_to_screened_candidates(self):
        request = SolicitacaoProspeccao.objects.create(
            contrato=self.project, lider_contrato=self.leader, aprovado=True,
            triagem_realizada=True, status="Triagem realizada",
        )
        candidate = self.create_supplier(nome="Candidato triado")
        request.fornecedores_selecionados.add(candidate)
        self.client.force_login(self.leader)
        response = self.client.post(reverse("detalhes_triagem_fornecedores", args=[request.pk]), {
            "fornecedor_escolhido": self.contract.empresa_terceira_id, "justificativa_fornecedor_escolhido": "POST manual",
        })
        self.assertEqual(response.status_code, 404)
        request.refresh_from_db()
        self.assertIsNone(request.fornecedor_escolhido_id)

    def test_completed_request_cannot_be_reapproved_to_reopen_flow(self):
        request = SolicitacaoContrato.objects.create(
            contrato=self.project, fornecedor_escolhido=self.contract.empresa_terceira,
            status="Onboarding", aprovacao_fornecedor_gerente="aprovado", aprovacao_fornecedor_diretor="aprovado",
        )
        self.client.force_login(self.manager)
        self.client.post(reverse("detalhes_solicitacao_contrato", args=[request.pk]), {"acao": "reprovar", "justificativa": "POST antigo"})
        request.refresh_from_db()
        self.assertEqual(request.status, "Onboarding")
        self.assertEqual(request.aprovacao_fornecedor_gerente, "aprovado")

    def test_get_draft_form_does_not_create_business_data(self):
        request = SolicitacaoContrato.objects.create(contrato=self.project, status="Planejamento do Contrato")
        self.client.force_login(self.supply)
        response = self.client.get(reverse("inserir_minuta_bm_contrato", args=[request.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DocumentoBM.objects.exists())

    def test_absent_manager_does_not_override_bm_operational_rejection(self):
        self.manager.gerente_contrato_ausente = True
        self.manager.save()
        bm = self.bm(status_coordenador="reprovado", status_gerente="pendente", aprovacao_pagamento="pendente")
        self.client.force_login(self.director)
        response = self.client.post(reverse("avaliar_bm", args=[bm.pk]), {"acao": "aprovar_pagamento"})
        self.assertEqual(response.status_code, 400)
        bm.refresh_from_db()
        self.assertEqual(bm.aprovacao_pagamento, "pendente")

    def test_manager_from_another_center_cannot_open_os_details(self):
        outsider = self.create_user("audit_other_manager", "gerente")
        os = self.create_os(contrato=self.contract, lider_contrato=self.leader)
        self.client.force_login(outsider)
        response = self.client.get(reverse("detalhes_os", args=[os.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home"))

    def test_every_registered_admin_search_resolves_its_field_paths(self):
        request = RequestFactory().get("/admin/", {"q": "auditoria"})
        request.user = self.supply
        for model, model_admin in admin.site._registry.items():
            if model._meta.app_label != "gestao_contratos":
                continue
            with self.subTest(model=model.__name__):
                queryset, _ = model_admin.get_search_results(request, model.objects.none(), "auditoria")
                self.assertEqual(list(queryset), [])

    def test_backup_uses_consistent_sqlite_snapshot_and_import_has_no_effect(self):
        import backup_diario
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "source.sqlite3"
            with closing(sqlite3.connect(database)) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("CREATE TABLE sample (value INTEGER)")
                conn.execute("INSERT INTO sample VALUES (42)")
                conn.commit()
                backup = backup_diario.create_backup(database, root / "backups")
            with closing(sqlite3.connect(backup)) as conn:
                self.assertEqual(conn.execute("SELECT value FROM sample").fetchone(), (42,))
            unrelated = root / "backups" / "preservar.txt"
            unrelated.write_text("preservar")
            backup_diario.cleanup_backups(root / "backups", retention_days=1)
            self.assertTrue(unrelated.exists())
