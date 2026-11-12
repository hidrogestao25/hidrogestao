"""Homologação das regras confirmadas em 23/10/2026, somente em banco de testes."""
from datetime import date
from decimal import Decimal
from io import BytesIO
import zipfile

from django.apps import apps
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import FileField
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from . import models as m
from .permissions import can_access_document
from .test_auditoria import pdf
from .tests import BaseUserTestCase
from .views import calculate_contract_payment_totals


class HomologacaoTests(BaseUserTestCase):
    def setUp(self):
        self.supply = self.create_user("hom_supply", "suprimento")
        self.finance = self.create_user("hom_finance", "financeiro")
        self.leaders = [self.create_user(f"hom_leader_{i}", "lider_contrato") for i in range(2)]
        self.coords = [self.create_user(f"hom_coord_{i}", "coordenador") for i in range(2)]
        self.centers = [self.create_center(f"H{i}", f"Centro {i}") for i in range(2)]
        self.supplier = self.create_supplier()
        self.projects, self.contracts, self.events, self.bms = [], [], [], []
        for i, amount in enumerate(("60000.00", "40000.00")):
            self.coords[i].centros.add(self.centers[i])
            project = self.create_contract(codigo=f"HOM-{i}", coordenador=self.coords[i], lider_contrato=self.leaders[i])
            contract = self.create_supplier_contract(cod_projeto=project, empresa_terceira=self.supplier,
                coordenador=self.coords[i], lider_contrato=self.leaders[i], num_contrato=f"HOM-C{i}")
            contract.valor_total = Decimal(amount)
            contract.save()
            event = self.create_event(contrato=contract)
            event.valor_previsto = Decimal(amount)
            event.data_prevista_pagamento = timezone.localdate()
            event.save()
            bm = m.BM.objects.create(contrato=contract, evento=event, numero_bm=10, parcela_paga=1,
                valor_pago=Decimal(amount), arquivo_bm=pdf(f"bm_{i}.pdf"),
                status_gerente="aprovado", data_aprovacao_gerente=timezone.now(), aprovacao_pagamento="aprovado")
            self.projects.append(project)
            self.contracts.append(contract)
            self.events.append(event)
            self.bms.append(bm)

    def document_inventory(self, i):
        project, contract, event, bm = self.projects[i], self.contracts[i], self.events[i], self.bms[i]
        request = m.SolicitacaoContrato.objects.create(contrato=project, coordenador=self.coords[i], lider_contrato=self.leaders[i])
        prospect = m.SolicitacaoProspeccao.objects.create(contrato=project, coordenador=self.coords[i], lider_contrato=self.leaders[i])
        os_request = self.create_os_request(contrato=contract, solicitante=self.leaders[i], lider_contrato=self.leaders[i])
        os_obj = self.create_os(contrato=contract, solicitacao=os_request)
        documents = [request, prospect, contract, event, bm, os_request, os_obj,
            m.PropostaFornecedor.objects.create(solicitacao=prospect, fornecedor=self.supplier),
            m.DocumentoBM.objects.create(solicitacao_contrato=request),
            m.NF.objects.create(contrato=contract, evento=event, bm=bm, parcela_paga=1),
            m.NFCliente.objects.create(contrato=project, parcela_paga=1),
            m.DocumentoContrato.objects.create(contrato=project, arquivo=pdf(f"cliente_{i}.pdf")),
            m.DocumentoContratoTerceiro.objects.create(solicitacao_contrato=request, numero_contrato=f"MIN-{i}",
                objeto="Minuta", prazo_inicio=date(2026, 1, 1), prazo_fim=date(2026, 12, 31), valor_total=100),
            m.AditivoContratoTerceiro.objects.create(contrato=contract, solicitado_por=self.leaders[i], motivo="Homologação")]
        result = {}
        for obj in documents:
            for field in obj._meta.fields:
                if isinstance(field, FileField):
                    key = (obj._meta.model_name, field.name)
                    field_file = getattr(obj, field.name)
                    if not field_file:
                        field_file.save(f"{i}_{obj._meta.model_name}_{field.name}.pdf", pdf(), save=True)
                    result[key] = (obj, field_file.name)
        from .payment_services import record_payment,renegotiate
        invoice=m.NF.objects.create(contrato=contract,evento=event,bm=bm,parcela_paga=1,valor_pago=100)
        movement,_=record_payment(nf_id=invoice.pk,user=self.finance,valor=10,data_pagamento=timezone.localdate(),comprovante=pdf(),key='inventory-payment-'+str(i))
        agreement,_=renegotiate(nf_id=invoice.pk,user=self.finance,novo_vencimento=date(2027,1,15),motivo='Inventário de privacidade',documento=pdf(),key='inventory-agreement-'+str(i))
        result[('pagamentonf','comprovante')]=(movement,movement.comprovante.name)
        result[('reprogramacaopagamento','documento')]=(agreement,agreement.documento.name)
        return result

    def assert_download(self, path, status):
        for prefix in ("/arquivos/", "/media/"):
            response = self.client.get(prefix + path)
            self.assertEqual(response.status_code, status, (prefix, path, response.status_code))
            if status == 200:
                self.assertIn("attachment", response["Content-Disposition"])
                self.assertEqual(response["Cache-Control"], "private, no-store")
                response.close()

    def test_inventory_covers_every_filefield(self):
        expected = {(model._meta.model_name, field.name)
            for model in apps.get_app_config("gestao_contratos").get_models()
            for field in model._meta.fields if isinstance(field, FileField)}
        inventory = self.document_inventory(0)
        self.assertEqual(set(inventory), expected)
        self.assertEqual(len(inventory), 21)

    def test_document_idor_matrix_all_filefields_and_both_endpoints(self):
        own, other = self.document_inventory(0), self.document_inventory(1)
        for user in (self.leaders[0], self.coords[0]):
            self.client.force_login(user)
            for key, (_, path) in own.items():
                with self.subTest(role=user.grupo, field=key):
                    self.assert_download(path, 200)
                    self.assert_download(other[key][1], 404)

    def test_global_roles_and_superuser_can_download_all_types(self):
        inventories = [self.document_inventory(i) for i in range(2)]
        users = [self.supply, self.finance, self.create_user("hom_director", "diretoria"),
                 self.create_user("hom_manager", "gerente_contrato")]
        admin = self.create_user("hom_admin", "")
        admin.is_superuser = admin.is_staff = True
        admin.save()
        for user in [*users, admin]:
            self.client.force_login(user)
            for inventory in inventories:
                for key, (_, path) in inventory.items():
                    with self.subTest(role=user.grupo or "superuser", field=key):
                        self.assert_download(path, 200)

    def test_center_managers_keep_only_their_center_documents(self):
        own, other = self.document_inventory(0), self.document_inventory(1)
        for role in ("gerente", "gerente_lider"):
            user = self.create_user(f"hom_{role}", role)
            user.centros.add(self.centers[0])
            self.client.force_login(user)
            for key, (_, path) in own.items():
                with self.subTest(role=role, field=key):
                    self.assert_download(path, 200)
                    self.assert_download(other[key][1], 404)

    def test_anonymous_no_role_inactive_and_staff_permissions(self):
        inventory = self.document_inventory(0)
        for _, path in inventory.values():
            self.assert_download(path, 302)
        for role in ("", "fornecedor"):
            self.client.force_login(self.create_user(f"hom_denied_{role}", role))
            for _, path in inventory.values():
                self.assert_download(path, 404)
        self.supply.is_active = False
        self.supply.save()
        self.assertFalse(can_access_document(self.supply, self.bms[0]))
        staff = self.create_user("hom_staff", "")
        staff.is_staff = True
        staff.save()
        staff.user_permissions.add(Permission.objects.get(codename="view_bm"))
        self.client.force_login(staff)
        self.assert_download(self.bms[0].arquivo_bm.name, 200)
        self.assert_download(inventory[("nf", "arquivo_nf")][1], 404)

    def test_umbrella_catalog_does_not_grant_document_or_other_os_access(self):
        umbrella = m.ContratoTerceiros.objects.create(empresa_terceira=self.supplier, guarda_chuva=True, objeto="Guarda-chuva", num_contrato_arquivo=pdf())
        orders = [self.create_os(contrato=self.contracts[i]) for i in range(2)]
        for order in orders:
            order.contrato = umbrella
            order.arquivo_os = pdf()
            order.save()
        self.client.force_login(self.leaders[0])
        self.assert_download(orders[0].arquivo_os.name, 200)
        self.assert_download(orders[1].arquivo_os.name, 404)
        self.assert_download(umbrella.num_contrato_arquivo.name, 404)

    def filters(self):
        today = timezone.localdate().isoformat()
        return {"data_inicial": today, "data_limite": today}

    def test_same_number_and_shared_file_sum_participations_not_document_total(self):
        second = self.bms[1]
        second.arquivo_bm = self.bms[0].arquivo_bm.name
        second.save()
        second.status_gerente = second.aprovacao_pagamento = "aprovado"
        second.data_aprovacao_gerente = timezone.now()
        second.save()
        self.client.force_login(self.finance)
        response = self.client.get(reverse("previsao_pagamentos"), self.filters())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_bm_pago"], Decimal("100000.00"))
        self.assertEqual(response.context["total_bm_previsto"], Decimal("100000.00"))
        self.assertEqual(response.context["total_previsto"], Decimal("100000.00"))
        response = self.client.get(reverse("download_bms_aprovados"), self.filters())
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            self.assertEqual(len(archive.namelist()), 1)
        for user in self.leaders:
            self.client.force_login(user)
            self.assert_download(second.arquivo_bm.name, 200)

    def test_planned_origin_is_not_repeated_for_multiple_bm_installments(self):
        m.BM.objects.create(contrato=self.contracts[0], evento=self.events[0], numero_bm=11,
            parcela_paga=2, valor_pago=0, status_gerente="aprovado", data_aprovacao_gerente=timezone.now())
        self.client.force_login(self.finance)
        response = self.client.get(reverse("previsao_pagamentos"), self.filters())
        self.assertEqual(response.context["total_bm_previsto"], Decimal("100000.00"))

    def test_cross_contract_bm_financial_owner_is_event_and_nf_follows_it(self):
        bm = m.BM.objects.create(contrato=self.contracts[1], evento=self.events[0], numero_bm=20,
                                 valor_pago=123, parcela_paga=2)
        self.assertEqual(bm.contrato_financeiro, self.contracts[0])
        self.assertEqual(bm.total_pago, Decimal("60123.00"))
        self.assertEqual(self.bms[1].total_pago, Decimal("40000.00"))
        self.assertTrue(can_access_document(self.leaders[0], bm))
        self.assertTrue(can_access_document(self.leaders[1], bm))
        self.client.force_login(self.finance)
        self.post_nf(self.events[0], bm, "120,00", paid=False)
        nf = m.NF.objects.get()
        self.assertEqual(nf.contrato, self.contracts[0])
        self.assertTrue(can_access_document(self.leaders[0], nf))
        self.assertFalse(can_access_document(self.leaders[1], nf))
        with self.assertRaises(ValidationError):
            m.NF.objects.create(contrato=self.contracts[1], evento=self.events[0], bm=bm, parcela_paga=1)

    def post_nf(self, event, bm, amount, nf=None, paid=True):
        url = reverse("editar_nf", args=[nf.pk]) if nf else reverse("cadastrar_nf", args=[event.pk])
        payload = {"justificativa_correcao":"Correção sintética conferida", "bm": bm.pk, "valor_pago": amount, "parcela_paga": 1, "data_pagamento": timezone.localdate().isoformat()}
        if paid:
            payload["financeiro_autorizou"] = "on"
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"], response.content)
        return m.NF.objects.filter(evento=event).latest("pk")

    def assert_paid(self, event, paid):
        event.refresh_from_db()
        self.assertEqual(event.valor_pago, Decimal(paid))
        totals = calculate_contract_payment_totals([event.contrato_terceiro])
        self.assertEqual(totals["valor_pago"], Decimal(paid))
        self.assertEqual(totals["valor_previsto"], event.valor_previsto - Decimal(paid))

    def test_nf_paid_edit_unpay_delete_sequence_on_shared_bm_and_balances(self):
        self.client.force_login(self.finance)
        self.post_nf(self.events[1], self.bms[1], "25000,00")
        first = self.post_nf(self.events[0], self.bms[0], "10000,00")
        self.assert_paid(self.events[0], "10000.00")
        second = self.post_nf(self.events[0], self.bms[0], "5000,00")
        self.assert_paid(self.events[0], "15000.00")
        # Os valores continuam sendo participações; correções pagas cabem a Suprimento.
        self.client.force_login(self.supply)
        self.post_nf(self.events[0], self.bms[0], "12000,00", nf=first)
        self.assert_paid(self.events[0], "15000.00")
        self.post_nf(self.events[0], self.bms[0], "5000,00", nf=second, paid=False)
        self.assert_paid(self.events[0], "10000.00")
        self.assertEqual(self.client.post(reverse("deletar_nf", args=[first.pk]), {"justificativa_correcao":"Exclusão sintética conferida"}).status_code, 302)
        self.assert_paid(self.events[0], "0.00")
        self.assertIsNone(self.events[0].data_pagamento)
        self.assert_paid(self.events[1], "25000.00")
        response = self.client.get(reverse("exportar_previsao_pagamentos_excel"), self.filters())
        workbook = load_workbook(BytesIO(response.content))
        rows = list(workbook.active.iter_rows(values_only=True))
        planned = sum(Decimal(str(row[5] or 0)) for row in rows[1:] if row[0] == "Evento")
        self.assertEqual(planned, Decimal("100000.00"))

    def test_zip_restricted_roles_cannot_collect_foreign_contract_files(self):
        # Distinct contents ensure ZIP's legitimate binary deduplication cannot
        # hide a missing authorization check.
        self.bms[1].arquivo_bm.save("outro.pdf", SimpleUploadedFile("outro.pdf", b"%PDF-1.4\noutro contrato"), save=True)
        for user in (self.leaders[0], self.coords[0]):
            self.client.force_login(user)
            response = self.client.get(reverse("download_bms_aprovados"), self.filters())
            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(BytesIO(response.content)) as archive:
                self.assertEqual(len(archive.namelist()), 1)
                self.assertTrue(archive.namelist()[0].startswith("HOM-0_"))

    def post_as(self, user, route, args, payload=None):
        self.client.force_login(user)
        response = self.client.post(reverse(route, args=args), payload or {})
        self.assertIn(response.status_code, (200, 302), (route, response.content[:1000]))
        if response.status_code == 200 and response.context and response.context.get("form"):
            self.assertFalse(response.context["form"].errors, (route, response.context["form"].errors))
        if response.status_code == 200 and response.get("Content-Type", "").startswith("application/json"):
            self.assertTrue(response.json().get("success"), response.content)
        return response

    def test_cross_contract_report_filter_follows_event_coordinator(self):
        bm = m.BM.objects.create(contrato=self.contracts[1], evento=self.events[0], numero_bm=30,
            parcela_paga=2, valor_pago=100, status_gerente="aprovado", data_aprovacao_gerente=timezone.now())
        from .test_bm_duas_liderancas import approve_shared_fixture
        approve_shared_fixture(self,bm)
        self.client.force_login(self.finance)
        for i in range(2):
            response = self.client.get(reverse("previsao_pagamentos"), {**self.filters(), "coordenador": self.coords[i].pk})
            ids = {obj.pk for obj in response.context["bms"]}
            self.assertEqual(bm.pk in ids, i == 0)

    def test_saving_only_approval_keeps_default_payment_date_and_decision(self):
        bm = m.BM.objects.create(contrato=self.contracts[0], evento=self.events[0], numero_bm=31,
                                 parcela_paga=2, valor_pago=100)
        bm.status_gerente = "aprovado"
        bm.save()
        bm.refresh_from_db()
        self.assertEqual(bm.status_gerente, "aprovado")

    def test_os_request_approvals_draft_double_submit_delivery_and_bm_reset(self):
        manager = self.create_user("hom_flow_manager", "gerente_contrato")
        director = self.create_user("hom_flow_director", "diretoria")
        contract = self.contracts[0]
        contract.guarda_chuva = True
        contract.save()
        self.post_as(self.leaders[0], "solicitar_os", [contract.pk], {
            "contrato": contract.pk, "cod_projeto": self.projects[0].pk,
            "titulo": "OS fluxo completo", "descricao": "Escopo", "valor_previsto": "500,00",
            "data_prevista_pagamento": "2026-11-01", "prazo_execucao": "2026-11-02"})
        request = m.SolicitacaoOrdemServico.objects.get(titulo="OS fluxo completo")
        for user, route, status in ((manager, "aprovar_os_gerente_contrato", "pendente_diretoria"),
                                    (director, "aprovar_os_diretoria", "pendente_suprimento")):
            self.post_as(user, route, [request.pk, "aprovar"])
            request.refresh_from_db()
            self.assertEqual(request.status, status)
        self.post_as(self.supply, "upload_contrato_os", [request.pk], {"arquivo_os": pdf("minuta.pdf")})
        request.refresh_from_db()
        self.assertEqual(request.status, "pendente_minuta_gerente")
        for _ in range(2):
            self.post_as(manager, "aprovar_os_gerente_contrato", [request.pk, "aprovar"])
        order = m.OS.objects.get(solicitacao=request)
        self.assertEqual(m.OS.objects.filter(solicitacao=request).count(), 1)
        self.client.force_login(self.leaders[1])
        self.assert_download(order.arquivo_os.name, 404)
        self.post_as(self.leaders[0], "registrar_entrega_os", [order.pk], {
            "data_entrega": "2026-11-01", "avaliacao": "Aprovado", "caminho_evidencia": "evidencia", "realizado": "on"})
        order.refresh_from_db()
        self.assertTrue(order.realizado)
        self.assertEqual(order.status, "finalizada")
        self.post_as(self.supply, "cadastrar_bm_os", [order.pk], {
            "numero_bm": 32, "parcela_paga": 1, "valor_pago": "500,00", "data_pagamento": "2026-11-03", "arquivo_bm": pdf()})
        bm = m.BM.objects.get(os=order)
        self.post_as(self.leaders[0], "avaliar_bm", [bm.pk], {"acao": "aprovar"})
        self.post_as(director, "avaliar_bm", [bm.pk], {"acao": "aprovar_pagamento"})
        bm.refresh_from_db()
        self.assertEqual(bm.status_coordenador, "aprovado")
        self.assertEqual(bm.aprovacao_pagamento, "aprovado")
        bm.valor_pago = Decimal("450.00")
        bm.save()
        bm.refresh_from_db()
        self.assertEqual((bm.status_coordenador, bm.status_gerente, bm.aprovacao_pagamento), ("pendente",) * 3)
        self.assertIsNone(bm.data_aprovacao_diretor)

    def test_two_complete_addenda_and_reapplication_of_older_document(self):
        manager = self.create_user("hom_ad_manager", "gerente_contrato")
        director = self.create_user("hom_ad_director", "diretoria")
        contract = self.contracts[0]
        contract.data_fim = date(2026, 12, 31)
        contract.save()
        completed = []
        for i, amount in enumerate(("100,00", "200,00")):
            self.post_as(self.leaders[0], "solicitar_aditivo_contrato", [contract.pk], {
                "motivo": f"Ampliação {i}", "novo_valor_total": amount, "nova_data_fim": f"2027-0{i+1}-28"})
            ad = m.AditivoContratoTerceiro.objects.latest("pk")
            for user, action in ((manager, "aprovar_gerente"), (director, "aprovar_diretoria")):
                self.post_as(user, "avaliar_solicitacao_aditivo_contrato", [ad.pk], {"acao": action})
            self.post_as(self.supply, "enviar_documento_aditivo_contrato", [ad.pk], {"arquivo_aditivo": pdf()})
            self.post_as(manager, "avaliar_minuta_aditivo_contrato", [ad.pk], {"acao": "aprovar_minuta"})
            self.post_as(self.supply, "enviar_aditivo_assinado_contrato", [ad.pk], {"arquivo_aditivo_assinado": pdf()})
            ad.refresh_from_db()
            self.assertTrue(ad.aprovado_totalmente)
            completed.append(ad)
        contract.refresh_from_db()
        self.assertEqual(contract.valor_total, Decimal("60300.00"))
        self.assertEqual(contract.data_fim, date(2027, 2, 28))
        for ad in reversed(completed):
            self.post_as(self.supply, "enviar_aditivo_assinado_contrato", [ad.pk], {"arquivo_aditivo_assinado": pdf()})
            contract.refresh_from_db()
            self.assertEqual(contract.valor_total, Decimal("60300.00"))
            self.assertEqual(contract.data_fim, date(2027, 2, 28))

    def request_payload(self):
        return {"contrato": self.projects[0].pk, "coordenador": self.coords[0].pk,
            "descricao": "Solicitação homologação", "requisitos": "Escopo", "valor_disponivel": "1000,00",
            "data_inicio": "01-11-2026", "data_fim": "01-12-2026", "forma_pagamento": "30",
            "justificativa_orcamento": "Homologação", "justificativa_fornecedor_escolhido": "Qualificação"}

    def event_payload(self):
        return {"descricao": "Planejamento homologação", "valor_previsto": "1000,00",
            "data_prevista": "2026-11-15", "data_prevista_pagamento": "2026-11-20"}

    def test_direct_hiring_request_planning_drafts_approvals_signature_and_delivery(self):
        manager = self.create_user("hom_hire_manager", "gerente_contrato")
        director = self.create_user("hom_hire_director", "diretoria")
        self.post_as(self.leaders[0], "nova_solicitacao_contrato", [], {
            **self.request_payload(), "fornecedor_escolhido": self.supplier.pk})
        request = m.SolicitacaoContrato.objects.get(descricao="Solicitação homologação")
        self.post_as(self.leaders[0], "cadastrar_evento_solicitacao", [request.pk], self.event_payload())
        for user in (manager, director):
            self.post_as(user, "detalhes_solicitacao_contrato", [request.pk], {"acao": "aprovar"})
        request.refresh_from_db()
        self.assertEqual(request.status, "Fornecedor aprovado")
        self.post_as(self.supply, "inserir_minuta_bm_contrato", [request.pk], {"minuta_boletim": pdf()})
        contract_payload = {"numero_contrato": "HOM-NEW", "objeto": "Escopo", "valor_total": "1000,00"}
        self.post_as(self.supply, "cadastrar_minuta_contrato", [request.pk], {**contract_payload, "arquivo_contrato": pdf()})
        doc_bm = m.DocumentoBM.objects.get(solicitacao_contrato=request)
        self.post_as(manager, "detalhe_bm_contrato", [doc_bm.pk], {"acao": "aprovar"})
        self.post_as(manager, "detalhes_minuta_contrato", [request.pk], {"acao": "aprovar"})
        self.post_as(self.supply, "cadastrar_minuta_contrato", [request.pk], {**contract_payload, "arquivo_contrato_assinado": pdf()})
        contract = m.ContratoTerceiros.objects.get(solicitacao=request)
        request.refresh_from_db()
        self.assertEqual(request.status, "Onboarding")
        event = m.Evento.objects.get(solicitacao_contrato=request)
        self.assertEqual(event.contrato_terceiro, contract)
        self.post_as(self.leaders[0], "registrar_entrega", [event.pk], {
            "avaliacao": "Aprovado", "data_entrega": "2026-11-15", "realizado": "on", "arquivo": pdf("evidencia.pdf")})
        event.refresh_from_db()
        self.assertTrue(event.realizado)

    def test_prospect_request_approval_triage_proposal_selection_and_management(self):
        manager = self.create_user("hom_prospect_manager", "gerente_contrato")
        director = self.create_user("hom_prospect_director", "diretoria")
        self.post_as(self.leaders[0], "nova_solicitacao_prospeccao", [], self.request_payload())
        request = m.SolicitacaoProspeccao.objects.get(descricao="Solicitação homologação")
        self.post_as(self.leaders[0], "cadastrar_evento", [request.pk], self.event_payload())
        self.post_as(self.supply, "aprovar_solicitacao", [request.pk, "aprovar"])
        self.post_as(self.supply, "triagem_fornecedores", [request.pk], {
            "fornecedores": [self.supplier.pk], f"valor_{self.supplier.pk}": "1000,00",
            f"arquivo_{self.supplier.pk}": pdf("proposta.pdf"), f"condicao_{self.supplier.pk}": "A definir"})
        request.refresh_from_db()
        self.assertTrue(request.triagem_realizada)
        self.assertTrue(m.PropostaFornecedor.objects.filter(solicitacao=request, fornecedor=self.supplier).exists())
        self.post_as(self.leaders[0], "detalhes_triagem_fornecedores", [request.pk], {
            "fornecedor_escolhido": self.supplier.pk, "justificativa_fornecedor_escolhido": "Qualificado"})
        for user, route in ((manager, "aprovar_fornecedor_gerente"), (director, "aprovar_fornecedor_diretor")):
            self.post_as(user, route, [request.pk], {"acao": "aprovar"})
        request.refresh_from_db()
        self.assertEqual(request.status, "Fornecedor aprovado")

    def test_supplier_create_edit_and_consult(self):
        payload = {"nome": "Fornecedor homologação", "cpf_cnpj": "22.222.222/0001-22",
            "informacoes_bancarias": "Banco homologação", "email": "homologacao@example.com"}
        self.post_as(self.supply, "novo_fornecedor", [], payload)
        supplier = m.EmpresaTerceira.objects.get(cpf_cnpj=payload["cpf_cnpj"])
        self.post_as(self.supply, "fornecedor_detalhe", [supplier.pk], {**payload, "nome": "Fornecedor editado"})
        supplier.refresh_from_db()
        self.assertEqual(supplier.nome, "FORNECEDOR EDITADO")
        self.assertContains(self.client.get(reverse("fornecedor_detalhe", args=[supplier.pk])), "FORNECEDOR EDITADO")

    def test_get_actions_and_forms_do_not_write_business_state(self):
        request = m.SolicitacaoContrato.objects.create(contrato=self.projects[0], lider_contrato=self.leaders[0],
            fornecedor_escolhido=self.supplier, data_inicio=date(2026, 1, 1), data_fim=date(2026, 12, 31), status="Fornecedor aprovado")
        prospect = m.SolicitacaoProspeccao.objects.create(contrato=self.projects[0], lider_contrato=self.leaders[0])
        os_request = self.create_os_request(contrato=self.contracts[0], solicitante=self.leaders[0])
        order = self.create_os(contrato=self.contracts[0])
        nf = m.NF.objects.create(contrato=self.contracts[0], evento=self.events[0], bm=self.bms[0], parcela_paga=1)
        ad = m.AditivoContratoTerceiro.objects.create(contrato=self.contracts[0], solicitado_por=self.leaders[0], motivo="GET")
        manager = self.create_user("hom_get_manager", "gerente_contrato")
        director = self.create_user("hom_get_director", "diretoria")
        routes = [(self.supply, "cadastrar_minuta_contrato", [request.pk]),
            (self.supply, "inserir_minuta_bm_contrato", [request.pk]),
            (self.supply, "triagem_fornecedores", [prospect.pk]),
            (self.supply, "aprovar_solicitacao", [prospect.pk, "aprovar"]),
            (self.supply, "duplicar_evento_contrato", [self.events[0].pk]),
            (self.supply, "excluir_evento_contrato", [self.events[0].pk]),
            (self.finance, "deletar_nf", [nf.pk]), (self.finance, "deletar_bm", [self.bms[0].pk]),
            (manager, "aprovar_os_gerente_contrato", [os_request.pk, "aprovar"]),
            (director, "aprovar_os_diretoria", [os_request.pk, "aprovar"]),
            (manager, "avaliar_bm", [self.bms[0].pk]),
            (self.supply, "enviar_aditivo_assinado_contrato", [ad.pk]),
            (self.supply, "enviar_documento_aditivo_contrato", [ad.pk]),
            (manager, "avaliar_minuta_aditivo_contrato", [ad.pk]),
            (self.leaders[0], "registrar_entrega_os", [order.pk]),
            (self.supply, "duplicar_os_cadastrada", [order.pk])]
        business_models = [model for model in apps.get_app_config("gestao_contratos").get_models()
                           if model not in (m.User, m.ChaveIdempotencia)]
        def snapshot():
            return {model._meta.label: list(model.objects.order_by("pk").values()) for model in business_models}
        for user, route, args in routes:
            self.client.force_login(user)
            before = snapshot()
            response = self.client.get(reverse(route, args=args))
            with self.subTest(route=route):
                self.assertLess(response.status_code, 500)
                self.assertEqual(snapshot(), before)

    def test_bm_and_nf_form_replay_is_blocked_for_event_and_os(self):
        order = self.create_os(contrato=self.contracts[0])
        self.client.force_login(self.finance)
        payload = {"numero_bm": 45, "valor_pago": "100,00", "parcela_paga": 1,
                   "data_pagamento": "2026-11-01", "financeiro_autorizou": "on"}
        cases = [("cadastrar_bm", [self.contracts[0].pk, self.events[0].pk], m.BM),
                 ("cadastrar_bm_os", [order.pk], m.BM),
                 ("cadastrar_nf", [self.events[0].pk], m.NF),
                 ("cadastrar_nf_os", [order.pk], m.NF)]
        for route, args, model in cases:
            url = reverse(route, args=args)
            page = self.client.get(url)
            token = page.context["submission_token"]
            data = {**payload, "submission_token": token}
            if model is m.NF:
                bm = self.bms[0] if route == "cadastrar_nf" else m.BM.objects.get(os=order)
                bm.status_gerente = bm.aprovacao_pagamento = "aprovado"
                bm.save()
                data["bm"] = bm.pk
            count = model.objects.count()
            first_response = self.client.post(url, data)
            self.assertEqual(first_response.status_code, 200)
            self.assertTrue(first_response.json()["success"], first_response.content)
            cache.clear()
            self.assertEqual(self.client.post(url, data).status_code, 409)
            self.assertEqual(model.objects.count(), count + 1)
        self.events[0].refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.events[0].valor_pago, Decimal("100.00"))
        self.assertEqual(order.valor_pago, Decimal("100.00"))

    def test_new_submission_token_allows_intentional_equal_nf_participations(self):
        self.client.force_login(self.finance)
        url = reverse("cadastrar_nf", args=[self.events[0].pk])
        for _ in range(2):
            page = self.client.get(url)
            response = self.client.post(url, {"submission_token": page.context["submission_token"],
                "bm": self.bms[0].pk, "valor_pago": "100,00", "parcela_paga": 1,
                "data_pagamento": "2026-11-01", "financeiro_autorizou": "on"})
            self.assertTrue(response.json()["success"], response.content)
        self.assertEqual(m.NF.objects.count(), 2)
        self.events[0].refresh_from_db()
        self.assertEqual(self.events[0].valor_pago, Decimal("200.00"))
