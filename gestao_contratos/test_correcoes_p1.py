"""Regressões P1 — exclusivamente fixtures, uploads temporários e e-mail locmem."""
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.utils import IntegrityError
from django.forms.models import model_to_dict
from django.test import RequestFactory
from django.urls import reverse
from openpyxl import load_workbook

from . import models as m, financial_queries as fq, payment_queries as pq, payment_services as payments
from . import prospeccao_services as prospects
from . import test_financeiro_fase2 as fixtures
from .tests import BaseUserTestCase


class CorrecoesP1Tests(BaseUserTestCase):
    bm = fixtures.FinanceiroFase2Tests.bm
    nf = fixtures.FinanceiroFase2Tests.nf

    def setUp(self):
        fixtures.FinanceiroFase2Tests.setUp(self)
        self.evidence = {}
        self.manager = self.create_user("p1_gc", "gerente_contrato")
        self.director = self.create_user("p1_d", "diretoria")
        for target in ("gestao_contratos.views.plot", "plotly.basedatatypes.BaseFigure.to_html"):
            mock = patch(target, return_value="<div>Gráfico sintético</div>")
            mock.start(); self.addCleanup(mock.stop)
        for contract in self.contracts:
            contract.guarda_chuva = True; contract.save()

    def source(self, **extra):
        values = dict(contrato=self.projects[0], lider_contrato=self.leader, coordenador=self.coord,
            descricao="Escopo preliminar", fornecedor_escolhido=self.supplier, status="Fornecedor selecionado",
            data_inicio=date(2026, 11, 1), data_fim=date(2026, 12, 31))
        values.update(extra)
        return m.SolicitacaoProspeccao.objects.create(**values)

    def document(self, source, **extra):
        return m.DocumentoContratoTerceiro.objects.create(solicitacao=source, numero_contrato="P1-"+str(source.pk),
            objeto="Objeto formal", prazo_inicio=date(2026, 11, 1), prazo_fim=date(2026, 12, 31), valor_total=100, **extra)

    def proposal(self, source, supplier=None, value=100):
        return m.PropostaFornecedor.objects.create(solicitacao=source, fornecedor=supplier or self.supplier, valor_proposta=value)

    def paid_nf(self):
        nf = self.nf(self.bm(os=True, operational="aprovado", director="aprovado"), value="100")
        payment = self.pay(nf, 40)
        return nf, payment

    def pay(self, nf, value):
        return payments.record_payment(nf_id=nf.pk, user=self.finance, valor=value,
            data_pagamento=date(2026, 11, 12), key=str(uuid4()))[0]

    def os_data(self, **extra):
        values = {"contrato": self.contracts[0].pk, "cod_projeto": self.projects[0].pk,
            "coordenador": self.coord.pk, "lider_contrato": self.leader.pk, "titulo": "OS revisada",
            "descricao": "Escopo", "valor": "777,00", "status": "em_execucao",
            "data_prevista_pagamento": "2026-11-20", "prazo_execucao": "2026-12-31"}
        values.update(extra)
        return values

    def test_001_os_sem_bm_pode_usar_outro_projeto_e_contrato(self):
        self.order.contrato = self.contracts[1]
        self.order.cod_projeto = self.projects[0]
        self.order.save()
        self.assertEqual((self.order.contrato_id, self.order.cod_projeto_id), (self.contracts[1].pk, self.projects[0].pk))

    def test_001_bm_sem_nf_ja_protege_identidade_em_clean_save(self):
        self.bm(os=True)
        for field, replacement in (("contrato", self.contracts[1]), ("cod_projeto", self.projects[1])):
            with self.subTest(field=field):
                order = m.OS.objects.get(pk=self.order.pk)
                setattr(order, field, replacement)
                with self.assertRaises(ValidationError): order.clean()
                with self.assertRaises(ValidationError): order.save()
        self.order.refresh_from_db()
        self.assertEqual(self.order.contrato_id, self.contracts[0].pk)

    def test_001_vinculo_de_solicitacao_nao_pode_ser_substituido(self):
        self.bm(os=True)
        request = self.create_os_request(contrato=self.contracts[0], solicitante=self.leader)
        self.order.solicitacao = request
        with self.assertRaises(ValidationError): self.order.save()

    def test_001_bm_os_incompativel_negado_em_insert_update_e_bulk(self):
        bm = self.bm(os=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            m.BM.objects.filter(pk=bm.pk).update(contrato=self.contracts[1])
        invalid = m.BM(contrato=self.contracts[1], os=self.order, numero_bm=99, parcela_paga=1, valor_pago=100)
        with self.assertRaises(IntegrityError), transaction.atomic():
            m.BM.objects.bulk_create([invalid])
        bm.refresh_from_db(); self.assertEqual(bm.contrato_id, self.order.contrato_id)
        self.assertEqual(m.BM.objects.filter(os=self.order).count(), 1)

    def test_001_queryset_bulk_sql_e_atualizacao_mista_rejeitam_sem_efeitos(self):
        nf, _ = self.paid_nf()
        old = m.OS.objects.values().get(pk=self.order.pk)
        operations = [lambda: m.OS.objects.filter(pk=self.order.pk).update(contrato=self.contracts[1], titulo="NÃO GRAVAR"),
            lambda: m.OS.objects.filter(pk=self.order.pk).update(cod_projeto=self.projects[1]),
            lambda: connection.cursor().execute("UPDATE gestao_contratos_os SET contrato_id=%s WHERE id=%s", [self.contracts[1].pk, self.order.pk])]
        self.order.cod_projeto = self.projects[1]
        operations.append(lambda: m.OS.objects.bulk_update([self.order], ["cod_projeto"]))
        for operation in operations:
            with self.assertRaises(IntegrityError), transaction.atomic(): operation()
        self.assertEqual(m.OS.objects.values().get(pk=self.order.pk), old)
        nf.refresh_from_db(); self.assertEqual((nf.total_pago, nf.saldo_pendente), (40, 60))

    def test_001_edicao_http_incompativel_rejeita_tambem_titulo_e_arquivo(self):
        from .test_auditoria import pdf
        nf, _ = self.paid_nf()
        before = m.OS.objects.values().get(pk=self.order.pk)
        self.client.force_login(self.supply)
        response = self.client.post(reverse("editar_os_cadastrada", args=[self.order.pk]),
            self.os_data(contrato=self.contracts[1].pk, cod_projeto=self.projects[1].pk, arquivo_os=pdf()))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(m.OS.objects.values().get(pk=self.order.pk), before)
        nf.refresh_from_db(); self.assertEqual(nf.total_pago, 40)
        from pathlib import Path
        from django.conf import settings
        self.assertFalse(any(p.is_file() for p in Path(settings.MEDIA_ROOT).rglob("*")))

    def test_001_campos_nao_estruturais_continuam_editaveis_com_historico(self):
        nf, _ = self.paid_nf()
        self.client.force_login(self.supply)
        response = self.client.post(reverse("editar_os_cadastrada", args=[self.order.pk]), self.os_data())
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db(); nf.refresh_from_db()
        self.assertEqual(self.order.titulo, "OS revisada")
        self.assertEqual((nf.total_pago, nf.saldo_pendente), (40, 60))

    def test_001_programacao_estorno_e_acordo_preservam_identidade_e_saldo(self):
        nf, payment = self.paid_nf()
        payments.schedule(nf_id=nf.pk, user=self.finance, valor=60, data_prevista=date(2026, 12, 1), motivo="Previsão", key=str(uuid4()))
        payments.reverse_payment(movement_id=payment.pk, user=self.supply, valor=10, data_estorno=date(2026, 11, 12), motivo="Revisão", key=str(uuid4()))
        payments.renegotiate(nf_id=nf.pk, user=self.finance, novo_vencimento=date(2026, 12, 2), motivo="Novo prazo de pagamento", key=str(uuid4()))
        self.order.cod_projeto = self.projects[1]
        with self.assertRaises(ValidationError): self.order.save()
        nf.refresh_from_db(); self.assertEqual((nf.total_pago, nf.saldo_pendente), (30, 70))
        self.assertEqual((nf.movimentos.count(), nf.reprogramacoes.count()), (2, 1))

    def test_001_admin_form_bloqueia_origem_com_nf(self):
        self.paid_nf()
        self.supply.is_staff = True; self.supply.save()
        self.supply.user_permissions.add(*Permission.objects.filter(content_type=ContentType.objects.get_for_model(m.OS)))
        self.client.force_login(self.supply)
        url = reverse("admin:gestao_contratos_os_change", args=[self.order.pk])
        get = self.client.get(url)
        values = model_to_dict(self.order)
        data = {name: values.get(name) if values.get(name) is not None else "" for name in get.context["adminform"].form.fields}
        data["arquivo_os"] = ""; data.update(contrato=self.contracts[1].pk, cod_projeto=self.projects[1].pk, _save="Salvar")
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("contrato", response.context["adminform"].form.errors)
        self.order.refresh_from_db(); self.assertEqual(self.order.contrato_id, self.contracts[0].pk)

    def foreign_os(self):
        self.order.cod_projeto = self.projects[1]
        self.order.lider_contrato = self.other
        self.order.titulo = "OS do projeto B"
        self.order.save()
        return self.order

    def test_002_leitura_interprojeto_no_catalogo_e_detalhe_e_permitida(self):
        order = self.foreign_os()
        self.client.force_login(self.leader)
        catalog = self.client.get(reverse("contrato_fornecedor_detalhe", args=[order.contrato_id]))
        detail = self.client.get(reverse("detalhes_os", args=[order.pk]))
        self.assertEqual((catalog.status_code, detail.status_code), (200, 200))
        self.assertIn(order.pk, [o.pk for o in catalog.context["ordens_servico"]])
        self.assertContains(detail, order.titulo)
        self.assertContains(detail, self.projects[1].cod_projeto)
        self.assertFalse(detail.context["can_manage_os_delivery"])
        self.assertFalse(detail.context["can_view_os_financial_details"])

    def test_002_post_fora_do_escopo_nao_edita_cancela_conclui_duplica_ou_aprova(self):
        order = self.foreign_os()
        bm = self.bm(os=True)
        self.client.force_login(self.leader)
        before = m.OS.objects.values().get(pk=order.pk)
        count = m.OS.objects.count()
        for route, args, data in (
            ("editar_os_cadastrada", [order.pk], self.os_data(status="cancelada", valor="9999")),
            ("duplicar_os_cadastrada", [order.pk], {}),
            ("registrar_entrega_os", [order.pk], {"data_entrega": "2026-11-12", "realizado": "on", "avaliacao": "Aprovado"}),
            ("avaliar_os_fornecedor", [order.pk], {"nota_gestao": "5"}),
            ("avaliar_bm", [bm.pk], {"acao": "aprovar"}),
            ("editar_bm", [bm.pk], {"valor_pago": "999"})):
            with self.subTest(route=route):
                response = self.client.post(reverse(route, args=args), data)
                self.assertIn(response.status_code, (302, 403))
                self.assertEqual(m.OS.objects.values().get(pk=order.pk), before)
                self.assertEqual(m.OS.objects.count(), count)
        bm.refresh_from_db(); self.assertEqual(bm.status_coordenador, "pendente")

    def test_002_lider_responsavel_conclui_e_avalia_sua_os(self):
        order = self.foreign_os()
        self.client.force_login(self.other)
        response = self.client.post(reverse("registrar_entrega_os", args=[order.pk]), {"data_entrega": "2026-11-12", "avaliacao": "Aprovado", "realizado": "on"})
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db(); self.assertTrue(order.realizado); self.assertEqual(order.status, "finalizada")
        response = self.client.post(reverse("avaliar_os_fornecedor", args=[order.pk]), {"nota_gestao": "5", "nota_tecnica": "5", "nota_entrega": "5"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(order.avaliacoes.filter(avaliador=self.other).exists())

    def test_002_leitura_nao_amplia_download_nem_contrato_normal(self):
        from .test_auditoria import pdf
        order = self.foreign_os()
        order.arquivo_os = pdf(); order.save()
        self.client.force_login(self.leader)
        response = self.client.get(reverse("detalhes_os", args=[order.pk]))
        self.assertFalse(response.context["can_download_os"])
        self.assertEqual(self.client.get(order.arquivo_os.url).status_code, 404)
        contract = self.contracts[1]; contract.guarda_chuva = False; contract.save()
        self.assertEqual(self.client.get(reverse("contrato_fornecedor_detalhe", args=[contract.pk])).status_code, 302)

    def test_002_admin_lider_com_permissoes_nao_altera_nem_exclui_os_estrangeira(self):
        order = self.foreign_os()
        self.leader.is_staff = True; self.leader.save()
        self.leader.user_permissions.add(*Permission.objects.filter(content_type=ContentType.objects.get_for_model(m.OS)))
        self.client.force_login(self.leader)
        response = self.client.post(reverse("admin:gestao_contratos_os_change", args=[order.pk]), self.os_data())
        self.assertEqual(response.status_code, 403)
        request = RequestFactory().post("/"); request.user = self.leader
        with self.assertRaises(PermissionDenied):
            admin.site._registry[m.OS].delete_queryset(request, m.OS.objects.filter(pk=order.pk))
        self.assertTrue(m.OS.objects.filter(pk=order.pk).exists())

    def test_002_superusuario_administrativo_sem_grupo_conserva_acesso(self):
        user = self.create_user("p1_admin", None)
        user.is_staff = user.is_superuser = True; user.save()
        request = RequestFactory().get("/"); request.user = user
        model_admin = admin.site._registry[m.OS]
        self.assertTrue(model_admin.has_change_permission(request, self.order))
        self.assertTrue(model_admin.has_delete_permission(request, self.order))
        self.paid_nf()
        self.order.contrato = self.contracts[1]
        with self.assertRaises(ValidationError): self.order.save()

    def test_003_caso_40777_e_caixa_no_projeto_da_os_sem_duplicar(self):
        self.order.cod_projeto = self.projects[1]; self.order.valor = 777; self.order.save()
        nf1 = self.nf(self.bm(os=True, value="50", operational="aprovado", director="aprovado"), value="50")
        nf2 = self.nf(self.bm(os=True, value="100", operational="aprovado", director="aprovado"), value="100")
        payment = self.pay(nf1, 30); self.pay(nf2, 20)
        payments.reverse_payment(movement_id=payment.pk, user=self.supply, valor=10, data_estorno=date(2026, 11, 12), motivo="Estorno parcial", key=str(uuid4()))
        from . import views
        self.client.force_login(self.supply)
        with patch.object(views.go.Figure, "add_trace", autospec=True) as traces:
            self.client.get(reverse("contrato_cliente_detalhe", args=[self.projects[1].pk]))
            planned = sum(c.args[1].y[0] for c in traces.call_args_list if c.args[1].x[0] == "Valor Previsto para Fornecedores")
            paid = sum(c.args[1].y[0] for c in traces.call_args_list if c.args[1].x[0] == "Valor Pago a Fornecedores")
        self.assertEqual((planned, paid), (Decimal("40777"), Decimal("40")))
        a = fq.FinancialData(self.finance, {"historico": True, "projeto": self.projects[0]}).indicators()
        b = fq.FinancialData(self.finance, {"historico": True, "projeto": self.projects[1]}).indicators()
        self.assertEqual((a["pago"], b["medido"], b["autorizado"], b["faturado"], b["pago"], b["saldo_pendente"]), (0, 150, 150, 150, 40, 110))
        self.evidence = {"planned": str(planned), "paid": str(paid), "balance": str(b["saldo_pendente"])}

    def test_003_guarda_chuva_sem_projeto_com_os_em_dois_projetos(self):
        umbrella = self.contracts[0]; umbrella.cod_projeto = None; umbrella.save()
        other = m.OS.objects.create(contrato=umbrella, cod_projeto=self.projects[1], titulo="B", descricao="B", valor=222)
        a = fq.FinancialData(self.finance, {"historico": True, "projeto": self.projects[0]}).indicators()
        b = fq.FinancialData(self.finance, {"historico": True, "projeto": self.projects[1]}).indicators()
        self.assertEqual((a["previsto"], b["previsto"]), (350, 40222))
        self.assertEqual(other.contrato_id, self.order.contrato_id)

    def test_003_ranking_inclui_projeto_da_os_sem_duplicar_valores(self):
        self.order.cod_projeto = self.projects[1]; self.order.valor = 777; self.order.save()
        nf, _ = self.paid_nf()
        self.client.force_login(self.supply)
        response = self.client.get(reverse("ranking_fornecedores"))
        row = next(row for row in response.context["dados"] if row["id"] == self.supplier.pk)
        self.assertEqual(row["valor_previsto"], Decimal("100777"))
        self.assertEqual(row["valor_pago"], 40)
        self.assertIn(self.projects[1].cod_projeto, row["projetos_ativos"])

    def test_003_exportacao_e_filtro_por_projeto_conservam_faturamento_e_caixa(self):
        self.order.cod_projeto = self.projects[1]; self.order.save()
        nf, _ = self.paid_nf()
        self.client.force_login(self.finance)
        filters = {"historico": "on", "projeto": self.projects[1].pk}
        response = self.client.get(reverse("contas_a_pagar"), filters)
        self.assertEqual((response.context["totals"]["billed"], response.context["totals"]["paid"], response.context["totals"]["unpaid"]), (100, 40, 60))
        export = self.client.get(reverse("relatorio_operacional", args=["contas"]), filters)
        book = load_workbook(BytesIO(export.content), read_only=True, data_only=True)
        values = list(book.worksheets[0].values); book.close()
        self.assertEqual(len(values), 2)
        self.assertIn(self.projects[1].cod_projeto, " ".join(map(str, values[1])))
        excluded = self.client.get(reverse("contas_a_pagar"), {"historico": "on", "projeto": self.projects[0].pk})
        self.assertEqual(excluded.context["totals"]["count"], 0)

    def test_004_assinatura_efetivacao_onboarding_ou_bm_assinado_bloqueiam_tres_rotas(self):
        for condition in ("assinatura", "efetivado", "onboarding", "bm_assinado"):
            source = self.source()
            document = self.document(source, arquivo_contrato_assinado="assinado.pdf" if condition == "assinatura" else "")
            proposal = self.proposal(source)
            if condition == "efetivado":
                self.contracts[0].prospeccao = source; self.contracts[0].save()
            if condition == "onboarding": source.status = "Onboarding"; source.save()
            if condition == "bm_assinado": m.DocumentoBM.objects.create(solicitacao=source, minuta_boletim_assinado="bm_assinado.pdf")
            self.client.force_login(self.leader)
            for route, data in (("renegociar_valor", {"valor_proposta": "999"}), ("renegociar_prazo", {"prazo_inicio": "2026-11-01", "prazo_fim": "2030-12-31"}), ("nova_prospeccao", {"descricao": "Novo objeto"})):
                with self.subTest(condition=condition, route=route):
                    count = m.SolicitacaoProspeccao.objects.count()
                    response = self.client.post(reverse(route, args=[source.pk]), data)
                    self.assertEqual(response.status_code, 409)
                    document.refresh_from_db(); proposal.refresh_from_db()
                    self.assertEqual((document.prazo_fim, proposal.valor_proposta), (date(2026, 12, 31), 100))
                    self.assertEqual(m.SolicitacaoProspeccao.objects.count(), count)

    def test_004_prazo_preliminar_valido_reabre_aprovacoes_sem_apagar_documento(self):
        source = self.source(aprovacao_gerencia=True, aprovacao_diretoria=True)
        document = self.document(source)
        bm = m.DocumentoBM.objects.create(solicitacao=source, status_coordenador="aprovado", status_gerente="aprovado")
        self.client.force_login(self.leader)
        response = self.client.post(reverse("renegociar_prazo", args=[source.pk]), {"prazo_inicio": "2026-11-01", "prazo_fim": "2027-01-31"})
        self.assertEqual(response.status_code, 302)
        source.refresh_from_db(); document.refresh_from_db(); bm.refresh_from_db()
        self.assertEqual(document.prazo_fim, date(2027, 1, 31))
        self.assertFalse(source.aprovacao_gerencia); self.assertFalse(source.aprovacao_diretoria)
        self.assertEqual((source.aprovacao_fornecedor_gerente, bm.status_gerente), ("pendente", "pendente"))

    def test_004_datas_invalidas_nao_persistem(self):
        source = self.source(); document = self.document(source)
        self.client.force_login(self.leader)
        response = self.client.post(reverse("renegociar_prazo", args=[source.pk]), {"prazo_inicio": "2027-01-01", "prazo_fim": "2026-01-01"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        document.refresh_from_db(); self.assertEqual(document.prazo_fim, date(2026, 12, 31))

    def test_005_proposta_escolhida_independe_da_ordem_e_reabre_decisoes(self):
        other = self.create_supplier("Não escolhido")
        for chosen_first in (True, False):
            source = self.source(aprovacao_gerencia=True, aprovacao_fornecedor_diretor="aprovado")
            suppliers = [self.supplier, other] if chosen_first else [other, self.supplier]
            proposals = [self.proposal(source, supplier=supplier) for supplier in suppliers]
            chosen = next(p for p in proposals if p.fornecedor_id == self.supplier.pk)
            self.client.force_login(self.leader)
            response = self.client.post(reverse("renegociar_valor", args=[source.pk]), {"valor_proposta": "1.234,56", "proposta_id": chosen.pk})
            self.assertEqual(response.status_code, 302)
            for proposal in proposals:
                proposal.refresh_from_db(); self.assertEqual(proposal.valor_proposta, Decimal("1234.56") if proposal.pk == chosen.pk else 100)
            source.refresh_from_db(); self.assertEqual(source.aprovacao_fornecedor_diretor, "pendente")

    def test_005_proposta_ausente_incompativel_valores_invalidos_nao_alteram(self):
        source = self.source()
        other = self.proposal(source, supplier=self.create_supplier("Outra proposta"))
        self.client.force_login(self.leader)
        url = reverse("renegociar_valor", args=[source.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url, {"valor_proposta": "200"})
        other.refresh_from_db(); self.assertEqual(other.valor_proposta, 100)
        chosen = self.proposal(source)
        for data in ({"valor_proposta": "200", "proposta_id": other.pk}, {"valor_proposta": "-1"}, {"valor_proposta": "NaN"}, {"valor_proposta": "1.2345"}):
            response = self.client.post(url, data)
            self.assertEqual(response.status_code, 200)
            chosen.refresh_from_db(); self.assertEqual(chosen.valor_proposta, 100)

    def test_005_sem_permissao_e_rollback_preservam_proposta(self):
        source = self.source(); chosen = self.proposal(source)
        with self.assertRaises(PermissionDenied):
            prospects.renegotiate_value(source_id=source.pk, user=self.finance, value=200)
        with patch("gestao_contratos.prospeccao_services.invalidate_approvals", side_effect=RuntimeError("Falha sintética")):
            with self.assertRaises(RuntimeError):
                prospects.renegotiate_value(source_id=source.pk, user=self.leader, value=200)
        chosen.refresh_from_db(); self.assertEqual(chosen.valor_proposta, 100)

    def test_006_get_post_valido_vinculos_planejamento_e_retry_sem_duplicacao(self):
        source = self.source()
        event = m.Evento.objects.create(prospeccao=source, descricao="Planejamento", valor_previsto=200,
            data_prevista=date(2026, 12, 1), realizado=True, caminho_evidencia="Não copiar", avaliacao="Aprovado")
        self.client.force_login(self.leader)
        url = reverse("nova_prospeccao", args=[source.pk])
        get = self.client.get(url); self.assertEqual(get.status_code, 200)
        data = {"descricao": "Escopo revisado", "requisitos": "Requisitos", "data_inicio": "2026-11-01", "data_fim": "2027-01-01", "submission_token": get.context["submission_token"], "contrato": self.projects[1].pk}
        first = self.client.post(url, data); retry = self.client.post(url, data)
        self.assertEqual((first.status_code, retry.status_code), (302, 302))
        revision = source.revisoes.get()
        self.assertEqual(revision.contrato_id, source.contrato_id)
        self.assertEqual(revision.status, "Solicitação de prospecção")
        self.assertIsNone(revision.fornecedor_escolhido_id)
        self.assertEqual(revision.lider_contrato_id, source.lider_contrato_id)
        planning = m.Evento.objects.get(prospeccao=revision)
        self.assertEqual(planning.valor_previsto, 200)
        self.assertFalse(planning.realizado); self.assertFalse(planning.caminho_evidencia); self.assertFalse(planning.avaliacao)
        source.refresh_from_db(); event.refresh_from_db()
        self.assertEqual(source.descricao, "Escopo preliminar"); self.assertTrue(event.realizado)
        self.assertEqual(revision.propostas.count(), 0)

    def test_006_post_invalido_permissoes_e_falha_de_evento_sem_revisao_parcial(self):
        source = self.source()
        m.Evento.objects.create(prospeccao=source, descricao="Planejamento")
        self.client.force_login(self.leader)
        response = self.client.post(reverse("nova_prospeccao", args=[source.pk]), {"descricao": "", "data_inicio": "2027-01-01", "data_fim": "2026-01-01"})
        self.assertEqual(response.status_code, 200); self.assertFalse(source.revisoes.exists())
        self.client.force_login(self.other)
        self.client.post(reverse("nova_prospeccao", args=[source.pk]), {"descricao": "Forjado"})
        self.assertFalse(source.revisoes.exists())
        with patch("gestao_contratos.prospeccao_services.m.Evento.objects.create", side_effect=RuntimeError("Falha sintética")):
            with self.assertRaises(RuntimeError):
                prospects.create_revision(source_id=source.pk, user=self.leader, values={"descricao": "Nova"})
        self.assertFalse(source.revisoes.exists())

    def test_008_get_sem_referer_e_retorno_interno_externo(self):
        self.client.force_login(self.supply)
        for route, args in (("nova_os", []), ("editar_os_cadastrada", [self.order.pk]), ("cadastrar_os_contrato_guarda_chuva", [self.contracts[0].pk])):
            for headers in ({}, {"HTTP_REFERER": "https://example.invalid/externo"}, {"HTTP_REFERER": "http://testserver/ordem-servicos/"}):
                response = self.client.get(reverse(route, args=args), **headers)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("example.invalid", response.context["cancel_url"])
        response = self.client.get(reverse("nova_os"), HTTP_REFERER="http://testserver/ordem-servicos/")
        self.assertEqual(response.context["cancel_url"], "http://testserver/ordem-servicos/")

    def test_008_post_valido_invalido_next_seguro_e_projeto_diferente(self):
        self.client.force_login(self.supply)
        count = m.OS.objects.count()
        invalid = self.client.post(reverse("nova_os"), self.os_data(titulo=""))
        self.assertEqual(invalid.status_code, 200); self.assertEqual(m.OS.objects.count(), count)
        response = self.client.post(reverse("nova_os"), self.os_data(next="https://example.invalid/externo"))
        self.assertEqual(response.status_code, 302); self.assertEqual(response.url, reverse("lista_ordens_servico"))
        response = self.client.post(reverse("nova_os"), self.os_data(next=reverse("lista_solicitacoes")))
        self.assertEqual(response.url, reverse("lista_solicitacoes"))
        direct = self.client.post(reverse("cadastrar_os_contrato_guarda_chuva", args=[self.contracts[0].pk]), self.os_data(cod_projeto=self.projects[1].pk))
        self.assertEqual(direct.status_code, 302)
        self.assertEqual(m.OS.objects.latest("pk").cod_projeto_id, self.projects[1].pk)

    def test_012_excecao_temporaria_admin_mantem_operador_real(self):
        from django.contrib.admin.models import LogEntry
        ad = m.AditivoContratoTerceiro.objects.create(contrato=self.contracts[0], solicitado_por=self.leader,
            motivo="Exceção administrativa aceita", novo_valor_total=100)
        self.supply.is_staff = True; self.supply.save()
        content_type = ContentType.objects.get_for_model(ad)
        self.supply.user_permissions.add(Permission.objects.get(content_type=content_type, codename="change_aditivocontratoterceiro"))
        self.client.force_login(self.supply)
        url = reverse("admin:gestao_contratos_aditivocontratoterceiro_change", args=[ad.pk])
        get = self.client.get(url)
        values = model_to_dict(ad)
        data = {name: values.get(name) if values.get(name) is not None else "" for name in get.context["adminform"].form.fields}
        for name, value in list(data.items()):
            if hasattr(value, "_committed"): data[name] = value.name or ""
        data.update(status_diretoria="aprovado", _save="Salvar")
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        ad.refresh_from_db(); self.assertEqual(ad.status_diretoria, "aprovado")
        self.assertTrue(LogEntry.objects.filter(user=self.supply, object_id=str(ad.pk), content_type=content_type, action_flag=2).exists())
        self.assertTrue(m.RegistroAuditoria.objects.filter(usuario=self.supply, object_id=ad.pk, content_type=content_type).exists())

    def test_modelagem_os_tem_um_projeto_sem_rateio_implicito(self):
        field = m.OS._meta.get_field("cod_projeto")
        self.assertTrue(field.many_to_one); self.assertFalse(field.many_to_many)
        self.assertFalse(any(f.related_model is m.Contrato for f in m.OS._meta.many_to_many))
