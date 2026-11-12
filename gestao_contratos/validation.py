"""Validações de domínio sem reescrever dados legados."""
from decimal import Decimal, InvalidOperation
from pathlib import Path
import zipfile

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class BusinessValidationMixin:
    def clean(self):
        super().clean()
        errors = {}
        for field in self._meta.fields:
            if not isinstance(field, models.DecimalField):
                continue
            value = getattr(self, field.name)
            if value is None:
                continue
            try:
                number = Decimal(value)
                if not number.is_finite() or (number < 0 and field.name != "novo_valor_total"):
                    errors[field.name] = "Informe um valor finito e não negativo."
            except (InvalidOperation, TypeError, ValueError):
                errors[field.name] = "Informe um valor monetário válido."
        for start, end in (("data_inicio", "data_fim"), ("prazo_inicio", "prazo_fim"),
                           ("data_inicial_medicao", "data_final_medicao")):
            first, last = getattr(self, start, None), getattr(self, end, None)
            if first and last and first > last:
                errors["__all__"] = "A data final não pode ser anterior à data inicial."
        if errors:
            raise ValidationError(errors)


def validate_upload(upload):
    # ModelForm revalida também o FieldFile já persistido. Apenas o arquivo
    # novo é entrada de upload; abrir o antigo deixa handles retidos no Windows.
    from django.db.models.fields.files import FieldFile
    if isinstance(upload,FieldFile) and upload._committed:
        return
    limit = getattr(settings, "MAX_UPLOAD_BYTES", 25 * 1024 * 1024)
    if upload.size > limit:
        raise ValidationError(f"O arquivo excede o limite de {limit // (1024 * 1024)} MB.")
    extension = Path(upload.name).suffix.lower()
    position = upload.tell()
    try:
        header = upload.read(8)
        if extension == ".pdf" and header.startswith(b"%PDF-"):
            return
        if extension == ".xls" and header == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            return
        if extension in {".xlsx", ".docx", ".docm"}:
            upload.seek(0)
            try:
                with zipfile.ZipFile(upload) as archive:
                    expected = "xl/workbook.xml" if extension == ".xlsx" else "word/document.xml"
                    if "[Content_Types].xml" in archive.namelist() and expected in archive.namelist():
                        return
            except (zipfile.BadZipFile, OSError):
                pass
        if extension == ".png" and header == b"\x89PNG\r\n\x1a\n":
            return
        if extension in {".jpg", ".jpeg"} and header.startswith(b"\xff\xd8\xff"):
            return
        raise ValidationError("Envie PDF, XLS, XLSX, DOCX, DOCM, PNG ou JPEG com conteúdo compatível.")
    finally:
        upload.seek(position)
