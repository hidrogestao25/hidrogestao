"""Regressões da consolidação Financeiro — fase 1 (dados exclusivamente sintéticos)."""
from datetime import date
from decimal import Decimal

from django.apps import apps
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from . import models as m
from .forms import FornecedorForm, ClienteForm
from .permissions import PAID_NF_READ_ONLY_MESSAGE
from .test_auditoria import pdf
from .tests import BaseUserTestCase


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class FinanceiroFase1Tests(BaseUserTestCase):
    def setUp(self):
        self.finance = self.create_user("fase1_fin", "financeiro")
        self.supply = self.create_user("fase1_sup", "suprimento")
        self.leader = self.create_user("fase1_lider", "lider_contrato")
        self.coord = self.create_user("fase1_tecnico", "coordenador")
        self.director = self.create_user("fase1_dir", "diretoria")
        self.manager = self.create_user("fase1_gercontrato", "gerente_contrato")
        self.project = self.create_contract(coordenador=self.coord, lider_contrato=self.leader)
        self.supplier = self.create_supplier()
        self.contract = self.create_supplier_contract(cod_projeto=self.project, empresa_terceira=self.supplier,
            coordenador=self.coord, lider_contrato=self.leader)
        self.event = self.create_event(contrato=self.contract)
        self.os_request = self.create_os_request(contrato=self.contract, lider_contrato=self.leader)
        self.order = self.create_os(contrato=self.contract, solicitacao=self.os_request)
        self.bm = self.make_bm(self.event)
        self.os_bm = self.make_bm(self.order)
        self.prospect = m.SolicitacaoProspeccao.objects.create(contrato=self.project,
            lider_contrato=self.leader, coordenador=self.coord, aprovado=True, triagem_realizada=True,
            fornecedor_escolhido=self.supplier, status="Planejamento do Contrato")
        self.request = m.SolicitacaoContrato.objects.create(contrato=self.project,
            lider_contrato=self.leader, coordenador=self.coord, fornecedor_escolhido=self.supplier)
        self.dbm = m.DocumentoBM.objects.create(solicitacao=self.prospect, minuta_boletim=pdf())
        self.dbmc = m.DocumentoBM.objects.create(solicitacao_contrato=self.request, minuta_boletim=pdf())
        self.proposal = m.PropostaFornecedor.objects.create(solicitacao=self.prospect, fornecedor=self.supplier, valor_proposta=100)
        self.minuta = m.DocumentoContratoTerceiro.objects.create(solicitacao=self.prospect,
            numero_contrato="FASE1", objeto="Sintético", prazo_inicio=date(2026, 1, 1),
            prazo_fim=date(2027, 1, 1), valor_total=100)
        self.addendum = m.AditivoContratoTerceiro.objects.create(contrato=self.contract,
            solicitado_por=self.leader, motivo="Sintético")
        self.client.force_login(self.finance)

    def make_bm(self, origin, approved=False):
        return m.BM.objects.create(contrato=self.contract,
            **({"evento": origin} if isinstance(origin, m.Evento) else {"os": origin}),
            numero_bm=15, parcela_paga=1, valor_pago=100,
            status_gerente="aprovado" if approved else "pendente",
            aprovacao_pagamento="aprovado" if approved else "pendente")

    def approve(self, bm):
        bm.status_gerente = bm.aprovacao_pagamento = "aprovado"
        bm.data_aprovacao_gerente = timezone.now()
        bm.save()

    def nf(self, origin=None, bm=None, paid=False):
        origin = origin or self.event
        bm = bm or (self.bm if isinstance(origin, m.Evento) else self.os_bm)
        from .payment_context import ledger_context
        with ledger_context(legacy=paid):
            return m.NF.objects.create(contrato=self.contract, bm=bm, parcela_paga=1, valor_pago=50,
                financeiro_autorizou=paid, **({"evento": origin} if isinstance(origin, m.Evento) else {"os": origin}))

    def payload(self, bm=None, paid=False, value="70,00"):
        return {"bm": bm.pk if bm else "", "valor_pago": value, "parcela_paga": 1,
            "data_pagamento": timezone.localdate().isoformat(), "observacao": "Sintética",
            "justificativa_correcao": "Correção sintética conferida",
            **({"financeiro_autorizou": "on"} if paid else {})}

    def create_nf(self, origin, payload):
        name = "cadastrar_nf" if isinstance(origin, m.Evento) else "cadastrar_nf_os"
        url = reverse(name, args=[origin.pk])
        get = self.client.get(url)
        self.assertEqual(get.status_code, 200)
        return self.client.post(url, payload | {"submission_token": get.context["submission_token"]})

    def snapshot(self):
        return {model._meta.label: list(model.objects.order_by("pk").values())
                for model in apps.get_app_config("gestao_contratos").get_models()}

    def assert_invalid(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["success"], response.content)

    def test_fornecedor_leitura_global_mantem_cadastro_e_edita_so_banco(self):
        response = self.client.get(reverse("fornecedor_detalhe", args=[self.supplier.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.supplier.nome)
        self.assertContains(response, self.supplier.cpf_cnpj)
        self.assertContains(response, self.supplier.informacoes_bancarias)
        self.assertNotContains(response, 'name="nome"')
        before = m.EmpresaTerceira.objects.values().get(pk=self.supplier.pk)
        response = self.client.post(reverse("fornecedor_detalhe", args=[self.supplier.pk]), {
            "informacoes_bancarias": "Banco novo", "nome": "FORJADO", "cpf_cnpj": "99",
            "guarda_chuva": "on", "email": "forjado@example.com", "observacao": "FORJADA"})
        self.assertEqual(response.status_code, 302)
        after = m.EmpresaTerceira.objects.values().get(pk=self.supplier.pk)
        self.assertEqual(after.pop("informacoes_bancarias"), "BANCO NOVO")
        before.pop("informacoes_bancarias")
        self.assertEqual(before, after)

    def test_post_bancario_nao_normaliza_outros_campos_legados(self):
        m.EmpresaTerceira.objects.filter(pk=self.supplier.pk).update(nome="nome legado minúsculo")
        self.client.post(reverse("fornecedor_detalhe", args=[self.supplier.pk]), {"informacoes_bancarias": "Banco novo"})
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.nome, "nome legado minúsculo")

    def test_suprimento_preserva_edicao_cadastral_completa(self):
        self.client.force_login(self.supply)
        data = {k: value if value is not None else "" for k, value in FornecedorForm(instance=self.supplier).initial.items()}
        data.update(nome="Nome corrigido", guarda_chuva=True, informacoes_bancarias="Banco corrigido")
        response = self.client.post(reverse("fornecedor_detalhe", args=[self.supplier.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.nome, "NOME CORRIGIDO")
        self.assertTrue(self.supplier.guarda_chuva)

    def test_cliente_global_somente_leitura_e_post_nao_muda_banco(self):
        url = reverse("cliente_detalhe", args=[self.project.cliente_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="nome"')
        before = self.snapshot()
        self.assertEqual(self.client.post(url, {"nome": "FORJADO"}).status_code, 403)
        self.assertEqual(before, self.snapshot())

    def test_cliente_suprimento_preserva_edicao(self):
        self.client.force_login(self.supply)
        data = {k: value if value is not None else "" for k, value in ClienteForm(instance=self.project.cliente).initial.items()}
        data["nome"] = "Cliente corrigido"
        self.assertEqual(self.client.post(reverse("cliente_detalhe", args=[self.project.cliente_id]), data).status_code, 302)
        self.project.cliente.refresh_from_db()
        self.assertEqual(self.project.cliente.nome, "CLIENTE CORRIGIDO")

    def test_nfcliente_criar_editar_excluir_preservados(self):
        data = {"valor_pago": "90,00", "parcela_paga": 1, "data_emissao": "2026-10-23", "data_pagamento": "2026-10-23"}
        self.client.post(reverse("cadastrar_nf_cliente", args=[self.project.pk]), data)
        nf = m.NFCliente.objects.get()
        self.client.post(reverse("editar_nf_cliente", args=[nf.pk]),
            {f"edit_{nf.pk}-{key}": value for key, value in data.items()} | {f"edit_{nf.pk}-valor_pago": "95,00"})
        nf.refresh_from_db(); self.assertEqual(nf.valor_pago, 95)
        self.client.post(reverse("excluir_nf_cliente", args=[nf.pk]))
        self.assertFalse(m.NFCliente.objects.exists())

    def test_nf_nao_paga_antes_das_aprovacoes_evento_e_os(self):
        for origin, bm in [(self.event, self.bm), (self.order, self.os_bm)]:
            for state in ("pendente", "operacional", "reprovado"):
                with self.subTest(origin=type(origin).__name__, state=state):
                    bm.status_gerente = "aprovado" if state == "operacional" else "pendente"
                    bm.aprovacao_pagamento = "reprovado" if state == "reprovado" else "pendente"
                    bm.save()
                    response = self.create_nf(origin, self.payload(bm))
                    self.assertTrue(response.json()["success"], response.content)
                    self.assertFalse(m.NF.objects.latest("pk").financeiro_autorizou)

    def test_nf_sem_bm_evento_os_rejeitada_sem_criacao_parcial(self):
        for origin in (self.event, self.order):
            url = reverse("cadastrar_nf" if isinstance(origin, m.Evento) else "cadastrar_nf_os", args=[origin.pk])
            token = self.client.get(url).context["submission_token"]
            before = self.snapshot()
            response = self.client.post(url, self.payload() | {"submission_token": token})
            self.assert_invalid(response)
            self.assertIn("bm", response.json()["errors"])
            self.assertEqual(before, self.snapshot())

    def test_modelo_rejeita_nf_sem_bm_e_origem_cruzada(self):
        for data in ({"evento": self.event}, {"os": self.order}, {"evento": self.event, "bm": self.os_bm}):
            with self.subTest(data=data), self.assertRaises(ValidationError):
                m.NF.objects.create(contrato=self.contract, parcela_paga=1, **data)
        self.assertEqual(m.NF.objects.count(), 0)

    def test_nf_rejeita_bm_de_outro_evento_ou_os(self):
        for origin, foreign_bm in [(self.event, self.os_bm), (self.order, self.bm)]:
            response = self.create_nf(origin, self.payload(foreign_bm))
            self.assert_invalid(response)
        self.assertFalse(m.NF.objects.exists())

    def test_pagamento_pre_diretoria_ou_operacional_invalida_rejeitado(self):
        for coord, manager, director in [("pendente", "pendente", "pendente"), ("pendente", "aprovado", "pendente"),
                ("aprovado", "reprovado", "aprovado"), ("pendente", "pendente", "aprovado"),
                ("pendente", "aprovado", "reprovado")]:
            for origin, bm in [(self.event, self.bm), (self.order, self.os_bm)]:
                with self.subTest(coord=coord, manager=manager, director=director, origin=type(origin).__name__):
                    bm.status_coordenador, bm.status_gerente, bm.aprovacao_pagamento = coord, manager, director
                    bm.save()
                    response = self.create_nf(origin, self.payload(bm, paid=True))
                    self.assert_invalid(response)
                    self.assertIn("financeiro_autorizou", response.json()["errors"])
        self.assertFalse(m.NF.objects.exists())

    def test_nf_paga_autorizada_evento_os_e_lider_ou_gerencia(self):
        for origin, bm in [(self.event, self.bm), (self.order, self.os_bm)]:
            for field in ("status_coordenador", "status_gerente"):
                bm.status_coordenador = bm.status_gerente = "pendente"
                setattr(bm, field, "aprovado"); bm.aprovacao_pagamento = "aprovado"; bm.save()
                response = self.create_nf(origin, self.payload(bm, paid=True))
                self.assertTrue(response.json()["success"], response.content)
                origin.refresh_from_db()
                self.assertEqual(origin.valor_pago, Decimal("70") if field == "status_coordenador" else Decimal("140"))

    def test_editar_nf_nao_paga_permitido_marcar_somente_apos_liberacao(self):
        nf = self.nf()
        url = reverse("editar_nf", args=[nf.pk])
        self.assertTrue(self.client.post(url, self.payload(self.bm, value="80,00")).json()["success"])
        self.assert_invalid(self.client.post(url, self.payload(self.bm, paid=True)))
        nf.refresh_from_db(); self.assertFalse(nf.financeiro_autorizou)
        self.approve(self.bm)
        self.assertTrue(self.client.post(url, self.payload(self.bm, paid=True)).json()["success"])
        nf.refresh_from_db(); self.assertTrue(nf.financeiro_autorizou)

    def test_nf_paga_bloqueia_todas_edicoes_e_exclusao_com_banco_identico(self):
        for origin, bm in [(self.event, self.bm), (self.order, self.os_bm)]:
            self.approve(bm)
            nf = self.nf(origin, bm, paid=True)
            alternate_bm = self.make_bm(origin)
            for paid in (True, False):
                before = self.snapshot()
                response = self.client.post(reverse("editar_nf", args=[nf.pk]),
                    self.payload(alternate_bm, paid=paid, value="999,00") | {"arquivo_nf": pdf("forjado.pdf"),
                        "observacao": "forjada", "parcela_paga": 99, "data_pagamento": "2030-01-01"})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(before, self.snapshot())
            before = self.snapshot()
            self.assertEqual(self.client.post(reverse("deletar_nf", args=[nf.pk])).status_code, 403)
            self.assertEqual(before, self.snapshot())

    def test_nf_paga_get_somente_leitura_sem_salvar_e_sem_excluir_nas_telas(self):
        nf = self.nf(paid=True)
        response = self.client.get(reverse("editar_nf", args=[nf.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, PAID_NF_READ_ONLY_MESSAGE)
        self.assertNotContains(response, 'id="btnSalvarNF"')
        self.assertTrue(all(f.disabled for f in response.context["form"].fields.values()))
        for page in ("registrar_entrega", "detalhes_entrega"):
            response = self.client.get(reverse(page, args=[self.event.pk]))
            self.assertContains(response, "Consultar")
            self.assertNotContains(response, f'action="{reverse("deletar_nf", args=[nf.pk])}"')
        os_nf = self.nf(self.order, self.os_bm, paid=True)
        response = self.client.get(reverse("registrar_entrega_os", args=[self.order.pk]))
        self.assertNotContains(response, f'action="{reverse("deletar_nf", args=[os_nf.pk])}"')

    def test_suprimento_corrige_desmarca_exclui_nf_paga_e_recalcula(self):
        from .payment_services import reverse_payment,record_payment
        self.client.force_login(self.supply)
        for origin,bm in [(self.event,self.bm),(self.order,self.os_bm)]:
            nf=self.nf(origin,bm,paid=True)
            self.approve(bm)
            url=reverse('editar_nf',args=[nf.pk])
            self.assertContains(self.client.get(url),'id="btnSalvarNF"')
            response=self.client.post(url,self.payload(bm,paid=True,value='90,00'))
            self.assertTrue(response.json()['success'],response.content)
            origin.refresh_from_db();self.assertEqual(origin.valor_pago,50)
            nf.refresh_from_db();self.assertEqual(nf.saldo_pendente,40)
            reverse_payment(movement_id=nf.movimentos.get().pk,user=self.supply,valor=50,data_estorno=timezone.localdate(),motivo='Correção sintética',key='reverse-'+str(nf.pk))
            record_payment(nf_id=nf.pk,user=self.supply,valor=90,data_pagamento=timezone.localdate(),key='new-'+str(nf.pk))
            origin.refresh_from_db();self.assertEqual(origin.valor_pago,90)
            self.assertEqual(self.client.post(reverse('deletar_nf',args=[nf.pk]),{'justificativa_correcao':'Exclusão sintética conferida'}).status_code,302)
            nf.refresh_from_db();self.assertIsNotNone(nf.cancelada_em);self.assertEqual(nf.movimentos.count(),4)
            origin.refresh_from_db();self.assertEqual(origin.valor_pago,0);self.assertIsNone(origin.data_pagamento)

    def test_suprimento_nao_pode_retirar_bm_em_correcao(self):
        nf = self.nf(paid=True)
        self.client.force_login(self.supply)
        before = self.snapshot()
        self.assert_invalid(self.client.post(reverse("editar_nf", args=[nf.pk]), self.payload()))
        self.assertEqual(before, self.snapshot())

    def test_os_cancelada_bloqueia_novo_pago_mas_preserva_documentos(self):
        nf = self.nf(self.order, self.os_bm)
        self.approve(self.os_bm)
        self.order.status = "cancelada"; self.order.save()
        self.assertEqual(self.client.get(reverse("registrar_entrega_os", args=[self.order.pk])).status_code, 200)
        self.assert_invalid(self.create_nf(self.order, self.payload(self.os_bm, paid=True)))
        before = self.snapshot()
        self.assert_invalid(self.client.post(reverse("editar_nf", args=[nf.pk]), self.payload(self.os_bm, paid=True)))
        self.assertEqual(before, self.snapshot())
        response = self.create_nf(self.order, self.payload(self.os_bm))
        self.assertTrue(response.json()["success"])
        self.assertEqual(m.NF.objects.filter(os=self.order).count(), 2)

    def test_escaladas_fin02_fin03_fin04_bloqueadas_sem_mutacao(self):
        self.contract.data_fim = date(2020, 1, 1); self.contract.save()
        cases = [("add_contrato", [], {"cod_projeto": "FORJADO", "cliente": self.project.cliente_id, "objeto": "Forjado"}),
                 ("renegociar_valor", [self.prospect.pk], {"valor_proposta": "999.00"}),
                 ("renegociar_prazo", [self.prospect.pk], {"prazo_inicio": "2026-01-01", "prazo_fim": "2030-01-01"}),
                 ("ocultar_contrato_vencido_home", [self.contract.pk], {}),
                 ("propostas_fornecedores", [self.prospect.pk], {}), ("nova_prospeccao", [self.prospect.pk], {})]
        before = self.snapshot()
        for name, args, data in cases:
            with self.subTest(name=name):
                self.assertEqual(self.client.post(reverse(name, args=args), data).status_code, 403)
        self.assertEqual(before, self.snapshot())

    def test_suprimento_preserva_ajax_renegociacao_e_alerta(self):
        self.client.force_login(self.supply)
        response = self.client.post(reverse("add_contrato"), {"cod_projeto": "SUPRIMENTO", "cliente": self.project.cliente_id, "objeto": "Sintético"})
        self.assertEqual(response.status_code, 200)
        self.client.post(reverse("renegociar_valor", args=[self.prospect.pk]), {"valor_proposta": "120.00"})
        self.proposal.refresh_from_db(); self.assertEqual(self.proposal.valor_proposta, 120)
        self.contract.data_fim = date(2020, 1, 1); self.contract.save()
        self.client.post(reverse("ocultar_contrato_vencido_home", args=[self.contract.pk]))
        self.contract.refresh_from_db(); self.assertTrue(self.contract.ocultar_home_contrato_vencido)

    def test_leitura_global_os_aditivo_minutas_solicitacoes_e_contratos(self):
        routes = [("detalhe_ordem_servico", self.os_request), ("detalhes_os", self.order),
            ("detalhes_aditivo_contrato", self.addendum), ("detalhe_bm", self.dbm), ("detalhe_bm_contrato", self.dbmc),
            ("detalhes_solicitacao", self.prospect), ("detalhes_solicitacao_contrato", self.request),
            ("contrato_cliente_detalhe", self.project), ("contrato_fornecedor_detalhe", self.contract)]
        for name, obj in routes:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, args=[obj.pk])).status_code, 200)
        response = self.client.get(reverse("lista_solicitacoes"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("detalhes_solicitacao", args=[self.prospect.pk]))
        response = self.client.get(reverse("detalhe_bm", args=[self.dbm.pk]))
        self.assertNotContains(response, 'value="aprovar"')
        self.assertNotContains(response, 'value="reprovar"')
        for prefix in ("/arquivos/", "/media/"):
            response = self.client.get(prefix + self.dbm.minuta_boletim.name)
            self.assertEqual(response.status_code, 200); response.close()

    def test_gets_globais_nao_liberam_posts_de_aprovacao_ou_edicao(self):
        cases = [("detalhe_ordem_servico", [self.os_request.pk]), ("detalhes_os", [self.order.pk]),
            ("detalhes_aditivo_contrato", [self.addendum.pk]), ("detalhe_bm", [self.dbm.pk]),
            ("detalhe_bm_contrato", [self.dbmc.pk]), ("detalhes_solicitacao", [self.prospect.pk]),
            ("detalhes_solicitacao_contrato", [self.request.pk]), ("lista_solicitacoes", [])]
        before = self.snapshot()
        for name, args in cases:
            self.assertEqual(self.client.post(reverse(name, args=args), {"acao": "aprovar"}).status_code, 403)
        self.assertEqual(before, self.snapshot())

    def test_barreiras_operacionais_e_contratuais_preservadas(self):
        cases = [("editar_evento", [self.event.pk]), ("excluir_evento", [self.event.pk]),
            ("duplicar_evento", [self.event.pk]), ("registrar_entrega", [self.event.pk]),
            ("avaliar_evento_fornecedor", [self.event.pk]), ("cadastrar_evento_contrato", [self.contract.pk]),
            ("registrar_entrega_os", [self.order.pk]), ("editar_os_cadastrada", [self.order.pk]),
            ("nova_os", []), ("avaliar_os_fornecedor", [self.order.pk]),
            ("aprovar_os_gerente_contrato", [self.os_request.pk, "aprovar"]),
            ("aprovar_os_diretoria", [self.os_request.pk, "aprovar"]),
            ("avaliar_bm", [self.bm.pk]), ("aprovar_bm", [self.dbm.pk, "gerente"]),
            ("aprovar_fornecedor_gerente", [self.prospect.pk]), ("aprovar_fornecedor_diretor", [self.prospect.pk]),
            ("solicitar_aditivo_contrato", [self.contract.pk]), ("avaliar_minuta_aditivo_contrato", [self.addendum.pk]),
            ("gerar_aditivo_contrato_docm", [self.addendum.pk]), ("contrato_fornecedor_editar", [self.contract.pk])]
        before = self.snapshot()
        for name, args in cases:
            with self.subTest(name=name):
                response = self.client.post(reverse(name, args=args), {"acao": "aprovar", "realizado": "on"})
                self.assertIn(response.status_code, (302, 403))
        self.assertEqual(before, self.snapshot())

    def test_bm_crud_financeiro_reset_spoof_e_protect(self):
        for origin, bm in [(self.event, self.bm), (self.order, self.os_bm)]:
            self.approve(bm)
            response = self.client.post(reverse("editar_bm", args=[bm.pk]), {"numero_bm": 15,
                "parcela_paga": 1, "valor_pago": "200,00", "data_pagamento": timezone.localdate().isoformat(),
                "status_gerente": "aprovado", "aprovacao_pagamento": "aprovado"})
            self.assertTrue(response.json()["success"])
            bm.refresh_from_db()
            self.assertEqual((bm.status_coordenador, bm.status_gerente, bm.aprovacao_pagamento), ("pendente",)*3)
            nf = self.nf(origin, bm)
            self.client.post(reverse("deletar_bm", args=[bm.pk]))
            self.assertTrue(m.BM.objects.filter(pk=bm.pk).exists())
            self.client.post(reverse("deletar_nf", args=[nf.pk]))
            self.client.post(reverse("deletar_bm", args=[bm.pk]))
            self.assertFalse(m.BM.objects.filter(pk=bm.pk).exists())

    def test_criar_bm_evento_os_e_excluir_sem_nf_preservados(self):
        for name, args in [("cadastrar_bm", [self.contract.pk, self.event.pk]), ("cadastrar_bm_os", [self.order.pk])]:
            url = reverse(name, args=args)
            page = self.client.get(url)
            response = self.client.post(url, {"submission_token": page.context["submission_token"],
                "numero_bm": 25, "parcela_paga": 2, "valor_pago": "75,00", "data_pagamento": "2026-10-23",
                "status_gerente": "aprovado", "aprovacao_pagamento": "aprovado"})
            self.assertTrue(response.json()["success"], response.content)
            bm = m.BM.objects.latest("pk")
            self.assertEqual((bm.status_coordenador, bm.status_gerente, bm.aprovacao_pagamento), ("pendente",)*3)
            self.client.post(reverse("deletar_bm", args=[bm.pk]))
            self.assertFalse(m.BM.objects.filter(pk=bm.pk).exists())

    def test_financeiro_designado_como_lider_nao_pode_rejeitar_triagem(self):
        self.prospect.lider_contrato = self.finance; self.prospect.save()
        before = self.snapshot()
        response = self.client.post(reverse("nenhum_fornecedor_ideal", args=[self.prospect.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(before, self.snapshot())

    def test_auditoria_nf_criacao_correcao_desmarcacao_exclusao(self):
        self.approve(self.bm)
        response = self.create_nf(self.event, self.payload(self.bm, paid=True))
        self.assertTrue(response.json()["success"])
        nf = m.NF.objects.get()
        ct = ContentType.objects.get_for_model(m.NF)
        logs = m.RegistroAuditoria.objects.filter(content_type=ct, object_id=nf.pk)
        self.assertTrue(logs.filter(usuario=self.finance, acao="criado").exists())
        self.client.force_login(self.supply)
        self.client.post(reverse("editar_nf", args=[nf.pk]), self.payload(self.bm, paid=False))
        self.assertTrue(logs.filter(usuario=self.supply, operacao_financeira="estorno").exists())
        self.client.post(reverse("deletar_nf", args=[nf.pk]),{"justificativa_correcao":"Cancelamento sintético"})
        self.assertTrue(logs.filter(usuario=self.supply, operacao_financeira="cancelamento").exists())
        self.assertTrue(all(log.data_hora and log.usuario_id for log in logs))

    def test_outros_perfis_mantem_escopos_documentais_e_nao_operam_nf(self):
        nf = self.nf()
        for user in (self.leader, self.coord, self.director, self.manager,
                     self.create_user("fase1_fornecedor", "fornecedor")):
            self.client.force_login(user)
            before = self.snapshot()
            self.assertIn(self.client.post(reverse("editar_nf", args=[nf.pk]), self.payload(self.bm)).status_code, (302, 403))
            self.assertEqual(before, self.snapshot())
            status = 404 if user.grupo == "fornecedor" else 200
            response = self.client.get("/arquivos/" + self.dbm.minuta_boletim.name)
            self.assertEqual(response.status_code, status, user.grupo); response.close()

    def enable_admin(self, user):
        user.is_staff = True; user.save()
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label="gestao_contratos"))
        self.client.force_login(user)

    def test_admin_financeiro_nao_contorna_nf_paga_nem_edicao_cadastral(self):
        nf = self.nf(paid=True)
        self.enable_admin(self.finance)
        before = self.snapshot()
        for url, data in [(f"/admin/gestao_contratos/nf/{nf.pk}/change/", self.payload(self.bm)),
                          (f"/admin/gestao_contratos/nf/{nf.pk}/delete/", {"post": "yes"}),
                          (f"/admin/gestao_contratos/cliente/{self.project.cliente_id}/change/", {"nome": "FORJADO"})]:
            self.assertEqual(self.client.post(url, data).status_code, 403)
        self.assertEqual(before, self.snapshot())
        model_admin = admin.site._registry[m.EmpresaTerceira]
        from django.test import RequestFactory
        request = RequestFactory().get("/admin/"); request.user = self.finance
        form = model_admin.get_form(request, self.supplier)
        self.assertEqual(set(form.base_fields), {"informacoes_bancarias"})
        self.assertFalse(model_admin.has_add_permission(request))

    def test_admin_financeiro_rejeita_registro_pago_antes_da_diretoria(self):
        self.enable_admin(self.finance)
        response = self.client.post("/admin/gestao_contratos/nf/add/", self.payload(self.bm, paid=True) | {
            "contrato": self.contract.pk, "evento": self.event.pk, "_save": "Salvar"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "aprovação operacional válida")
        self.assertFalse(m.NF.objects.exists())

    def test_admin_suprimento_corrige_nf_paga_e_recalcula(self):
        nf = self.nf(paid=True)
        self.enable_admin(self.supply)
        response = self.client.post(f"/admin/gestao_contratos/nf/{nf.pk}/change/", self.payload(self.bm, value="90,00") | {
            "contrato": self.contract.pk, "evento": self.event.pk, "valor_pago": "90.00", "_save": "Salvar"})
        self.assertEqual(response.status_code, 302, response.context["adminform"].form.errors if response.status_code == 200 else "")
        nf.refresh_from_db(); self.assertFalse(nf.financeiro_autorizou)
        self.event.refresh_from_db(); self.assertEqual(self.event.valor_pago, 0)
