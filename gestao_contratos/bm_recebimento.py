"""Informações de medição/recebimento: edição exclusiva do Financeiro e trilha por BM."""
from functools import wraps

from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from . import models as m
from .permissions import can_access_document, can_view_object, is_internal
from .workflows import locked_action


class MedicaoRecebimentoForm(forms.Form):
    sobre_medicao = forms.CharField(label='Sobre medição', max_length=4000, strip=True)
    sobre_medicao_recebimento = forms.CharField(label='Sobre medição e recebimento', max_length=4000, strip=True)


def financeiro_only(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_internal(request.user) or request.user.grupo != 'financeiro':
            return JsonResponse({'success': False, 'error': 'Somente o Financeiro pode alterar estas informações.'}, status=403)
        return view(request, *args, **kwargs)
    return wrapped


def snapshot(info):
    if info is None:
        return None
    return dict(sobre_medicao=info.sobre_medicao, sobre_medicao_recebimento=info.sobre_medicao_recebimento,
                criado_por=info.criado_por_id, criado_em=info.criado_em.isoformat(),
                atualizado_por=info.atualizado_por_id, atualizado_em=info.atualizado_em.isoformat(),
                identificacao_criador=info.identificacao_criador, identificacao_editor=info.identificacao_editor)


@login_required
@require_http_methods(['GET', 'POST'])
@never_cache
@financeiro_only
@locked_action(m.BM, key='bm_id', sqlite_immediate=True)
def informacao_medicao_recebimento(request, bm_id):
    bm = get_object_or_404(m.BM.objects.select_related('evento__contrato_terceiro', 'os__contrato', 'contrato'), pk=bm_id)
    if not can_view_object(request.user, bm) or not can_access_document(request.user, bm):
        raise Http404
    info = m.MedicaoRecebimentoBM.objects.select_related('criado_por', 'atualizado_por').filter(bm=bm).first()
    version = info.atualizado_em.isoformat() if info else ''
    if request.method == 'GET':
        return JsonResponse({'success': True, 'informacao': snapshot(info), 'versao': version})
    action = request.POST.get('acao')
    if action not in {'salvar', 'excluir'}:
        return JsonResponse({'success': False, 'error': 'Ação inválida.'}, status=400)
    if 'versao' not in request.POST or request.POST['versao'] != version:
        return JsonResponse({'success': False, 'error': 'As informações foram alteradas por outro usuário. Feche e abra o formulário novamente antes de continuar.'}, status=409)
    before = snapshot(info)
    created = info is None
    if action == 'salvar':
        form = MedicaoRecebimentoForm(request.POST)
        if not form.is_valid():
            return JsonResponse({'success': False, 'error': 'Preencha os dois campos obrigatórios, com até 4.000 caracteres cada.',
                                 'errors': form.errors.get_json_data()}, status=400)
        if created:
            info = m.MedicaoRecebimentoBM(bm=bm, criado_por=request.user)
        info.sobre_medicao = form.cleaned_data['sobre_medicao']
        info.sobre_medicao_recebimento = form.cleaned_data['sobre_medicao_recebimento']
        info.atualizado_por = request.user
        info.save()
        after = snapshot(info)
    else:
        if info is None:
            return JsonResponse({'success': False, 'error': 'Não há informação para excluir.'}, status=409)
        info.delete()
        after = None
    # O objeto da trilha é o BM: o histórico sobrevive à exclusão da informação.
    m.RegistroAuditoria.objects.create(
        content_type=ContentType.objects.get_for_model(m.BM), object_id=bm.pk,
        acao='criado' if created else 'atualizado', usuario=request.user, modelo='BM',
        representacao_objeto=f'Medição e recebimento do BM #{bm.pk}',
        detalhes=f'{request.method} {request.path} | Medição e recebimento: {action}',
        operacao_financeira='medicao_recebimento_bm', estado_anterior=before, estado_posterior=after,
        justificativa='Exclusão da informação pelo Financeiro' if action == 'excluir' else None,
        autor_nome=request.user.get_full_name() or request.user.username, autor_grupo=request.user.grupo,
    )
    return JsonResponse({'success': True, 'informacao': after,
                         'versao': after['atualizado_em'] if after else ''})
