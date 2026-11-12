"""Entrega uploads sem publicar MEDIA_ROOT como conteúdo estático."""
from pathlib import PurePosixPath

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.db.models import FileField, Q
from django.http import FileResponse, Http404

from .permissions import can_access_document


@login_required
def private_download(request, name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise Http404
    for model in apps.get_app_config("gestao_contratos").get_models():
        fields = [field for field in model._meta.fields if isinstance(field, FileField)]
        if not fields:
            continue
        query = Q()
        for field in fields:
            query |= Q(**{field.name: name})
        for obj in model.objects.filter(query):
            if not can_access_document(request.user, obj):
                continue
            field_file = next(getattr(obj, field.name) for field in fields
                              if getattr(obj, field.name).name == name)
            try:
                response = FileResponse(field_file.open("rb"), as_attachment=True, filename=path.name)
            except (FileNotFoundError, OSError, ValueError):
                raise Http404 from None
            response["X-Content-Type-Options"] = "nosniff"
            response["Cache-Control"] = "private, no-store"
            return response
    raise Http404
