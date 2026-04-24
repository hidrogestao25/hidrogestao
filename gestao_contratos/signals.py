from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver

from .middleware import get_current_request, get_current_user
from .models import RegistroAuditoria


@receiver(post_save)
def registrar_auditoria_post_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return

    if sender._meta.app_label != "gestao_contratos":
        return

    if sender is RegistroAuditoria or sender.__name__ == "User":
        return

    user = get_current_user()
    request = get_current_request()

    if request is None:
        return

    detalhes = None
    if request is not None:
        detalhes = f"{request.method} {request.path}"

    RegistroAuditoria.objects.create(
        content_type=ContentType.objects.get_for_model(sender),
        object_id=instance.pk,
        acao="criado" if created else "atualizado",
        usuario=user if getattr(user, "is_authenticated", False) else None,
        modelo=sender._meta.verbose_name.title(),
        representacao_objeto=str(instance)[:255],
        detalhes=detalhes,
    )
