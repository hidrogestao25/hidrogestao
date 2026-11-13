"""Informação do Financeiro no BM: permissões, ciclo de edição, telas e Excel."""
from datetime import date, datetime
from io import BytesIO
from unittest.mock import patch

from django.core import mail
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from . import models as m, payment_services as payments
from . import test_financeiro_fase2 as fixtures
from .tests import BaseUserTestCase


class MedicaoRecebimentoBMTests(BaseUserTestCase):
    setUp = fixtures.FinanceiroFase2Tests.setUp
    bm = fixtures.FinanceiroFase2Tests.bm
    nf = fixtures.FinanceiroFase2Tests.nf

    def approved(self, **extra):
        return self.bm(operational='aprovado', director='aprovado',
                       data_aprovacao_gerente=timezone.make_aware(datetime(2026, 11, 15, 12)), **extra)

    def url(self, bm):
        return reverse('informacao_medicao_recebimento_bm', args=[bm.pk])

    def save_info(self, bm, first='Medição conferida', second='Recebimento pendente', **extra):
        response = self.client.get(self.url(bm))
        self.assertEqual(response.status_code, 200)
        return self.client.post(self.url(bm), dict(acao='salvar', versao=response.json()['versao'],
            sobre_medicao=first, sobre_medicao_recebimento=second, **extra))

    def history(self, bm):
        return m.RegistroAuditoria.objects.filter(object_id=bm.pk, operacao_financeira='medicao_recebimento_bm')

    def forecast(self):
        return self.client.get(reverse('previsao_pagamentos'), {'data_inicial': '2026-11-01', 'data_limite': '2026-11-30'})

    def test_financeiro_insere_sem_alterar_aprovacoes_pagamentos_ou_notificacoes(self):
        bm = self.approved()
        nf = self.nf(bm, value='100')
        payments.record_payment(nf_id=nf.pk, user=self.finance, valor=20, data_pagamento=date(2026, 11, 15), key='receipt-test')
        before = m.BM.objects.values().get(pk=bm.pk)
        before_nf = m.NF.objects.values().get(pk=nf.pk)
        moves = list(m.PagamentoNF.objects.values())
        sent = len(mail.outbox)
        response = self.save_info(bm, '  Medição conferida  ', '  Em recebimento  ', criado_por=self.supply.pk)
        self.assertEqual(response.status_code, 200)
        info = m.MedicaoRecebimentoBM.objects.get(bm=bm)
        self.assertEqual((info.sobre_medicao, info.sobre_medicao_recebimento), ('Medição conferida', 'Em recebimento'))
        self.assertEqual((info.criado_por, info.atualizado_por), (self.finance, self.finance))
        self.assertEqual(m.BM.objects.values().get(pk=bm.pk), before)
        self.assertEqual(m.NF.objects.values().get(pk=nf.pk), before_nf)
        self.assertEqual(list(m.PagamentoNF.objects.values()), moves)
        self.assertEqual(len(mail.outbox), sent)
        self.assertEqual(self.history(bm).count(), 1)
        self.assertIsNone(self.history(bm).get().estado_anterior)

    def test_ambos_os_textos_obrigatorios_inclusive_espacos_e_limite(self):
        bm = self.approved()
        for first, second in [('', 'Texto'), ('Texto', ''), (' \n ', 'Texto'), ('Texto', ' \t '), ('x' * 4001, 'Texto'), ('Texto', 'x' * 4001)]:
            self.assertEqual(self.save_info(bm, first, second).status_code, 400)
        self.assertFalse(m.MedicaoRecebimentoBM.objects.exists())
        self.assertFalse(self.history(bm).exists())
        self.assertEqual(self.client.post(self.url(bm), {'acao': 'salvar', 'versao': ''}).status_code, 400)

    def test_apenas_grupo_financeiro_pode_usar_o_endpoint(self):
        bm = self.approved()
        self.save_info(bm)
        for role in ('suprimento', 'diretoria', 'lider_contrato', 'gerente_contrato', 'gerente_lider', 'coordenador', 'gerente', 'fornecedor'):
            user = self.create_user('info_' + role, role)
            user.is_staff = user.is_superuser = True
            user.save()
            self.client.force_login(user)
            for method in ('get', 'post'):
                self.assertEqual(getattr(self.client, method)(self.url(bm), {'acao': 'excluir'}).status_code, 403, role)
        self.assertEqual(m.MedicaoRecebimentoBM.objects.count(), 1)
        self.assertEqual(self.history(bm).count(), 1)

    def test_edicao_por_outro_financeiro_preserva_criador_e_audita(self):
        bm = self.approved()
        self.save_info(bm)
        info = m.MedicaoRecebimentoBM.objects.get(bm=bm)
        created_at = info.criado_em
        finance2 = self.create_user('segundo_financeiro', 'financeiro')
        self.client.force_login(finance2)
        self.assertEqual(self.save_info(bm, 'Medição revisada', 'Recebido').status_code, 200)
        info.refresh_from_db()
        self.assertEqual(info.criado_por, self.finance)
        self.assertEqual(info.criado_em, created_at)
        self.assertEqual(info.atualizado_por, finance2)
        audit = self.history(bm).first()
        self.assertEqual(audit.usuario, finance2)
        self.assertEqual(audit.estado_anterior['sobre_medicao'], 'Medição conferida')
        self.assertEqual(audit.estado_posterior['sobre_medicao'], 'Medição revisada')

    def test_exclusao_preserva_bm_e_historico_e_permite_nova_insercao(self):
        bm = self.approved()
        before = m.BM.objects.values().get(pk=bm.pk)
        created = self.save_info(bm).json()
        response = self.client.post(self.url(bm), {'acao': 'excluir', 'versao': created['versao']})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(m.MedicaoRecebimentoBM.objects.exists())
        self.assertEqual(m.BM.objects.values().get(pk=bm.pk), before)
        self.assertIsNone(self.history(bm).first().estado_posterior)
        self.assertEqual(self.history(bm).count(), 2)
        self.assertEqual(self.save_info(bm).status_code, 200)
        self.assertEqual(self.history(bm).count(), 3)

    def test_versao_antiga_nao_sobrescreve_nem_exclui_nota_atual(self):
        bm = self.approved()
        old = self.save_info(bm).json()['versao']
        self.save_info(bm, 'Atual', 'Atualizado')
        for action, version in [('salvar', old), ('excluir', old), ('salvar', '')]:
            response = self.client.post(self.url(bm), {'acao': action, 'versao': version, 'sobre_medicao': 'Forjado', 'sobre_medicao_recebimento': 'Forjado'})
            self.assertEqual(response.status_code, 409)
        self.assertEqual(m.MedicaoRecebimentoBM.objects.get(bm=bm).sobre_medicao, 'Atual')
        self.assertEqual(self.history(bm).count(), 2)

    def test_get_metodos_csrf_autenticacao_e_cache(self):
        bm = self.approved()
        response = self.client.get(self.url(bm))
        self.assertIsNone(response.json()['informacao'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(self.client.delete(self.url(bm)).status_code, 405)
        self.save_info(bm)
        self.client.get(self.url(bm), {'acao': 'excluir'})
        self.assertTrue(m.MedicaoRecebimentoBM.objects.exists())
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.finance)
        self.assertEqual(csrf.post(self.url(bm), {'acao': 'excluir'}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.post(self.url(bm), {}).status_code, 302)

    def test_interface_financeiro_edita_e_outros_perfis_consultam(self):
        first = self.approved()
        self.approved(index=1)
        self.save_info(first, 'Dados de medição', 'Dados do recebimento')
        response = self.forecast()
        for text in ('Medição e recebimento', 'Dados de medição', 'Dados do recebimento', self.finance.username,
                     'data-bm-recebimento-action="salvar"', 'data-bm-recebimento-action="excluir"', 'Inserir informação', 'name="sobre_medicao"', 'name="sobre_medicao_recebimento"'):
            self.assertContains(response, text)
        self.assertContains(response, 'js/bm_medicao_recebimento.js')
        for user in (self.supply, self.create_user('info_director', 'diretoria')):
            self.client.force_login(user)
            response = self.forecast()
            self.assertContains(response, 'Dados de medição')
            self.assertContains(response, 'Dados do recebimento')
            self.assertNotContains(response, 'data-bm-recebimento-action=')
            self.assertNotContains(response, 'data-bm-recebimento-form')

    def test_evento_exibe_textos_e_autor_sem_botoes_e_sem_html_executavel(self):
        bm = self.approved()
        self.save_info(bm, '<img src=x onerror=alert(1)>\nLinha 2', 'Recebido')
        for user in (self.finance, self.supply, self.leader):
            self.client.force_login(user)
            response = self.client.get(reverse('detalhes_entrega', args=[self.events[0].pk]))
            self.assertContains(response, '<th>Medição e recebimento</th>')
            self.assertContains(response, '&lt;img src=x onerror=alert(1)&gt;')
            self.assertNotContains(response, '<img src=x onerror=alert(1)>')
            self.assertContains(response, self.finance.username)
            self.assertNotContains(response, 'data-bm-recebimento-action=')
        self.client.force_login(self.other)
        response = self.client.get(reverse('detalhes_entrega', args=[self.events[0].pk]))
        self.assertNotEqual(response.status_code, 200)

    def test_excel_coluna_entre_observacao_e_projeto_apenas_com_textos(self):
        bm = self.approved()
        empty = self.approved(index=1)
        self.save_info(bm, '=FÓRMULA\nMedição de novembro', 'Recebimento confirmado')
        response = self.client.get(reverse('exportar_bms_previsao_excel'), {'data_inicial': '2026-11-01', 'data_limite': '2026-11-30'})
        self.assertEqual(response.status_code, 200)
        sheet = load_workbook(BytesIO(response.content))['Boletins de Medição']
        self.assertEqual([sheet.cell(1, n).value for n in (3, 4, 5)], ['Observação', 'Medição e recebimento', 'Projeto'])
        self.assertEqual(sheet.max_column, 14)
        rows = {row[4].value: row for row in sheet.iter_rows(min_row=2)}
        value = rows[self.projects[0].cod_projeto][3]
        self.assertEqual(value.value, 'Sobre medição: =FÓRMULA\nMedição de novembro\nSobre medição e recebimento: Recebimento confirmado')
        self.assertEqual(value.data_type, 's')
        self.assertTrue(value.alignment.wrap_text)
        self.assertIsNone(rows[self.projects[1].cod_projeto][3].value)
        self.assertEqual(rows[self.projects[0].cod_projeto][7].data_type, 'n')
        self.assertEqual(rows[self.projects[0].cod_projeto][8].number_format, 'dd/mm/yyyy')

    def test_informacao_independente_por_bm_inclusive_os_e_arquivo_compartilhado(self):
        a = self.approved(arquivo_bm='BM/mesmo.pdf')
        b = self.approved(index=1, arquivo_bm='BM/mesmo.pdf')
        c = self.approved(os=True)
        self.save_info(a, 'Somente A', 'Recebimento A')
        self.save_info(c, 'Somente OS', 'Recebimento OS')
        self.assertIsNone(self.client.get(self.url(b)).json()['informacao'])
        response = self.forecast()
        self.assertContains(response, 'Somente A')
        self.assertContains(response, 'Somente OS')
        self.assertEqual(m.MedicaoRecebimentoBM.objects.count(), 2)

    def test_operacoes_invalidas_e_inexistentes_nao_alteram(self):
        bm = self.approved()
        self.assertEqual(self.client.post(self.url(bm), {'acao': 'excluir', 'versao': ''}).status_code, 409)
        self.assertEqual(self.client.post(self.url(bm), {'acao': 'outra', 'versao': ''}).status_code, 400)
        self.assertEqual(self.client.get(reverse('informacao_medicao_recebimento_bm', args=[99999999])).status_code, 404)
        self.assertFalse(self.history(bm).exists())

    def test_falha_de_auditoria_reverte_a_informacao(self):
        bm = self.approved()
        with patch('gestao_contratos.bm_recebimento.m.RegistroAuditoria.objects.create', side_effect=RuntimeError('Auditoria indisponível')):
            with self.assertRaises(RuntimeError):
                self.save_info(bm)
        self.assertFalse(m.MedicaoRecebimentoBM.objects.exists())

    def test_leitura_dos_textos_e_autores_nao_faz_consultas_por_linha(self):
        from .views import forecast_bms
        bm = self.approved()
        self.save_info(bm)
        rows = list(forecast_bms(self.finance, date(2026, 11, 1), date(2026, 11, 30)))
        with self.assertNumQueries(0):
            for row in rows:
                info = row.medicao_recebimento
                self.assertIn(self.finance.username, info.identificacao_criador)
                self.assertEqual(info.texto_exportacao, 'Sobre medição: Medição conferida\nSobre medição e recebimento: Recebimento pendente')

    def test_banco_rejeita_texto_vazio(self):
        bm = self.approved()
        with self.assertRaises(IntegrityError), transaction.atomic():
            m.MedicaoRecebimentoBM.objects.create(bm=bm, criado_por=self.finance, atualizado_por=self.finance,
                sobre_medicao='', sobre_medicao_recebimento='Recebido')
