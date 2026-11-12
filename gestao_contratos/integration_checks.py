"""Cenários de integração em subprocesso, com SQLite e media descartáveis.

Executável pelos testes do app, sem depender de diretórios de evidências locais.
"""
from datetime import date
from hashlib import sha256
from pathlib import Path
import os
import sys
import tempfile
import threading


def concurrent_pair(actions):
    from django.db import connections
    barrier = threading.Barrier(2)
    results = []

    def worker(action):
        try:
            barrier.wait(timeout=15)
            results.append(action())
        except Exception as error:
            results.append({"error": repr(error)})
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(action,)) for action in actions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads), "Worker não terminou."
    assert len(results) == 2 and not any("error" in row for row in results), results
    return results


def bm_decisions(fixture):
    from django.contrib.contenttypes.models import ContentType
    from django.test import Client
    from django.urls import reverse
    from . import models as m

    director = fixture.create_user("integration_director", "diretoria")
    fixture.client.force_login(director)
    bm = fixture.bm(operational="aprovado")

    def decide(action):
        client = Client()
        client.cookies = fixture.client.cookies.copy()
        response = client.post(reverse("avaliar_bm", args=[bm.pk]),
            {"acao": action, "justificativa": "Decisão concorrente de teste"})
        return {"status": response.status_code, "action": action}

    results = concurrent_pair([lambda: decide("aprovar_pagamento"), lambda: decide("reprovar_pagamento")])
    assert sorted(row["status"] for row in results) == [200, 409], results
    entries = m.RegistroAuditoria.objects.filter(content_type=ContentType.objects.get_for_model(bm),
        object_id=bm.pk, operacao_financeira="decisao_bm")
    assert entries.count() == 1
    bm.refresh_from_db()
    winner = next(row["action"] for row in results if row["status"] == 200)
    assert bm.aprovacao_pagamento == ("aprovado" if winner == "aprovar_pagamento" else "reprovado")


def payments(fixture):
    from django.core.exceptions import ValidationError
    from . import models as m, payment_services

    for same_key in (False, True):
        bm = fixture.bm(value="100", operational="aprovado", director="aprovado")
        nf = fixture.nf(bm, value="100")

        def pay(key):
            try:
                record, created = payment_services.record_payment(nf_id=nf.pk,
                    user=m.User.objects.get(pk=fixture.finance.pk), valor=80,
                    data_pagamento=date(2026, 11, 5), key=key)
                return {"id": record.pk, "created": created}
            except ValidationError:
                return {"denied": True}

        results = concurrent_pair([lambda: pay("shared" if same_key else "first"),
                                   lambda: pay("shared" if same_key else "second")])
        nf.refresh_from_db()
        assert (nf.movimentos.count(), nf.total_pago, nf.saldo_pendente) == (1, 80, 20), results
        if same_key:
            assert len({row["id"] for row in results}) == 1 and sum(row["created"] for row in results) == 1, results
        else:
            assert sum(row.get("denied", False) for row in results) == 1, results


def legacy_migration(fixture):
    from importlib import import_module
    from django.apps import apps
    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from django.conf import settings
    from . import models as m
    from .financial_audit import financial_audit_context

    historical = MigrationExecutor(connection).loader.project_state(
        [("gestao_contratos", "0119_indices_conferencia_nf")]).apps
    old_bm = historical.get_model("gestao_contratos", "BM")
    old_nf = historical.get_model("gestao_contratos", "NF")
    receipt_name = "NF/Comprovantes/legacy.pdf"
    receipt = Path(settings.MEDIA_ROOT) / receipt_name
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_bytes(b"%PDF-1.4\nsynthetic receipt")
    receipt_hash = sha256(receipt.read_bytes()).hexdigest()
    bms = [old_bm.objects.create(contrato_id=contract.pk, evento_id=event.pk, numero_bm=15,
        parcela_paga=1, valor_pago=value, status_gerente="aprovado", aprovacao_pagamento="aprovado",
        arquivo_bm="BM/shared.pdf") for contract, event, value in zip(fixture.contracts, fixture.events, (60000, 40000))]

    def invoice(bm, value, paid, day, receipt=""):
        return old_nf.objects.create(contrato_id=bm.contrato_id, evento_id=bm.evento_id, bm_id=bm.pk,
            valor_pago=value, parcela_paga=1, financeiro_autorizou=paid,
            data_pagamento=day, comprovante_pagamento=receipt)

    with financial_audit_context(fixture.finance):
        known = invoice(bms[0], 20000, True, date(2026, 10, 15), receipt_name)
    unknown = invoice(bms[1], 40000, True, date(2026, 10, 20))
    unpaid = invoice(bms[0], 10000, False, date(2026, 10, 25))
    call_command("migrate", verbosity=0, interactive=False)
    payment = m.PagamentoNF.objects.get(nf_id=known.pk)
    assert (payment.valor, payment.registrado_por_id, payment.comprovante.name,
            payment.data_pagamento) == (20000, fixture.finance.pk, receipt_name, date(2026, 10, 15))
    assert m.PagamentoNF.objects.get(nf_id=unknown.pk).registrado_por_id is None
    assert not m.PagamentoNF.objects.filter(nf_id=unpaid.pk).exists()
    assert m.PagamentoNF.objects.count() == 2
    assert sha256(receipt.read_bytes()).hexdigest() == receipt_hash
    for nf, contract in ((known, fixture.contracts[0]), (unknown, fixture.contracts[1])):
        assert m.NF.objects.get(pk=nf.pk).contrato_id == contract.pk
    with connection.schema_editor() as editor:
        import_module("gestao_contratos.migrations.0121_abertura_legada_nf").forwards(apps, editor)
    assert m.PagamentoNF.objects.count() == 2


def main():
    checks = {"bm-decisions": bm_decisions, "payments": payments, "legacy-migration": legacy_migration}
    if len(sys.argv) != 2 or sys.argv[1] not in checks:
        raise SystemExit("Informe bm-decisions, payments ou legacy-migration.")
    name = sys.argv[1]
    # Configuração aplicada somente a este subprocesso de testes.
    os.environ["DJANGO_DEBUG"] = "True"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "HIDROGestao.settings")
    from django.conf import settings
    with tempfile.TemporaryDirectory(prefix="hidro-integration-") as directory:
        settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",
            "NAME": str(Path(directory) / "test.sqlite3"), "OPTIONS": {"timeout": 15}}}
        settings.MEDIA_ROOT = str(Path(directory) / "media")
        settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
        settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
        settings.ALLOWED_HOSTS = ["testserver"]
        settings.SECURE_SSL_REDIRECT = False
        import django
        django.setup()
        from django.core.management import call_command
        from django.db import connections
        from django.test import Client
        from .test_financeiro_fase2 import FinanceiroFase2Tests
        if name == "legacy-migration":
            call_command("migrate", "gestao_contratos", "0119", verbosity=0, interactive=False)
            call_command("migrate", "sessions", verbosity=0, interactive=False)
        else:
            call_command("migrate", verbosity=0, interactive=False)
        fixture = FinanceiroFase2Tests()
        fixture.client = Client()
        try:
            fixture.setUp()
            checks[name](fixture)
            print(f"{name}: OK")
        finally:
            fixture.doCleanups()
            connections.close_all()


if __name__ == "__main__":
    main()
