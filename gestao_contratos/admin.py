from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.db import models
from django import forms
from django.db.models import Q
from django.core.exceptions import FieldDoesNotExist
from django.core.exceptions import PermissionDenied
from django.db import transaction

from .forms import ContratoFornecedorForm
from .permissions import can_change_nf, payment_registration_error, can_write_os_scope
from .workflows import sync_paid_total, lock_payment_origin, audit_nf_deletion
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

    def has_add_permission(self, request):
        if request.user.grupo == "financeiro" and self.model not in {BM, NF, NFCliente}:
            return False
        return super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        if isinstance(obj, OS) and not can_write_os_scope(request.user, obj):
            return False
        if isinstance(obj, (SolicitacaoProspeccao, SolicitacaoContrato, SolicitacaoOrdemServico, AditivoContratoTerceiro)) and (obj.cancelada or obj.arquivada):
            return False
        if request.user.grupo == "financeiro":
            if self.model not in {BM, NF, NFCliente, EmpresaTerceira}:
                return False
            if isinstance(obj, NF) and not can_change_nf(request.user, obj):
                return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if isinstance(obj, OS) and not can_write_os_scope(request.user, obj):
            return False
        if request.user.grupo == "financeiro":
            if self.model not in {BM, NF, NFCliente}:
                return False
            if isinstance(obj, NF) and not can_change_nf(request.user, obj):
                return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if request.user.grupo == "financeiro":
            actions.pop("delete_selected", None)
        return actions

    def get_readonly_fields(self, request, obj=None):
        if self.model in {SolicitacaoProspeccao, SolicitacaoContrato, SolicitacaoOrdemServico, AditivoContratoTerceiro}:
            # Status operacional só muda pelas ações validadas do fluxo.
            return (*super().get_readonly_fields(request, obj), "status", "arquivada", "arquivada_em",
                    "arquivada_por", "motivo_arquivamento", "cancelada_em", "cancelada_por", "motivo_cancelamento")
        if request.user.grupo == "financeiro":
            if self.model is EmpresaTerceira:
                return tuple(f.name for f in self.model._meta.fields if f.name != "informacoes_bancarias")
            if self.model is BM:
                editable = {"contrato", "evento", "os", "numero_bm", "parcela_paga", "valor_pago", "data_pagamento",
                            "data_inicial_medicao", "data_final_medicao", "arquivo_bm", "observacao"}
                return tuple(f.name for f in self.model._meta.fields if f.name not in editable)
        fields=super().get_readonly_fields(request,obj)
        if self.model is BM:
            # Decisões e justificativas passam pelo endpoint validado, inclusive
            # para usuários staff; editar a medição continua reabrindo aprovações.
            return (*fields,'status_coordenador','status_gerente','aprovacao_pagamento',
                'data_aprovacao_coordenador','data_aprovacao_gerente','data_aprovacao_diretor',
                'justificativa_reprovacao_coordenador','justificativa_reprovacao_gerente',
                'justificativa_reprovacao_diretor','justificativa_aprovacao_diretor')
        return fields

    def save_model(self, request, obj, form, change):
        if isinstance(obj, OS) and not can_write_os_scope(request.user, obj):
            raise PermissionDenied("Sem competência para alterar esta OS.")
        if request.user.grupo == "financeiro" and isinstance(obj, EmpresaTerceira) and change:
            obj.save(update_fields=["informacoes_bancarias"])
            return
        super().save_model(request, obj, form, change)

    def delete_queryset(self, request, queryset):
        if self.model is OS and any(not can_write_os_scope(request.user, obj) for obj in queryset):
            raise PermissionDenied("A seleção contém OS fora da sua competência.")
        return super().delete_queryset(request, queryset)

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
            "contrato": ["contrato__num_contrato", "contrato__cod_projeto__cod_projeto", "contrato__cod_projeto"],
            "contrato_terceiro": ["contrato_terceiro__num_contrato", "contrato_terceiro__cod_projeto__cod_projeto"],
            "coordenador": ["coordenador__username", "coordenador__first_name", "coordenador__last_name"],
            "lider_contrato": ["lider_contrato__username", "lider_contrato__first_name", "lider_contrato__last_name"],
            "fornecedor_escolhido": ["fornecedor_escolhido__nome"],
            "evento": ["evento__descricao"],
        }

        for relation_name, lookups in related_candidates.items():
            if relation_name in fields_by_name:
                for lookup in lookups:
                    current_model = self.model
                    valid = True
                    for index, part in enumerate(lookup.split("__")):
                        try:
                            field = current_model._meta.get_field(part)
                        except FieldDoesNotExist:
                            valid = False
                            break
                        if index < len(lookup.split("__")) - 1:
                            if not field.is_relation:
                                valid = False
                                break
                            current_model = field.related_model
                    if valid and isinstance(field, searchable_field_types):
                        search_fields.append(lookup)

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


class NFAuditAdminForm(forms.ModelForm):
    justificativa_correcao=forms.CharField(required=False,max_length=4000,
        label='Justificativa da correção de NF paga',widget=forms.Textarea)
    class Meta:
        model=NF
        fields='__all__'


class NFAdmin(DefaultAdmin):
    form=NFAuditAdminForm
    delete_confirmation_template='admin/nf_delete_confirmation.html'
    delete_selected_confirmation_template='admin/nf_delete_selected_confirmation.html'
    def has_change_permission(self,request,obj=None):
        if obj and obj.possui_pagamentos and request.user.grupo!='suprimento':return False
        return super().has_change_permission(request,obj)

    def has_delete_permission(self,request,obj=None):
        if obj and obj.possui_historico_financeiro and request.user.grupo!='suprimento':return False
        return super().has_delete_permission(request,obj)

    def get_deleted_objects(self,objs,request):
        objects=list(objs)
        history=[obj for obj in objects if obj.possui_historico_financeiro]
        physical=[obj for obj in objects if obj not in history]
        deleted,counts,permissions,protected=super().get_deleted_objects(physical,request)
        for obj in history:
            deleted.append(f'NF #{obj.pk}: cancelamento lógico com estornos; movimentos e documentos preservados.')
            if request.user.grupo!='suprimento':permissions.add('cancelar NF com histórico (Suprimento)')
        return deleted,counts,permissions,protected
    def get_form(self, request, obj=None, **kwargs):
        base_form = super().get_form(request, obj, **kwargs)

        class RequestNFForm(base_form):
            justificativa_correcao=forms.CharField(required=False,max_length=4000,
                label='Justificativa da correção de NF paga',widget=forms.Textarea)
            def __init__(self, *args, **form_kwargs):
                super().__init__(*args, **form_kwargs)
                self.was_paid=bool(self.instance.pk and self.instance.possui_pagamentos)
                if self.instance.vencimento_original and 'vencimento_original' in self.fields:self.fields['vencimento_original'].disabled=True
                if "bm" in self.fields:
                    self.fields["bm"].required = True
                if "financeiro_autorizou" in self.fields:
                    self.fields["financeiro_autorizou"].label = "Pagamento realizado ao fornecedor"

            def clean(self):
                cleaned = super().clean()
                if self.was_paid and not cleaned.get('justificativa_correcao'):
                    self.add_error('justificativa_correcao','Informe o motivo da correção da NF paga.')
                if cleaned.get("financeiro_autorizou"):
                    from types import SimpleNamespace
                    actor=SimpleNamespace(grupo='financeiro') if not self.instance.financeiro_autorizou else request.user
                    error = payment_registration_error(actor, cleaned.get("bm"), cleaned.get("evento") or cleaned.get("os"))
                    if error:
                        self.add_error("financeiro_autorizou", error)
                return cleaned

        return RequestNFForm

    def save_model(self, request, obj, form, change):
        previous = NF.objects.filter(pk=obj.pk).first() if change else None
        if previous and not can_change_nf(request.user, previous) and request.user.grupo == "financeiro":
            raise PermissionDenied
        old_origin = (previous.evento or previous.os) if previous else None
        origin = obj.evento or obj.os
        obj._audit_user=request.user
        obj._audit_reason=form.cleaned_data.get('justificativa_correcao','')
        lock_payment_origin(old_origin)
        lock_payment_origin(origin)
        obj._audit_operation = f"{'Edição' if change else 'Cadastro'} de NF no admin; paga anteriormente: {'sim' if previous and previous.financeiro_autorizou else 'não'}."
        super().save_model(request, obj, form, change)
        if old_origin and (type(old_origin), old_origin.pk) != (type(origin), getattr(origin, "pk", None)):
            sync_paid_total(old_origin)
        sync_paid_total(origin)

    def delete_model(self, request, obj):
        if request.user.grupo == "financeiro" and not can_change_nf(request.user, obj):
            raise PermissionDenied
        reason=request.POST.get('justificativa_correcao','').strip()
        if obj.possui_historico_financeiro and not reason:
            raise PermissionDenied('Justificativa obrigatória para exclusão de NF paga.')
        obj._audit_reason=reason[:4000]
        origin = obj.evento or obj.os
        lock_payment_origin(origin)
        audit_nf_deletion(request.user, obj)
        super().delete_model(request, obj)
        sync_paid_total(origin)

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            for obj in queryset.select_for_update():
                self.delete_model(request, obj)


admin.site.register(NF, NFAdmin)


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
    SolicitacaoOrdemServico,
    OS,
    SolicitacaoContrato,
    AditivoContratoTerceiro,
    ConfiguracaoSLA,
    Feriado,
]

for modelo in MODELOS_PADRAO:
    admin.site.register(modelo, DefaultAdmin)


@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(DefaultAdmin):
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
    def get_actions(self, request): return {}
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)


from .models import PagamentoNF,ProgramacaoPagamento,ReprogramacaoPagamento,CicloPagamentoBM,DecisaoCicloBM,PagamentoCicloBM
for financial_model in (PagamentoNF,ProgramacaoPagamento,ReprogramacaoPagamento,CicloPagamentoBM,DecisaoCicloBM,PagamentoCicloBM):
    admin.site.register(financial_model,RegistroAuditoriaAdmin)
