from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.db import models

from .models import (
    User, Cliente, EmpresaTerceira, Proposta, Contrato, PropostaFornecedor,
    ContratoTerceiros, Evento,
    AvaliacaoFornecedor, Indicadores, NFCliente,
    BM, DocumentoContrato, DocumentoContratoTerceiro,
    SolicitacaoProspeccao, CentroDeTrabalho, DocumentoBM, CalendarioPagamento, NF,
    SolicitacaoOrdemServico, OS, SolicitacaoContrato, RegistroAuditoria, AditivoContratoTerceiro,
    ConfiguracaoSLA, Feriado,
)


class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")


class CustomUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = (
            "username",
            "email",
            "first_name",
            "last_name",
            "is_active",
            "is_staff",
            "is_superuser",
            "grupo",
            "gerente_contrato_ausente",
            "centros",
        )


class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = User

    list_display = (
        "username",
        "email",
        "grupo",
        "gerente_contrato_ausente",
        "get_centros",
        "is_staff",
        "is_active",
    )
    list_filter = ("grupo", "gerente_contrato_ausente", "centros", "is_staff", "is_active")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Informações pessoais", {"fields": ("first_name", "last_name", "email", "grupo", "gerente_contrato_ausente", "centros")}),
        ("Permissões", {"fields": ("is_staff", "is_active", "is_superuser", "groups", "user_permissions")}),
        ("Datas importantes", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "email",
                    "password1",
                    "password2",
                    "grupo",
                    "gerente_contrato_ausente",
                    "centros",
                    "is_staff",
                    "is_active",
                ),
            },
        ),
    )

    search_fields = ("username", "email")
    ordering = ("username",)

    def get_centros(self, obj):
        return ", ".join([c.nome for c in obj.centros.all()])

    get_centros.short_description = "Centros"


class DefaultAdmin(admin.ModelAdmin):
    ordering = ("id",)
    search_help_text = "Pesquise pelos principais campos de texto e relacionamentos."

    def get_list_display(self, request):
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

    def get_search_fields(self, request):
        fields_by_name = {field.name: field for field in self.model._meta.get_fields()}
        search_fields = []

        searchable_field_types = (
            models.CharField,
            models.TextField,
            models.EmailField,
            models.SlugField,
        )

        for field_name in [
            "nome",
            "titulo",
            "codigo",
            "numero",
            "cpf_cnpj",
            "cod_projeto",
            "descricao",
            "status",
            "email",
            "username",
        ]:
            field = fields_by_name.get(field_name)
            if field and not field.is_relation and isinstance(field, searchable_field_types):
                search_fields.append(field_name)

        related_candidates = {
            "cliente": ["cliente__nome", "cliente__cpf_cnpj"],
            "empresa_terceira": ["empresa_terceira__nome", "empresa_terceira__cpf_cnpj"],
            "contrato": ["contrato__num_contrato", "contrato__cod_projeto__cod_projeto"],
            "contrato_terceiro": ["contrato_terceiro__num_contrato", "contrato_terceiro__cod_projeto__cod_projeto"],
            "coordenador": ["coordenador__username", "coordenador__first_name", "coordenador__last_name"],
            "lider_contrato": ["lider_contrato__username", "lider_contrato__first_name", "lider_contrato__last_name"],
            "fornecedor_escolhido": ["fornecedor_escolhido__nome"],
            "evento": ["evento__descricao"],
        }

        for relation_name, lookups in related_candidates.items():
            if relation_name in fields_by_name:
                search_fields.extend(lookups)

        return tuple(dict.fromkeys(search_fields))


admin.site.register(User, CustomUserAdmin)

MODELOS_PADRAO = [
    Cliente,
    EmpresaTerceira,
    Proposta,
    Contrato,
    PropostaFornecedor,
    ContratoTerceiros,
    Evento,
    AvaliacaoFornecedor,
    Indicadores,
    BM,
    DocumentoContrato,
    DocumentoContratoTerceiro,
    NFCliente,
    SolicitacaoProspeccao,
    CentroDeTrabalho,
    DocumentoBM,
    CalendarioPagamento,
    NF,
    SolicitacaoOrdemServico,
    OS,
    SolicitacaoContrato,
    RegistroAuditoria,
    AditivoContratoTerceiro,
    ConfiguracaoSLA,
    Feriado,
]

for modelo in MODELOS_PADRAO:
    admin.site.register(modelo, DefaultAdmin)
