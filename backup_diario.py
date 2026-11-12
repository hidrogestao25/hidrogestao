"""Backup SQLite e avisos. Importar este módulo não executa a rotina."""
import argparse
from contextlib import closing
from datetime import datetime, timezone as datetime_timezone
import logging
import os
from pathlib import Path
import sqlite3

logger = logging.getLogger(__name__)


def create_backup(database, backup_dir):
    database = Path(database).resolve(strict=True)
    backup_dir = Path(backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"backup_{datetime.now(datetime_timezone.utc):%Y-%m-%d_%H-%M-%S_%f}.sqlite3"
    # A API captura uma imagem consistente, inclusive com SQLite em WAL.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(target)) as destination:
            source.backup(destination)
            if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("A cópia não passou na verificação de integridade.")
    return target


def cleanup_backups(backup_dir, retention_days=30):
    if retention_days < 1:
        raise ValueError("A retenção deve ser de pelo menos um dia.")
    root = Path(backup_dir).resolve(strict=True)
    cutoff = datetime.now(datetime_timezone.utc).timestamp() - retention_days * 86400
    removed = 0
    for candidate in root.glob("backup_*.sqlite3"):
        if candidate.is_symlink() or candidate.resolve().parent != root:
            continue
        if candidate.is_file() and candidate.stat().st_mtime < cutoff:
            candidate.unlink()
            removed += 1
    return removed


def send_reminders():
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives
    from django.utils import timezone
    from django.utils.html import strip_tags
    from gestao_contratos.models import ContratoTerceiros, Evento, User
    from gestao_contratos.views import build_weekly_supply_report, send_mail

    today = timezone.localdate()
    failed = 0
    events = Evento.objects.filter(
        data_prevista=today, contrato_terceiro__isnull=False, realizado=False,
    ).exclude(contrato_terceiro__status="encerrado").select_related(
        "contrato_terceiro__coordenador", "contrato_terceiro__lider_contrato",
        "contrato_terceiro__empresa_terceira",
    )
    supply = list(User.objects.filter(grupo="suprimento", is_active=True).exclude(email="").values_list("email", flat=True))

    def recipients(contract):
        people = contract.referencia_todos_coordenadores
        leader = contract.referencia_lider_contrato
        if leader:
            people = [*people, leader]
        return {person.email for person in people if person.is_active and person.email}

    def send(subject, body, emails):
        nonlocal failed
        if emails and not send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, sorted(emails), fail_silently=False):
            failed += 1

    for event in events:
        contract = event.contrato_terceiro
        send(f"Lembrete de entrega - Evento #{event.pk}",
             f"Entrega prevista hoje ({today:%d/%m/%Y}).\nFornecedor: {contract.empresa_terceira}\nDescrição: {event.descricao}\nContrato: {contract.num_contrato or 'N/A'}",
             recipients(contract))

    for contract in ContratoTerceiros.objects.filter(data_fim=today).exclude(status="encerrado"):
        send(f"Encerramento de contrato - {contract.empresa_terceira}",
             f"O contrato {contract.num_contrato or 'N/A'} encerra hoje ({today:%d/%m/%Y}). Verifique as providências necessárias.",
             recipients(contract) | set(supply))

    if today.weekday() == 0:
        report_user = User.objects.filter(grupo="suprimento", is_active=True).exclude(email="").first()
        emails = sorted(set(User.objects.filter(
            grupo__in=["lider_contrato", "gerente_contrato", "gerente_lider"], is_active=True,
        ).exclude(email="").values_list("email", flat=True)))
        if report_user and emails:
            try:
                html = build_weekly_supply_report(report_user)
                email = EmailMultiAlternatives("Report Semanal de Suprimentos", strip_tags(html), settings.DEFAULT_FROM_EMAIL, emails)
                email.attach_alternative(html, "text/html")
                email.send()
            except Exception as exc:
                # Não imprimir destinatários, conteúdo ou credenciais do SMTP.
                logger.warning("Falha no report semanal (%s).", type(exc).__name__)
                failed += 1
    return failed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--skip-notifications", action="store_true")
    args = parser.parse_args(argv)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "HIDROGestao.settings")
    import django
    django.setup()
    from django.conf import settings
    if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
        raise RuntimeError("Esta rotina exige SQLite; use o backup nativo do banco configurado.")
    backup_dir = args.backup_dir or Path(os.environ.get("DJANGO_BACKUP_DIR", settings.BASE_DIR / "backups"))
    target = create_backup(settings.DATABASES["default"]["NAME"], backup_dir)
    cleanup_backups(backup_dir, args.retention_days)
    logger.info("Backup verificado: %s", target.name)
    return 1 if not args.skip_notifications and send_reminders() else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
