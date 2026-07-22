from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.db import models
from django.db.models import Q

from .forms import ContratoFornecedorForm
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

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if obj and obj.grupo == "gerente_contrato":
            return fieldsets
        return self._without_gerente_contrato_ausente(fieldsets)

    def _without_gerente_contrato_ausente(self, fieldsets):
        adjusted = []
        for name, options in fieldsets:
            options = options.copy()
            fields = options.get("fields", ())
            options["fields"] = tuple(
                field for field in fields if field != "gerente_contrato_ausente"
            )
            adjusted.append((name, options))
        return tuple(adjusted)

    def save_model(self, request, obj, form, change):
        if obj.grupo != "gerente_contrato":
            obj.gerente_contrato_ausente = False
        super().save_model(request, obj, form, change)

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


class ContratoTerceirosAdminForm(ContratoFornecedorForm):
    preserve_lider_contrato_for_guarda_chuva = True


class ContratoTerceirosAdmin(DefaultAdmin):
    form = ContratoTerceirosAdminForm


admin.site.register(ContratoTerceiros, ContratoTerceirosAdmin)


class BMAdmin(DefaultAdmin):
    list_display = (
        "id",
        "numero_bm",
        "parcela_paga",
        "valor_pago",
        "contrato",
        "evento",
        "os",
        "status_coordenador",
        "status_gerente",
        "aprovacao_pagamento",
    )
    list_filter = (
        "status_coordenador",
        "status_gerente",
        "aprovacao_pagamento",
        "data_pagamento",
    )
    search_fields = (
        "=numero_bm",
        "contrato__num_contrato",
        "contrato__cod_projeto__cod_projeto",
        "contrato__empresa_terceira__nome",
        "contrato__empresa_terceira__cpf_cnpj",
        "evento__descricao",
        "os__titulo",
        "observacao",
    )
    search_help_text = (
        "Pesquise por número do BM, contrato, projeto, fornecedor, evento, OS ou observação."
    )

    def get_search_results(self, request, queryset, search_term):
        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        search_term = search_term.strip()
        if not search_term:
            return queryset, may_have_duplicates

        extra_query = (
            Q(contrato__num_contrato__icontains=search_term)
            | Q(contrato__cod_projeto__cod_projeto__icontains=search_term)
            | Q(contrato__empresa_terceira__nome__icontains=search_term)
            | Q(contrato__empresa_terceira__cpf_cnpj__icontains=search_term)
            | Q(evento__descricao__icontains=search_term)
            | Q(os__titulo__icontains=search_term)
            | Q(observacao__icontains=search_term)
        )

        try:
            extra_query |= Q(numero_bm=int(search_term))
        except ValueError:
            pass

        return queryset | self.model.objects.filter(extra_query), True


admin.site.register(BM, BMAdmin)


MODELOS_PADRAO = [
    Cliente,
    EmpresaTerceira,
    Proposta,
    Contrato,
    PropostaFornecedor,
    Evento,
    AvaliacaoFornecedor,
    Indicadores,
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
