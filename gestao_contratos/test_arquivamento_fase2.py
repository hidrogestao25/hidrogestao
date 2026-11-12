"""Onboarding e ciclo de vida das solicitações de OS/aditivos, sem efeitos financeiros."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (AditivoContratoTerceiro, BM, ChaveIdempotencia, ContratoTerceiros,
                     Evento, NF, OS, PagamentoNF, RegistroAuditoria, SolicitacaoContrato,
                     SolicitacaoOrdemServico, SolicitacaoProspeccao)
from .solicitacao_services import MODELOS, alterar_solicitacao, registrar_evento
from .tests import BaseUserTestCase


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ArquivamentoFase2Tests(BaseUserTestCase):
    def setUp(self):
        self.supply = self.create_user("fase2_supply", "suprimento")
        self.leader = self.create_user("fase2_leader", "lider_contrato")
        self.outside = self.create_user("fase2_outside", "lider_contrato")
        self.finance = self.create_user("fase2_finance", "financeiro")
        self.project = self.create_contract(lider_contrato=self.leader)
        self.contract = self.create_supplier_contract(cod_projeto=self.project, lider_contrato=self.leader,
                                                      guarda_chuva=True)
        self.contract.valor_total = Decimal("5000.00")
        self.contract.data_fim = timezone.localdate() + timedelta(days=60)
        self.contract.save()
        self.grant(self.supply, "arquivar", "cancelar")
        self.client.force_login(self.supply)

    def grant(self, user, *actions):
        for model in MODELOS.values():
            for action in actions:
                user.user_permissions.add(Permission.objects.get(
                    content_type=ContentType.objects.get_for_model(model), codename=f"{action}_{model._meta.model_name}"))
        for key in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
            user.__dict__.pop(key, None)

    def new(self, tipo, **kwargs):
        if tipo in {"prospeccao", "contratacao"}:
            values = dict(contrato=self.project, lider_contrato=self.leader, descricao="Demanda fase dois",
                          solicitante=self.leader.username, status="Em análise")
            values.update(kwargs)
            return MODELOS[tipo].objects.create(**values)
        if tipo == "os":
            values = dict(contrato=self.contract, cod_projeto=self.project, solicitante=self.leader,
                          lider_contrato=self.leader, titulo="Demanda fase dois OS", descricao="Descrição",
                          status="pendente_gerente")
        else:
            values = dict(contrato=self.contract, solicitado_por=self.leader, motivo="Demanda fase dois aditivo",
                          valor_total_anterior=self.contract.valor_total, data_fim_anterior=self.contract.data_fim,
                          novo_valor_total=Decimal("100.00"), nova_data_fim=self.contract.data_fim + timedelta(days=30))
        values.update(kwargs)
        return MODELOS[tipo].objects.create(**values)

    def act(self, obj, action, **kwargs):
        return alterar_solicitacao(model=type(obj), pk=obj.pk, user=kwargs.pop("user", self.supply),
                                   operacao=action, **kwargs)

    def history(self, obj):
        return RegistroAuditoria.objects.filter(content_type=ContentType.objects.get_for_model(obj),
            object_id=obj.pk, detalhes__startswith="solicitacao:")

    def page(self, **params):
        return self.client.get(reverse("lista_solicitacoes"), params)

    def items(self, response, tipo):
        key = {"prospeccao": "page_obj", "contratacao": "page_obj_contrato",
               "os": "ordens_servico_page", "aditivo": "aditivos_page"}[tipo]
        return response.context[key]

    def url(self, tipo, obj, action):
        return reverse("operar_solicitacao", args=[tipo, obj.pk, action])

    def test_01_onboarding_prospeccao_fora_de_ativas(self):
        obj = self.new("prospeccao", status="Onboarding")
        self.assertNotIn(obj, self.items(self.page(), "prospeccao"))

    def test_02_onboarding_contratacao_fora_de_ativas(self):
        obj = self.new("contratacao", status="Onboarding")
        self.assertNotIn(obj, self.items(self.page(), "contratacao"))

    def test_03_onboarding_fora_de_arquivadas_em_ambos_estados_legados(self):
        for tipo in ("prospeccao", "contratacao"):
            for arquivada in (False, True):
                self.new(tipo, status="Onboarding", arquivada=arquivada)
        response = self.page(visualizacao="arquivadas", q="Demanda", status="Onboarding")
        self.assertEqual(len(self.items(response, "prospeccao")), 0)
        self.assertEqual(len(self.items(response, "contratacao")), 0)

    def test_04_todas_inclui_onboarding_e_preserva_estado_legado(self):
        for tipo in ("prospeccao", "contratacao"):
            obj = self.new(tipo, status="Onboarding", arquivada=True, motivo_arquivamento="Legado")
            before = MODELOS[tipo].objects.values().get(pk=obj.pk)
            response = self.page(visualizacao="todas", status="Onboarding", q=f"#{obj.pk}")
            self.assertIn(obj, self.items(response, tipo))
            self.assertEqual(MODELOS[tipo].objects.values().get(pk=obj.pk), before)

    def test_05_transicao_onboarding_e_regresso_legitimo_so_mudam_visibilidade(self):
        for tipo in ("prospeccao", "contratacao"):
            obj = self.new(tipo)
            self.assertIn(obj, self.items(self.page(), tipo))
            obj.status = "Onboarding"; obj.save(update_fields=["status"])
            self.assertNotIn(obj, self.items(self.page(), tipo))
            self.assertIn(obj, self.items(self.page(visualizacao="todas"), tipo))
            # Usa o endpoint existente, permitido para este legado sem contrato gerado.
            route = ("regredir_solicitacao_aprovacao_fornecedor" if tipo == "prospeccao"
                     else "regredir_solicitacao_contrato_aprovacao_fornecedor")
            with patch("gestao_contratos.views._notify_request_regression"):
                response = self.client.post(reverse(route, args=[obj.pk]), dict(target_status="Planejamento do Contrato"))
            self.assertEqual(response.status_code, 302)
            obj.refresh_from_db()
            self.assertEqual(obj.status, "Planejamento do Contrato")
            self.assertIn(obj, self.items(self.page(), tipo))
            obj.refresh_from_db()
            self.assertFalse(obj.arquivada)
            self.assertIsNone(obj.cancelada_em)

    def test_06_onboarding_arquivada_nao_reaparece_ao_regredir(self):
        obj = self.new("prospeccao", status="Onboarding", arquivada=True)
        obj.status = "Planejamento do Contrato"; obj.save(update_fields=["status"])
        self.assertNotIn(obj, self.items(self.page(), "prospeccao"))
        self.assertIn(obj, self.items(self.page(visualizacao="arquivadas"), "prospeccao"))

    def test_07_onboarding_detalhes_documentos_e_auditoria_preservados(self):
        for tipo, route in (("prospeccao", "detalhes_solicitacao"), ("contratacao", "detalhes_solicitacao_contrato")):
            obj = self.new(tipo, status="Onboarding", cronograma="cronograma/legado.pdf")
            before = self.history(obj).count()
            self.assertEqual(self.client.get(reverse(route, args=[obj.pk])).status_code, 200)
            self.page(); self.page(visualizacao="arquivadas"); self.page(visualizacao="todas")
            obj.refresh_from_db()
            self.assertEqual(obj.status, "Onboarding")
            self.assertFalse(obj.arquivada)
            self.assertEqual(obj.cronograma.name, "cronograma/legado.pdf")
            self.assertEqual(self.history(obj).count(), before)

    def test_08_onboarding_historico_nao_perdido_nos_indicadores(self):
        for tipo in ("prospeccao", "contratacao"):
            obj = self.new(tipo, status="Onboarding", arquivada=True)
            RegistroAuditoria.objects.create(content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk,
                acao="atualizado", usuario=self.supply, modelo="Solicitação", representacao_objeto=str(obj), detalhes="Onboarding")
        response = self.client.get(reverse("indicadores_suprimento"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["backlog_total"], 0)
        self.assertEqual(response.context["total_solicitacoes_prospeccao"], 1)
        self.assertEqual(response.context["total_solicitacoes_contratacao"], 1)
        home = self.client.get(reverse("home"))
        self.assertNotContains(home, "Demanda fase dois")

    def test_09_os_arquiva_preservando_status_e_metadados(self):
        obj = self.new("os")
        self.act(obj, "arquivar", motivo="Planejamento suspenso")
        obj.refresh_from_db()
        self.assertTrue(obj.arquivada)
        self.assertEqual(obj.status, "pendente_gerente")
        self.assertEqual(obj.arquivada_por_id, self.supply.pk)
        self.assertEqual(obj.motivo_arquivamento, "Planejamento suspenso")
        self.assertIn(obj, self.items(self.page(visualizacao="arquivadas"), "os"))

    def test_10_os_desarquiva_preservando_historico(self):
        obj = self.new("os")
        self.act(obj, "arquivar"); self.act(obj, "desarquivar")
        obj.refresh_from_db()
        self.assertFalse(obj.arquivada)
        self.assertEqual(obj.status, "pendente_gerente")
        self.assertEqual(self.history(obj).count(), 2)
        self.assertIn(obj, self.items(self.page(), "os"))

    def test_11_os_cancela_sem_arquivar(self):
        obj = self.new("os")
        self.act(obj, "cancelar", motivo="Sem necessidade")
        obj.refresh_from_db()
        self.assertEqual(obj.status, "cancelada")
        self.assertEqual(obj.get_status_display(), "Cancelada")
        self.assertFalse(obj.arquivada)
        self.assertIn(obj, self.items(self.page(), "os"))

    def test_12_os_cancela_e_arquiva(self):
        obj = self.new("os")
        response = self.client.post(self.url("os", obj, "cancelar"), dict(motivo="Nova decisão", arquivar="on", confirmar="on", token=uuid4()), follow=True)
        self.assertContains(response, "Solicitação cancelada e arquivada com sucesso.")
        obj.refresh_from_db()
        self.assertTrue(obj.arquivada and obj.cancelada)
        self.assertNotIn(obj, self.items(response, "os"))
        self.assertIn(obj, self.items(self.page(visualizacao="arquivadas"), "os"))

    def test_13_os_documento_relacoes_e_aprovacoes_preservados(self):
        obj = self.new("os", arquivo_os="os/minuta.pdf", aprovacao_gerente="aprovado", aprovacao_diretor="pendente")
        self.act(obj, "cancelar", arquivar=True, motivo="Preservação")
        obj.refresh_from_db()
        self.assertEqual(obj.arquivo_os.name, "os/minuta.pdf")
        self.assertEqual(obj.contrato_id, self.contract.pk)
        self.assertEqual(obj.cod_projeto_id, self.project.pk)
        self.assertEqual(obj.solicitante_id, self.leader.pk)
        self.assertEqual(obj.aprovacao_gerente, "aprovado")
        self.assertEqual(obj.aprovacao_diretor, "pendente")

    def test_14_os_emitida_impede_cancelamento_em_qualquer_estado(self):
        for estado in ("em_execucao", "paralizada", "finalizada", "cancelada"):
            obj = self.new("os", status="aprovada")
            emitted = self.create_os(contrato=self.contract, solicitacao=obj, status=estado)
            before = OS.objects.values().get(pk=emitted.pk)
            with self.assertRaises(ValidationError):
                self.act(obj, "cancelar", arquivar=True, motivo="Não cancelar OS")
            self.assertEqual(OS.objects.values().get(pk=emitted.pk), before)
            obj.refresh_from_db()
            self.assertIsNone(obj.cancelada_em)

    def test_15_os_execucao_e_financeiro_pendente_bloqueiam_arquivo(self):
        obj = self.new("os", status="aprovada")
        emitted = self.create_os(contrato=self.contract, solicitacao=obj)
        with self.assertRaises(ValidationError):
            self.act(obj, "arquivar")
        emitted.status = "finalizada"; emitted.save()
        bm = BM.objects.create(contrato=self.contract, os=emitted, numero_bm=1, parcela_paga=1, valor_pago=100,
            status_gerente="aprovado", aprovacao_pagamento="aprovado")
        nf = NF.objects.create(contrato=self.contract, os=emitted, bm=bm, parcela_paga=1, valor_pago=100,
            data_pagamento=timezone.localdate())
        with self.assertRaises(ValidationError):
            self.act(obj, "arquivar")
        from .payment_services import record_payment
        record_payment(nf_id=nf.pk, user=self.supply, valor=100, data_pagamento=timezone.localdate(), key="fase2-pay")
        before = (list(OS.objects.values()), list(BM.objects.values()), list(NF.objects.values()), list(PagamentoNF.objects.values()))
        self.act(obj, "arquivar")
        self.assertEqual(before, (list(OS.objects.values()), list(BM.objects.values()), list(NF.objects.values()), list(PagamentoNF.objects.values())))

    def test_16_os_cancelada_nao_avanca_nem_e_editada(self):
        obj = self.new("os")
        self.act(obj, "cancelar", motivo="Fluxo encerrado")
        manager = self.create_user("fase2_manager", "gerente_contrato")
        self.client.force_login(manager)
        self.client.post(reverse("aprovar_os_gerente_contrato", args=[obj.pk, "aprovar"]))
        self.client.force_login(self.supply)
        self.client.post(reverse("editar_ordem_servico", args=[obj.pk]), dict(titulo="Alteração indevida"))
        self.client.post(reverse("regredir_solicitacao_os", args=[obj.pk]), dict(target_status="solicitacao_os"))
        obj.refresh_from_db()
        self.assertTrue(obj.cancelada)
        self.assertEqual(obj.titulo, "Demanda fase dois OS")
        self.assertFalse(OS.objects.filter(solicitacao=obj).exists())

    def test_17_aditivo_arquiva_sem_mudar_aprovacoes_ou_contrato(self):
        obj = self.new("aditivo", status_gerente="aprovado")
        before = ContratoTerceiros.objects.values().get(pk=self.contract.pk)
        status = obj.status
        self.act(obj, "arquivar", motivo="Aguardando decisão")
        obj.refresh_from_db()
        self.assertEqual(obj.status, status)
        self.assertEqual(obj.status_gerente, "aprovado")
        self.assertEqual(ContratoTerceiros.objects.values().get(pk=self.contract.pk), before)

    def test_18_aditivo_desarquiva_sem_reativar(self):
        obj = self.new("aditivo")
        self.act(obj, "cancelar", arquivar=True, motivo="Original")
        obj.refresh_from_db(); original = (obj.cancelada_em, obj.cancelada_por_id, obj.motivo_cancelamento)
        self.act(obj, "desarquivar")
        obj.refresh_from_db()
        self.assertFalse(obj.arquivada)
        self.assertTrue(obj.cancelada)
        self.assertEqual(obj.etapa_atual, "Cancelada")
        self.assertEqual((obj.cancelada_em, obj.cancelada_por_id, obj.motivo_cancelamento), original)

    def test_19_aditivo_cancela_sem_arquivar(self):
        obj = self.new("aditivo")
        self.act(obj, "cancelar", motivo="Dispensado")
        obj.refresh_from_db()
        self.assertFalse(obj.arquivada)
        self.assertEqual(obj.status, "Cancelada")
        self.assertIn(obj, self.items(self.page(), "aditivo"))

    def test_20_aditivo_cancela_e_arquiva_documentos_e_eventos_planejados_intactos(self):
        obj = self.new("aditivo", arquivo_aditivo="aditivos/minuta.pdf", status_gerente="aprovado")
        event = Evento.objects.create(aditivo=obj, descricao="Entrega planejada", valor_previsto=50)
        before = ContratoTerceiros.objects.values().get(pk=self.contract.pk)
        self.act(obj, "cancelar", arquivar=True, motivo="Dispensado")
        obj.refresh_from_db(); event.refresh_from_db()
        self.assertTrue(obj.arquivada and obj.cancelada)
        self.assertEqual(obj.arquivo_aditivo.name, "aditivos/minuta.pdf")
        self.assertEqual(obj.status_gerente, "aprovado")
        self.assertEqual(event.aditivo_id, obj.pk)
        self.assertEqual(event.valor_previsto, 50)
        self.assertEqual(ContratoTerceiros.objects.values().get(pk=self.contract.pk), before)

    def test_21_aditivo_formalizado_bloqueia_cancelamento_sem_reverter_contrato(self):
        for values in (dict(arquivo_aditivo_assinado="aditivos/assinado.pdf"), dict(documento_assinado_enviado_em=timezone.now())):
            obj = self.new("aditivo", **values)
            before = ContratoTerceiros.objects.values().get(pk=self.contract.pk)
            with self.assertRaises(ValidationError):
                self.act(obj, "cancelar", arquivar=True, motivo="Indevido")
            obj.refresh_from_db()
            self.assertFalse(obj.cancelada or obj.arquivada)
            self.assertEqual(ContratoTerceiros.objects.values().get(pk=self.contract.pk), before)

    def test_22_aditivo_assinado_so_arquiva_apos_encerrar_contrato_preservando_documento(self):
        obj = self.new("aditivo", arquivo_aditivo_assinado="aditivos/assinado.pdf")
        with self.assertRaises(ValidationError):
            self.act(obj, "arquivar")
        self.contract.status = "encerrado"; self.contract.save()
        before = ContratoTerceiros.objects.values().get(pk=self.contract.pk)
        self.act(obj, "arquivar")
        obj.refresh_from_db()
        self.assertEqual(obj.arquivo_aditivo_assinado.name, "aditivos/assinado.pdf")
        self.assertEqual(obj.status, "Concluido")
        self.assertEqual(ContratoTerceiros.objects.values().get(pk=self.contract.pk), before)

    def test_23_aditivo_cancelado_bloqueia_aprovacao_upload_e_novos_eventos(self):
        obj = self.new("aditivo", status_gerente="aprovado", status_diretoria="aprovado")
        self.act(obj, "cancelar", motivo="Fim")
        for route in ("avaliar_solicitacao_aditivo_contrato", "enviar_documento_aditivo_contrato",
                      "avaliar_minuta_aditivo_contrato", "enviar_aditivo_assinado_contrato", "cadastrar_evento_aditivo"):
            self.client.post(reverse(route, args=[obj.pk]), dict(acao="aprovar", descricao="Não criar"))
        obj.refresh_from_db()
        self.assertTrue(obj.cancelada)
        self.assertFalse(obj.arquivo_aditivo or obj.arquivo_aditivo_assinado)
        self.assertFalse(obj.eventos.exists())

    def test_24_os_aditivo_permissoes_escopo_e_financeiro_somente_consulta(self):
        for tipo in ("os", "aditivo"):
            obj = self.new(tipo)
            for user in (self.leader, self.outside, self.finance):
                with self.assertRaises(PermissionDenied):
                    self.act(obj, "arquivar", user=user)
            self.grant(self.leader, "arquivar", "cancelar")
            self.grant(self.outside, "arquivar", "cancelar")
            self.grant(self.finance, "arquivar", "cancelar")
            for user in (self.outside, self.finance):
                with self.assertRaises(PermissionDenied):
                    self.act(obj, "arquivar", user=user)
                self.client.force_login(user)
                response = self.client.post(self.url(tipo, obj, "arquivar"), dict(confirmar="on", token=uuid4()))
                self.assertEqual(response.status_code, 403)
            self.client.force_login(self.outside)
            self.assertEqual(len(self.items(self.page(visualizacao="todas"), tipo)), 0)
            self.client.force_login(self.supply)
            self.act(obj, "arquivar", user=self.leader)
            with self.assertRaises(PermissionDenied):
                self.act(obj, "cancelar", user=self.leader, motivo="Sem poder de cancelamento")
            self.leader.user_permissions.clear()
            for key in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
                self.leader.__dict__.pop(key, None)
        coordinator = self.create_user("fase2_coordinator", "coordenador")
        self.grant(coordinator, "arquivar")
        other_request = self.new("os", coordenador=coordinator)
        with self.assertRaises(PermissionDenied):
            self.act(other_request, "arquivar", user=coordinator)
        own_request = self.new("os", solicitante=coordinator, coordenador=coordinator)
        self.act(own_request, "arquivar", user=coordinator)
        # O líder de um guarda-chuva vem do projeto; a solicitação não precisa ser dele.
        project_request = self.new("aditivo", solicitado_por=self.supply)
        self.grant(self.leader, "arquivar")
        self.client.force_login(self.leader)
        self.assertIn(project_request, self.items(self.page(visualizacao="todas"), "aditivo"))
        self.act(project_request, "arquivar", user=self.leader)

    def test_25_quatro_categorias_integradas_nas_tres_abas(self):
        for tipo in MODELOS:
            active, archived = self.new(tipo), self.new(tipo)
            self.act(archived, "arquivar")
            self.assertIn(active, self.items(self.page(), tipo))
            self.assertNotIn(archived, self.items(self.page(), tipo))
            self.assertIn(archived, self.items(self.page(visualizacao="arquivadas"), tipo))
            self.assertNotIn(active, self.items(self.page(visualizacao="arquivadas"), tipo))
            all_items = self.items(self.page(visualizacao="todas"), tipo)
            self.assertIn(active, all_items); self.assertIn(archived, all_items)
            cancelled = self.new(tipo)
            self.act(cancelled, "cancelar", motivo="Listagem de canceladas")
            self.assertIn(cancelled, self.items(self.page(visualizacao="todas", status="Cancelada"), tipo))

    def test_26_filtros_pesquisa_responsavel_datas_tipo_ordenacao_e_paginacao(self):
        today = timezone.localdate().isoformat()
        for tipo in MODELOS:
            for _ in range(11):
                self.new(tipo)
            response = self.page(visualizacao="todas", tipo=tipo, q="fase dois", responsavel=self.leader.username,
                inicio=today, fim=today, ordem="id", **{dict(prospeccao="page", contratacao="page_c", os="page_os", aditivo="page_ad")[tipo]: 2})
            page = self.items(response, tipo)
            self.assertEqual(page.paginator.count, 11)
            self.assertEqual(len(page), 1)
            self.assertContains(response, f"tipo={tipo}")
            self.assertContains(response, "responsavel=fase2_leader")
            self.assertContains(response, "visualizacao=todas")
            self.assertContains(response, "ordem=id")
            for other in MODELOS:
                if other != tipo:
                    self.assertEqual(len(self.items(response, other)), 0)
        response = self.page(tipo="aditivo", status="Aguardando Aprovacao da Solicitacao", q="#1")
        self.assertEqual(self.items(response, "aditivo").paginator.count, 1)

    def test_27_requisicoes_repetidas_e_formularios_antigos_nao_duplicam_operacoes(self):
        for tipo in ("os", "aditivo"):
            obj = self.new(tipo); token = str(uuid4())
            self.act(obj, "arquivar", token=token); self.act(obj, "arquivar", token=token)
            self.assertEqual(self.history(obj).count(), 1)
            self.act(obj, "desarquivar")
            self.act(obj, "arquivar", token=token)
            obj.refresh_from_db(); self.assertFalse(obj.arquivada)
            self.act(obj, "cancelar", arquivar=True, motivo="Original")
            self.act(obj, "cancelar", arquivar=True, motivo="Reenvio")
            obj.refresh_from_db(); self.assertEqual(obj.motivo_cancelamento, "Original")
            self.assertEqual(self.history(obj).count(), 5)

    def test_28_rollback_combinado_inclui_auditoria_e_token(self):
        for tipo in ("os", "aditivo"):
            obj = self.new(tipo)
            def fail(*args):
                if args[2] == "arquivamento":
                    raise DatabaseError("Falha simulada após cancelar")
                return registrar_evento(*args)
            with patch("gestao_contratos.solicitacao_services.registrar_evento", side_effect=fail), self.assertRaises(DatabaseError):
                self.act(obj, "cancelar", arquivar=True, motivo="Atômica", token=str(uuid4()))
            obj.refresh_from_db()
            self.assertFalse(obj.arquivada or obj.cancelada)
            self.assertEqual(self.history(obj).count(), 0)
            self.assertEqual(ChaveIdempotencia.objects.count(), 0)

    def test_29_auditoria_combina_eventos_sem_sobrescrever_cancelamento(self):
        for tipo in ("os", "aditivo"):
            obj = self.new(tipo)
            self.act(obj, "cancelar", arquivar=True, motivo="Decisão")
            events = list(self.history(obj).order_by("pk"))
            self.assertEqual(len(events), 3)
            self.assertTrue(all(event.usuario_id == self.supply.pk and event.justificativa == "Decisão" for event in events))
            self.assertEqual(len({event.detalhes.split("conjunta: ")[1] for event in events}), 1)
            original = events[0].estado_posterior["cancelada_em"]
            self.act(obj, "desarquivar"); self.act(obj, "arquivar", motivo="Organização")
            obj.refresh_from_db()
            self.assertEqual(obj.cancelada_em.isoformat(), original)
            self.assertEqual(obj.motivo_cancelamento, "Decisão")

    def test_30_post_csrf_confirmacao_e_justificativa_obrigatorios(self):
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.supply)
        for tipo in ("os", "aditivo"):
            obj = self.new(tipo); url = self.url(tipo, obj, "cancelar")
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(csrf.post(url, dict(token=uuid4(), confirmar="on", motivo="Justificativa")).status_code, 403)
            self.client.post(url, dict(token=uuid4(), confirmar="on", arquivar="on"))
            obj.refresh_from_db(); self.assertFalse(obj.arquivada or obj.cancelada)
            self.client.post(url, dict(token=uuid4(), motivo="Falta confirmação"))
            obj.refresh_from_db(); self.assertFalse(obj.cancelada)

    def test_31_pendencias_home_sla_e_backlog_excluem_arquivadas_canceladas(self):
        for tipo in ("os", "aditivo"):
            obj = self.new(tipo)
            self.act(obj, "arquivar")
            cancelled = self.new(tipo)
            self.act(cancelled, "cancelar", motivo="Fim")
        self.assertNotContains(self.client.get(reverse("home")), "Demanda fase dois")
        indicators = self.client.get(reverse("indicadores_suprimento"))
        self.assertEqual(indicators.context["backlog_total"], 0)
        from .views import build_request_sla_display
        for model in (SolicitacaoOrdemServico, AditivoContratoTerceiro):
            for obj in model.objects.all():
                self.assertIsNone(build_request_sla_display(obj))

    def test_32_cancelamento_com_arquivamento_exige_ambas_permissoes(self):
        self.supply.user_permissions.clear(); self.grant(self.supply, "cancelar")
        for tipo in ("os", "aditivo"):
            obj = self.new(tipo)
            with self.assertRaises(PermissionDenied):
                self.act(obj, "cancelar", arquivar=True, motivo="Sem permissão de arquivo")
            obj.refresh_from_db(); self.assertFalse(obj.cancelada or obj.arquivada)
            self.act(obj, "cancelar", motivo="Só cancelar")

    def test_33_status_aprovado_legado_os_sem_emissao_nao_e_cancelado(self):
        obj = self.new("os", status="aprovada")
        with self.assertRaises(ValidationError):
            self.act(obj, "cancelar", motivo="Regularizar legado")
        with self.assertRaises(ValidationError):
            self.act(obj, "arquivar")
        obj.refresh_from_db(); self.assertEqual(obj.status, "aprovada")

    def test_34_os_aditivo_detalhes_incluem_controles_e_historico(self):
        for tipo, route in (("os", "detalhe_ordem_servico"), ("aditivo", "detalhes_aditivo_contrato")):
            obj = self.new(tipo)
            response = self.client.get(reverse(route, args=[obj.pk]))
            self.assertContains(response, "Cancelar solicitação")
            self.assertContains(response, "Arquivar esta solicitação após o cancelamento")
            self.act(obj, "cancelar", arquivar=True, motivo="Fim")
            response = self.client.get(reverse(route, args=[obj.pk]))
            self.assertContains(response, "Histórico de cancelamento e arquivamento")
            self.assertContains(response, "Desarquivar")
            self.assertNotContains(response, 'class="timeline"')

    def test_35_arquivar_canceladas_e_cancelar_ja_arquivadas_preserva_datas(self):
        for tipo in ("os", "aditivo"):
            obj = self.new(tipo)
            self.act(obj, "arquivar", motivo="Original")
            obj.refresh_from_db(); original = (obj.arquivada_em, obj.motivo_arquivamento)
            self.act(obj, "cancelar", motivo="Fim")
            obj.refresh_from_db()
            self.assertEqual((obj.arquivada_em, obj.motivo_arquivamento), original)
            cancellation = obj.cancelada_em
            self.act(obj, "desarquivar"); self.act(obj, "arquivar")
            obj.refresh_from_db(); self.assertEqual(obj.cancelada_em, cancellation)
        legacy = self.new("os", status="cancelada")
        self.act(legacy, "arquivar"); self.act(legacy, "desarquivar")
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, "cancelada")
        self.assertIsNone(legacy.cancelada_em)
