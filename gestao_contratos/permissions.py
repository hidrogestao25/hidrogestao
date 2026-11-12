"""Escopo de leitura compartilhado por páginas, ações e downloads privados."""
from functools import wraps

from django.shortcuts import redirect
from django.contrib import messages
from django.http import JsonResponse

from . import models


INTERNAL_ROLES = {
    "suprimento", "financeiro", "diretoria", "gerente_contrato",
    "coordenador", "lider_contrato", "gerente", "gerente_lider",
}
GLOBAL_ROLES = {"suprimento", "financeiro", "diretoria", "gerente_contrato"}


PAID_NF_READ_ONLY_MESSAGE = (
    "Pagamento já registrado. Alterações posteriores devem ser realizadas pelo Suprimento."
)


def can_change_nf(user, nf):
    return bool(is_internal(user) and user.grupo in {"suprimento", "financeiro"}
                and (user.grupo == "suprimento" or (not nf.cancelada_em and not nf.possui_pagamentos)))


def bm_has_valid_operational_approval(bm):
    return bool(bm and (
        bm.status_coordenador == "aprovado" or bm.status_gerente == "aprovado"
    ) and bm.status_coordenador != "reprovado" and bm.status_gerente != "reprovado")


def payment_registration_error(user, bm, origin=None):
    """Financeiro registra uma liquidação autorizada; Suprimento conserva correções."""
    if not user or user.grupo != "financeiro":
        return None
    if not bm:
        return "Selecione o BM da nota fiscal antes de registrar o pagamento."
    if isinstance(origin, models.OS) and origin.status == "cancelada":
        return "Não é permitido registrar novo pagamento de uma OS cancelada."
    if not bm_has_valid_operational_approval(bm):
        return "O BM precisa de aprovação operacional válida para registrar o pagamento."
    if bm.aprovacao_pagamento != "aprovado":
        return "Pagamento ainda não autorizado pela Diretoria."
    return None


def financeiro_read_only(view):
    """Libera consulta sem transformar o escopo global em poder de alteração."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.user.grupo == "financeiro" and request.method not in {"GET", "HEAD", "OPTIONS"}:
            return JsonResponse({"success": False, "error": "Esta página é somente leitura para o Financeiro."}, status=403)
        return view(request, *args, **kwargs)
    return wrapped


def is_internal(user):
    return bool(user and user.is_authenticated and user.is_active
                and user.grupo in INTERNAL_ROLES)


def _assigned(user, obj):
    leader_id = getattr(obj, "lider_contrato_id", None) or getattr(getattr(obj, "lider_contrato", None), "pk", None)
    if leader_id == user.pk:
        return True
    coordinator_ids = set()
    coordinator_id = getattr(obj, "coordenador_id", None) or getattr(getattr(obj, "coordenador", None), "pk", None)
    if coordinator_id:
        coordinator_ids.add(coordinator_id)
    if hasattr(obj, "coordenadores"):
        coordinator_ids.update(obj.coordenadores.values_list("pk", flat=True))
    if user.grupo == "coordenador":
        return user.pk in coordinator_ids
    if user.grupo in {"gerente", "gerente_lider"}:
        return models.User.objects.filter(
            pk__in=coordinator_ids, centros__in=user.centros.all()
        ).exists()
    return False


def can_view_object(user, obj):
    if not is_internal(user) or obj is None:
        return False
    if user.grupo in GLOBAL_ROLES:
        return True
    if isinstance(obj,(models.PagamentoNF,models.ProgramacaoPagamento,models.ReprogramacaoPagamento)):
        return can_view_object(user,obj.nf)
    if isinstance(obj, models.Contrato):
        return _assigned(user, obj)
    if isinstance(obj, models.ContratoTerceiros):
        # O catálogo de contratos guarda-chuva é compartilhado entre perfis internos.
        return bool(obj.guarda_chuva or _assigned(user, obj))
    if isinstance(obj, (models.SolicitacaoContrato, models.SolicitacaoProspeccao)):
        return bool(_assigned(user, obj) or (
            obj.contrato_id and can_view_object(user, obj.contrato)
        ))
    if isinstance(obj, (models.OS, models.SolicitacaoOrdemServico)):
        return bool(_assigned(user, obj) or getattr(obj, "solicitante_id", None) == user.pk)
    if isinstance(obj, models.AditivoContratoTerceiro):
        return obj.solicitado_por_id == user.pk or can_view_object(user, obj.contrato)
    if isinstance(obj, models.Evento):
        parent = obj.contrato_terceiro or obj.prospeccao or obj.solicitacao_contrato or obj.aditivo
        return can_view_object(user, parent)
    if isinstance(obj, (models.BM, models.NF)):
        return can_view_object(user, obj.os or obj.evento or obj.contrato)
    if isinstance(obj, (models.DocumentoBM, models.DocumentoContratoTerceiro)):
        return can_view_object(user, obj.solicitacao or obj.solicitacao_contrato)
    if isinstance(obj, (models.NFCliente, models.DocumentoContrato)):
        return can_view_object(user, obj.contrato)
    if isinstance(obj, models.PropostaFornecedor):
        return can_view_object(user, obj.solicitacao or obj.solicitacao_contrato)
    if isinstance(obj, models.Proposta):
        return models.Contrato.objects.filter(proposta=obj).exists() and can_view_object(user, obj.contrato)
    if isinstance(obj, models.Cliente):
        return any(can_view_object(user, contract) for contract in obj.contratos.all())
    if isinstance(obj, models.EmpresaTerceira):
        return any(can_view_object(user, contract) for contract in obj.contratos.all())
    return False


def _document_admin(user, model=None):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return bool(model and user.is_staff and user.has_perm(
        f"{model._meta.app_label}.view_{model._meta.model_name}"
    ))


def can_read_os(user, order):
    """Leitura operacional pelo catálogo não concede acesso documental/escrita."""
    return bool(is_internal(user) and order and (
        can_view_object(user, order)
        or (user.grupo in {"lider_contrato", "gerente_lider"}
            and order.contrato.guarda_chuva and can_view_object(user, order.contrato))
    ))


def can_write_os_scope(user, order):
    """Escopo adicional; cada ação ainda exige seu perfil/permissão específicos."""
    if (user and user.is_authenticated and user.is_active and user.is_superuser
            and user.grupo != "financeiro"):
        return order is not None
    return bool(is_internal(user) and user.grupo != "financeiro" and order and (
        user.grupo in {"suprimento", "diretoria", "gerente_contrato"}
        or _assigned(user, order)
    ))


def can_access_contract(user, contract):
    """Escopo de documentos: guarda-chuva exige vínculo, como os demais contratos."""
    if contract is None or not user or not user.is_authenticated or not user.is_active:
        return False
    if _document_admin(user):
        return True
    if not is_internal(user):
        return False
    if user.grupo in GLOBAL_ROLES or _assigned(user, contract):
        return True
    if isinstance(contract, models.ContratoTerceiros) and contract.cod_projeto_id:
        return _assigned(user, contract.cod_projeto)
    return False


def document_contracts(document):
    """Resolve os contratos/projetos responsáveis por cada classe de upload.

    BM compartilhado relaciona o vínculo documental e a origem financeira.
    Repetir somente o número nunca cria uma relação de acesso.
    """
    if isinstance(document,(models.PagamentoNF,models.ProgramacaoPagamento,models.ReprogramacaoPagamento)):
        return document_contracts(document.nf)
    if isinstance(document, (models.Contrato, models.ContratoTerceiros)):
        return [document]
    if isinstance(document, (models.BM, models.NF)) and document.os_id:
        return document_contracts(document.os)
    if isinstance(document, models.BM):
        contracts = [document.contrato]
        if document.evento_id and document.evento.contrato_terceiro_id:
            contracts.append(document.evento.contrato_terceiro)
        return contracts
    if isinstance(document, (models.NF, models.NFCliente,
                             models.DocumentoContrato, models.AditivoContratoTerceiro)):
        return [document.contrato] if document.contrato_id else []
    if isinstance(document, (models.OS, models.SolicitacaoOrdemServico)):
        # OS de um projeto não herda acesso de todos os usuários do guarda-chuva.
        return [document.cod_projeto] if document.cod_projeto_id else [document.contrato]
    if isinstance(document, models.Evento):
        if document.contrato_terceiro_id:
            return [document.contrato_terceiro]
        if document.aditivo_id:
            return document_contracts(document.aditivo)
        return document_contracts(document.prospeccao or document.solicitacao_contrato)
    if isinstance(document, (models.SolicitacaoContrato, models.SolicitacaoProspeccao)):
        return [document.contrato] if document.contrato_id else []
    if isinstance(document, (models.DocumentoBM, models.DocumentoContratoTerceiro,
                             models.PropostaFornecedor)):
        return document_contracts(document.solicitacao or document.solicitacao_contrato)
    return []


def can_access_document(user, document):
    if not user or not user.is_authenticated or not user.is_active or document is None:
        return False
    if _document_admin(user, type(document)):
        return True
    if not is_internal(user):
        return False
    if user.grupo in GLOBAL_ROLES:
        return True
    if isinstance(document,(models.PagamentoNF,models.ProgramacaoPagamento,models.ReprogramacaoPagamento)):
        nf=document.nf
        return can_view_object(user,nf) and can_access_document(user,nf) and bool(nf.bm_id and can_view_object(user,nf.bm) and can_access_document(user,nf.bm))
    if isinstance(document, (models.BM, models.NF)) and document.os_id:
        return can_access_document(user, document.os)
    if isinstance(document, (models.DocumentoBM, models.DocumentoContratoTerceiro,
                             models.PropostaFornecedor)):
        return can_access_document(user, document.solicitacao or document.solicitacao_contrato)
    if isinstance(document, models.Evento) and not document.contrato_terceiro_id:
        return can_access_document(user, document.aditivo or document.prospeccao or document.solicitacao_contrato)
    if isinstance(document, (models.OS, models.SolicitacaoOrdemServico,
                             models.SolicitacaoContrato, models.SolicitacaoProspeccao)):
        # Vínculo operacional direto continua válido antes de materializar contrato.
        if _assigned(user, document):
            return True
    return any(can_access_contract(user, contract) for contract in document_contracts(document))


def accessible_document_bms(user, queryset):
    """Usa a mesma decisão dos downloads individuais para listas/ZIP de BM."""
    if not user or not user.is_authenticated or not user.is_active:
        return queryset.none()
    if _document_admin(user, models.BM) or user.grupo in GLOBAL_ROLES:
        return queryset
    if not is_internal(user):
        return queryset.none()
    candidates = queryset.select_related("contrato__cod_projeto", "os__cod_projeto", "os__contrato",
                                        "evento__contrato_terceiro__cod_projeto")
    allowed_ids = [bm.pk for bm in candidates if can_access_document(user, bm)]
    return queryset.filter(pk__in=allowed_ids)


def object_access(model, key="pk"):
    """Completa verificações de perfil já presentes nas views com o escopo do objeto."""
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            obj = model.objects.filter(pk=kwargs.get(key, args[0] if args else None)).first()
            if obj is None:
                return view(request, *args, **kwargs)
            if not can_view_object(request.user, obj):
                messages.error(request, "Você não tem permissão para acessar este registro.")
                return redirect("home")
            return view(request, *args, **kwargs)
        return wrapped
    return decorate
