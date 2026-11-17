"""Decisão e justificativa na previsão: os mesmos serviços dos detalhes do BM."""
import hashlib
import json

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError, PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import models as m, bm_cycles as cycles
from .bm_cycle_views import access, info as cycle_info
from .workflows import locked_action


def payment_info(bm, user, *, notes=None):
    from .views import user_can_approve_bm_payment
    state = getattr(bm, 'ciclo_contexto', None)
    if state is None:
        state = cycle_info(bm, user)
    if not access(user, bm):
        return None
    cycle = state['cycle'] if state else None
    current_cycle = cycle if cycle and cycle['tipo'] != 'inicial' else None
    version = state['version'] if state else cycles.financial_state(cycles.raw_connection(), bm.pk)['version']
    status = bm.aprovacao_pagamento
    fallback = bm.justificativa_reprovacao_diretor if status == 'reprovado' else bm.justificativa_aprovacao_diretor
    can_decide = user_can_approve_bm_payment(user, bm)
    if current_cycle:
        decision = state.get('decisions', {}).get('diretoria')
        valid = decision and decision['versao_material'] == version
        status = decision['situacao'] if valid else 'pendente'
        fallback = decision['justificativa'] if valid else ''
        can_decide = state['can_decide'] and state['stage'] == 'diretoria'
    key = (bm.pk, current_cycle['id'] if current_cycle else None)
    note = notes.get(key) if notes is not None else m.JustificativaPagamentoBM.objects.filter(bm=bm, ciclo_id=key[1]).first()
    text = note.texto if note and note.versao_material == version else (fallback or '')
    # Inclui saldo/versão e edição de texto: formulários antigos não sobrescrevem decisões.
    token = hashlib.sha256(json.dumps([version, key[1], status, text, state.get('balance_cents') if state else None,
        note.atualizado_em.isoformat() if note else None], ensure_ascii=False).encode()).hexdigest()
    return dict(status=status, text=text, version=version, cycle_id=key[1], token=token,
                can_decide=bool(can_decide and user.grupo == 'diretoria'),
                can_edit=user.grupo == 'diretoria', url=reverse('acao_pagamento_bm_previsao', args=[bm.pk]))


def prepare_payment_rows(bms, user):
    bms = list(bms)
    notes = {(note.bm_id, note.ciclo_id): note for note in m.JustificativaPagamentoBM.objects.filter(bm_id__in=[b.pk for b in bms])}
    for bm in bms:
        bm.pagamento_diretoria = payment_info(bm, user, notes=notes)
    return bms


def save_note(bm, user, current, text):
    before = current['text']
    m.JustificativaPagamentoBM.objects.update_or_create(bm=bm, ciclo_id=current['cycle_id'], defaults={
        'versao_material': current['version'], 'texto': text, 'atualizado_por': user})
    if current['cycle_id'] is None:
        # Compatibilidade com as justificativas já exibidas no Evento/OS e no Excel.
        field = 'justificativa_reprovacao_diretor' if bm.aprovacao_pagamento == 'reprovado' else 'justificativa_aprovacao_diretor'
        setattr(bm, field, text or None)
        bm.save(update_fields=[field])
    m.RegistroAuditoria.objects.create(content_type=ContentType.objects.get_for_model(bm), object_id=bm.pk,
        acao='atualizado', usuario=user, modelo='BM', representacao_objeto=str(bm)[:255],
        detalhes='Justificativa da Diretoria: '+('excluída' if not text else 'atualizada'),
        operacao_financeira='justificativa_bm', autor_nome=user.get_full_name() or user.username, autor_grupo=user.grupo,
        estado_anterior={'justificativa': before, 'ciclo_id': current['cycle_id']},
        estado_posterior={'justificativa': text, 'ciclo_id': current['cycle_id']})


@login_required
@require_POST
@locked_action(m.BM, key='bm_id', sqlite_immediate=True)
def action(request, bm_id):
    if not request.user.is_active or request.user.grupo != 'diretoria':
        return JsonResponse({'success': False, 'error': 'Somente a Diretoria pode registrar esta operação.'}, status=403)
    bm = get_object_or_404(m.BM, pk=bm_id)
    if not access(request.user, bm):
        return JsonResponse({'success': False, 'error': 'BM fora do seu escopo de acesso.'}, status=403)
    current = payment_info(bm, request.user)
    if request.POST.get('token') != current['token']:
        return JsonResponse({'success': False, 'error': 'O BM ou a justificativa mudou. Atualize a página antes de confirmar.'}, status=409)
    operation = request.POST.get('acao')
    text = request.POST.get('justificativa', '').strip()
    if operation == 'excluir_justificativa':
        text = ''
    if len(text) > 4000:
        return JsonResponse({'success': False, 'error': 'A justificativa deve ter no máximo 4.000 caracteres.'}, status=400)
    if operation in {'salvar_justificativa', 'excluir_justificativa'}:
        if operation == 'salvar_justificativa' and not text:
            return JsonResponse({'success': False, 'error': 'Preencha a justificativa ou use Excluir.'}, status=400)
        save_note(bm, request.user, current, text)
        return JsonResponse({'success': True})
    if operation not in {'aprovar_pagamento', 'reprovar_pagamento'}:
        return JsonResponse({'success': False, 'error': 'Ação inválida.'}, status=400)
    if not current['can_decide']:
        return JsonResponse({'success': False, 'error': 'Decisão indisponível. Confira as aprovações e o ciclo atual.'}, status=409)
    if operation == 'reprovar_pagamento' and not text:
        return JsonResponse({'success': False, 'error': 'A justificativa é obrigatória para reprovar o pagamento do BM.'}, status=400)
    if current['cycle_id']:
        try:
            cycles.decide(current['cycle_id'], request.user, 'diretoria', operation == 'aprovar_pagamento', text,
                          expected_version=current['version'])
        except (ValidationError, PermissionDenied) as error:
            return JsonResponse({'success': False, 'error': ' '.join(error.messages) if hasattr(error, 'messages') else str(error)}, status=409)
    else:
        from .views import avaliar_bm
        response = avaliar_bm(request, bm_id=bm_id)
        if response.status_code != 200 or not json.loads(response.content).get('success'):
            return response
    bm.refresh_from_db()
    fresh = payment_info(bm, request.user)
    save_note(bm, request.user, fresh, text)
    return JsonResponse({'success': True})
