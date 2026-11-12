"""Transações e projeção dos pagamentos registrados em notas fiscais."""
from decimal import Decimal
from datetime import timedelta
import hashlib
from functools import wraps

from django.db import transaction, IntegrityError,connection
from django.utils import timezone
from django.db.models import Sum, Max,F
from django.contrib.contenttypes.models import ContentType

from .models import NF, ChaveIdempotencia, RegistroAuditoria


def audit_nf_deletion(user, nf):
    # O trigger registra a exclusão na mesma transação; evita duas fontes.
    nf._audit_user = user


def claim_once(key, lifetime_seconds):
    """Unicidade compartilhada pelos workers e independente do cache local."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    now = timezone.now()
    try:
        with transaction.atomic():
            ChaveIdempotencia.objects.filter(expira_em__lte=now).delete()
            ChaveIdempotencia.objects.create(
                chave=digest, expira_em=now + timedelta(seconds=lifetime_seconds),
            )
    except IntegrityError:
        return False
    return True


def locked_action(model, key="pk",*,sqlite_immediate=False):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method != "POST":
                return view(request, *args, **kwargs)
            def begin(execute,sql,params,many,context):
                if sqlite_immediate and connection.vendor=='sqlite' and sql.strip().upper()=='BEGIN':sql='BEGIN IMMEDIATE'
                return execute(sql,params,many,context)
            with connection.execute_wrapper(begin),transaction.atomic():
                if sqlite_immediate and connection.vendor=='sqlite':
                    field=model._meta.pk.attname
                    model.objects.filter(pk=kwargs[key]).update(**{field:F(field)})
                # Em SQLite select_for_update não oferece lock de linha; as
                # constraints continuam sendo a defesa contra duplicação.
                model.objects.select_for_update().filter(pk=kwargs[key]).first()
                return view(request, *args, **kwargs)
        return wrapped
    return decorate


def lock_payment_origin(origin):
    if origin:
        type(origin).objects.select_for_update().get(pk=origin.pk)


def sync_paid_total(origin):
    if origin is None:
        return
    lookup = {"evento": origin} if origin._meta.model_name == "evento" else {"os": origin}
    from .models import PagamentoNF
    from .payment_queries import signed_cents,money,invoice_annotations
    moves=PagamentoNF.objects.filter(**{'nf__'+key:value for key,value in lookup.items()})
    origin.valor_pago=money(moves.aggregate(total=Sum(signed_cents(),default=0))['total'])
    from django.db.models import OuterRef,Subquery,BigIntegerField,F
    from django.db.models.functions import Coalesce
    reversed_moves=PagamentoNF.objects.filter(referencia_estorno_id=OuterRef('pk')).order_by().values('referencia_estorno_id').annotate(total=Sum('centavos')).values('total')
    originals=moves.filter(tipo='pagamento').annotate(reversed_cents=Coalesce(Subquery(reversed_moves,output_field=BigIntegerField()),0)).filter(centavos__gt=F('reversed_cents'))
    origin.data_pagamento=originals.aggregate(last=Max('data_pagamento'))['last'] if origin.valor_pago else None
    latest_paid = invoice_annotations(NF.objects.filter(**lookup)).filter(ledger_paid_cents__gt=0).order_by("-data_pagamento", "-pk").first()
    note_field = "justificativa" if origin._meta.model_name == "evento" else "observacao"
    setattr(origin, note_field, latest_paid.observacao if latest_paid else None)
    origin.save(update_fields=["valor_pago", "data_pagamento", note_field])
