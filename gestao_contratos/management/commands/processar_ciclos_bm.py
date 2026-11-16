"""Rotina agendável e idempotente; não é executada por consultas GET."""
import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from gestao_contratos import bm_cycles as cycles, models as m


class Command(BaseCommand):
    help = 'Registra programações e reapresenta o saldo dos BMs na próxima data válida do calendário.'

    def add_arguments(self, parser):
        parser.add_argument('--bm', type=int, action='append', dest='bm_ids', help='Restringe aos IDs de participação informados; pode repetir.')
        parser.add_argument('--ate', type=date.fromisoformat, help='Data de referência, sem antecipar o encerramento de ciclos futuros.')
        parser.add_argument('--dry-run', action='store_true', help='Consulta impedimentos e saldo, sem gravar.')

    def handle(self, *args, **options):
        if not cycles.enabled():
            raise CommandError('Aplique e confira a migration 0129 antes de ativar a rotina de ciclos. O comando não aplica migrations.')
        today = options['ate'] or timezone.localdate()
        if today > timezone.localdate():
            raise CommandError('Data futura não permitida para encerramento de programação.')
        queryset = m.BM.objects.order_by('pk')
        if options['bm_ids']:
            queryset = queryset.filter(pk__in=options['bm_ids'])
        report = dict(consultados=0, ciclos_criados=0, pendencias=[], dry_run=options['dry_run'])
        for bm_id in queryset.values_list('pk', flat=True).iterator(chunk_size=200):
            report['consultados'] += 1
            if options['dry_run']:
                state = cycles.financial_state(cycles.raw_connection(), bm_id, today)
                result = dict(created=[], reason='; '.join(state['errors']) or ('Data prevista não informada.' if not state['reference'] else 'Liquidado.' if state['full'] else 'Saldo pendente: '+str(cycles.money(state['balance_cents']))))
            else:
                result = cycles.process_bm(bm_id, today=today)
            report['ciclos_criados'] += len(result['created'])
            report['pendencias'].append(dict(bm_id=bm_id, **result))
        self.stdout.write(json.dumps(report, ensure_ascii=False))
