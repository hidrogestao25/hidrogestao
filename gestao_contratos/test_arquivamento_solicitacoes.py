"""Regressões de estado, transação, segurança, consultas e integridade de vínculos."""
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (BM, ChaveIdempotencia, DocumentoContratoTerceiro, Evento,
                     NF, PropostaFornecedor, RegistroAuditoria,
                     SolicitacaoContrato, SolicitacaoProspeccao)
from .solicitacao_services import alterar_solicitacao, eventos_operacionais, registrar_evento
from .tests import BaseUserTestCase
from .views import build_latest_audit_map, build_request_sla_display, build_weekly_supply_report


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ArquivamentoSolicitacoesTests(BaseUserTestCase):
    def setUp(self):
        self.supply = self.create_user("arquivo_supply", "suprimento")
        self.leader = self.create_user("arquivo_leader", "lider_contrato")
        self.outside = self.create_user("arquivo_outside", "lider_contrato")
        self.finance = self.create_user("arquivo_finance", "financeiro")
        self.project = self.create_contract(lider_contrato=self.leader)
        self.vendor = self.create_supplier()
        self.grant(self.supply, "arquivar", "cancelar")
        self.client.force_login(self.supply)

    def grant(self, user, *actions):
        for model in (SolicitacaoProspeccao, SolicitacaoContrato):
            for action in actions:
                user.user_permissions.add(Permission.objects.get(
                    content_type=ContentType.objects.get_for_model(model),
                    codename=f"{action}_{model._meta.model_name}",
                ))
        for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            user.__dict__.pop(attr, None)

    def solicitacao(self, model=SolicitacaoProspeccao, **kwargs):
        values = dict(contrato=self.project, lider_contrato=self.leader,
                      descricao="Demanda de ensaios", status="Em análise")
        values.update(kwargs)
        return model.objects.create(**values)

    def operar(self, obj, action, user=None, **kwargs):
        return alterar_solicitacao(model=type(obj), pk=obj.pk, user=user or self.supply,
                                   operacao=action, **kwargs)

    def url(self, obj, action):
        tipo = "prospeccao" if isinstance(obj, SolicitacaoProspeccao) else "contratacao"
        return reverse("operar_solicitacao", args=[tipo, obj.pk, action])

    def history(self, obj):
        return RegistroAuditoria.objects.filter(content_type=ContentType.objects.get_for_model(obj),
                                                object_id=obj.pk, detalhes__startswith="solicitacao:")

    def test_arquivar_e_desarquivar_ambos_modelos_preserva_status_e_historico(self):
        for model in (SolicitacaoProspeccao, SolicitacaoContrato):
            with self.subTest(model=model):
                obj = self.solicitacao(model)
                self.assertFalse(obj.arquivada)
                self.operar(obj, "arquivar", motivo="Substituída")
                obj.refresh_from_db()
                self.assertTrue(obj.arquivada)
                self.assertEqual(obj.status, "Em análise")
                self.assertEqual(obj.arquivada_por, self.supply)
                self.assertIsNotNone(obj.arquivada_em)
                self.assertEqual(obj.motivo_arquivamento, "Substituída")
                self.operar(obj, "desarquivar")
                obj.refresh_from_db()
                self.assertFalse(obj.arquivada)
                self.assertEqual(obj.status, "Em análise")
                self.assertEqual(self.history(obj).count(), 2)
                self.assertEqual(self.history(obj).last().justificativa, "Substituída")

    def test_cancelar_sem_arquivar_permanece_na_lista(self):
        for model in (SolicitacaoProspeccao, SolicitacaoContrato):
            obj = self.solicitacao(model)
            self.operar(obj, "cancelar", motivo="Sem necessidade")
            obj.refresh_from_db()
            self.assertEqual(obj.status, "Cancelada")
            self.assertFalse(obj.arquivada)
            self.assertIsNotNone(obj.cancelada_em)
            self.assertEqual(obj.cancelada_por, self.supply)
            self.assertEqual(obj.motivo_cancelamento, "Sem necessidade")
        response = self.client.get(reverse("lista_solicitacoes"))
        self.assertEqual(len(response.context["page_obj"]), 1)
        self.assertEqual(len(response.context["page_obj_contrato"]), 1)

    def test_cancelar_e_arquivar_eventos_correlacionados(self):
        for model in (SolicitacaoProspeccao, SolicitacaoContrato):
            obj = self.solicitacao(model)
            response = self.client.post(self.url(obj, "cancelar"), dict(
                motivo="Cancelamento definitivo", arquivar="on", token=uuid4(), confirmar="on"), follow=True)
            self.assertContains(response, "Solicitação cancelada e arquivada com sucesso.")
            obj.refresh_from_db()
            self.assertTrue(obj.arquivada)
            self.assertEqual(obj.status, "Cancelada")
            events = list(self.history(obj).order_by("pk"))
            self.assertEqual(len(events), 3)
            self.assertIn("solicitacao:cancelamento |", events[0].detalhes)
            self.assertIn("solicitacao:arquivamento |", events[1].detalhes)
            self.assertIn("solicitacao:cancelamento_com_arquivamento |", events[2].detalhes)
            self.assertEqual(events[0].detalhes.split("conjunta: ")[1], events[1].detalhes.split("conjunta: ")[1])
            self.assertFalse(events[0].estado_anterior["arquivada"])
            self.assertTrue(events[1].estado_posterior["arquivada"])
            self.assertEqual(events[1].usuario, self.supply)

    def test_cancelar_ja_arquivada_preserva_dados_do_arquivo(self):
        obj = self.solicitacao()
        self.operar(obj, "arquivar", motivo="Pausa")
        obj.refresh_from_db()
        date, reason = obj.arquivada_em, obj.motivo_arquivamento
        self.operar(obj, "cancelar", motivo="Não prosseguir")
        obj.refresh_from_db()
        self.assertTrue(obj.cancelada)
        self.assertTrue(obj.arquivada)
        self.assertEqual(obj.arquivada_em, date)
        self.assertEqual(obj.motivo_arquivamento, reason)

    def test_arquivar_cancelada_e_desarquivar_nao_reativa(self):
        obj = self.solicitacao()
        self.operar(obj, "cancelar", motivo="Motivo original")
        obj.refresh_from_db()
        original = (obj.cancelada_em, obj.cancelada_por_id, obj.motivo_cancelamento)
        self.operar(obj, "arquivar", motivo="Organização")
        self.operar(obj, "desarquivar")
        obj.refresh_from_db()
        self.assertEqual(obj.status, "Cancelada")
        self.assertEqual((obj.cancelada_em, obj.cancelada_por_id, obj.motivo_cancelamento), original)

    def test_cancelada_legada_sem_data_pode_ser_arquivada(self):
        obj = self.solicitacao(status="Cancelada")
        self.operar(obj, "arquivar")
        self.operar(obj, "desarquivar")
        obj.refresh_from_db()
        self.assertEqual(obj.status, "Cancelada")
        self.assertIsNone(obj.cancelada_em)

    def test_justificativa_obrigatoria_nao_arquiva_se_cancelamento_falhar(self):
        obj = self.solicitacao()
        with self.assertRaises(ValidationError):
            self.operar(obj, "cancelar", arquivar=True)
        obj.refresh_from_db()
        self.assertFalse(obj.arquivada)
        self.assertFalse(obj.cancelada)
        self.assertEqual(self.history(obj).count(), 0)

    def test_rollback_se_falhar_arquivamento_apos_cancelamento(self):
        obj = self.solicitacao()
        token = str(uuid4())
        def fail_archive(*args):
            if args[2] == "arquivamento":
                raise DatabaseError("simulação")
            registrar_evento(*args)
        with self.assertLogs("gestao_contratos.solicitacao_views", level="ERROR"), patch("gestao_contratos.solicitacao_services.registrar_evento", side_effect=fail_archive):
            response = self.client.post(self.url(obj, "cancelar"), dict(
                motivo="Rollback", arquivar="on", token=token, confirmar="on"), follow=True)
        self.assertContains(response, "Nenhuma alteração foi confirmada.")
        obj.refresh_from_db()
        self.assertFalse(obj.arquivada)
        self.assertEqual(obj.status, "Em análise")
        self.assertIsNone(obj.cancelada_em)
        self.assertEqual(self.history(obj).count(), 0)
        self.assertEqual(ChaveIdempotencia.objects.count(), 0)
        self.operar(obj, "cancelar", arquivar=True, motivo="Nova tentativa", token=token)
        self.assertEqual(self.history(obj).count(), 3)

    def test_permissoes_escopo_e_permissao_dupla(self):
        obj = self.solicitacao()
        self.grant(self.leader, "arquivar", "cancelar")
        self.grant(self.outside, "arquivar", "cancelar")
        self.grant(self.finance, "arquivar", "cancelar")
        self.operar(obj, "arquivar", user=self.leader)
        for user in (self.outside, self.finance):
            with self.subTest(user=user.grupo), self.assertRaises(PermissionDenied):
                self.operar(obj, "desarquivar", user=user)
        with self.assertRaises(PermissionDenied):
            self.operar(obj, "cancelar", user=self.leader, motivo="Sem poder de cancelamento")
        self.supply.user_permissions.clear()
        self.grant(self.supply, "cancelar")
        with self.assertRaises(PermissionDenied):
            self.operar(obj, "cancelar", motivo="Dupla permissão", arquivar=True)
        obj.refresh_from_db()
        self.assertFalse(obj.cancelada)
        self.operar(obj, "cancelar", motivo="Só cancelar")

    def test_permissao_negada_no_backend_e_botoes_ocultos(self):
        obj = self.solicitacao()
        self.client.force_login(self.outside)
        response = self.client.post(self.url(obj, "arquivar"), dict(token=uuid4(), confirmar="on"))
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.finance)
        response = self.client.get(reverse("lista_solicitacoes"))
        self.assertNotContains(response, "Confirmar arquivamento")
        self.assertNotContains(response, "Cancelar solicitação")

    def test_post_csrf_confirmacao_e_destino_local(self):
        obj = self.solicitacao()
        self.assertEqual(self.client.get(self.url(obj, "arquivar")).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.supply)
        self.assertEqual(csrf_client.post(self.url(obj, "arquivar"), dict(token=uuid4(), confirmar="on")).status_code, 403)
        self.client.post(self.url(obj, "arquivar"), dict(token=uuid4()))
        obj.refresh_from_db()
        self.assertFalse(obj.arquivada)
        response = self.client.post(self.url(obj, "arquivar"), dict(token=uuid4(), confirmar="on", next="https://exemplo.invalid/"))
        self.assertEqual(response.url, reverse("lista_solicitacoes"))

    def test_repeticoes_nao_duplicam_auditoria_e_formulario_antigo_nao_rearquiva(self):
        obj = self.solicitacao()
        token = str(uuid4())
        self.operar(obj, "arquivar", token=token)
        self.operar(obj, "arquivar", token=token)
        self.operar(obj, "arquivar")
        self.assertEqual(self.history(obj).count(), 1)
        self.operar(obj, "desarquivar")
        self.operar(obj, "arquivar", token=token)
        obj.refresh_from_db()
        self.assertFalse(obj.arquivada)
        self.operar(obj, "cancelar", arquivar=True, motivo="Primeira")
        self.operar(obj, "cancelar", arquivar=True, motivo="Repetida")
        self.assertEqual(self.history(obj).count(), 5)
        obj.refresh_from_db()
        self.assertEqual(obj.motivo_cancelamento, "Primeira")

    def test_documentos_propostas_eventos_e_fornecedores_preservados(self):
        obj = self.solicitacao(cronograma="cronogramas/original.pdf")
        obj.fornecedores_selecionados.add(self.vendor)
        proposta = PropostaFornecedor.objects.create(solicitacao=obj, fornecedor=self.vendor, arquivo_proposta="orcamentos/original.pdf")
        evento = Evento.objects.create(prospeccao=obj, descricao="Planejado", valor_previsto=Decimal("120.00"))
        minuta = DocumentoContratoTerceiro.objects.create(solicitacao=obj, numero_contrato="ARQ-001", objeto="Escopo",
            prazo_inicio=timezone.localdate(), prazo_fim=timezone.localdate(), valor_total=Decimal("120.00"), arquivo_contrato="minutas/original.pdf")
        self.operar(obj, "cancelar", motivo="Preservar", arquivar=True)
        self.operar(obj, "desarquivar")
        obj.refresh_from_db(); proposta.refresh_from_db(); evento.refresh_from_db(); minuta.refresh_from_db()
        self.assertEqual(obj.cronograma.name, "cronogramas/original.pdf")
        self.assertEqual(obj.fornecedores_selecionados.get(), self.vendor)
        self.assertEqual(proposta.arquivo_proposta.name, "orcamentos/original.pdf")
        self.assertEqual(evento.prospeccao_id, obj.pk)
        self.assertEqual(evento.valor_previsto, Decimal("120.00"))
        self.assertEqual(minuta.arquivo_contrato.name, "minutas/original.pdf")

    def test_contrato_gerado_bloqueia_cancelar_e_arquivar_ativo(self):
        for model in (SolicitacaoProspeccao, SolicitacaoContrato):
            obj = self.solicitacao(model)
            contrato = self.create_supplier_contract(cod_projeto=self.project, empresa_terceira=self.vendor)
            field = "prospeccao" if model is SolicitacaoProspeccao else "solicitacao"
            setattr(contrato, field, obj); contrato.save()
            for action in ("cancelar", "arquivar"):
                with self.assertRaises(ValidationError):
                    self.operar(obj, action, motivo="Contrato existe", arquivar=action == "cancelar")
            contrato.status = "encerrado"; contrato.save()
            self.operar(obj, "arquivar")
            contrato.refresh_from_db()
            self.assertEqual(getattr(contrato, field+"_id"), obj.pk)
            self.assertEqual(contrato.status, "encerrado")

    def test_entrega_e_contrato_assinado_bloqueiam_cancelamento(self):
        obj = self.solicitacao()
        event = Evento.objects.create(prospeccao=obj, descricao="Entregue", realizado=True)
        with self.assertRaises(ValidationError):
            self.operar(obj, "cancelar", motivo="Não permitido", arquivar=True)
        event.realizado = False; event.save()
        DocumentoContratoTerceiro.objects.create(solicitacao=obj, numero_contrato="ASS-001", objeto="Escopo",
            prazo_inicio=timezone.localdate(), prazo_fim=timezone.localdate(), valor_total=Decimal("120.00"), arquivo_contrato_assinado="contratos/assinado.pdf")
        with self.assertRaises(ValidationError):
            self.operar(obj, "cancelar", motivo="Não permitido", arquivar=True)
        obj.refresh_from_db()
        self.assertFalse(obj.cancelada)
        self.assertFalse(obj.arquivada)

    def test_financeiro_intacto_e_pendencias_bloqueiam_arquivo(self):
        obj = self.solicitacao()
        contrato = self.create_supplier_contract(cod_projeto=self.project, empresa_terceira=self.vendor, status="encerrado")
        contrato.prospeccao = obj; contrato.save()
        event = self.create_event(contrato=contrato)
        bm = BM.objects.create(contrato=contrato, evento=event, numero_bm=1, parcela_paga=1,
                               valor_pago=Decimal("100.00"), status_gerente="aprovado")
        nf = NF.objects.create(contrato=contrato, evento=event, bm=bm, parcela_paga=1,
                               valor_pago=Decimal("100.00"), data_pagamento=timezone.localdate())
        before = list(NF.objects.values())
        with self.assertRaises(ValidationError):
            self.operar(obj, "arquivar")
        self.assertEqual(list(NF.objects.values()), before)
        self.assertEqual(NF.objects.get(pk=nf.pk).saldo_pendente, Decimal("100.00"))

    def test_arquivar_contrato_encerrado_preserva_ledger_e_consulta_financeira(self):
        from .payment_services import record_payment
        from .models import PagamentoNF
        obj = self.solicitacao()
        contrato = self.create_supplier_contract(cod_projeto=self.project, empresa_terceira=self.vendor, status="encerrado")
        contrato.prospeccao = obj; contrato.save()
        event = self.create_event(contrato=contrato)
        bm = BM.objects.create(contrato=contrato, evento=event, numero_bm=1, parcela_paga=1,
                               valor_pago=Decimal("100.00"), status_gerente="aprovado", aprovacao_pagamento="aprovado")
        nf = NF.objects.create(contrato=contrato, evento=event, bm=bm, parcela_paga=1,
                               valor_pago=Decimal("100.00"), data_pagamento=timezone.localdate())
        record_payment(nf_id=nf.pk, user=self.supply, valor=Decimal("100.00"), data_pagamento=timezone.localdate(), key="arquivo-pagamento")
        before = (list(NF.objects.values()), list(PagamentoNF.objects.values()), list(BM.objects.values()))
        self.operar(obj, "arquivar")
        self.assertEqual((list(NF.objects.values()), list(PagamentoNF.objects.values()), list(BM.objects.values())), before)
        self.client.force_login(self.finance)
        self.assertEqual(self.client.get(reverse("detalhe_nf", args=[nf.pk])).status_code, 200)

    def test_os_em_andamento_impede_arquivo_sem_modificar_os(self):
        obj = self.solicitacao()
        contrato = self.create_supplier_contract(cod_projeto=self.project, empresa_terceira=self.vendor,
                                                 status="encerrado", guarda_chuva=True)
        contrato.prospeccao = obj; contrato.save()
        os = self.create_os(contrato=contrato)
        with self.assertRaises(ValidationError):
            self.operar(obj, "arquivar")
        os.refresh_from_db()
        self.assertEqual(os.status, "em_execucao")
        os.status = "finalizada"; os.save()
        self.operar(obj, "arquivar")

    def test_administracao_nao_reativa_cancelada_nem_edita_estado_diretamente(self):
        obj = self.solicitacao()
        request = RequestFactory().get("/admin/"); request.user = self.supply
        model_admin = admin.site._registry[SolicitacaoProspeccao]
        request.user.is_staff = True
        request.user.is_superuser = True
        self.assertTrue(model_admin.has_change_permission(request, obj))
        self.assertIn("status", model_admin.get_readonly_fields(request, obj))
        self.operar(obj, "cancelar", motivo="Sem reabertura")
        obj.refresh_from_db()
        self.assertFalse(model_admin.has_change_permission(request, obj))

    def test_arquivamento_nao_reinicia_data_de_sla(self):
        obj = self.solicitacao()
        audit = RegistroAuditoria.objects.create(content_type=ContentType.objects.get_for_model(obj),
            object_id=obj.pk, acao="atualizado", usuario=self.supply, modelo="Solicitação", representacao_objeto=str(obj), detalhes="Mudança operacional")
        self.operar(obj, "arquivar")
        self.operar(obj, "desarquivar")
        self.assertEqual(build_latest_audit_map(type(obj), [obj.pk])[obj.pk].pk, audit.pk)

    def test_listas_pesquisa_ordenacao_paginacao_e_detalhes(self):
        active = self.solicitacao()
        archived = self.solicitacao(descricao="Demanda arquivada")
        self.operar(archived, "arquivar", motivo="Organização")
        self.solicitacao(SolicitacaoContrato, descricao="Contratação")
        for _ in range(11):
            self.solicitacao(descricao="Pesquisar bomba")
        base = reverse("lista_solicitacoes")
        response = self.client.get(base)
        self.assertEqual(response.context["page_obj"].paginator.count, 12)
        response = self.client.get(base, dict(visualizacao="arquivadas"))
        self.assertEqual(list(response.context["page_obj"]), [archived])
        self.assertContains(response, "Organização")
        self.assertContains(response, "Desarquivar")
        response = self.client.get(base, dict(visualizacao="todas", q="bomba", ordem="id", status="Em análise", page=2))
        self.assertEqual(response.context["page_obj"].paginator.count, 11)
        self.assertEqual(len(response.context["page_obj"]), 1)
        self.assertContains(response, "visualizacao=todas")
        self.assertContains(response, "q=bomba")
        self.assertContains(response, "ordem=id")
        response = self.client.get(base, dict(visualizacao="todas", q=f"#{archived.pk}"))
        self.assertEqual(list(response.context["page_obj"]), [archived])
        for model, route in ((SolicitacaoProspeccao, "detalhes_solicitacao"), (SolicitacaoContrato, "detalhes_solicitacao_contrato")):
            obj = self.solicitacao(model)
            self.operar(obj, "arquivar")
            self.assertContains(self.client.get(reverse(route, args=[obj.pk])), "Histórico de cancelamento e arquivamento")
            self.operar(obj, "cancelar", motivo="Fluxo encerrado")
            detail = self.client.get(reverse(route, args=[obj.pk]))
            self.assertContains(detail, "Solicitação cancelada. O fluxo operacional está encerrado.")
            self.assertNotContains(detail, 'class="timeline"')
            self.assertNotContains(detail, "ERRO DE STATUS")

    def test_escopo_de_consulta_nao_vaza_arquivadas(self):
        obj = self.solicitacao()
        self.operar(obj, "arquivar")
        self.client.force_login(self.outside)
        response = self.client.get(reverse("lista_solicitacoes"), dict(visualizacao="todas"))
        self.assertEqual(response.context["page_obj"].paginator.count, 0)
        self.client.force_login(self.leader)
        response = self.client.get(reverse("lista_solicitacoes"), dict(visualizacao="arquivadas"))
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_cancelada_nao_pode_avancar_por_urls_antigas(self):
        obj = self.solicitacao()
        self.operar(obj, "cancelar", motivo="Encerrada")
        self.client.post(reverse("aprovar_solicitacao", args=[obj.pk, "aprovar"]))
        self.client.post(reverse("cadastrar_evento", args=[obj.pk]), dict(descricao="Não criar"))
        obj.refresh_from_db()
        self.assertEqual(obj.status, "Cancelada")
        self.assertFalse(Evento.objects.filter(prospeccao=obj).exists())
        self.assertEqual(self.history(obj).count(), 1)
        obj_c = self.solicitacao(SolicitacaoContrato)
        self.operar(obj_c, "cancelar", motivo="Encerrada")
        self.client.post(reverse("editar_solicitacao_contrato", args=[obj_c.pk]), dict(descricao="Não alterar"))
        obj_c.refresh_from_db()
        self.assertEqual(obj_c.descricao, "Demanda de ensaios")

    def test_dashboard_sla_indicadores_e_relatorio_excluem_pendencias_arquivadas(self):
        active = self.solicitacao(descricao="Operacional")
        obj = self.solicitacao(descricao="Arquivada fora das pendências")
        cancelled = self.solicitacao(descricao="Cancelada fora das pendências")
        self.operar(obj, "arquivar")
        self.operar(cancelled, "cancelar", motivo="Encerrada")
        archived_event = Evento.objects.create(prospeccao=obj, descricao="Evento arquivado", data_prevista=timezone.localdate())
        cancelled_event = Evento.objects.create(prospeccao=cancelled, descricao="Evento cancelado", data_prevista=timezone.localdate())
        self.assertFalse(eventos_operacionais().filter(pk__in=[archived_event.pk, cancelled_event.pk]).exists())
        obj.refresh_from_db(); cancelled.refresh_from_db()
        self.assertEqual(list(SolicitacaoProspeccao.objects.operacionais()), [active])
        self.assertIsNone(build_request_sla_display(obj))
        self.assertIsNone(build_request_sla_display(cancelled))
        home = self.client.get(reverse("home"))
        self.assertEqual(home.status_code, 200)
        self.assertNotContains(home, "Arquivada fora das pendências")
        self.assertNotContains(home, "Cancelada fora das pendências")
        self.assertNotContains(home, "Evento arquivado")
        self.assertNotContains(home, "Evento cancelado")
        indicators = self.client.get(reverse("indicadores_suprimento"))
        self.assertEqual(indicators.status_code, 200)
        self.assertNotContains(indicators, "Arquivada fora das pendências")
        report = str(build_weekly_supply_report(self.supply))
        self.assertNotIn("Arquivada fora das pendências", report)
        self.assertNotIn("Cancelada fora das pendências", report)
        self.assertEqual(SolicitacaoProspeccao.objects.count(), 3)
