"""Escopo e filtros das quatro seções da listagem, antes da paginação."""
from django.db.models import Case, CharField, Q, Value, When

from .models import AditivoContratoTerceiro, SolicitacaoOrdemServico
from .permissions import GLOBAL_ROLES, is_internal


def com_etapa_aditivo(queryset):
    documento = Q(arquivo_aditivo__isnull=False) & ~Q(arquivo_aditivo="")
    assinado = Q(arquivo_aditivo_assinado__isnull=False) & ~Q(arquivo_aditivo_assinado="")
    return queryset.annotate(etapa_listagem=Case(
        When(cancelada_em__isnull=False, then=Value("Cancelada")),
        When(assinado, then=Value("Concluido")),
        When(documento & Q(status_lider="aprovado"), then=Value("Aguardando Documento Assinado")),
        When(documento & Q(status_lider="reprovado"), then=Value("Minuta Reprovada")),
        When(documento, then=Value("Aguardando Aprovacao da Minuta")),
        When(status_gerente="aprovado", status_diretoria="aprovado", then=Value("Aguardando Minuta do Aditivo")),
        When(Q(status_gerente="reprovado") | Q(status_diretoria="reprovado"), then=Value("Solicitacao Reprovada")),
        default=Value("Aguardando Aprovacao da Solicitacao"), output_field=CharField(),
    ))


def escopo_solicitacoes(user, model):
    if not is_internal(user):
        return model.objects.none()
    if model is AditivoContratoTerceiro:
        from .views import get_visible_addendums_for_user
        return com_etapa_aditivo(get_visible_addendums_for_user(user).select_related("arquivada_por"))
    queryset = model.objects.select_related("arquivada_por", "contrato")
    if model is not SolicitacaoOrdemServico:
        queryset = queryset.select_related("fornecedor_escolhido")
    if user.grupo in GLOBAL_ROLES:
        return queryset
    if model is SolicitacaoOrdemServico and user.grupo == "coordenador":
        return queryset.filter(solicitante=user)
    if model is SolicitacaoOrdemServico and user.grupo == "lider_contrato":
        return queryset.filter(lider_contrato=user)
    lookup = Q(lider_contrato=user)
    if user.grupo == "coordenador":
        lookup |= Q(coordenador=user)
    if user.grupo in {"gerente", "gerente_lider"}:
        lookup |= Q(coordenador__centros__in=user.centros.all())
    if model is SolicitacaoOrdemServico:
        if user.grupo == "gerente":
            lookup |= Q(solicitante=user)
        return queryset.filter(lookup).distinct()
    lookup |= Q(contrato__lider_contrato=user)
    if user.grupo == "coordenador":
        lookup |= Q(contrato__coordenador=user) | Q(contrato__coordenadores=user)
    if user.grupo in {"gerente", "gerente_lider"}:
        lookup |= Q(contrato__coordenador__centros__in=user.centros.all()) | Q(contrato__coordenadores__centros__in=user.centros.all())
    return queryset.filter(lookup).distinct()


def consulta_texto(model, text, *, responsavel=False):
    if model is AditivoContratoTerceiro:
        query = (Q(solicitado_por__username__icontains=text) | Q(solicitado_por__first_name__icontains=text) |
                 Q(solicitado_por__last_name__icontains=text))
        if responsavel:
            query |= (Q(contrato__lider_contrato__username__icontains=text) |
                      Q(contrato__lider_contrato__first_name__icontains=text) |
                      Q(contrato__lider_contrato__last_name__icontains=text) |
                      Q(contrato__coordenador__username__icontains=text) |
                      Q(contrato__coordenador__first_name__icontains=text) |
                      Q(contrato__coordenador__last_name__icontains=text) |
                      Q(contrato__guarda_chuva=True, contrato__cod_projeto__lider_contrato__username__icontains=text) |
                      Q(contrato__guarda_chuva=True, contrato__cod_projeto__lider_contrato__first_name__icontains=text) |
                      Q(contrato__guarda_chuva=True, contrato__cod_projeto__lider_contrato__last_name__icontains=text) |
                      Q(contrato__guarda_chuva=True, contrato__cod_projeto__coordenador__username__icontains=text))
        if not responsavel:
            query |= Q(motivo__icontains=text) | Q(contrato__num_contrato__icontains=text) | Q(contrato__empresa_terceira__nome__icontains=text)
    elif model is SolicitacaoOrdemServico:
        query = (Q(solicitante__username__icontains=text) | Q(solicitante__first_name__icontains=text) |
                 Q(solicitante__last_name__icontains=text))
        if not responsavel:
            query |= Q(titulo__icontains=text) | Q(descricao__icontains=text) | Q(contrato__empresa_terceira__nome__icontains=text) | Q(cod_projeto__cod_projeto__icontains=text)
    else:
        query = Q(solicitante__icontains=text)
        if not responsavel:
            query |= Q(descricao__icontains=text) | Q(fornecedor_escolhido__nome__icontains=text) | Q(contrato__cod_projeto__icontains=text)
    if responsavel and model is not AditivoContratoTerceiro:
        query |= (Q(lider_contrato__username__icontains=text) | Q(lider_contrato__first_name__icontains=text) |
                  Q(lider_contrato__last_name__icontains=text) | Q(coordenador__username__icontains=text) |
                  Q(coordenador__first_name__icontains=text) | Q(coordenador__last_name__icontains=text))
    if not responsavel and text.lstrip("#").isdigit():
        query |= Q(pk=int(text.lstrip("#")))
    return query


def filtrar_solicitacoes(queryset, *, visualizacao, busca="", status="", ordem="-data_solicitacao",
                         responsavel="", inicio=None, fim=None):
    model = queryset.model
    queryset = queryset.em_visualizacao(visualizacao)
    if busca:
        queryset = queryset.filter(consulta_texto(model, busca))
    if responsavel:
        queryset = queryset.filter(consulta_texto(model, responsavel, responsavel=True))
    status_field = "etapa_listagem" if model is AditivoContratoTerceiro else "status"
    if status:
        valor_status = "cancelada" if model is SolicitacaoOrdemServico and status in {"Cancelada", "cancelada"} else status
        queryset = queryset.filter(**{status_field: valor_status})
    data_field = "criado_em" if model in {AditivoContratoTerceiro, SolicitacaoOrdemServico} else "data_solicitacao"
    if inicio:
        queryset = queryset.filter(**{f"{data_field}__date__gte": inicio})
    if fim:
        queryset = queryset.filter(**{f"{data_field}__date__lte": fim})
    field = ordem.lstrip("-")
    field = data_field if field == "data_solicitacao" else status_field if field == "status" else field
    return queryset.order_by(("-" if ordem.startswith("-") else "") + field, "pk")
