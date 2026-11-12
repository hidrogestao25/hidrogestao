"""Revisões preliminares; não transferem contratos, documentos ou pagamentos."""
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError

from . import models as m
from .permissions import is_internal
from .solicitacao_services import transacao_solicitacao


REVISION_FIELDS = ("descricao", "requisitos", "previsto_no_orcamento", "justificativa_orcamento",
                   "forma_pagamento", "valor_disponivel", "valor_vendido", "data_inicio", "data_fim")


def can_revise(user, source):
    from .views import can_user_manage_supplier_choice
    return bool(is_internal(user) and (user.grupo == "suprimento"
                or can_user_manage_supplier_choice(user, source)))


def preliminary_error(source):
    documents = m.DocumentoContratoTerceiro.objects.filter(solicitacao=source)
    if (source.status == "Onboarding" or m.ContratoTerceiros.objects.filter(prospeccao=source).exists()
            or documents.exclude(arquivo_contrato_assinado="").exclude(arquivo_contrato_assinado__isnull=True).exists()
            or m.DocumentoBM.objects.filter(solicitacao=source).exclude(minuta_boletim_assinado="").exclude(minuta_boletim_assinado__isnull=True).exists()
            or m.Evento.objects.filter(prospeccao=source, contrato_terceiro__isnull=False).exists()):
        return ("Contratação assinada ou efetivada: condições formalizadas não podem ser alteradas "
                "pela renegociação preliminar. Consulte o contrato e utilize o fluxo existente de aditivo.")
    return None


def ensure_preliminary(user, source):
    if not can_revise(user, source):
        raise PermissionDenied("Sem permissão para revisar esta solicitação.")
    if source.cancelada or source.arquivada:
        raise ValidationError("Solicitação cancelada ou arquivada: revisão bloqueada.")
    error = preliminary_error(source)
    if error:
        raise ValidationError(error)


def chosen_proposal(source, proposal_id=None):
    if not source.fornecedor_escolhido_id:
        raise ValidationError("Selecione um fornecedor válido na triagem antes de renegociar a proposta.")
    try:
        proposal = m.PropostaFornecedor.objects.get(solicitacao=source, fornecedor_id=source.fornecedor_escolhido_id)
    except (m.PropostaFornecedor.DoesNotExist, m.PropostaFornecedor.MultipleObjectsReturned):
        raise ValidationError("A proposta do fornecedor escolhido está ausente ou ambígua. Regularize a triagem.")
    if proposal_id is not None and str(proposal.pk) != str(proposal_id):
        raise ValidationError("A proposta informada não corresponde ao fornecedor escolhido nesta solicitação.")
    return proposal


def invalidate_approvals(source):
    from .views import apply_request_regression
    apply_request_regression(source, "Fornecedor selecionado" if source.fornecedor_escolhido_id else "Solicitação de prospecção")
    source.save()
    for document in m.DocumentoBM.objects.filter(solicitacao=source):
        document.status_coordenador = document.status_gerente = "pendente"
        document.data_aprovacao_coordenador = document.data_aprovacao_gerente = None
        document.save(update_fields=["status_coordenador", "status_gerente", "data_aprovacao_coordenador", "data_aprovacao_gerente"])


def audit(source, user, operation, before, after):
    m.RegistroAuditoria.objects.create(content_type=ContentType.objects.get_for_model(source), object_id=source.pk,
        acao="atualizado", usuario=user, modelo=source._meta.verbose_name.title(),
        representacao_objeto=str(source)[:255], detalhes=f"prospeccao:{operation}",
        autor_nome=user.get_full_name() or user.username, autor_grupo=user.grupo,
        estado_anterior=before, estado_posterior=after)


def renegotiate_value(*, source_id, user, value, proposal_id=None):
    with transacao_solicitacao(m.SolicitacaoProspeccao, source_id) as source:
        ensure_preliminary(user, source)
        proposal = chosen_proposal(source, proposal_id)
        previous = proposal.valor_proposta
        proposal.valor_proposta = value
        proposal.full_clean()
        if previous != proposal.valor_proposta:
            proposal.save(update_fields=["valor_proposta"])
            invalidate_approvals(source)
            audit(source, user, "renegociar_valor", {"proposta": proposal.pk, "valor": str(previous)},
                  {"proposta": proposal.pk, "valor": str(proposal.valor_proposta), "status": source.status})
        return proposal


def renegotiate_term(*, source_id, user, start, end):
    with transacao_solicitacao(m.SolicitacaoProspeccao, source_id) as source:
        ensure_preliminary(user, source)
        try:
            document = m.DocumentoContratoTerceiro.objects.get(solicitacao=source)
        except m.DocumentoContratoTerceiro.DoesNotExist:
            raise ValidationError("Nenhuma minuta encontrada. Regularize o planejamento do contrato.")
        previous = {"prazo_inicio": document.prazo_inicio.isoformat(), "prazo_fim": document.prazo_fim.isoformat()}
        document.prazo_inicio, document.prazo_fim = start, end
        document.full_clean()
        after = {"prazo_inicio": start.isoformat(), "prazo_fim": end.isoformat()}
        if previous != after:
            document.save(update_fields=["prazo_inicio", "prazo_fim"])
            invalidate_approvals(source)
            audit(source, user, "renegociar_prazo", previous, after)
        return document


def create_revision(*, source_id, user, values):
    with transacao_solicitacao(m.SolicitacaoProspeccao, source_id) as source:
        ensure_preliminary(user, source)
        events = m.Evento.objects.filter(prospeccao=source)
        if events.filter(boletins_medicao__isnull=False).exists() or m.NF.objects.filter(evento__in=events).exists():
            raise ValidationError("O planejamento possui BM/NF. Regularize os vínculos antes de criar uma revisão.")
        revision = m.SolicitacaoProspeccao(
            contrato_id=source.contrato_id, coordenador_id=source.coordenador_id, lider_contrato_id=source.lider_contrato_id,
            guarda_chuva=source.guarda_chuva, solicitacao_origem=source,
            solicitante=(user.get_full_name() or user.username)[:50], status="Solicitação de prospecção",
            **{field: values.get(field, getattr(source, field)) for field in REVISION_FIELDS})
        revision.full_clean()
        revision.save()
        # Só planejamento: nunca clonar entrega, avaliação, BM, NF ou documento assinado.
        for event in events:
            m.Evento.objects.create(prospeccao=revision, descricao=event.descricao, data_prevista=event.data_prevista,
                valor_previsto=event.valor_previsto, data_prevista_pagamento=event.data_prevista_pagamento)
        audit(source, user, "nova_revisao", {"solicitacao": source.pk}, {"revisao": revision.pk})
        return revision
