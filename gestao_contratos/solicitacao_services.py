"""Operações de solicitações, preservando vínculos e efeitos contratuais/financeiros."""
from contextlib import contextmanager
from functools import wraps
from uuid import uuid4

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import (AditivoContratoTerceiro, ContratoTerceiros, DocumentoBM,
                     DocumentoContratoTerceiro, Evento, NF, OS, RegistroAuditoria,
                     SolicitacaoContrato, SolicitacaoOrdemServico, SolicitacaoProspeccao)
from .permissions import can_view_object, is_internal
from .workflows import claim_once


MODELOS = {"prospeccao": SolicitacaoProspeccao, "contratacao": SolicitacaoContrato,
           "os": SolicitacaoOrdemServico, "aditivo": AditivoContratoTerceiro}
DETALHES = {"prospeccao": "detalhes_solicitacao", "contratacao": "detalhes_solicitacao_contrato",
            "os": "detalhe_ordem_servico", "aditivo": "detalhes_aditivo_contrato"}


def eventos_operacionais():
    # Compromissos contratuais continuam visíveis nos módulos de contrato e financeiro.
    return Evento.objects.exclude(
        Q(prospeccao__arquivada=True) | Q(prospeccao__cancelada_em__isnull=False) |
        Q(prospeccao__status="Cancelada") | Q(solicitacao_contrato__arquivada=True) |
        Q(solicitacao_contrato__cancelada_em__isnull=False) | Q(solicitacao_contrato__status="Cancelada") |
        Q(aditivo__cancelada_em__isnull=False) | Q(aditivo__arquivada=True, contrato_terceiro__isnull=True)
    )


def pode_consultar(user, solicitacao):
    if not can_view_object(user, solicitacao):
        return False
    if isinstance(solicitacao, SolicitacaoOrdemServico):
        # A solicitação conserva o escopo mais restrito de seus detalhes; uma OS
        # emitida possui regras próprias de leitura contratual/financeira.
        if user.grupo == "coordenador":
            return solicitacao.solicitante_id == user.pk
        if user.grupo == "lider_contrato":
            return solicitacao.lider_contrato_id == user.pk
        if user.grupo == "gerente_lider":
            from .views import user_shares_center_with_coordinator
            return (solicitacao.lider_contrato_id == user.pk or
                    user_shares_center_with_coordinator(user, solicitacao.coordenador))
    if isinstance(solicitacao, AditivoContratoTerceiro):
        from .views import can_user_view_addendum
        return can_user_view_addendum(user, solicitacao)
    return True


def pode_operar(user, solicitacao, operacao):
    if not is_internal(user) or user.grupo == "financeiro" or not pode_consultar(user, solicitacao):
        return False
    if operacao == "cancelar" and user.grupo != "suprimento":
        return False
    permission = "cancelar" if operacao == "cancelar" else "arquivar"
    return user.has_perm(f"gestao_contratos.{permission}_{solicitacao._meta.model_name}")


def erro_financeiro(notas):
    if any(nota.saldo_pendente > 0 for nota in notas):
        return "Existem obrigações financeiras pendentes vinculadas à solicitação."
    return None


def erro_cancelamento_os(solicitacao):
    if OS.objects.filter(solicitacao=solicitacao).exists() or solicitacao.status in {"aprovada", "finalizada"}:
        return "Esta solicitação já originou uma OS formalizada. Utilize o fluxo da OS emitida."
    if solicitacao.status not in {"solicitacao_os", "pendente_lider", "pendente_gerente", "pendente_diretoria",
                                 "pendente_suprimento", "pendente_minuta_gerente", "reprovada"}:
        return "A etapa atual da solicitação de OS não permite cancelamento."
    return None


def erro_arquivamento_os(solicitacao):
    ordens = OS.objects.filter(solicitacao=solicitacao)
    if ordens.exclude(status__in=["finalizada", "cancelada"]).exists():
        return "A OS emitida está em execução ou paralisada. Regularize seu encerramento antes de arquivar a solicitação."
    if solicitacao.status == "aprovada" and not ordens.exists():
        return "Regularize o vínculo com a OS emitida antes de arquivar esta solicitação aprovada."
    return erro_financeiro(NF.objects.filter(os__in=ordens))


def aditivo_formalizado(solicitacao):
    return bool(solicitacao.tem_documento_assinado or solicitacao.documento_assinado_enviado_em)


def erro_cancelamento_aditivo(solicitacao):
    eventos = solicitacao.eventos.all()
    if aditivo_formalizado(solicitacao):
        return "O aditivo já foi formalizado. O cancelamento da solicitação não pode reverter o contrato ou o documento assinado."
    if (eventos.filter(Q(realizado=True) | Q(data_entrega__isnull=False) |
                       Q(valor_pago__gt=0) | Q(contrato_terceiro__isnull=False)).exists()
            or NF.objects.filter(evento__in=eventos).exists()
            or eventos.filter(boletins_medicao__isnull=False).exists()):
        return "O aditivo possui entregas ou vínculos contratuais/financeiros. Regularize-os antes de cancelar a solicitação."
    return None


def erro_arquivamento_aditivo(solicitacao):
    eventos = solicitacao.eventos.all()
    formalizado = aditivo_formalizado(solicitacao) or eventos.filter(contrato_terceiro__isnull=False).exists()
    if formalizado and solicitacao.contrato.status != "encerrado":
        return "O aditivo possui efeitos contratuais formalizados. Encerre o contrato pelo fluxo próprio antes de arquivar a solicitação."
    notas = NF.objects.filter(evento__in=eventos)
    if formalizado:
        if OS.objects.filter(contrato=solicitacao.contrato).exclude(status__in=["finalizada", "cancelada"]).exists():
            return "Existem ordens de serviço em andamento no contrato do aditivo."
        notas = NF.objects.filter(Q(evento__in=eventos) | Q(contrato=solicitacao.contrato))
    return erro_financeiro(notas)


def vinculos(solicitacao):
    prospeccao = isinstance(solicitacao, SolicitacaoProspeccao)
    contratos = ContratoTerceiros.objects.filter(**{
        "prospeccao" if prospeccao else "solicitacao": solicitacao,
    })
    eventos = Evento.objects.filter(**{
        "prospeccao" if prospeccao else "solicitacao_contrato": solicitacao,
    })
    return contratos, eventos


def erro_cancelamento(solicitacao):
    if isinstance(solicitacao, SolicitacaoOrdemServico):
        return erro_cancelamento_os(solicitacao)
    if isinstance(solicitacao, AditivoContratoTerceiro):
        return erro_cancelamento_aditivo(solicitacao)
    contratos, eventos = vinculos(solicitacao)
    if contratos.exists() or solicitacao.status == "Onboarding":
        return "A solicitação possui contrato gerado. Utilize o fluxo de encerramento contratual."
    documentos = DocumentoContratoTerceiro.objects.filter(**{
        "solicitacao" if isinstance(solicitacao, SolicitacaoProspeccao) else "solicitacao_contrato": solicitacao,
    })
    if documentos.exclude(arquivo_contrato_assinado="").exclude(arquivo_contrato_assinado__isnull=True).exists():
        return "A solicitação possui contrato assinado. Utilize o fluxo de encerramento contratual."
    if (eventos.filter(Q(realizado=True) | Q(data_entrega__isnull=False) |
                       Q(valor_pago__gt=0) | Q(contrato_terceiro__isnull=False)).exists()
            or NF.objects.filter(evento__in=eventos).exists()
            or eventos.filter(boletins_medicao__isnull=False).exists()):
        return "A solicitação possui entregas ou registros financeiros. Regularize os vínculos antes de cancelar."
    return None


def erro_arquivamento(solicitacao):
    if isinstance(solicitacao, SolicitacaoOrdemServico):
        return erro_arquivamento_os(solicitacao)
    if isinstance(solicitacao, AditivoContratoTerceiro):
        return erro_arquivamento_aditivo(solicitacao)
    contratos, eventos = vinculos(solicitacao)
    if contratos.exclude(status="encerrado").exists():
        return "Encerre o contrato vinculado pelo fluxo contratual antes de arquivar a solicitação."
    documentos = DocumentoContratoTerceiro.objects.filter(**{
        "solicitacao" if isinstance(solicitacao, SolicitacaoProspeccao) else "solicitacao_contrato": solicitacao,
    })
    if not contratos.exists() and documentos.exclude(arquivo_contrato_assinado="").exclude(arquivo_contrato_assinado__isnull=True).exists():
        return "Regularize o encerramento do contrato assinado antes de arquivar a solicitação."
    if OS.objects.filter(contrato__in=contratos).exclude(status__in=["finalizada", "cancelada"]).exists():
        return "Existem ordens de serviço em andamento no contrato vinculado."
    notas = NF.objects.filter(Q(evento__in=eventos) | Q(contrato__in=contratos))
    return erro_financeiro(notas)


@contextmanager
def transacao_solicitacao(model, pk):
    # Mesma estratégia de locked_action: SQLite adquire escrita antes da leitura.
    def immediate(execute, sql, params, many, context):
        if connection.vendor == "sqlite" and sql.strip().upper() == "BEGIN":
            sql = "BEGIN IMMEDIATE"
        return execute(sql, params, many, context)
    with connection.execute_wrapper(immediate), transaction.atomic():
        if connection.vendor == "sqlite":
            field = model._meta.pk.attname
            model.objects.filter(pk=pk).update(**{field: F(field)})
        yield model.objects.select_for_update().get(pk=pk)


def estado(solicitacao):
    return {field: (value.isoformat() if hasattr(value, "isoformat") else value)
            for field in ("status", "arquivada", "arquivada_em", "arquivada_por_id",
                          "motivo_arquivamento", "cancelada_em", "cancelada_por_id", "motivo_cancelamento")
            for value in [getattr(solicitacao, field)]}


def registrar_evento(solicitacao, user, operacao, motivo, anterior, conjunto):
    RegistroAuditoria.objects.create(
        content_type=ContentType.objects.get_for_model(solicitacao), object_id=solicitacao.pk,
        acao="atualizado", usuario=user, modelo=solicitacao._meta.verbose_name.title(),
        representacao_objeto=str(solicitacao)[:255],
        detalhes=f"solicitacao:{operacao} | operação conjunta: {conjunto or '-'}",
        justificativa=motivo, estado_anterior=anterior, estado_posterior=estado(solicitacao),
        autor_nome=user.get_full_name() or user.username, autor_grupo=user.grupo,
    )


def alterar_solicitacao(*, model, pk, user, operacao, motivo="", arquivar=False, token=None):
    if model not in MODELOS.values() or operacao not in {"arquivar", "desarquivar", "cancelar"}:
        raise ValidationError("Operação inválida.")
    motivo = motivo.strip()
    with transacao_solicitacao(model, pk) as solicitacao:
        if not pode_operar(user, solicitacao, operacao):
            raise PermissionDenied("Você não tem permissão para esta operação.")
        if operacao == "cancelar" and arquivar and not pode_operar(user, solicitacao, "arquivar"):
            raise PermissionDenied("Você não tem permissão para arquivar esta solicitação.")
        # Estado e token protegem repetições imediatas e reenvios de formulários antigos.
        if token and not claim_once(f"solicitacao:{model._meta.label_lower}:{pk}:{user.pk}:{token}", 315360000):
            return solicitacao, False
        if operacao == "cancelar" and solicitacao.cancelada:
            return solicitacao, False
        if operacao == "arquivar" and solicitacao.arquivada:
            return solicitacao, False
        if operacao == "desarquivar" and not solicitacao.arquivada:
            return solicitacao, False
        if operacao == "cancelar":
            if not motivo:
                raise ValidationError("Informe a justificativa do cancelamento.")
            error = erro_cancelamento(solicitacao)
            if error:
                raise ValidationError(error)
        if operacao == "arquivar" or (operacao == "cancelar" and arquivar and not solicitacao.arquivada):
            error = erro_arquivamento(solicitacao)
            if error:
                raise ValidationError(error)
        conjunto = str(uuid4()) if operacao == "cancelar" and arquivar else None
        estado_inicial = estado(solicitacao)

        def persistir(evento, updates):
            anterior = estado(solicitacao)
            # Atualização restrita evita sinais genéricos duplicados; auditoria explícita na mesma transação.
            model.objects.filter(pk=pk).update(**updates)
            for field, value in updates.items():
                setattr(solicitacao, field, value)
            registrar_evento(solicitacao, user, evento, motivo, anterior, conjunto)

        if operacao == "cancelar":
            updates = dict(cancelada_em=timezone.now(), cancelada_por_id=user.pk, motivo_cancelamento=motivo)
            if not isinstance(solicitacao, AditivoContratoTerceiro):
                updates["status"] = "cancelada" if isinstance(solicitacao, SolicitacaoOrdemServico) else "Cancelada"
            persistir("cancelamento", updates)
        if operacao == "arquivar" or (operacao == "cancelar" and arquivar and not solicitacao.arquivada):
            persistir("arquivamento", dict(arquivada=True, arquivada_em=timezone.now(),
                                          arquivada_por_id=user.pk, motivo_arquivamento=motivo))
        if operacao == "desarquivar":
            persistir("desarquivamento", dict(arquivada=False, arquivada_em=None,
                                             arquivada_por_id=None, motivo_arquivamento=""))
        if conjunto:
            registrar_evento(solicitacao, user, "cancelamento_com_arquivamento", motivo,
                             estado_inicial, conjunto)
        return solicitacao, True


def preparar_controles(solicitacao, user):
    from django.urls import reverse
    solicitacao.tipo_arquivo = next(tipo for tipo, model in MODELOS.items() if isinstance(solicitacao, model))
    solicitacao.url_detalhes = reverse(DETALHES[solicitacao.tipo_arquivo], args=[solicitacao.pk])
    solicitacao.token_operacao = str(uuid4())
    solicitacao.pode_arquivar = (not solicitacao.arquivada and pode_operar(user, solicitacao, "arquivar")
                               and not erro_arquivamento(solicitacao))
    solicitacao.pode_desarquivar = solicitacao.arquivada and pode_operar(user, solicitacao, "desarquivar")
    solicitacao.pode_cancelar = (not solicitacao.cancelada and pode_operar(user, solicitacao, "cancelar")
                               and not erro_cancelamento(solicitacao))
    solicitacao.historico_arquivo = RegistroAuditoria.objects.filter(
        content_type=ContentType.objects.get_for_model(solicitacao), object_id=solicitacao.pk,
        detalhes__startswith="solicitacao:",
    ).select_related("usuario").order_by("-data_hora", "-pk")


def proteger_fluxo_solicitacao(model, key="pk"):
    """Protege URLs antigas de aprovação/edição e serializa com o cancelamento."""
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method in {"GET", "HEAD", "OPTIONS"}:
                return view(request, *args, **kwargs)
            from django.shortcuts import get_object_or_404
            obj = get_object_or_404(model, pk=kwargs.get(key, args[0] if args else None))
            if isinstance(obj, Evento) and obj.contrato_terceiro_id:
                # Após gerar contrato, os eventos seguem seu escopo contratual/financeiro próprio.
                return view(request, *args, **kwargs)
            if isinstance(obj, tuple(MODELOS.values())):
                solicitacao = obj
            elif isinstance(obj, Evento):
                solicitacao = obj.prospeccao or obj.solicitacao_contrato or obj.aditivo
            elif isinstance(obj, DocumentoBM):
                solicitacao = obj.solicitacao or obj.solicitacao_contrato
            else:
                solicitacao = None
            if solicitacao is None:
                return view(request, *args, **kwargs)
            with transacao_solicitacao(type(solicitacao), solicitacao.pk) as atual:
                acesso = can_view_object(request.user, obj) if isinstance(obj, Evento) else pode_consultar(request.user, atual)
                if not acesso:
                    from django.contrib import messages
                    from django.shortcuts import redirect
                    messages.error(request, "Você não tem permissão para esta solicitação.")
                    return redirect("home")
                if atual.cancelada or (atual.arquivada and model is not Evento):
                    from django.contrib import messages
                    from django.shortcuts import redirect
                    messages.error(request, "Solicitação cancelada: o fluxo está encerrado." if atual.cancelada
                                   else "Desarquive a solicitação antes de continuar seu fluxo.")
                    return redirect("lista_solicitacoes")
                return view(request, *args, **kwargs)
        return wrapped
    return decorate
