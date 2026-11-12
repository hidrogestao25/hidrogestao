from threading import local

from django.core.exceptions import ValidationError
from django.http import HttpResponseBadRequest
from django.utils.html import escape

from .validation import validate_upload


_audit_local = local()


def get_current_user():
    return getattr(_audit_local, "user", None)


def get_current_request():
    return getattr(_audit_local, "request", None)


class AuditoriaUsuarioMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _audit_local.user = getattr(request, "user", None)
        _audit_local.request = request
        try:
            return self.get_response(request)
        finally:
            _audit_local.user = None
            _audit_local.request = None


class UploadValidationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST":
            try:
                for uploads in request.FILES.lists():
                    for upload in uploads[1]:
                        validate_upload(upload)
            except ValidationError as exc:
                return HttpResponseBadRequest(escape(" ".join(exc.messages)))
        return self.get_response(request)
