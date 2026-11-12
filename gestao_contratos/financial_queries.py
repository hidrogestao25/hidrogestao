"""Consultas de acompanhamento: não grava, aprova, liquida ou deduplica documentos.

Os indicadores agregam cada tabela separadamente. Filas BM são disjuntas entre
si; filas NF também. A atenção reúne tipos distintos, nunca uma soma financeira.
"""
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import Q, F, Case, When, Value, IntegerField, BooleanField, Exists, OuterRef, Count, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.urls import reverse

from . import models as m
from . import payment_queries as pq
from .permissions import GLOBAL_ROLES, is_internal, can_change_nf, can_view_object, can_access_document, bm_has_valid_operational_approval


QUEUE_DEFINITIONS = (
    ("aprovacao", "A", "Boletins Pendentes de Aprovação", "Acompanhamento operacional e da Diretoria.", "bm"),
    ("sem_nf", "B", "BMs autorizados sem NF", "Participações liberadas que ainda não possuem NF vinculada.", "bm"),
    ("autorizacao", "C", "NFs aguardando autorização", "Documento recebido; pagamento ainda não liberado.", "nf"),
    ("pagamento", "D", "NFs aguardando pagamento", "Autorização válida; pagamento ainda não registrado.", "nf"),
    ("pagos", "E", "Pagamentos registrados", "NFs pagas. Casos que exigem revisão aparecem na fila F.", "nf"),
    ("atencao", "F", "Registros que exigem atenção", "Revisar o contexto e o histórico, sem correção automática.", "nf"),
)


def can_view_financial_panel(user):
    return is_internal(user) and user.grupo in GLOBAL_ROLES


def can_view_exclusive_financial_panel(user):
    """Página do Financeiro; não altera a leitura global das demais rotas."""
    return is_internal(user) and user.grupo == "financeiro"


def operational_query(prefix=""):
    return (Q(**{prefix + "status_coordenador": "aprovado"}) | Q(**{prefix + "status_gerente": "aprovado"})) & ~(
        Q(**{prefix + "status_coordenador": "reprovado"}) | Q(**{prefix + "status_gerente": "reprovado"}))


def authorized_query(prefix=""):
    return operational_query(prefix) & Q(**{prefix + "aprovacao_pagamento": "aprovado"})


def rejected_query(prefix=""):
    return (Q(**{prefix + "status_coordenador": "reprovado"}) | Q(**{prefix + "status_gerente": "reprovado"})
            | Q(**{prefix + "aprovacao_pagamento": "reprovado"}))


def bm_origin_query(prefix=""):
    return (Q(**{prefix + "evento__isnull": False, prefix + "os__isnull": True,
                 prefix + "evento__contrato_terceiro__isnull": False})
            | Q(**{prefix + "evento__isnull": True, prefix + "os__isnull": False,
                    prefix + "os__contrato_id": F(prefix + "contrato_id")}))


def nf_origin_query():
    return (Q(bm__isnull=False, evento__isnull=False, os__isnull=True, bm__os__isnull=True,
              bm__evento_id=F("evento_id"), evento__contrato_terceiro_id=F("contrato_id"))
            | Q(bm__isnull=False, evento__isnull=True, os__isnull=False, bm__evento__isnull=True,
                bm__os_id=F("os_id"), os__contrato_id=F("contrato_id"), bm__contrato_id=F("contrato_id")))


def financial_bms():
    # Evento é dono da participação, mesmo com vínculo documental cruzado.
    return m.BM.objects.annotate(
        finance_contract_id=Case(When(evento__isnull=False, then=F("evento__contrato_terceiro_id")),
            When(os__isnull=False, then=F("os__contrato_id")), default=F("contrato_id"), output_field=IntegerField()),
        finance_supplier_id=Case(When(evento__isnull=False, then=F("evento__contrato_terceiro__empresa_terceira_id")),
            When(os__isnull=False, then=F("os__contrato__empresa_terceira_id")), default=F("contrato__empresa_terceira_id"), output_field=IntegerField()),
        finance_project_id=Case(When(os__isnull=False, then=F("os__cod_projeto_id")),
            When(evento__isnull=False, then=F("evento__contrato_terceiro__cod_projeto_id")),
            default=F("contrato__cod_projeto_id"), output_field=IntegerField()),
        has_nf=Exists(m.NF.objects.filter(bm_id=OuterRef("pk"),cancelada_em__isnull=True)),
        has_paid_nf=Exists(pq.invoice_annotations(m.NF.objects.filter(bm_id=OuterRef('pk'))).filter(ledger_paid_cents__gt=0)),
        has_unpaid_nf=Exists(pq.invoice_annotations(m.NF.objects.filter(bm_id=OuterRef('pk'))).filter(ledger_balance_cents__gt=0)),
        origin_valid=Case(When(bm_origin_query(), then=Value(True)), default=Value(False), output_field=BooleanField()),
    )


def financial_nfs():
    return pq.invoice_annotations(m.NF.objects.annotate(
        finance_contract_id=F("contrato_id"), finance_supplier_id=F("contrato__empresa_terceira_id"),
        finance_project_id=Case(When(os__isnull=False, then=F("os__cod_projeto_id")),
            default=F("contrato__cod_projeto_id"), output_field=IntegerField()),
        origin_valid=Case(When(nf_origin_query(), then=Value(True)), default=Value(False), output_field=BooleanField()),
    ))


def bm_attention_query():
    return (Q(origin_valid=False) | rejected_query() | Q(os__status="cancelada")
            | (Q(aprovacao_pagamento="aprovado") & ~operational_query()))


def nf_attention_query():
    return (Q(origin_valid=False) | rejected_query("bm__") | Q(os__status="cancelada") | Q(cancelada_em__isnull=False)
            | (Q(bm__aprovacao_pagamento="aprovado") & ~operational_query("bm__"))
            | (Q(ledger_paid_cents__gt=0) & ~authorized_query("bm__"))
            | Q(ledger_balance_cents__gt=0,ledger_scheduled_cents__gt=F('ledger_balance_cents')))


def bm_home_stages():
    valid = ~bm_attention_query()
    return {
        "autorizados": valid & authorized_query(),
        "diretoria": valid & operational_query() & Q(aprovacao_pagamento="pendente"),
        "operacional": valid & ~operational_query(),
    }


def contract_coordinator_query(coordinator):
    return (Q(coordenador=coordinator) | Q(coordenadores=coordinator)
            | Q(cod_projeto__coordenador=coordinator) | Q(cod_projeto__coordenadores=coordinator))


def leader_assignment_query(leader):
    return Q(lider_contrato=leader) | Q(cod_projeto__lider_contrato=leader)


def technical_center_query(center):
    return (Q(coordenador__centros=center)|Q(coordenadores__centros=center)
        |Q(cod_projeto__coordenador__centros=center)|Q(cod_projeto__coordenadores__centros=center))


def financial_filter_choices(*, coordinator=None, leader=None, supplier=None, project=None):
    """Cascata responsável → fornecedor → projeto → contrato, por vínculos.

    Inclui contratos ainda sem BM/NF e projetos próprios da OS, seguindo o
    mesmo escopo de liderança/coordenação das consultas financeiras.
    """
    contracts = m.ContratoTerceiros.objects.all()
    orders = m.OS.objects.all()
    if coordinator is not None:
        coordinated = m.ContratoTerceiros.objects.filter(contract_coordinator_query(coordinator))
        contracts = contracts.filter(pk__in=coordinated.values('pk'))
        orders = orders.filter(Q(contrato_id__in=coordinated.values('pk')) | Q(coordenador_id=coordinator))
    if leader is not None:
        led_contracts = m.ContratoTerceiros.objects.filter(leader_assignment_query(leader))
        contracts = contracts.filter(pk__in=led_contracts.values('pk'))
        orders = orders.filter(Q(contrato_id__in=led_contracts.values('pk')) | leader_assignment_query(leader))
    suppliers = m.EmpresaTerceira.objects.order_by('nome', 'pk')
    if coordinator is not None or leader is not None:
        suppliers = suppliers.filter(Q(pk__in=contracts.values('empresa_terceira_id'))
            | Q(pk__in=orders.values('contrato__empresa_terceira_id')))
    if supplier is not None:
        contracts = contracts.filter(empresa_terceira_id=supplier)
        orders = orders.filter(contrato__empresa_terceira_id=supplier)
    projects = m.Contrato.objects.select_related('cliente').order_by('cod_projeto', 'pk')
    if coordinator is not None or leader is not None or supplier is not None:
        projects = projects.filter(Q(pk__in=contracts.values('cod_projeto_id')) | Q(pk__in=orders.values('cod_projeto_id')))
    if project is not None:
        contracts = contracts.filter(cod_projeto_id=project)
        orders = orders.filter(cod_projeto_id=project)
    matching_contracts = m.ContratoTerceiros.objects.filter(
        Q(pk__in=contracts.values('pk')) | Q(pk__in=orders.values('contrato_id'))
    ).select_related('empresa_terceira').order_by('num_contrato', 'pk')
    return {'fornecedor': suppliers, 'projeto': projects, 'contrato': matching_contracts}


def apply_structural_filters(queryset, filters, *, kind):
    if filters.get('centro'):
        contracts=m.ContratoTerceiros.objects.filter(pk=OuterRef('finance_contract_id')).filter(technical_center_query(filters['centro']))
        orders=m.OS.objects.filter(pk=OuterRef('os_id'),coordenador__centros=filters['centro'])
        queryset=queryset.filter(Exists(contracts)|Exists(orders))
    for name, annotation in (("fornecedor", "finance_supplier_id"), ("contrato", "finance_contract_id"), ("projeto", "finance_project_id")):
        if filters.get(name):
            queryset = queryset.filter(**{annotation: filters[name].pk})
    if filters.get("origem"):
        queryset = queryset.filter(**{filters["origem"] + "__isnull": False})
    if filters.get("referencia"):
        ref = filters["referencia"]
        queryset = queryset.filter(Q(evento_id=ref) | Q(os_id=ref))
    prefix = "bm__" if kind == "nf" else ""
    if filters.get("numero_bm"):
        queryset = queryset.filter(**{prefix + "numero_bm": filters["numero_bm"]})
    if filters.get("bm_id"):
        queryset = queryset.filter(**{("bm_id" if kind == "nf" else "pk"): filters["bm_id"]})
    status = filters.get("autorizacao")
    if status == "operacional":
        queryset = queryset.filter(**{prefix + "status_coordenador": "pendente", prefix + "status_gerente": "pendente"})
    elif status == "diretoria":
        queryset = queryset.filter(operational_query(prefix), **{prefix + "aprovacao_pagamento": "pendente"})
    elif status == "autorizado":
        queryset = queryset.filter(authorized_query(prefix))
    elif status == "reprovado":
        queryset = queryset.filter(rejected_query(prefix))
    if filters.get("pagamento"):
        paid = filters["pagamento"] == "pago"
        if kind == "nf":
            queryset = queryset.filter(ledger_paid_cents__gt=0) if paid else queryset.filter(ledger_balance_cents__gt=0)
        elif paid:
            queryset = queryset.filter(has_paid_nf=True)
        else:
            queryset = queryset.filter(Q(has_unpaid_nf=True) | Q(has_nf=False))
    if filters.get("coordenador"):
        coord = filters["coordenador"]
        # EXISTS evita multiplicar participações por coordenadores M2M.
        contracts = m.ContratoTerceiros.objects.filter(pk=OuterRef("finance_contract_id")).filter(contract_coordinator_query(coord))
        queryset = queryset.filter(Exists(contracts) | Q(os__coordenador=coord))
    if filters.get('lider_contrato'):
        leader = filters['lider_contrato']
        contracts = m.ContratoTerceiros.objects.filter(pk=OuterRef('finance_contract_id')).filter(leader_assignment_query(leader))
        queryset = queryset.filter(Exists(contracts) | Q(os__lider_contrato=leader) | Q(os__cod_projeto__lider_contrato=leader))
    return queryset


def in_period(queryset, filters, field):
    if filters.get("historico"):
        return queryset
    return queryset.filter(**{field + "__range": [filters["data_inicial"], filters["data_limite"]]})


class FinancialData:
    def __init__(self, user, filters):
        if not can_view_financial_panel(user):
            raise PermissionDenied
        self.filters = filters
        self.bms_scope = apply_structural_filters(financial_bms(), filters, kind="bm")
        self.nfs_scope = apply_structural_filters(financial_nfs(), filters, kind="nf")
        self.bms = in_period(self.bms_scope, filters, "data_pagamento")
        self.nfs = in_period(self.nfs_scope, filters, "data_pagamento")
        self.payments=in_period(m.PagamentoNF.objects.filter(nf_id__in=self.nfs_scope.values('pk')),filters,'data_pagamento')
        bm_attention, nf_attention = bm_attention_query(), nf_attention_query()
        self.queries = {
            "aprovacao": self.bms.filter(~bm_attention & ~authorized_query()),
            "sem_nf": self.bms.filter(~bm_attention & authorized_query(), has_nf=False),
            "autorizacao": self.nfs.filter(~nf_attention & ~authorized_query("bm__"), ledger_balance_cents__gt=0),
            "pagamento": self.nfs.filter(~nf_attention & authorized_query("bm__"), ledger_balance_cents__gt=0),
            "pagos": self.nfs_scope.filter(~nf_attention,ledger_paid_cents__gt=0,pk__in=self.payments.values('nf_id')),
            "atencao_bm": self.bms.filter(bm_attention),
            "atencao_nf": self.nfs.filter(nf_attention),
        }
        self.queries.update({key: self.bms.filter(condition) for key, condition in bm_home_stages().items()})

    def home_counts(self):
        """Contagens de participações/lançamentos, sem somas ou planejamento."""
        counts = self.bms.aggregate(
            **{key: Count("pk", filter=condition) for key, condition in bm_home_stages().items()},
            sem_nf=Count("pk", filter=~bm_attention_query() & authorized_query() & Q(has_nf=False)),
            atencao_bm=Count("pk", filter=bm_attention_query()),
        )
        counts.update(self.nfs.aggregate(
            pagamento=Count("pk", filter=~nf_attention_query() & authorized_query("bm__") & Q(ledger_balance_cents__gt=0)),
            atencao_nf=Count("pk", filter=nf_attention_query()),
        ))
        counts["atencao"] = counts["atencao_bm"] + counts["atencao_nf"]
        return counts

    def indicators(self, *, by_contract=False):
        bm_expressions = dict(
            medido=Sum("valor_pago", default=Decimal("0")),
            autorizado=Sum("valor_pago", filter=authorized_query() & ~bm_attention_query(), default=Decimal("0")),
            operacional=Sum("valor_pago", filter=operational_query(), default=Decimal("0")),
            aprovacao_count=Count("pk", filter=~bm_attention_query() & ~authorized_query()),
            sem_nf_count=Count("pk", filter=~bm_attention_query() & authorized_query() & Q(has_nf=False)),
            atencao_bm_count=Count("pk", filter=bm_attention_query()),
        )
        nf_expressions = dict(
            faturado=Sum("valor_pago",filter=Q(cancelada_em__isnull=True),default=Decimal("0")),
            nao_autorizado_centavos=Sum("ledger_balance_cents",filter=~nf_attention_query() & ~authorized_query("bm__") & Q(ledger_balance_cents__gt=0),default=0),
            a_pagar_centavos=Sum("ledger_balance_cents",filter=~nf_attention_query() & authorized_query("bm__") & Q(ledger_balance_cents__gt=0),default=0),
            em_revisao_centavos=Sum("ledger_balance_cents",filter=nf_attention_query() & Q(ledger_balance_cents__gt=0),default=0),
            autorizacao_count=Count("pk", filter=~nf_attention_query() & ~authorized_query("bm__") & Q(ledger_balance_cents__gt=0)),
            pagamento_count=Count("pk", filter=~nf_attention_query() & authorized_query("bm__") & Q(ledger_balance_cents__gt=0)),
            pagos_count=Count("pk", filter=~nf_attention_query() & Q(ledger_paid_cents__gt=0)),
            atencao_nf_count=Count("pk", filter=nf_attention_query()),
        )
        if by_contract:
            from collections import defaultdict
            def empty():
                return {key:0 if key.endswith('_count') else Decimal('0') for key in (*bm_expressions,*nf_expressions,'previsto','pago','saldo_pendente','pago_acumulado')}
            grouped=defaultdict(empty)
            for qs,expressions in ((self.bms,bm_expressions),(self.nfs,nf_expressions)):
                for row in qs.order_by().values('finance_contract_id').annotate(**expressions):
                    key=row.pop('finance_contract_id');grouped[key].update(row)
            for qs,value_field in self.planned_origins():
                path='contrato_terceiro_id' if qs.model is m.Evento else 'contrato_id'
                for row in qs.order_by().values(path).annotate(total=Sum(value_field,default=Decimal('0'))):
                    grouped[row[path]]['previsto']+=row['total']
            for row in self.payments.order_by().values('nf__contrato_id').annotate(total=Sum(pq.signed_cents(),default=0)):
                grouped[row['nf__contrato_id']]['pago']=pq.money(row['total'])
            for row in self.nfs_scope.order_by().values('finance_contract_id').annotate(balance=Sum('ledger_balance_cents',default=0),paid=Sum('ledger_paid_cents',default=0)):
                grouped[row['finance_contract_id']].update(saldo_pendente=pq.money(row['balance']),pago_acumulado=pq.money(row['paid']))
            for values in grouped.values():
                for name in ('nao_autorizado','a_pagar','em_revisao'):values[name]=pq.money(values.pop(name+'_centavos',0))
            return grouped
        b=self.bms.aggregate(**bm_expressions)
        n=self.nfs.aggregate(**nf_expressions)
        n['pago']=pq.money(self.payments.aggregate(total=Sum(pq.signed_cents(),default=0))['total'])
        current=self.nfs_scope.aggregate(balance=Sum('ledger_balance_cents',default=0),paid=Sum('ledger_paid_cents',default=0))
        n.update(saldo_pendente=pq.money(current['balance']),pago_acumulado=pq.money(current['paid']))
        for name in ('nao_autorizado','a_pagar','em_revisao'):n[name]=pq.money(n.pop(name+'_centavos',0))
        b.update(n)
        b["atencao_count"] = b["atencao_bm_count"] + b["atencao_nf_count"]
        b["previsto"] = self.planned_total()
        return b

    def planned_total(self):
        return sum((qs.aggregate(value=Sum(field,default=Decimal('0')))['value'] for qs,field in self.planned_origins()),Decimal('0'))

    def planned_origins(self, *, use_period=True):
        """Mesma seleção de planejamento para indicadores e série mensal."""
        for model, kind, contract_path, value_field in ((m.Evento, "evento", "contrato_terceiro", "valor_previsto"), (m.OS, "os", "contrato", "valor")):
            if self.filters.get("origem") and self.filters["origem"] != kind:
                continue
            qs = model.objects.all()
            if kind == "evento":
                qs = qs.filter(contrato_terceiro__isnull=False)
            for name, path in (("fornecedor", contract_path + "__empresa_terceira"), ("contrato", contract_path),
                               ("projeto", "cod_projeto" if kind == "os" else contract_path + "__cod_projeto")):
                if self.filters.get(name): qs = qs.filter(**{path: self.filters[name]})
            if self.filters.get("referencia"): qs = qs.filter(pk=self.filters["referencia"])
            if self.filters.get("coordenador"):
                coord = self.filters["coordenador"]
                contracts = m.ContratoTerceiros.objects.filter(pk=OuterRef(contract_path + "_id")).filter(contract_coordinator_query(coord))
                qs = qs.filter(Exists(contracts) | (Q(coordenador=coord) if kind == "os" else Q(pk__in=[])))
            if self.filters.get('lider_contrato'):
                leader = self.filters['lider_contrato']
                contracts = m.ContratoTerceiros.objects.filter(pk=OuterRef(contract_path + '_id')).filter(leader_assignment_query(leader))
                qs = qs.filter(Exists(contracts) | (leader_assignment_query(leader) if kind == 'os' else Q(pk__in=[])))
            if self.filters.get('centro'):
                center=self.filters['centro']
                contracts=m.ContratoTerceiros.objects.filter(pk=OuterRef(contract_path+'_id')).filter(technical_center_query(center))
                own=m.OS.objects.filter(pk=OuterRef('pk'),coordenador__centros=center)
                qs=qs.filter(Exists(contracts)|(Exists(own) if kind=='os' else Q(pk__in=[])))
            if any(self.filters.get(x) for x in ("numero_bm", "bm_id", "autorizacao", "pagamento")):
                qs = qs.filter(Exists(self.bms_scope.filter(**{kind + "_id": OuterRef("pk")})))
            if use_period: qs = in_period(qs, self.filters, "data_prevista_pagamento")
            yield qs,value_field


def eager_bms(queryset):
    return queryset.select_related("contrato__empresa_terceira", "contrato__cod_projeto",
        "evento__contrato_terceiro__empresa_terceira", "evento__contrato_terceiro__cod_projeto",
        "os__contrato__empresa_terceira", "os__cod_projeto")


def eager_nfs(queryset):
    if 'ledger_paid_cents' not in queryset.query.annotations:queryset=pq.invoice_annotations(queryset)
    return queryset.select_related("contrato__empresa_terceira", "contrato__cod_projeto", "evento", "os__cod_projeto", "os__contrato",
        "bm__evento__contrato_terceiro", "bm__os__contrato", "bm__contrato")


def with_return(url, next_url):
    return url + ("&" if "?" in url else "?") + urlencode({"next": next_url}) if next_url else url


def bm_review_reasons(bm):
    reasons = []
    if not ((bm.evento_id and not bm.os_id and bm.evento.contrato_terceiro_id)
            or (bm.os_id and not bm.evento_id and bm.os.contrato_id == bm.contrato_id)):
        reasons.append("Conferir origem financeira do BM")
    if "reprovado" in (bm.status_coordenador, bm.status_gerente, bm.aprovacao_pagamento):
        reasons.append("BM com reprovação registrada")
    if bm.os_id and bm.os.status == "cancelada": reasons.append("OS cancelada com medição registrada")
    if bm.aprovacao_pagamento == "aprovado" and not bm_has_valid_operational_approval(bm):
        reasons.append("Autorização da Diretoria sem aprovação operacional válida no estado atual")
    return reasons


def nf_review_reasons(nf):
    reasons = []
    bm = nf.bm
    if not bm:
        reasons.append("Registro legado sem BM: vínculo requer revisão")
    elif (bm.evento_id != nf.evento_id or bm.os_id != nf.os_id or not bm.contrato_financeiro
          or bm.contrato_financeiro.pk != nf.contrato_id or bool(nf.evento_id) == bool(nf.os_id)
          or (nf.evento_id and nf.evento.contrato_terceiro_id != nf.contrato_id)
          or (nf.os_id and nf.os.contrato_id != nf.contrato_id)):
        reasons.append("Conferir vínculo da NF com a participação financeira")
    if bm:
        reasons.extend(bm_review_reasons(bm))
        if nf.total_pago>0 and not (bm_has_valid_operational_approval(bm) and bm.aprovacao_pagamento == "aprovado"):
            reasons.append("Pagamento registrado; autorização atual do BM requer revisão do histórico")
    if nf.os_id and nf.os.status == "cancelada": reasons.append("OS cancelada com NF registrada; preservar histórico")
    if nf.cancelada_em:reasons.append('NF cancelada logicamente; movimentos e histórico preservados.')
    return list(dict.fromkeys(reasons))


def context_links(user, contract, origin):
    return {
        "contract": contract, "supplier": contract.empresa_terceira if contract else None,
        "project": (origin.cod_projeto if isinstance(origin, m.OS) else contract.cod_projeto if contract else None),
        "contract_url": reverse("contrato_fornecedor_detalhe", args=[contract.pk]) if contract else "",
        "supplier_url": reverse("fornecedor_detalhe", args=[contract.empresa_terceira_id]) if contract else "",
        "origin": origin,
        "origin_label": f"{'Evento' if isinstance(origin, m.Evento) else 'OS'} #{origin.pk}" if origin else "Origem não informada",
        "origin_url": reverse("detalhes_entrega" if isinstance(origin, m.Evento) else "detalhes_os", args=[origin.pk]) if origin else "",
    }


def bm_row(bm, user, next_url=""):
    origin = bm.evento or bm.os
    contract = bm.contrato_financeiro
    row = context_links(user, contract, origin)
    op = bm_has_valid_operational_approval(bm)
    row.update(kind="bm", record=bm, id=bm.pk, number=bm.numero_bm, value=bm.valor_pago, date=bm.data_pagamento,
        operational="Aprovado" if op else "Reprovado" if "reprovado" in (bm.status_coordenador, bm.status_gerente) else "Pendente",
        director=bm.get_aprovacao_pagamento_display(), authorized=op and bm.aprovacao_pagamento == "aprovado",
        detail_url=with_return(reverse("detalhe_bm_financeiro", args=[bm.pk]), next_url),
        document_url=bm.arquivo_bm.url if bm.arquivo_bm else "", reasons=bm_review_reasons(bm),
        can_edit=user.grupo in {"financeiro", "suprimento"},
        edit_url=reverse("editar_bm", args=[bm.pk]),
        nf_create_url=(reverse("cadastrar_nf" if bm.evento_id else "cadastrar_nf_os", args=[origin.pk]) + "?" + urlencode({"bm": bm.pk})) if origin and contract else "")
    return row


def nf_rows(nfs, user, next_url=""):
    nfs = list(nfs)
    # Só uma transição explícita não-pago -> pago identifica confiavelmente o ator.
    ids = [nf.pk for nf in nfs if nf.total_pago>0]
    actors = {}
    if ids:
        ct = ContentType.objects.get_for_model(m.NF)
        audits = m.RegistroAuditoria.objects.filter(content_type=ct, object_id__in=ids).filter(
            Q(operacao_financeira__in=['pagamento','liquidacao']) | Q(operacao_financeira='criacao',estado_posterior__financeiro_autorizou=1)
            | Q(operacao_financeira__isnull=True,detalhes__contains="paga anteriormente: não; pagamento realizado após edição: sim.")
        ).select_related("usuario").order_by("-data_hora", "-pk")
        for audit in audits:
            actors.setdefault(audit.object_id, audit.autor_nome or ((audit.usuario.get_full_name() or audit.usuario.username) if audit.usuario else None))
    result = []
    visible_bms = {}
    for nf in nfs:
        row = context_links(user, nf.contrato, nf.evento or nf.os)
        reasons = nf_review_reasons(nf)
        ready = bool(nf.bm and not reasons and bm_has_valid_operational_approval(nf.bm) and nf.bm.aprovacao_pagamento == "aprovado")
        if getattr(nf,'ledger_scheduled_cents',0)>getattr(nf,'ledger_balance_cents',0) and nf.saldo_pendente>0:
            reasons.append('Programação superior ao saldo: exige conferência de pagamentos sem vínculo.')
        actor = actors.get(nf.pk)
        if nf.bm_id not in visible_bms:
            visible_bms[nf.bm_id] = bool(nf.bm_id and can_view_object(user, nf.bm) and can_access_document(user, nf.bm))
        visible_bm = visible_bms[nf.bm_id]
        row.update(kind="nf", record=nf, id=nf.pk, number=nf.bm.numero_bm if visible_bm else "—", value=nf.valor_pago,
            paid_value=nf.total_pago,balance=nf.saldo_pendente,liquidation=nf.situacao_liquidacao,
            date=nf.data_pagamento, paid=nf.total_pago>0, authorized=ready, reasons=reasons,
            status='Cancelada' if nf.cancelada_em else nf.situacao_liquidacao if nf.total_pago>0 else "Revisar contexto" if reasons else "Liberada para pagamento" if ready else "Aguardando autorização",
            detail_url=with_return(reverse("detalhe_nf", args=[nf.pk]), next_url),
            bm_url=reverse("detalhe_bm_financeiro", args=[nf.bm_id]) if visible_bm else "",
            edit_url=reverse("editar_nf", args=[nf.pk]), delete_url=reverse("deletar_nf", args=[nf.pk]),
            can_edit=can_change_nf(user, nf), can_pay=user.grupo in {'financeiro','suprimento'} and nf.saldo_pendente>0 and ready and not nf.cancelada_em,
            can_delete=can_change_nf(user,nf) and not nf.cancelada_em and (user.grupo=='suprimento' or not nf.possui_historico_financeiro),
            payment_url=reverse('pagamento_nf',args=[nf.pk]),
            document_url=nf.arquivo_nf.url if nf.arquivo_nf else "",
            receipt_url=(m.PagamentoNF._meta.get_field('comprovante').storage.url(nf.ledger_last_receipt) if getattr(nf,'ledger_last_receipt',None) else nf.comprovante_pagamento.url if nf.comprovante_pagamento else ''),
            payment_actor=actor or "Responsável não identificado no histórico disponível.")
        result.append(row)
    return result


def monthly_paid_series(nfs,first=None,last=None):
    moves=m.PagamentoNF.objects.filter(nf_id__in=nfs.values('pk'))
    if first and last:moves=moves.filter(data_pagamento__range=[first,last])
    rows=list(moves.annotate(month=TruncMonth('data_pagamento')).values('month').annotate(total_centavos=Sum(pq.signed_cents())).order_by('month'))
    return [dict(month=row['month'],total=pq.money(row['total_centavos'])) for row in rows]
