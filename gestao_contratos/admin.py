from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import (
    User, Cliente, EmpresaTerceira, Proposta, Contrato, PropostaFornecedor,
    SolicitacaoContratacaoTerceiro, ContratoTerceiros, EntregaFornecedor,
    AvaliacaoFornecedor, Indicadores, ContratoTimeline, ContratoTimelineTerceiro,
    Aditivo, AditivoTerceiro, BM, DocumentoContrato, DocumentoContratoTerceiro,
    SolicitacaoProspeccao, CentroDeTrabalho, DocumentoBM
)


# ==============================
# USER CUSTOMIZADO
# ==============================
class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")


class CustomUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = (
            "username", "email", "first_name", "last_name",
            "is_active", "is_staff", "is_superuser", "grupo", "centros"
        )


class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = User

    list_display = ("username", "email", "grupo", "get_centros", "is_staff", "is_active")
    list_filter = ("grupo", "centros", "is_staff", "is_active")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Informações pessoais", {"fields": ("first_name", "last_name", "email", "grupo", "centros")}),
        ("Permissões", {"fields": ("is_staff", "is_active", "is_superuser", "groups", "user_permissions")}),
        ("Datas importantes", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "username", "email", "password1", "password2",
                "grupo", "centros", "is_staff", "is_active"
            )}
        ),
    )

    search_fields = ("username", "email")
    ordering = ("username",)

    def get_centros(self, obj):
        return ", ".join([c.nome for c in obj.centros.all()])
    get_centros.short_description = "Centros"

# ==============================
# ADMIN PADRÃO
# ==============================
class DefaultAdmin(admin.ModelAdmin):
    ordering = ("id",)

    def get_list_display(self, request):
        """
        Lista colunas automaticamente:
        - id
        - nome / titulo / codigo (se existirem)
        - campos de auditoria (created_at / updated_at / data_criacao / data_atualizacao)
        - __str__
        """
        fields = []

        if hasattr(self.model, "id"):
            fields.append("id")

        for col in ["nome", "titulo", "codigo"]:
            if hasattr(self.model, col):
                fields.append(col)

        for extra in ["created_at", "updated_at", "data_criacao", "data_atualizacao"]:
            if hasattr(self.model, extra):
                fields.append(extra)

        fields.append("__str__")
        return fields


# ==============================
# REGISTROS
# ==============================
admin.site.register(User, CustomUserAdmin)

MODELOS_PADRAO = [
    Cliente, EmpresaTerceira, Proposta, Contrato, PropostaFornecedor,
    SolicitacaoContratacaoTerceiro, ContratoTerceiros, EntregaFornecedor,
    AvaliacaoFornecedor, Indicadores, ContratoTimeline, ContratoTimelineTerceiro,
    Aditivo, AditivoTerceiro, BM, DocumentoContrato, DocumentoContratoTerceiro,
    SolicitacaoProspeccao, CentroDeTrabalho, DocumentoBM
]

for modelo in MODELOS_PADRAO:
    admin.site.register(modelo, DefaultAdmin)
