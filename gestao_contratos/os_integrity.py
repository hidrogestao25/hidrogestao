"""Identidade financeira de OS: validação amigável e defesa no banco (0126)."""
from django.core.exceptions import ValidationError
from contextlib import contextmanager
from django.db import connections, transaction
from django.db.models import F


IDENTITY_FIELDS = ("contrato_id", "cod_projeto_id", "solicitacao_id")
IDENTITY_ERROR = (
    "Esta OS possui BM ou NF. Contrato, projeto e solicitação de origem não podem "
    "ser transferidos. Regularize o histórico por procedimento formal, sem mover pagamentos."
)


@contextmanager
def os_identity_transaction(order, using=None):
    alias = using or order._state.db or "default"
    connection = connections[alias]
    def immediate(execute, sql, params, many, context):
        if connection.vendor == "sqlite" and sql.strip().upper() == "BEGIN":
            sql = "BEGIN IMMEDIATE"
        return execute(sql, params, many, context)
    with connection.execute_wrapper(immediate), transaction.atomic(using=alias):
        if order.pk and not order._state.adding:
            from .models import OS
            if connection.vendor == "sqlite":
                OS.objects.using(alias).filter(pk=order.pk).update(id=F("id"))
            else:
                OS.objects.using(alias).select_for_update().get(pk=order.pk)
        yield


def validate_os_identity(order, *, using=None, update_fields=None):
    if not order.pk or order._state.adding:
        return
    fields = set(IDENTITY_FIELDS)
    if update_fields is not None:
        fields &= {name if name.endswith("_id") else name + "_id" for name in update_fields}
    if not fields:
        return
    from .models import BM, NF, OS
    alias = using or order._state.db or "default"
    previous = OS.objects.using(alias).filter(pk=order.pk).values(*fields).first()
    changed = [name for name in fields if previous and previous[name] != getattr(order, name)]
    if changed and (BM.objects.using(alias).filter(os_id=order.pk).exists()
                    or NF.objects.using(alias).filter(os_id=order.pk).exists()):
        raise ValidationError({name.removesuffix("_id"): IDENTITY_ERROR for name in changed})
