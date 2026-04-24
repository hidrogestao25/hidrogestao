from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    CentroDeTrabalho,
    Cliente,
    Contrato,
    ContratoTerceiros,
    DocumentoBM,
    DocumentoContratoTerceiro,
    EmpresaTerceira,
    Evento,
    OS,
    PropostaFornecedor,
    RegistroAuditoria,
    SolicitacaoContrato,
    SolicitacaoOrdemServico,
    SolicitacaoProspeccao,
)
from .views import (
    build_weekly_supply_report,
    can_user_manage_event_delivery,
    can_user_manage_os_delivery,
    can_user_manage_supplier_choice,
    criar_contrato_se_aprovado,
    criar_contrato_se_aprovado_minuta,
    format_request_line,
    get_week_ranges,
    is_request_concluded,
    send_request_notification_to_management,
    user_shares_center_with_coordinator,
)


User = get_user_model()


class BaseUserTestCase(TestCase):
    def create_user(self, username, grupo, password="senha123", email=None):
        return User.objects.create_user(
            username=username,
            password=password,
            grupo=grupo,
            email=f"{username}@example.com" if email is None else email,
            first_name=username.capitalize(),
        )

    def create_center(self, codigo="CT1", nome="Centro 1"):
        return CentroDeTrabalho.objects.create(codigo=codigo, nome=nome)

    def create_client(self, nome="Cliente Teste", cpf_cnpj=None):
        if cpf_cnpj is None:
            cpf_cnpj = f"00.000.000/0001-{Cliente.objects.count() + 1:02d}"
        return Cliente.objects.create(nome=nome, cpf_cnpj=cpf_cnpj)

    def create_contract(
        self,
        codigo="PRJ-001",
        cliente=None,
        coordenador=None,
        lider_contrato=None,
        valor_total=Decimal("1000.00"),
    ):
        return Contrato.objects.create(
            cod_projeto=codigo,
            cliente=cliente or self.create_client(),
            coordenador=coordenador,
            lider_contrato=lider_contrato,
            valor_total=valor_total,
            objeto="Objeto do contrato",
            status="ativo",
        )

    def create_supplier(self, nome="Fornecedor Teste", cpf_cnpj=None):
        if cpf_cnpj is None:
            cpf_cnpj = f"11.111.111/0001-{EmpresaTerceira.objects.count() + 1:02d}"
        email_base = nome.lower().replace(" ", "")
        return EmpresaTerceira.objects.create(
            nome=nome,
            cpf_cnpj=cpf_cnpj,
            informacoes_bancarias="Banco XPTO",
            email=f"{email_base}{EmpresaTerceira.objects.count() + 1}@example.com",
        )

    def create_supplier_contract(
        self,
        cod_projeto=None,
        empresa_terceira=None,
        coordenador=None,
        lider_contrato=None,
        guarda_chuva=False,
        status="ativo",
        num_contrato="CT-001",
    ):
        return ContratoTerceiros.objects.create(
            cod_projeto=cod_projeto or self.create_contract(),
            empresa_terceira=empresa_terceira or self.create_supplier(),
            coordenador=coordenador,
            lider_contrato=lider_contrato,
            guarda_chuva=guarda_chuva,
            num_contrato=num_contrato,
            objeto="Objeto contrato fornecedor",
            status=status,
        )

    def create_os_request(
        self,
        contrato=None,
        solicitante=None,
        lider_contrato=None,
        coordenador=None,
        titulo="OS Solicitada",
        status="pendente_lider",
    ):
        contrato = contrato or self.create_supplier_contract(guarda_chuva=True)
        return SolicitacaoOrdemServico.objects.create(
            contrato=contrato,
            cod_projeto=contrato.cod_projeto,
            solicitante=solicitante or lider_contrato or self.create_user("solicitante_os", "lider_contrato"),
            lider_contrato=lider_contrato,
            coordenador=coordenador or contrato.coordenador,
            titulo=titulo,
            descricao="Descrição da solicitação de OS",
            valor_previsto=Decimal("250.00"),
            prazo_execucao=date(2026, 4, 30),
            status=status,
        )

    def create_os(
        self,
        contrato=None,
        solicitacao=None,
        coordenador=None,
        lider_contrato=None,
        titulo="OS Cadastrada",
        status="em_execucao",
        prazo_execucao=None,
    ):
        contrato = contrato or self.create_supplier_contract(guarda_chuva=True)
        return OS.objects.create(
            contrato=contrato,
            solicitacao=solicitacao,
            cod_projeto=contrato.cod_projeto,
            coordenador=coordenador or contrato.coordenador,
            lider_contrato=lider_contrato or contrato.lider_contrato,
            titulo=titulo,
            descricao="Descrição da OS",
            valor=Decimal("350.00"),
            prazo_execucao=prazo_execucao or date(2026, 4, 20),
            status=status,
        )

    def create_event(
        self,
        contrato=None,
        prospeccao=None,
        empresa_terceira=None,
        data_prevista=None,
        realizado=False,
    ):
        contrato = contrato or self.create_supplier_contract()
        empresa_terceira = empresa_terceira or contrato.empresa_terceira
        return Evento.objects.create(
            contrato_terceiro=contrato,
            prospeccao=prospeccao,
            empresa_terceira=empresa_terceira,
            descricao="Entrega prevista",
            data_prevista=data_prevista or date(2026, 4, 18),
            valor_previsto=Decimal("500.00"),
            realizado=realizado,
        )


class GuiaPermissoesTests(BaseUserTestCase):
    def test_guia_permissoes_exige_login(self):
        response = self.client.get(reverse("guia_permissoes"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_usuario_suprimento_ve_todos_os_grupos(self):
        user = self.create_user("supri", "suprimento")
        self.client.force_login(user)

        response = self.client.get(reverse("guia_permissoes"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_view_all_groups"])
        self.assertEqual(len(response.context["group_guides"]), len(User.GRUPOS_CHOICES))
        self.assertContains(response, "Coordenador de Contrato")
        self.assertContains(response, "Gerente de Contratos")
        self.assertContains(response, "Fornecedor")

    def test_usuario_nao_suprimento_ve_apenas_o_proprio_grupo(self):
        user = self.create_user("lider", "lider_contrato")
        self.client.force_login(user)

        response = self.client.get(reverse("guia_permissoes"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_view_all_groups"])
        self.assertEqual(response.context["current_group_item"]["key"], "lider_contrato")
        self.assertContains(response, "Seu grupo")
        self.assertContains(response, "Líder de Contrato")
        self.assertNotContains(response, "Gerente de Contratos")
        self.assertNotContains(response, "Coordenador de Contrato")


class ReportSuprimentoViewTests(BaseUserTestCase):
    def test_report_suprimento_bloqueia_usuario_de_outro_grupo(self):
        user = self.create_user("lider", "lider_contrato")
        self.client.force_login(user)

        response = self.client.post(reverse("enviar_report_suprimento"), follow=True)

        self.assertRedirects(response, reverse("home"))
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("Você não tem permissão para isso!", messages)
        self.assertEqual(len(mail.outbox), 0)

    def test_report_suprimento_requer_post(self):
        user = self.create_user("supri", "suprimento")
        self.client.force_login(user)

        response = self.client.get(reverse("enviar_report_suprimento"))

        self.assertRedirects(response, reverse("home"))
        self.assertEqual(len(mail.outbox), 0)

    def test_report_suprimento_exige_email_no_usuario(self):
        user = self.create_user("supri", "suprimento", email="")
        self.client.force_login(user)

        response = self.client.post(reverse("enviar_report_suprimento"), follow=True)

        self.assertRedirects(response, reverse("home"))
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("Seu usuário não possui e-mail cadastrado.", messages)
        self.assertEqual(len(mail.outbox), 0)

    def test_report_suprimento_post_envia_email_para_o_proprio_usuario(self):
        user = self.create_user("supri", "suprimento", email="suprimento@example.com")
        self.client.force_login(user)

        response = self.client.post(reverse("enviar_report_suprimento"), follow=True)

        self.assertRedirects(response, reverse("home"))
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["suprimento@example.com"])
        self.assertEqual(email.subject, "Report Semanal de Suprimentos")

        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertIn("Report enviado para suprimento@example.com.", messages)


class PermissionHelperTests(BaseUserTestCase):
    def test_user_shares_center_with_coordinator_returns_true_when_centers_intersect(self):
        centro = self.create_center()
        gerente_lider = self.create_user("gl", "gerente_lider")
        coordenador = self.create_user("coord", "coordenador")
        gerente_lider.centros.add(centro)
        coordenador.centros.add(centro)

        self.assertTrue(user_shares_center_with_coordinator(gerente_lider, coordenador))

    def test_user_shares_center_with_coordinator_returns_false_without_intersection(self):
        centro_a = self.create_center("CTA", "Centro A")
        centro_b = self.create_center("CTB", "Centro B")
        gerente_lider = self.create_user("gl", "gerente_lider")
        coordenador = self.create_user("coord", "coordenador")
        gerente_lider.centros.add(centro_a)
        coordenador.centros.add(centro_b)

        self.assertFalse(user_shares_center_with_coordinator(gerente_lider, coordenador))

    def test_can_user_manage_supplier_choice_respects_group_rules(self):
        centro = self.create_center()
        lider = self.create_user("lider", "lider_contrato")
        outro_lider = self.create_user("outro", "lider_contrato")
        gerente_lider = self.create_user("gl", "gerente_lider")
        gerente_contrato = self.create_user("gc", "gerente_contrato")
        coordenador = self.create_user("coord", "coordenador")
        gerente_lider.centros.add(centro)
        coordenador.centros.add(centro)
        contrato = self.create_contract(codigo="PRJ-SUP", coordenador=coordenador, lider_contrato=lider)
        solicitacao = SolicitacaoProspeccao.objects.create(
            contrato=contrato,
            coordenador=coordenador,
            lider_contrato=lider,
            descricao="Solicitação teste",
            status="Triagem realizada",
        )

        self.assertTrue(can_user_manage_supplier_choice(lider, solicitacao))
        self.assertFalse(can_user_manage_supplier_choice(outro_lider, solicitacao))
        self.assertTrue(can_user_manage_supplier_choice(gerente_contrato, solicitacao))
        self.assertTrue(can_user_manage_supplier_choice(gerente_lider, solicitacao))

    def test_can_user_manage_supplier_choice_blocks_gerente_lider_outside_center(self):
        centro_a = self.create_center("CTA", "Centro A")
        centro_b = self.create_center("CTB", "Centro B")
        lider = self.create_user("lider", "lider_contrato")
        gerente_lider = self.create_user("gl", "gerente_lider")
        coordenador = self.create_user("coord", "coordenador")
        gerente_lider.centros.add(centro_a)
        coordenador.centros.add(centro_b)
        contrato = self.create_contract(codigo="PRJ-NO", coordenador=coordenador, lider_contrato=lider)
        solicitacao = SolicitacaoProspeccao.objects.create(
            contrato=contrato,
            coordenador=coordenador,
            lider_contrato=lider,
            descricao="Solicitação teste",
            status="Triagem realizada",
        )

        self.assertFalse(can_user_manage_supplier_choice(gerente_lider, solicitacao))

    def test_can_user_manage_event_delivery_respects_group_rules(self):
        centro = self.create_center()
        lider = self.create_user("lider", "lider_contrato")
        outro_lider = self.create_user("outro", "lider_contrato")
        gerente_lider = self.create_user("gl", "gerente_lider")
        gerente_contrato = self.create_user("gc", "gerente_contrato")
        coordenador = self.create_user("coord", "coordenador")
        gerente_lider.centros.add(centro)
        coordenador.centros.add(centro)
        contrato = SimpleNamespace(lider_contrato=lider, coordenador=coordenador)

        self.assertTrue(can_user_manage_event_delivery(lider, contrato))
        self.assertFalse(can_user_manage_event_delivery(outro_lider, contrato))
        self.assertTrue(can_user_manage_event_delivery(gerente_contrato, contrato))
        self.assertTrue(can_user_manage_event_delivery(gerente_lider, contrato))

    def test_can_user_manage_os_delivery_respects_group_rules(self):
        centro = self.create_center()
        lider = self.create_user("lider", "lider_contrato")
        outro_lider = self.create_user("outro", "lider_contrato")
        gerente_lider = self.create_user("gl", "gerente_lider")
        gerente_contrato = self.create_user("gc", "gerente_contrato")
        coordenador = self.create_user("coord", "coordenador")
        gerente_lider.centros.add(centro)
        coordenador.centros.add(centro)
        os_obj = SimpleNamespace(lider_contrato=lider, coordenador=coordenador)

        self.assertTrue(can_user_manage_os_delivery(lider, os_obj))
        self.assertFalse(can_user_manage_os_delivery(outro_lider, os_obj))
        self.assertTrue(can_user_manage_os_delivery(gerente_contrato, os_obj))
        self.assertTrue(can_user_manage_os_delivery(gerente_lider, os_obj))
        self.assertFalse(can_user_manage_os_delivery(None, os_obj))


class HelperFunctionTests(BaseUserTestCase):
    def test_get_week_ranges_returns_expected_boundaries(self):
        reference = date(2026, 4, 24)  # sexta-feira

        weeks = get_week_ranges(reference)

        self.assertEqual(weeks["current_week_start"], date(2026, 4, 20))
        self.assertEqual(weeks["current_week_end"], date(2026, 4, 26))
        self.assertEqual(weeks["previous_week_start"], date(2026, 4, 13))
        self.assertEqual(weeks["previous_week_end"], date(2026, 4, 19))
        self.assertEqual(weeks["next_week_start"], date(2026, 4, 27))
        self.assertEqual(weeks["next_week_end"], date(2026, 5, 3))

    def test_is_request_concluded_by_status(self):
        contrato = self.create_contract(codigo="PRJ-HELP")
        guarda_chuva = self.create_supplier_contract(
            cod_projeto=contrato,
            guarda_chuva=True,
            num_contrato="CT-HELP",
        )
        solicitante = self.create_user("solicitante", "lider_contrato")

        prospeccao = SolicitacaoProspeccao(contrato=contrato, status="Onboarding")
        solicitacao_contrato = SolicitacaoContrato(status="Onboarding")
        solicitacao_os = SolicitacaoOrdemServico(
            contrato=guarda_chuva,
            solicitante=solicitante,
            titulo="OS",
            descricao="Descrição",
            status="finalizada",
        )
        solicitacao_os_pendente = SolicitacaoOrdemServico(
            contrato=guarda_chuva,
            solicitante=solicitante,
            titulo="OS pendente",
            descricao="Descrição",
            status="pendente_lider",
        )

        self.assertTrue(is_request_concluded(prospeccao))
        self.assertTrue(is_request_concluded(solicitacao_contrato))
        self.assertTrue(is_request_concluded(solicitacao_os))
        self.assertFalse(is_request_concluded(solicitacao_os_pendente))

    def test_format_request_line_uses_type_id_and_status(self):
        contrato = self.create_contract(codigo="PRJ-LINE")
        solicitacao = SolicitacaoProspeccao.objects.create(
            contrato=contrato,
            descricao="Comprar serviço especializado",
            status="Triagem realizada",
        )

        line = format_request_line("Prospecção", solicitacao)

        self.assertIn("Prospecção", line)
        self.assertIn(f"#{solicitacao.id}", line)
        self.assertIn("Triagem realizada", line)

    def test_send_request_notification_to_management_sends_only_to_valid_recipients(self):
        self.create_user("diretor", "diretoria", email="diretor@example.com")
        self.create_user("gerente_contrato", "gerente_contrato", email="gc@example.com")
        self.create_user("sem_email", "diretoria", email="")
        self.create_user("lider", "lider_contrato", email="lider@example.com")

        send_request_notification_to_management("Nova solicitação", "Mensagem de teste")

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.subject, "Nova solicitação")
        self.assertCountEqual(email.to, ["diretor@example.com", "gc@example.com"])


class WeeklyReportBuilderTests(BaseUserTestCase):
    def test_build_weekly_supply_report_includes_expected_sections_and_records(self):
        reference_date = date(2026, 4, 24)
        weeks = get_week_ranges(reference_date)

        suprimento = self.create_user("supri", "suprimento", email="supri@example.com")
        coordenador = self.create_user("coord", "coordenador")
        lider = self.create_user("lider", "lider_contrato")
        cliente = self.create_client("Cliente Report", "22.222.222/0001-22")
        contrato = self.create_contract(
            codigo="PRJ-REPORT",
            cliente=cliente,
            coordenador=coordenador,
            lider_contrato=lider,
        )
        fornecedor = self.create_supplier("Fornecedor Report", "33.333.333/0001-33")
        contrato_terceiro = self.create_supplier_contract(
            cod_projeto=contrato,
            empresa_terceira=fornecedor,
            coordenador=coordenador,
            lider_contrato=lider,
            guarda_chuva=True,
            status="encerrado",
            num_contrato="CTR-REPORT",
        )
        contrato_terceiro.data_fim = weeks["previous_week_end"]
        contrato_terceiro.save(update_fields=["data_fim"])

        prospeccao = SolicitacaoProspeccao.objects.create(
            contrato=contrato,
            coordenador=coordenador,
            lider_contrato=lider,
            descricao="Prospecção semanal",
            status="Em análise",
        )
        SolicitacaoProspeccao.objects.filter(pk=prospeccao.pk).update(
            data_solicitacao=timezone.make_aware(
                datetime.combine(weeks["previous_week_start"], datetime.min.time())
            )
        )
        prospeccao.refresh_from_db()

        solicitacao_os = SolicitacaoOrdemServico.objects.create(
            contrato=contrato_terceiro,
            cod_projeto=contrato,
            solicitante=lider,
            lider_contrato=lider,
            coordenador=coordenador,
            titulo="OS semanal",
            descricao="OS criada na semana anterior",
            status="finalizada",
        )
        SolicitacaoOrdemServico.objects.filter(pk=solicitacao_os.pk).update(
            criado_em=timezone.make_aware(
                datetime.combine(weeks["previous_week_start"], datetime.min.time())
            )
        )

        Evento.objects.create(
            empresa_terceira=fornecedor,
            contrato_terceiro=contrato_terceiro,
            descricao="Entrega semana anterior",
            data_prevista=weeks["previous_week_end"],
            data_entrega=weeks["previous_week_end"],
            realizado=True,
        )
        Evento.objects.create(
            empresa_terceira=fornecedor,
            contrato_terceiro=contrato_terceiro,
            descricao="Entrega semana atual",
            data_prevista=weeks["current_week_start"],
            realizado=False,
        )
        contrato_proxima_semana = self.create_supplier_contract(
            cod_projeto=contrato,
            empresa_terceira=fornecedor,
            coordenador=coordenador,
            lider_contrato=lider,
            guarda_chuva=False,
            status="ativo",
            num_contrato="CTR-NEXT",
        )
        contrato_proxima_semana.data_fim = weeks["next_week_start"]
        contrato_proxima_semana.save(update_fields=["data_fim"])

        with patch("gestao_contratos.views.timezone.localdate", return_value=reference_date):
            html = build_weekly_supply_report(suprimento)

        self.assertIn("Report Semanal de Suprimentos", html)
        self.assertIn("Semana anterior", html)
        self.assertIn("Semana atual", html)
        self.assertIn("Próxima semana", html)
        self.assertIn("Solicitação para PRJ-REPORT - Cliente Report", html)
        self.assertIn("OS semanal", html)
        self.assertIn("Entrega semana anterior", html)
        self.assertIn("Entrega semana atual", html)
        self.assertIn("Fornecedor Report", html)
        self.assertIn("Solicitações criadas", html)
        self.assertIn("Contratos previstos para finalizar na próxima semana", html)


class ApproveFornecedorGerenteTests(BaseUserTestCase):
    def setUp(self):
        self.centro = self.create_center()
        self.coordenador = self.create_user("coord", "coordenador")
        self.lider = self.create_user("lider", "lider_contrato")
        self.gerente_contrato = self.create_user("gc", "gerente_contrato")
        self.gerente_lider = self.create_user("gl", "gerente_lider")
        self.suprimento = self.create_user("supri", "suprimento")
        self.diretor = self.create_user("diretor", "diretoria")
        self.coordenador.centros.add(self.centro)
        self.gerente_lider.centros.add(self.centro)
        self.contrato = self.create_contract(
            codigo="PRJ-APR",
            coordenador=self.coordenador,
            lider_contrato=self.lider,
        )
        self.fornecedor = self.create_supplier("Fornecedor Aprovação", "44.444.444/0001-44")
        self.solicitacao = SolicitacaoProspeccao.objects.create(
            contrato=self.contrato,
            coordenador=self.coordenador,
            lider_contrato=self.lider,
            descricao="Solicitação para aprovação",
            aprovado=True,
            triagem_realizada=True,
            fornecedor_escolhido=self.fornecedor,
            status="Fornecedor selecionado",
        )

    def test_aprovar_fornecedor_gerente_bloqueia_usuario_sem_permissao(self):
        self.client.force_login(self.suprimento)

        response = self.client.post(
            reverse("aprovar_fornecedor_gerente", args=[self.solicitacao.pk]),
            {"acao": "aprovar"},
            follow=True,
        )

        self.assertRedirects(response, reverse("home"))
        self.solicitacao.refresh_from_db()
        self.assertEqual(self.solicitacao.aprovacao_fornecedor_gerente, "pendente")

    def test_aprovar_fornecedor_gerente_como_gerente_contrato(self):
        self.client.force_login(self.gerente_contrato)

        response = self.client.post(
            reverse("aprovar_fornecedor_gerente", args=[self.solicitacao.pk]),
            {"acao": "aprovar"},
            follow=True,
        )

        self.assertRedirects(response, reverse("lista_solicitacoes"))
        self.solicitacao.refresh_from_db()
        self.assertEqual(self.solicitacao.aprovacao_fornecedor_gerente, "aprovado")
        self.assertIsNotNone(self.solicitacao.aprocacao_fornecedor_gerente_em)

    def test_aprovar_fornecedor_gerente_como_gerente_lider_fora_do_centro(self):
        outro_centro = self.create_center("CT2", "Centro 2")
        gerente_lider_sem_escopo = self.create_user("gl2", "gerente_lider")
        gerente_lider_sem_escopo.centros.add(outro_centro)
        self.client.force_login(gerente_lider_sem_escopo)

        response = self.client.post(
            reverse("aprovar_fornecedor_gerente", args=[self.solicitacao.pk]),
            {"acao": "aprovar"},
            follow=True,
        )

        self.assertRedirects(response, reverse("home"))
        self.solicitacao.refresh_from_db()
        self.assertEqual(self.solicitacao.aprovacao_fornecedor_gerente, "pendente")

    def test_reprovar_fornecedor_gerente_limpa_escolha_e_solicita_nova_triagem(self):
        self.client.force_login(self.gerente_contrato)

        response = self.client.post(
            reverse("aprovar_fornecedor_gerente", args=[self.solicitacao.pk]),
            {"acao": "reprovar", "justificativa": "Fornecedor fora do escopo"},
            follow=True,
        )

        self.assertRedirects(response, reverse("lista_solicitacoes"))
        self.solicitacao.refresh_from_db()
        self.assertEqual(self.solicitacao.aprovacao_fornecedor_gerente, "reprovado")
        self.assertEqual(self.solicitacao.status, "Fornecedor reprovado pela gerência")
        self.assertFalse(self.solicitacao.triagem_realizada)
        self.assertIsNone(self.solicitacao.fornecedor_escolhido)
        self.assertEqual(self.solicitacao.justificativa_gerencia, "Fornecedor fora do escopo")

    def test_aprovar_fornecedor_gerente_define_status_final_quando_diretoria_ja_aprovou(self):
        self.solicitacao.aprovacao_fornecedor_diretor = "aprovado"
        self.solicitacao.save(update_fields=["aprovacao_fornecedor_diretor"])
        self.client.force_login(self.gerente_contrato)

        response = self.client.post(
            reverse("aprovar_fornecedor_gerente", args=[self.solicitacao.pk]),
            {"acao": "aprovar"},
            follow=True,
        )

        self.assertRedirects(response, reverse("lista_solicitacoes"))
        self.solicitacao.refresh_from_db()
        self.assertEqual(self.solicitacao.status, "Fornecedor aprovado")
        self.assertGreaterEqual(len(mail.outbox), 1)


class DocumentoBMApprovalTests(BaseUserTestCase):
    def setUp(self):
        self.coordenador_group = Group.objects.create(name="Coordenador de Contrato")
        self.gerente_group = Group.objects.create(name="Gerente de Contrato")
        self.coordenador = self.create_user("coord", "coordenador")
        self.gerente_contrato = self.create_user("gc", "gerente_contrato")
        self.suprimento = self.create_user("supri", "suprimento")
        self.coordenador.groups.add(self.coordenador_group)
        self.gerente_contrato.groups.add(self.gerente_group)

        self.cliente = self.create_client("Cliente BM", "55.555.555/0001-55")
        self.contrato = self.create_contract(
            codigo="PRJ-BM",
            cliente=self.cliente,
            coordenador=self.coordenador,
            lider_contrato=self.gerente_contrato,
        )
        self.solicitacao = SolicitacaoProspeccao.objects.create(
            contrato=self.contrato,
            coordenador=self.coordenador,
            lider_contrato=self.gerente_contrato,
            descricao="Solicitação BM",
            status="Planejamento do contrato",
        )
        self.documento_bm = DocumentoBM.objects.create(solicitacao=self.solicitacao)

    def test_aprovar_bm_como_coordenador(self):
        self.client.force_login(self.coordenador)

        response = self.client.get(reverse("aprovar_bm", args=[self.documento_bm.pk, "coordenador"]))

        self.assertRedirects(
            response,
            reverse("detalhe_bm", kwargs={"pk": self.documento_bm.pk}),
            fetch_redirect_response=False,
        )
        self.documento_bm.refresh_from_db()
        self.assertEqual(self.documento_bm.status_coordenador, "aprovado")
        self.assertIsNotNone(self.documento_bm.data_aprovacao_coordenador)

    def test_aprovar_bm_como_gerente(self):
        self.client.force_login(self.gerente_contrato)

        response = self.client.get(reverse("aprovar_bm", args=[self.documento_bm.pk, "gerente"]))

        self.assertRedirects(response, reverse("detalhe_bm", kwargs={"pk": self.documento_bm.pk}))
        self.documento_bm.refresh_from_db()
        self.assertEqual(self.documento_bm.status_gerente, "aprovado")
        self.assertIsNotNone(self.documento_bm.data_aprovacao_gerente)

    def test_aprovar_bm_bloqueia_usuario_sem_group_do_django(self):
        self.client.force_login(self.suprimento)

        response = self.client.get(
            reverse("aprovar_bm", args=[self.documento_bm.pk, "gerente"]),
            follow=True,
        )

        self.assertRedirects(response, reverse("lista_solicitacoes"))
        self.documento_bm.refresh_from_db()
        self.assertEqual(self.documento_bm.status_gerente, "pendente")

    def test_reprovar_bm_como_gerente_envia_email_para_suprimento(self):
        self.client.force_login(self.gerente_contrato)

        response = self.client.get(reverse("reprovar_bm", args=[self.documento_bm.pk, "gerente"]))

        self.assertRedirects(response, reverse("detalhe_bm", kwargs={"pk": self.documento_bm.pk}))
        self.documento_bm.refresh_from_db()
        self.assertEqual(self.documento_bm.status_gerente, "reprovado")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.suprimento.email, mail.outbox[0].to)

    def test_reprovar_bm_bloqueia_usuario_sem_permissao(self):
        self.client.force_login(self.suprimento)

        response = self.client.get(
            reverse("reprovar_bm", args=[self.documento_bm.pk, "coordenador"]),
            follow=True,
        )

        self.assertRedirects(response, reverse("lista_solicitacoes"))
        self.documento_bm.refresh_from_db()
        self.assertEqual(self.documento_bm.status_coordenador, "pendente")


class SolicitarOSViewTests(BaseUserTestCase):
    def setUp(self):
        self.centro = self.create_center()
        self.lider = self.create_user("lideros", "lider_contrato")
        self.gerente_lider = self.create_user("glos", "gerente_lider")
        self.coordenador = self.create_user("coordos", "coordenador")
        self.suprimento = self.create_user("suprios", "suprimento")
        self.coordenador.centros.add(self.centro)
        self.gerente_lider.centros.add(self.centro)
        self.contrato_base = self.create_contract(
            codigo="PRJ-OS",
            coordenador=self.coordenador,
            lider_contrato=self.lider,
        )
        self.contrato_terceiro = self.create_supplier_contract(
            cod_projeto=self.contrato_base,
            coordenador=self.coordenador,
            lider_contrato=self.lider,
            guarda_chuva=True,
            num_contrato="CT-OS-001",
        )

    def test_solicitar_os_com_contrato_bloqueia_usuario_sem_permissao(self):
        self.client.force_login(self.suprimento)

        response = self.client.get(reverse("solicitar_os_com_contrato"), follow=True)

        self.assertRedirects(response, reverse("home"))
        self.assertEqual(SolicitacaoOrdemServico.objects.count(), 0)

    def test_lider_contrato_pode_criar_solicitacao_os_com_contrato(self):
        self.client.force_login(self.lider)

        response = self.client.post(
            reverse("solicitar_os_com_contrato"),
            {
                "contrato": self.contrato_terceiro.pk,
                "cod_projeto": self.contrato_base.pk,
                "titulo": "Nova OS do líder",
                "descricao": "Precisa executar o serviço",
                "valor_previsto": "R$ 1.234,56",
                "prazo_execucao": "2026-04-30",
                "coordenador": self.coordenador.pk,
            },
            follow=False,
        )

        os_request = SolicitacaoOrdemServico.objects.get()
        self.assertRedirects(response, reverse("detalhe_ordem_servico", kwargs={"pk": os_request.pk}), fetch_redirect_response=False)
        self.assertEqual(os_request.solicitante, self.lider)
        self.assertEqual(os_request.lider_contrato, self.lider)
        self.assertEqual(os_request.status, "pendente_lider")
        self.assertEqual(os_request.contrato, self.contrato_terceiro)
        self.assertEqual(os_request.valor_previsto, Decimal("1234.56"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.lider.email])

    def test_gerente_lider_ve_apenas_contratos_do_mesmo_centro_no_form(self):
        outro_centro = self.create_center("CT2", "Centro 2")
        outro_coord = self.create_user("coordfora", "coordenador")
        outro_coord.centros.add(outro_centro)
        outro_base = self.create_contract(codigo="PRJ-FORA", coordenador=outro_coord, lider_contrato=self.lider)
        self.create_supplier_contract(
            cod_projeto=outro_base,
            coordenador=outro_coord,
            lider_contrato=self.lider,
            guarda_chuva=True,
            num_contrato="CT-OS-002",
        )

        self.client.force_login(self.gerente_lider)
        response = self.client.get(reverse("solicitar_os_com_contrato"))

        self.assertEqual(response.status_code, 200)
        contratos = list(response.context["form"].fields["contrato"].queryset)
        coordenadores = list(response.context["form"].fields["coordenador"].queryset)
        self.assertEqual(contratos, [self.contrato_terceiro])
        self.assertEqual(coordenadores, [self.coordenador])


class CenterScopedViewTests(BaseUserTestCase):
    def setUp(self):
        self.centro_compartilhado = self.create_center()
        self.centro_outro = self.create_center("CT2", "Centro 2")
        self.gerente_lider = self.create_user("glscope", "gerente_lider")
        self.lider = self.create_user("liderscope", "lider_contrato")
        self.gerente_lider.centros.add(self.centro_compartilhado)
        self.coord_ok = self.create_user("coordok", "coordenador")
        self.coord_ok.centros.add(self.centro_compartilhado)
        self.coord_fora = self.create_user("coordfora2", "coordenador")
        self.coord_fora.centros.add(self.centro_outro)

        self.base_ok = self.create_contract(codigo="PRJ-OK", coordenador=self.coord_ok, lider_contrato=self.lider)
        self.base_fora = self.create_contract(codigo="PRJ-FORA2", coordenador=self.coord_fora, lider_contrato=self.lider)
        self.ct_ok = self.create_supplier_contract(
            cod_projeto=self.base_ok,
            coordenador=self.coord_ok,
            lider_contrato=self.lider,
            guarda_chuva=True,
            num_contrato="CT-SCOPE-1",
        )
        self.ct_fora = self.create_supplier_contract(
            cod_projeto=self.base_fora,
            coordenador=self.coord_fora,
            lider_contrato=self.lider,
            guarda_chuva=True,
            num_contrato="CT-SCOPE-2",
        )
        self.solic_ok = SolicitacaoProspeccao.objects.create(
            contrato=self.base_ok,
            coordenador=self.coord_ok,
            lider_contrato=self.lider,
            descricao="Solicitação visível",
            status="Solicitação de prospecção",
        )
        self.solic_fora = SolicitacaoProspeccao.objects.create(
            contrato=self.base_fora,
            coordenador=self.coord_fora,
            lider_contrato=self.lider,
            descricao="Solicitação oculta",
            status="Solicitação de prospecção",
        )
        self.os_visivel = self.create_os(
            contrato=self.ct_ok,
            coordenador=self.coord_ok,
            lider_contrato=self.lider,
            titulo="OS visível",
        )
        self.os_oculta = self.create_os(
            contrato=self.ct_fora,
            coordenador=self.coord_fora,
            lider_contrato=self.lider,
            titulo="OS oculta",
        )
        self.os_request_visivel = self.create_os_request(
            contrato=self.ct_ok,
            solicitante=self.lider,
            lider_contrato=self.lider,
            coordenador=self.coord_ok,
            titulo="Solicitação OS visível",
        )
        self.os_request_oculta = self.create_os_request(
            contrato=self.ct_fora,
            solicitante=self.lider,
            lider_contrato=self.lider,
            coordenador=self.coord_fora,
            titulo="Solicitação OS oculta",
        )

    def test_lista_solicitacoes_do_gerente_lider_filtra_por_centro(self):
        self.client.force_login(self.gerente_lider)

        response = self.client.get(reverse("lista_solicitacoes"))

        self.assertEqual(response.status_code, 200)
        lista_ids = {item["solicitacao"].pk for item in response.context["lista_solicitacoes"]}
        os_ids = {item.pk for item in response.context["ordens_servico_page"].object_list}
        self.assertIn(self.solic_ok.pk, lista_ids)
        self.assertNotIn(self.solic_fora.pk, lista_ids)
        self.assertIn(self.os_visivel.pk, os_ids)
        self.assertNotIn(self.os_oculta.pk, os_ids)

    def test_detalhes_solicitacao_bloqueia_gerente_lider_fora_do_centro(self):
        self.client.force_login(self.gerente_lider)

        response = self.client.get(reverse("detalhes_solicitacao", args=[self.solic_fora.pk]), follow=True)

        self.assertRedirects(response, reverse("home"))

    def test_detalhe_os_bloqueia_gerente_lider_fora_do_centro(self):
        self.client.force_login(self.gerente_lider)

        response = self.client.get(reverse("detalhe_ordem_servico", args=[self.os_request_oculta.pk]), follow=True)

        self.assertRedirects(response, reverse("lista_solicitacoes"))

    def test_lista_ordens_servico_filtra_por_centro_e_busca_por_titulo(self):
        self.client.force_login(self.gerente_lider)

        response = self.client.get(reverse("lista_ordens_servico"), {"search": "visível"})

        self.assertEqual(response.status_code, 200)
        os_ids = {item.pk for item in response.context["page_obj"].object_list}
        self.assertEqual(os_ids, {self.os_visivel.pk})


class DeliveryRegistrationTests(BaseUserTestCase):
    def setUp(self):
        self.centro = self.create_center()
        self.outro_centro = self.create_center("CT2", "Centro 2")
        self.lider = self.create_user("liderent", "lider_contrato")
        self.gerente_lider = self.create_user("glent", "gerente_lider")
        self.gerente_contrato = self.create_user("gcent", "gerente_contrato")
        self.suprimento = self.create_user("suprent", "suprimento")
        self.coordenador = self.create_user("coordent", "coordenador")
        self.coordenador.centros.add(self.centro)
        self.gerente_lider.centros.add(self.centro)
        self.contrato_base = self.create_contract(
            codigo="PRJ-ENT",
            coordenador=self.coordenador,
            lider_contrato=self.lider,
        )
        self.contrato_terceiro = self.create_supplier_contract(
            cod_projeto=self.contrato_base,
            coordenador=self.coordenador,
            lider_contrato=self.lider,
            guarda_chuva=True,
            num_contrato="CT-ENT-1",
        )
        self.evento = self.create_event(contrato=self.contrato_terceiro, data_prevista=date(2026, 4, 18))
        self.os = self.create_os(
            contrato=self.contrato_terceiro,
            coordenador=self.coordenador,
            lider_contrato=self.lider,
            prazo_execucao=date(2026, 4, 20),
        )

    def test_registrar_entrega_evento_bloqueia_lider_sem_vinculo(self):
        outro_lider = self.create_user("liderfora", "lider_contrato")
        self.client.force_login(outro_lider)

        response = self.client.get(reverse("registrar_entrega", args=[self.evento.pk]), follow=True)

        self.assertRedirects(response, reverse("home"))

    def test_registrar_entrega_evento_como_gerente_contrato_atualiza_campos(self):
        self.client.force_login(self.gerente_contrato)

        response = self.client.post(
            reverse("registrar_entrega", args=[self.evento.pk]),
            {
                "observacao": "Entrega concluída",
                "caminho_evidencia": "C:/evidencias/entrega.pdf",
                "justificativa": "",
                "avaliacao": "Aprovado",
                "data_entrega": "2026-04-21",
                "realizado": "on",
                "valor_pago": "480.00",
                "data_pagamento": "2026-04-22",
            },
            follow=False,
        )

        self.assertRedirects(
            response,
            reverse("contrato_fornecedor_detalhe", kwargs={"pk": self.contrato_terceiro.pk}),
            fetch_redirect_response=False,
        )
        self.evento.refresh_from_db()
        self.assertTrue(self.evento.realizado)
        self.assertEqual(self.evento.avaliacao, "Aprovado")
        self.assertEqual(self.evento.data_entrega, date(2026, 4, 21))
        self.assertEqual(self.evento.valor_pago, Decimal("480.00"))

    def test_registrar_entrega_os_como_gerente_lider_finaliza_com_atraso(self):
        self.client.force_login(self.gerente_lider)

        response = self.client.post(
            reverse("registrar_entrega_os", args=[self.os.pk]),
            {
                "caminho_evidencia": "C:/evidencias/os.pdf",
                "avaliacao": "Aprovado",
                "data_entrega": "2026-04-22",
                "realizado": "on",
                "valor_pago": "350.00",
                "data_pagamento": "2026-04-23",
                "observacao": "Finalizada com atraso",
            },
            follow=False,
        )

        self.assertRedirects(
            response,
            reverse("detalhes_os", kwargs={"pk": self.os.pk}),
            fetch_redirect_response=False,
        )


class OrdemServicoApprovalFlowTests(BaseUserTestCase):
    def setUp(self):
        self.centro = self.create_center()
        self.outro_centro = self.create_center("CT2", "Centro 2")
        self.lider = self.create_user("liderflow", "lider_contrato")
        self.gerente_lider = self.create_user("glflow", "gerente_lider")
        self.gerente_contrato = self.create_user("gcflow", "gerente_contrato")
        self.suprimento = self.create_user("supriflow", "suprimento")
        self.coordenador = self.create_user("coordflow", "coordenador")
        self.coordenador.centros.add(self.centro)
        self.gerente_lider.centros.add(self.centro)
        self.contrato_base = self.create_contract(
            codigo="PRJ-FLOW",
            coordenador=self.coordenador,
            lider_contrato=self.lider,
        )
        self.contrato_terceiro = self.create_supplier_contract(
            cod_projeto=self.contrato_base,
            coordenador=self.coordenador,
            lider_contrato=self.lider,
            guarda_chuva=True,
            num_contrato="CT-FLOW-1",
        )

    def test_aprovar_os_lider_como_lider_envia_para_suprimento(self):
        os_request = self.create_os_request(
            contrato=self.contrato_terceiro,
            solicitante=self.lider,
            lider_contrato=self.lider,
            coordenador=self.coordenador,
            status="pendente_lider",
        )
        self.client.force_login(self.lider)

        response = self.client.get(reverse("aprovar_os_lider", args=[os_request.pk, "aprovar"]), follow=False)

        self.assertRedirects(
            response,
            reverse("detalhe_ordem_servico", kwargs={"pk": os_request.pk}),
            fetch_redirect_response=False,
        )
        os_request.refresh_from_db()
        self.assertEqual(os_request.status, "pendente_suprimento")
        self.assertEqual(os_request.aprovacao_lider, self.lider.username)
        self.assertIsNotNone(os_request.aprovado_lider_em)
        self.assertGreaterEqual(len(mail.outbox), 1)

    def test_aprovar_os_lider_bloqueia_gerente_lider_fora_do_centro(self):
        gerente_lider_fora = self.create_user("glsemfluxo", "gerente_lider")
        gerente_lider_fora.centros.add(self.outro_centro)
        os_request = self.create_os_request(
            contrato=self.contrato_terceiro,
            solicitante=self.lider,
            lider_contrato=self.lider,
            coordenador=self.coordenador,
            status="pendente_lider",
        )
        self.client.force_login(gerente_lider_fora)

        response = self.client.get(reverse("aprovar_os_lider", args=[os_request.pk, "aprovar"]), follow=False)

        self.assertRedirects(
            response,
            reverse("detalhe_ordem_servico", kwargs={"pk": os_request.pk}),
            fetch_redirect_response=False,
        )
        os_request.refresh_from_db()
        self.assertEqual(os_request.status, "pendente_lider")

    def test_aprovar_os_gerente_contrato_cria_os(self):
        os_request = self.create_os_request(
            contrato=self.contrato_terceiro,
            solicitante=self.lider,
            lider_contrato=self.lider,
            coordenador=self.coordenador,
            status="pendente_gerente",
            titulo="OS para aprovação final",
        )
        self.client.force_login(self.gerente_contrato)

        response = self.client.get(reverse("aprovar_os_gerente_contrato", args=[os_request.pk, "aprovar"]), follow=False)

        self.assertRedirects(
            response,
            reverse("detalhe_ordem_servico", kwargs={"pk": os_request.pk}),
            fetch_redirect_response=False,
        )
        os_request.refresh_from_db()
        self.assertEqual(os_request.status, "aprovada")
        os_cadastrada = OS.objects.get(solicitacao=os_request)
        self.assertEqual(os_cadastrada.contrato, self.contrato_terceiro)
        self.assertEqual(os_cadastrada.titulo, "OS para aprovação final")
        self.assertEqual(os_cadastrada.coordenador, self.lider)
        self.assertEqual(os_cadastrada.valor, os_request.valor_previsto)

    def test_aprovar_os_gerente_contrato_reprova_sem_criar_os(self):
        os_request = self.create_os_request(
            contrato=self.contrato_terceiro,
            solicitante=self.lider,
            lider_contrato=self.lider,
            coordenador=self.coordenador,
            status="pendente_gerente",
        )
        self.client.force_login(self.gerente_contrato)

        response = self.client.get(reverse("aprovar_os_gerente_contrato", args=[os_request.pk, "reprovar"]), follow=False)

        self.assertRedirects(
            response,
            reverse("detalhe_ordem_servico", kwargs={"pk": os_request.pk}),
            fetch_redirect_response=False,
        )
        os_request.refresh_from_db()
        self.assertEqual(os_request.status, "reprovada")
        self.assertFalse(OS.objects.filter(solicitacao=os_request).exists())


class AuditoriaTests(BaseUserTestCase):
    def setUp(self):
        self.centro = self.create_center()
        self.lider = self.create_user("lideraudit", "lider_contrato")
        self.gerente_lider = self.create_user("glaudit", "gerente_lider")
        self.coordenador = self.create_user("coordaudit", "coordenador")
        self.coordenador.centros.add(self.centro)
        self.gerente_lider.centros.add(self.centro)
        self.contrato_base = self.create_contract(
            codigo="PRJ-AUD",
            coordenador=self.coordenador,
            lider_contrato=self.lider,
        )
        self.contrato_terceiro = self.create_supplier_contract(
            cod_projeto=self.contrato_base,
            coordenador=self.coordenador,
            lider_contrato=self.lider,
            guarda_chuva=True,
            num_contrato="CT-AUD-1",
        )

    def xest_criacao_via_view_gera_registro_auditoria(self):
        self.client.force_login(self.lider)

        response = self.client.post(
            reverse("solicitar_os_com_contrato"),
            {
                "contrato": self.contrato_terceiro.pk,
                "cod_projeto": self.contrato_base.pk,
                "titulo": "OS auditada",
                "descricao": "Criada com auditoria",
                "valor_previsto": "R$ 999,99",
                "prazo_execucao": "2026-04-30",
                "coordenador": self.coordenador.pk,
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        os_request = SolicitacaoOrdemServico.objects.get(titulo="OS auditada")
        auditoria = RegistroAuditoria.objects.filter(
            object_id=os_request.pk,
            acao="criado",
            modelo="Solicitação Ordem Servico",
        ).first()
        self.assertIsNotNone(auditoria)
        self.assertEqual(auditoria.usuario, self.lider)
        self.assertEqual(auditoria.detalhes, "POST /solicitar-os/")

    def xest_atualizacao_via_view_gera_registro_auditoria(self):
        os_cadastrada = self.create_os(
            contrato=self.contrato_terceiro,
            coordenador=self.coordenador,
            lider_contrato=self.lider,
            prazo_execucao=date(2026, 4, 20),
        )
        self.client.force_login(self.gerente_lider)

        response = self.client.post(
            reverse("registrar_entrega_os", args=[os_cadastrada.pk]),
            {
                "caminho_evidencia": "C:/audit/os.pdf",
                "avaliacao": "Aprovado",
                "data_entrega": "2026-04-21",
                "realizado": "on",
                "valor_pago": "350.00",
                "data_pagamento": "2026-04-22",
                "observacao": "Atualização auditada",
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        auditoria = RegistroAuditoria.objects.filter(
            object_id=os_cadastrada.pk,
            acao="atualizado",
            modelo="Os",
        ).first()
        self.assertIsNotNone(auditoria)
        self.assertEqual(auditoria.usuario, self.gerente_lider)
        self.assertEqual(auditoria.detalhes, f"POST /ordem-servico/{os_cadastrada.pk}/registrar-entrega/")
        self.os.refresh_from_db()
        self.assertTrue(self.os.realizado)
        self.assertTrue(self.os.com_atraso)
        self.assertEqual(self.os.status, "finalizada")
        self.assertEqual(self.os.data_entrega, date(2026, 4, 22))

    def xest_registrar_entrega_os_bloqueia_gerente_lider_sem_centro_compartilhado(self):
        gerente_lider_fora = self.create_user("glfora", "gerente_lider")
        gerente_lider_fora.centros.add(self.outro_centro)
        self.client.force_login(gerente_lider_fora)

        response = self.client.get(reverse("registrar_entrega_os", args=[self.os.pk]), follow=False)

        self.assertRedirects(
            response,
            reverse("detalhes_os", kwargs={"pk": self.os.pk}),
            fetch_redirect_response=False,
        )


class AuditoriaViewTests(BaseUserTestCase):
    def setUp(self):
        self.centro = self.create_center()
        self.lider = self.create_user("lideraudit2", "lider_contrato")
        self.gerente_lider = self.create_user("glaudit2", "gerente_lider")
        self.coordenador = self.create_user("coordaudit2", "coordenador")
        self.coordenador.centros.add(self.centro)
        self.gerente_lider.centros.add(self.centro)
        self.contrato_base = self.create_contract(
            codigo="PRJ-AUD2",
            coordenador=self.coordenador,
            lider_contrato=self.lider,
        )
        self.contrato_terceiro = self.create_supplier_contract(
            cod_projeto=self.contrato_base,
            coordenador=self.coordenador,
            lider_contrato=self.lider,
            guarda_chuva=True,
            num_contrato="CT-AUD-2",
        )

    def test_criacao_via_view_gera_registro_auditoria(self):
        self.client.force_login(self.lider)

        response = self.client.post(
            reverse("solicitar_os_com_contrato"),
            {
                "contrato": self.contrato_terceiro.pk,
                "cod_projeto": self.contrato_base.pk,
                "titulo": "OS auditada 2",
                "descricao": "Criada com auditoria",
                "valor_previsto": "R$ 999,99",
                "prazo_execucao": "2026-04-30",
                "coordenador": self.coordenador.pk,
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        os_request = SolicitacaoOrdemServico.objects.get(titulo="OS auditada 2")
        auditoria = RegistroAuditoria.objects.filter(
            object_id=os_request.pk,
            acao="criado",
            usuario=self.lider,
            detalhes="POST /solicitar-os/",
        ).first()
        self.assertIsNotNone(auditoria)

    def test_atualizacao_via_view_gera_registro_auditoria(self):
        os_cadastrada = self.create_os(
            contrato=self.contrato_terceiro,
            coordenador=self.coordenador,
            lider_contrato=self.lider,
            prazo_execucao=date(2026, 4, 20),
        )
        self.client.force_login(self.gerente_lider)

        response = self.client.post(
            reverse("registrar_entrega_os", args=[os_cadastrada.pk]),
            {
                "caminho_evidencia": "C:/audit/os.pdf",
                "avaliacao": "Aprovado",
                "data_entrega": "2026-04-21",
                "realizado": "on",
                "valor_pago": "350.00",
                "data_pagamento": "2026-04-22",
                "observacao": "Atualização auditada",
            },
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        auditoria = RegistroAuditoria.objects.filter(
            object_id=os_cadastrada.pk,
            acao="atualizado",
            usuario=self.gerente_lider,
            detalhes=f"POST /ordem-servico/{os_cadastrada.pk}/registrar-entrega/",
        ).first()
        self.assertIsNotNone(auditoria)
        os_cadastrada.refresh_from_db()
        self.assertTrue(os_cadastrada.realizado)
        self.assertTrue(os_cadastrada.com_atraso)
        self.assertEqual(os_cadastrada.status, "finalizada")


class ContratacaoFlowTests(BaseUserTestCase):
    def setUp(self):
        self.centro = self.create_center()
        self.lider = self.create_user("lidercontr", "lider_contrato")
        self.gerente_lider = self.create_user("glcontr", "gerente_lider")
        self.gerente_contrato = self.create_user("gccontr", "gerente_contrato")
        self.diretoria = self.create_user("dircontr", "diretoria")
        self.suprimento = self.create_user("supcontr", "suprimento")
        self.coordenador = self.create_user("coordcontr", "coordenador")
        self.coordenador.centros.add(self.centro)
        self.gerente_lider.centros.add(self.centro)
        self.contrato_base = self.create_contract(
            codigo="PRJ-CONTR",
            coordenador=self.coordenador,
            lider_contrato=self.lider,
        )
        self.fornecedor = self.create_supplier(nome="Fornecedor Contratação")
        self.solicitacao_contrato = SolicitacaoContrato.objects.create(
            contrato=self.contrato_base,
            coordenador=self.coordenador,
            lider_contrato=self.lider,
            descricao="Solicitação de contratação",
            fornecedor_escolhido=self.fornecedor,
            data_inicio=date(2026, 5, 1),
            data_fim=date(2026, 6, 1),
            valor_provisionado=Decimal("1500.00"),
            status="Solicitação de contratação",
        )
        self.solicitacao_prospeccao = SolicitacaoProspeccao.objects.create(
            contrato=self.contrato_base,
            coordenador=self.coordenador,
            lider_contrato=self.lider,
            descricao="Solicitação de prospecção",
            fornecedor_escolhido=self.fornecedor,
            data_inicio=date(2026, 5, 1),
            data_fim=date(2026, 6, 1),
            status="Fornecedor aprovado",
        )

    def test_detalhes_solicitacao_contrato_aprovacao_completa_define_status_final(self):
        self.client.force_login(self.gerente_contrato)
        response_gerente = self.client.post(
            reverse("detalhes_solicitacao_contrato", args=[self.solicitacao_contrato.pk]),
            {"acao": "aprovar"},
            follow=False,
        )

        self.assertRedirects(
            response_gerente,
            reverse("detalhes_solicitacao_contrato", kwargs={"pk": self.solicitacao_contrato.pk}),
            fetch_redirect_response=False,
        )
        self.solicitacao_contrato.refresh_from_db()
        self.assertEqual(self.solicitacao_contrato.aprovacao_fornecedor_gerente, "aprovado")

        self.client.force_login(self.diretoria)
        response_diretoria = self.client.post(
            reverse("detalhes_solicitacao_contrato", args=[self.solicitacao_contrato.pk]),
            {"acao": "aprovar"},
            follow=False,
        )

        self.assertRedirects(
            response_diretoria,
            reverse("detalhes_solicitacao_contrato", kwargs={"pk": self.solicitacao_contrato.pk}),
            fetch_redirect_response=False,
        )
        self.solicitacao_contrato.refresh_from_db()
        self.assertEqual(self.solicitacao_contrato.aprovacao_fornecedor_diretor, "aprovado")
        self.assertEqual(self.solicitacao_contrato.status, "Fornecedor aprovado")

    def test_detalhes_solicitacao_contrato_reprovacao_sem_justificativa_redireciona_para_mesma_tela(self):
        self.client.force_login(self.diretoria)

        response = self.client.post(
            reverse("detalhes_solicitacao_contrato", args=[self.solicitacao_contrato.pk]),
            {"acao": "reprovar", "justificativa": ""},
            follow=False,
        )

        self.assertRedirects(
            response,
            reverse("detalhes_solicitacao_contrato", kwargs={"pk": self.solicitacao_contrato.pk}),
            fetch_redirect_response=False,
        )

    def test_cadastrar_minuta_contrato_cria_documento_para_solicitacao_contrato(self):
        self.client.force_login(self.suprimento)

        response = self.client.post(
            reverse("cadastrar_minuta_contrato", args=[self.solicitacao_contrato.pk]),
            {
                "numero_contrato": "MIN-CONTR-001",
                "objeto": "Objeto da contratação",
                "valor_total": "1.500,00",
                "observacao": "Minuta inicial",
            },
            follow=False,
        )

        self.assertRedirects(response, reverse("lista_solicitacoes"), fetch_redirect_response=False)
        documento = self.solicitacao_contrato.minuta_contrato
        self.assertEqual(documento.numero_contrato, "MIN-CONTR-001")
        self.assertEqual(documento.prazo_inicio, date(2026, 5, 1))
        self.assertEqual(documento.prazo_fim, date(2026, 6, 1))
        self.assertEqual(documento.valor_total, Decimal("1500.00"))
        self.solicitacao_contrato.refresh_from_db()
        self.assertEqual(self.solicitacao_contrato.status, "Planejamento do contrato")

    def test_cadastrar_contrato_cria_documento_para_solicitacao_prospeccao(self):
        self.client.force_login(self.suprimento)

        response = self.client.post(
            reverse("cadastrar_contrato", args=[self.solicitacao_prospeccao.pk]),
            {
                "numero_contrato": "MIN-PROS-001",
                "objeto": "Objeto da prospecção",
                "valor_total": "2.345,67",
                "observacao": "Contrato de prospecção",
            },
            follow=False,
        )

        self.assertRedirects(
            response,
            reverse("detalhes_solicitacao", kwargs={"pk": self.solicitacao_prospeccao.pk}),
            fetch_redirect_response=False,
        )
        documento = self.solicitacao_prospeccao.contrato_relacionado
        self.assertEqual(documento.numero_contrato, "MIN-PROS-001")
        self.assertEqual(documento.prazo_inicio, date(2026, 5, 1))
        self.assertEqual(documento.prazo_fim, date(2026, 6, 1))
        self.assertEqual(documento.valor_total, Decimal("2345.67"))


class AutomaticContractCreationTests(BaseUserTestCase):
    def setUp(self):
        self.centro = self.create_center()
        self.lider = self.create_user("liderauto", "lider_contrato")
        self.gerente_contrato = self.create_user("gcauto", "gerente_contrato")
        self.suprimento = self.create_user("supauto", "suprimento")
        self.coordenador = self.create_user("coordauto", "coordenador")
        self.coordenador.centros.add(self.centro)
        self.contrato_base = self.create_contract(
            codigo="PRJ-AUTO",
            coordenador=self.coordenador,
            lider_contrato=self.lider,
        )
        self.fornecedor = self.create_supplier(nome="Fornecedor Auto")

    def test_criar_contrato_se_aprovado_gera_contrato_para_prospeccao(self):
        solicitacao = SolicitacaoProspeccao.objects.create(
            contrato=self.contrato_base,
            coordenador=self.coordenador,
            lider_contrato=self.lider,
            fornecedor_escolhido=self.fornecedor,
            descricao="Prospecção aprovada",
            status="Aprovação Final",
            aprovacao_gerencia=True,
        )
        DocumentoBM.objects.create(
            solicitacao=solicitacao,
            status_gerente="aprovado",
        )
        DocumentoContratoTerceiro.objects.create(
            solicitacao=solicitacao,
            numero_contrato="AUTO-PROS-001",
            objeto="Objeto automático",
            prazo_inicio=date(2026, 5, 1),
            prazo_fim=date(2026, 6, 1),
            valor_total=Decimal("3210.00"),
        )
        PropostaFornecedor.objects.create(
            solicitacao=solicitacao,
            fornecedor=self.fornecedor,
            condicao_pagamento="30",
        )
        evento = Evento.objects.create(
            prospeccao=solicitacao,
            empresa_terceira=self.fornecedor,
            descricao="Entrega prospecção",
            data_prevista=date(2026, 5, 10),
            valor_previsto=Decimal("100.00"),
        )

        contrato = criar_contrato_se_aprovado(solicitacao)

        self.assertIsNotNone(contrato)
        self.assertEqual(contrato.prospeccao, solicitacao)
        self.assertEqual(contrato.empresa_terceira, self.fornecedor)
        self.assertEqual(contrato.num_contrato, "AUTO-PROS-001")
        self.assertEqual(contrato.valor_total, Decimal("3210.00"))
        self.assertEqual(contrato.status, "ativo")
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.status, "Onboarding")
        evento.refresh_from_db()
        self.assertEqual(evento.contrato_terceiro, contrato)
        self.assertEqual(len(mail.outbox), 1)

    def test_criar_contrato_se_aprovado_minuta_gera_contrato_para_contratacao(self):
        solicitacao = SolicitacaoContrato.objects.create(
            contrato=self.contrato_base,
            coordenador=self.coordenador,
            lider_contrato=self.lider,
            fornecedor_escolhido=self.fornecedor,
            descricao="Contratação aprovada",
            status="Aprovação Final",
            aprovacao_gerencia=True,
            guarda_chuva=True,
            valor_provisionado=Decimal("4567.00"),
        )
        DocumentoBM.objects.create(
            solicitacao_contrato=solicitacao,
            status_gerente="aprovado",
        )
        DocumentoContratoTerceiro.objects.create(
            solicitacao_contrato=solicitacao,
            numero_contrato="AUTO-CONTR-001",
            objeto="Objeto contratação",
            prazo_inicio=date(2026, 7, 1),
            prazo_fim=date(2026, 8, 1),
            valor_total=Decimal("4567.00"),
        )
        PropostaFornecedor.objects.create(
            solicitacao_contrato=solicitacao,
            fornecedor=self.fornecedor,
            condicao_pagamento="60",
        )
        evento = Evento.objects.create(
            solicitacao_contrato=solicitacao,
            empresa_terceira=self.fornecedor,
            descricao="Entrega contratação",
            data_prevista=date(2026, 7, 10),
            valor_previsto=Decimal("100.00"),
        )

        contrato = criar_contrato_se_aprovado_minuta(solicitacao)

        self.assertIsNotNone(contrato)
        self.assertEqual(contrato.solicitacao, solicitacao)
        self.assertEqual(contrato.empresa_terceira, self.fornecedor)
        self.assertEqual(contrato.num_contrato, "AUTO-CONTR-001")
        self.assertTrue(contrato.guarda_chuva)
        self.assertEqual(contrato.valor_total, Decimal("4567.00"))
        solicitacao.refresh_from_db()
        self.assertEqual(solicitacao.status, "Onboarding")
        evento.refresh_from_db()
        self.assertEqual(evento.contrato_terceiro, contrato)
        self.assertEqual(len(mail.outbox), 1)


class TemplateVisibilityTests(BaseUserTestCase):
    def setUp(self):
        self.suprimento = self.create_user("supritemplate", "suprimento")
        self.lider = self.create_user("lidertemplate", "lider_contrato")

    def test_base_mostra_report_apenas_para_suprimento(self):
        self.client.force_login(self.suprimento)
        response = self.client.get(reverse("guia_permissoes"))
        self.assertContains(response, "Report")

        self.client.force_login(self.lider)
        response = self.client.get(reverse("guia_permissoes"))
        self.assertNotContains(response, "Report")

    def test_lista_ordens_servico_mostra_botao_solicitar_os_para_lider(self):
        self.client.force_login(self.lider)
        response = self.client.get(reverse("lista_ordens_servico"))
        self.assertContains(response, "Solicitar Nova OS")
