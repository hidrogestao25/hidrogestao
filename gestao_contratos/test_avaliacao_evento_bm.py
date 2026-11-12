"""Avaliação única do Evento deve atender todos os seus BMs e aprovadores autorizados."""
from decimal import Decimal

from django.urls import reverse

from . import models as m
from . import tests as fixtures


class AvaliacaoEventoMultiplosBMTests(fixtures.BaseUserTestCase):
    setUp = fixtures.EventBMApprovalFlowTests.setUp
    avaliar_evento_com = fixtures.EventBMApprovalFlowTests.avaliar_evento_com

    def bm(self, numero, **kwargs):
        return m.BM.objects.create(
            contrato=self.contrato_terceiro, evento=self.evento,
            numero_bm=numero, parcela_paga=numero, valor_pago=Decimal("100.00"), **kwargs,
        )

    def decidir(self, user, bm, acao="aprovar", justificativa=""):
        self.client.force_login(user)
        return self.client.post(reverse("avaliar_bm", args=[bm.pk]), {
            "acao": acao, "justificativa": justificativa,
        })

    def test_mesmo_lider_aprova_dois_bms_com_uma_avaliacao_do_evento(self):
        avaliacao = self.avaliar_evento_com(self.lider)
        primeiro = self.bm(2)
        self.assertEqual(self.decidir(self.lider, primeiro).status_code, 200)
        segundo = self.bm(3)
        response = self.decidir(self.lider, segundo)
        self.assertEqual(response.status_code, 200, response.content)
        for bm in (primeiro, segundo):
            bm.refresh_from_db()
            self.assertEqual(bm.status_coordenador, "aprovado")
        self.assertEqual(list(self.evento.avaliacoes.values_list("pk", flat=True)), [avaliacao.pk])

    def test_novo_lider_aprova_segundo_bm_avaliado_pelo_lider_anterior(self):
        # Reproduz a autoria diferente do Evento 450 sem alterar os dados reais.
        self.contrato_terceiro.lider_contrato = self.gerente_lider
        self.contrato_terceiro.save()
        avaliacao = self.avaliar_evento_com(self.gerente_lider)
        primeiro = self.bm(2)
        self.assertEqual(self.decidir(self.gerente_lider, primeiro).status_code, 200)
        primeiro.refresh_from_db()
        data_primeira_decisao = primeiro.data_aprovacao_coordenador

        self.contrato_terceiro.lider_contrato = self.lider
        self.contrato_terceiro.save()
        segundo = self.bm(3)
        response = self.decidir(self.lider, segundo)
        self.assertEqual(response.status_code, 200, response.content)
        segundo.refresh_from_db()
        primeiro.refresh_from_db()
        self.assertEqual(segundo.status_coordenador, "aprovado")
        self.assertEqual(primeiro.data_aprovacao_coordenador, data_primeira_decisao)
        self.assertEqual(primeiro.status_coordenador, "aprovado")
        avaliacao.refresh_from_db()
        self.assertEqual(avaliacao.avaliador, self.gerente_lider)
        self.assertEqual(self.evento.avaliacoes.count(), 1)

        response = self.client.post(reverse("avaliar_evento_fornecedor", args=[self.evento.pk]), {
            "nota_gestao": 1, "nota_tecnica": 1, "nota_entrega": 1,
        })
        self.assertEqual(response.json(), {"success": False, "error": "Evento já avaliado."})
        avaliacao.refresh_from_db()
        self.assertEqual(avaliacao.nota_gestao, 5)
        self.assertEqual(self.evento.avaliacoes.count(), 1)

    def test_lider_reprova_segundo_bm_com_avaliacao_de_outro_responsavel(self):
        self.avaliar_evento_com(self.gerente_contrato)
        primeiro = self.bm(2, status_coordenador="aprovado")
        segundo = self.bm(3)
        response = self.decidir(self.lider, segundo, "reprovar", "Revisar a segunda medição.")
        self.assertEqual(response.status_code, 200, response.content)
        segundo.refresh_from_db()
        primeiro.refresh_from_db()
        self.assertEqual(segundo.status_coordenador, "reprovado")
        self.assertEqual(segundo.justificativa_reprovacao_coordenador, "Revisar a segunda medição.")
        self.assertEqual(primeiro.status_coordenador, "aprovado")

    def test_gerente_aprova_segundo_bm_com_avaliacao_realizada_pelo_lider(self):
        self.avaliar_evento_com(self.lider)
        primeiro = self.bm(2)
        self.assertEqual(self.decidir(self.lider, primeiro).status_code, 200)
        segundo = self.bm(3)
        response = self.decidir(self.gerente_contrato, segundo)
        self.assertEqual(response.status_code, 200, response.content)
        segundo.refresh_from_db()
        self.assertEqual(segundo.status_gerente, "aprovado")
        self.assertEqual(self.evento.avaliacoes.count(), 1)

    def test_bm_anterior_aprovado_nao_substitui_avaliacao_ausente_do_evento(self):
        self.bm(2, status_coordenador="aprovado")
        segundo = self.bm(3)
        for user in (self.lider, self.gerente_contrato):
            response = self.decidir(user, segundo)
            self.assertEqual(response.status_code, 400)
            self.assertIn("Avalie o evento", response.json()["error"])
        segundo.refresh_from_db()
        self.assertEqual(segundo.status_coordenador, "pendente")
        self.assertEqual(segundo.status_gerente, "pendente")

    def test_avaliacao_de_outro_evento_nao_libera_bm(self):
        outro = self.create_event(contrato=self.contrato_terceiro)
        m.AvaliacaoFornecedor.objects.create(
            empresa_terceira=self.contrato_terceiro.empresa_terceira,
            contrato_terceiro=self.contrato_terceiro, evento=outro,
            area_avaliadora=self.lider.grupo, avaliador=self.lider,
            nota_gestao=5, nota_tecnica=5, nota_entrega=5,
        )
        response = self.decidir(self.lider, self.bm(3))
        self.assertEqual(response.status_code, 400)
        self.assertIn("Avalie o evento", response.json()["error"])

    def test_avaliacao_existente_nao_libera_lider_de_outro_contrato(self):
        self.avaliar_evento_com(self.lider)
        terceiro = self.create_user("lider_outro_evento_bm", "lider_contrato")
        segundo = self.bm(3)
        response = self.decidir(terceiro, segundo)
        self.assertEqual(response.status_code, 403)
        segundo.refresh_from_db()
        self.assertEqual(segundo.status_coordenador, "pendente")

    def test_reprovacao_continua_exigindo_justificativa(self):
        self.avaliar_evento_com(self.gerente_contrato)
        segundo = self.bm(3)
        response = self.decidir(self.lider, segundo, "reprovar")
        self.assertEqual(response.status_code, 400)
        self.assertIn("justificativa", response.json()["error"].lower())
        segundo.refresh_from_db()
        self.assertEqual(segundo.status_coordenador, "pendente")
