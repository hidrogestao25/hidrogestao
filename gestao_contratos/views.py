from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Sum, Q, DecimalField, Avg
from decimal import Decimal
from django.db.models.functions import Coalesce, Greatest
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic.edit import CreateView
from .models import Contrato, Cliente, EmpresaTerceira, ContratoTerceiros, SolicitacaoProspeccao, Indicadores, PropostaFornecedor, DocumentoContratoTerceiro, DocumentoBM, Evento, CalendarioPagamento, BM, NF, AvaliacaoFornecedor, NFCliente, SolicitacaoOrdemServico, OS, SolicitacaoContrato
from .forms import ContratoForm, ClienteForm, FornecedorForm, ContratoFornecedorForm, SolicitacaoProspeccaoForm, DocumentoContratoTerceiroForm, DocumentoBMForm, EventoPrevisaoForm, EventoEntregaForm, FiltroPrevisaoForm, BMForm, NFForm, NFClienteForm, SolicitacaoOrdemServicoForm, UploadContratoOSForm, RegistroEntregaOSForm, OrdemServicoForm, SolicitacaoContratoForm

import plotly.graph_objs as go
import plotly.express as px
import pandas as pd
from plotly.offline import plot
import plotly.colors as pc

import os
import zipfile
import openpyxl
from django.http import HttpResponse, JsonResponse
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference, LineChart
from openpyxl.styles import Font
from io import BytesIO
from datetime import datetime, timedelta

User = get_user_model()


class ContratoCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = Contrato
    form_class = ContratoForm
    template_name = 'forms/contrato_form.html'
    success_url = reverse_lazy('lista_contratos')

    def test_func(self):
        # Só permite se for grupo suprimento
        return self.request.user.grupo == "suprimento"

    def handle_no_permission(self):
        # Redireciona para a home
        return redirect('home')


class ClienteCreateView(LoginRequiredMixin, UserPassesTestMixin,CreateView):
    model = Cliente
    form_class = ClienteForm
    template_name = 'forms/cliente_form.html'
    success_url = reverse_lazy('lista_clientes')

    def test_func(self):
        # Só permite se for grupo suprimento
        return self.request.user.grupo == "suprimento"

    def handle_no_permission(self):
        # Redireciona para a home
        return redirect('home')


class FornecedorCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = EmpresaTerceira
    form_class = FornecedorForm
    template_name = 'forms/fornecedor_form.html'
    success_url = reverse_lazy('lista_fornecedores')

    def test_func(self):
        # Só permite se for grupo suprimento
        return self.request.user.grupo == "suprimento"

    def handle_no_permission(self):
        # Redireciona para a home
        return redirect('home')


class ContratoFornecedorCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = ContratoTerceiros
    form_class = ContratoFornecedorForm
    template_name = 'forms/contrato_fornecedor_form.html'
    success_url = reverse_lazy('lista_contratos_fornecedores')

    def test_func(self):
        # Só permite se for grupo suprimento
        return self.request.user.grupo == "suprimento"

    def handle_no_permission(self):
        # Redireciona para a home
        return redirect('home')

    def form_valid(self, form):
        print("==== DEBUG FORM_VALID ====")
        print("Arquivos recebidos:", self.request.FILES)
        print("Campos POST:", self.request.POST)

        response = super().form_valid(form)

        print("Objeto salvo:", self.object)
        print("Arquivo salvo:", self.object.num_contrato_arquivo)
        print("==========================")

        return response


class OSCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = OS
    form_class = OrdemServicoForm
    template_name = 'forms/os_form.html'
    success_url = reverse_lazy('lista_ordens_servico')

    def test_func(self):
        # Só permite se for grupo suprimento
        return self.request.user.grupo == "suprimento"

    def handle_no_permission(self):
        # Redireciona para a home
        return redirect('home')


#def is_financeiro(user):
#    return user.is_authenticated and getattr(user, "grupo", None) == "financeiro"


def home(request):
    user = request.user
    hoje = timezone.now().date()
    limite = hoje + timedelta(days=10)

    grupo = getattr(user, "grupo", None)
    is_suprimento = grupo == "suprimento"
    is_coordenador = grupo == "coordenador"
    is_gerente = grupo == "gerente"
    is_diretoria = grupo == "diretoria"
    is_financeiro = grupo == "financeiro"
    is_lider = grupo == "lider_contrato"
    is_gerente_contrato = grupo == "gerente_contrato"

    context = {
        "is_suprimento": is_suprimento,
        "is_coordenador": is_coordenador,
        "is_lider":is_lider,
        "is_gerente": is_gerente,
        "is_gerente_contrato":is_gerente_contrato,
        "is_diretoria": is_diretoria,
        "is_financeiro": is_financeiro
    }

    # ==================== SUPRIMENTO ====================
    if is_suprimento:
        solicitacoes_pendentes = SolicitacaoProspeccao.objects.filter(
            Q(aprovado__isnull=True)
            | (Q(aprovado=True) & Q(triagem_realizada=False))
            | (Q(aprovado=True) & Q(triagem_realizada=True) & Q(fornecedor_escolhido__isnull=True))
            | (Q(aprovacao_fornecedor_gerente="aprovado") & Q(aprovacao_gerencia=False))
            | Q(status__in=["Fornecedor aprovado", "Planejamento do Contrato"])
        ).exclude(status__in=["Onboarding"]).distinct()

        eventos_proximos = Evento.objects.filter(
            data_prevista__range=[hoje, limite]
        ).order_by("data_prevista")

        # Entregas atrasadas (todas)
        entregas_atrasadas = Evento.objects.filter(
            Q(realizado=False) & Q(data_prevista__lt=hoje)
        ).order_by("data_prevista")

        context.update({
            "painel_titulo": "Painel de Suprimentos",
            "solicitacoes_pendentes": solicitacoes_pendentes,
            "eventos_proximos": eventos_proximos,
            "entregas_atrasadas": entregas_atrasadas,
        })

    # ==================== COORDENADOR ====================
    elif is_coordenador:
        solicitacoes_pendentes = SolicitacaoProspeccao.objects.filter(
            Q(coordenador=user)
        ).distinct()

        bms_pendentes = BM.objects.filter(
            contrato__coordenador=user,
            status_coordenador="pendente"
        ).select_related("contrato", "contrato__empresa_terceira").order_by("-data_pagamento")

        eventos_proximos = Evento.objects.filter(
            data_prevista__range=[hoje, limite],
            contrato_terceiro__coordenador=user
        ).order_by("data_prevista")

        # Entregas atrasadas do coordenador
        entregas_atrasadas = Evento.objects.filter(
            Q(contrato_terceiro__coordenador=user)
            & Q(realizado=False)
            & Q(data_prevista__lt=hoje)
        ).order_by("data_prevista")

        eventos_para_avaliar = (
            Evento.objects.filter(
                Q(contrato_terceiro__coordenador=user)
                & Q(realizado=True)
                & Q(avaliacoes__isnull=True)
            ).order_by("data_entrega")
        )

        context.update({
            "painel_titulo": "Painel do Coordenador",
            "solicitacoes_pendentes": solicitacoes_pendentes,
            "bms_pendentes": bms_pendentes,
            "eventos_proximos": eventos_proximos,
            "entregas_atrasadas": entregas_atrasadas,
            "eventos_para_avaliar":eventos_para_avaliar,
        })


    # ==================== LIDER DE CONTRATO ==========

    elif is_lider:
        solicitacoes_pendentes = SolicitacaoProspeccao.objects.filter(
            Q(lider_contrato=user)
            & (Q(triagem_realizada=True, status="Triagem realizada") |
               Q(minuta_boletins_medicao__status_coordenador="pendente") |
               Q(status="Solicitação de prospecção")
               )
        ).distinct()

        bms_pendentes = BM.objects.filter(
            contrato__coordenador=user,
            status_coordenador="pendente"
        ).select_related("contrato", "contrato__empresa_terceira").order_by("-data_pagamento")

        eventos_proximos = Evento.objects.filter(
            data_prevista__range=[hoje, limite],
            contrato_terceiro__lider_contrato=user
        ).order_by("data_prevista")

        # Entregas atrasadas do coordenador
        entregas_atrasadas = Evento.objects.filter(
            Q(contrato_terceiro__lider_contrato=user)
            & Q(realizado=False)
            & Q(data_prevista__lt=hoje)
        ).order_by("data_prevista")

        eventos_para_avaliar = (
            Evento.objects.filter(
                Q(contrato_terceiro__lider_contrato=user)
                & Q(realizado=True)
                & Q(avaliacoes__isnull=True)
            ).order_by("data_entrega")
        )

        context.update({
            "painel_titulo": "Painel do Lider de Contratos",
            "solicitacoes_pendentes": solicitacoes_pendentes,
            "bms_pendentes": bms_pendentes,
            "eventos_proximos": eventos_proximos,
            "entregas_atrasadas": entregas_atrasadas,
            "eventos_para_avaliar":eventos_para_avaliar,
        })

    # ==================== GERENTE ====================
    elif is_gerente:
        centros_gerente = getattr(user, "centros", None)
        centros_ids = centros_gerente.values_list("id", flat=True) if centros_gerente else []

        solicitacoes = SolicitacaoProspeccao.objects.filter(
            coordenador__centros__in=centros_ids).select_related("fornecedor_escolhido", "coordenador"
            ).exclude(status__in=["Onboarding"]).distinct()


        lista_solicitacoes = []
        for s in solicitacoes:
            proposta_escolhida = PropostaFornecedor.objects.filter(
                solicitacao=s, fornecedor=s.fornecedor_escolhido
            ).first()
            contrato = DocumentoContratoTerceiro.objects.filter(solicitacao=s).first()

            pendente_fornecedor = s.fornecedor_escolhido and s.aprovacao_fornecedor_gerente == "pendente"
            pendente_contrato = contrato and not getattr(contrato, "aprovacao_gerencia", False)

            if pendente_fornecedor or pendente_contrato:
                lista_solicitacoes.append({
                    "solicitacoes_pendentes": s,
                    "fornecedor": s.fornecedor_escolhido,
                    "proposta": proposta_escolhida,
                    "contrato": contrato,
                })

        bms_pendentes = BM.objects.filter(
            contrato__coordenador__centros__in=centros_ids,
            status_gerente="pendente"
        ).select_related("contrato", "contrato__empresa_terceira").order_by("-data_pagamento").distinct()

        eventos_proximos = Evento.objects.filter(
            data_prevista__range=[hoje, limite],
            contrato_terceiro__coordenador__centros__in=centros_ids
        ).order_by("data_prevista").distinct()

        # Entregas atrasadas dos centros do gerente
        entregas_atrasadas = Evento.objects.filter(
            contrato_terceiro__coordenador__centros__in=centros_ids,
            realizado=False,
            data_prevista__lt=hoje
        ).order_by("data_prevista").distinct()

        context.update({
            "painel_titulo": "Painel da Gerência",
            "solicitacoes_pendentes": lista_solicitacoes,
            "bms_pendentes": bms_pendentes,
            "eventos_proximos": eventos_proximos,
            "entregas_atrasadas": entregas_atrasadas,
        })

    #===================== GERENTE DE CONTRATO ==========
    elif is_gerente_contrato:
        """centros_gerente = getattr(user, "centros", None)
        centros_ids = centros_gerente.values_list("id", flat=True) if centros_gerente else []"""

        solicitacoes = (
            SolicitacaoProspeccao.objects.filter(lider_contrato__grupo__in=["lider_contrato", "gerente_contrato"])
            .select_related("fornecedor_escolhido", "lider_contrato")
            .exclude(status__in=["Onboarding"]).distinct()
        )

        lista_solicitacoes = []
        for s in solicitacoes:
            proposta_escolhida = PropostaFornecedor.objects.filter(
                solicitacao=s, fornecedor=s.fornecedor_escolhido
            ).first()
            contrato = DocumentoContratoTerceiro.objects.filter(solicitacao=s).first()

            pendente_fornecedor = s.fornecedor_escolhido and s.aprovacao_fornecedor_gerente == "pendente"
            pendente_contrato = contrato and not getattr(contrato, "aprovacao_gerencia", False)

            if pendente_fornecedor or pendente_contrato:
                lista_solicitacoes.append({
                    "solicitacao": s,
                    "fornecedor": s.fornecedor_escolhido,
                    "proposta": proposta_escolhida,
                    "contrato": contrato,
                })

        bms_pendentes = BM.objects.filter(
            contrato__lider_contrato__grupo="lider_contrato",
            status_gerente="pendente"
        ).select_related("contrato", "contrato__empresa_terceira").order_by("-data_pagamento").distinct()

        eventos_proximos = Evento.objects.filter(
            data_prevista__range=[hoje, limite],
            contrato_terceiro__lider_contrato__grupo="lider_contrato"
        ).order_by("data_prevista").distinct()

        # Entregas atrasadas dos centros do gerente
        entregas_atrasadas = Evento.objects.filter(
            contrato_terceiro__lider_contrato__grupo="lider_contrato",
            realizado=False,
            data_prevista__lt=hoje
        ).order_by("data_prevista").distinct()

        context.update({
            "painel_titulo": "Painel da Gerência de Contratos",
            "solicitacoes_pendentes": lista_solicitacoes,
            "bms_pendentes": bms_pendentes,
            "eventos_proximos": eventos_proximos,
            "entregas_atrasadas": entregas_atrasadas,
        })

    # ==================== DIRETORIA ====================
    elif is_diretoria:

        # BM aprovados por Coordenador e Gerente mas pendentes na Diretoria
        bms_pendentes_diretoria = BM.objects.filter(
            status_coordenador="aprovado",
            status_gerente="aprovado",
            aprovacao_pagamento="pendente"
        ).select_related("contrato", "contrato__empresa_terceira").order_by("-data_pagamento")

        # Entregas atrasadas (todas)
        entregas_atrasadas = Evento.objects.filter(
            realizado=False,
            data_prevista__lt=hoje
        ).order_by("data_prevista")

        # Próximas entregas (10 dias)
        eventos_proximos = Evento.objects.filter(
            data_prevista__range=[hoje, limite]
        ).order_by("data_prevista")

        context.update({
            "painel_titulo": "Painel da Diretoria",
            "bms_pendentes_diretoria": bms_pendentes_diretoria,
            "entregas_atrasadas": entregas_atrasadas,
            "eventos_proximos": eventos_proximos,
        })

    # ==================== FINANCEIRO ====================
    elif is_financeiro:
        solicitacoes_pendentes = SolicitacaoProspeccao.objects.filter(
            Q(coordenador=user)
            & (Q(triagem_realizada=True, status="Triagem realizada") |
               Q(minuta_boletins_medicao__status_coordenador="pendente"))
        ).distinct()

        eventos_sem_nf = BM.objects.filter(
            status_coordenador="aprovado",
            status_gerente="aprovado",
            aprovacao_pagamento="aprovado"
        ).filter(
            Q(nota_fiscal__isnull=True)
        ).select_related("contrato", "contrato__empresa_terceira").order_by("-data_pagamento")

        eventos_proximos = Evento.objects.filter(
            data_prevista__range=[hoje, limite]
        ).order_by("data_prevista")

        context.update({
            "solicitacoes_pendentes": solicitacoes_pendentes,
            "eventos_sem_nf": eventos_sem_nf,
            "eventos_proximos": eventos_proximos,
        })


    return render(request, "home.html", context)



def logout(request):
    return render(request, 'logged_out.html')


@login_required
def lista_contratos(request):
    if request.user.grupo in ['suprimento', 'financeiro', 'diretoria']:
        contratos = Contrato.objects.all()
    elif request.user.grupo == 'coordenador':
        contratos = Contrato.objects.filter(coordenador=request.user)
    elif request.user.grupo == 'lider_contrato':
        contratos = Contrato.objects.filter(lider_contrato=request.user)
    elif request.user.grupo == 'gerente':
        contratos = Contrato.objects.filter(coordenador__centros__in=request.user.centros.all())
    elif request.user.grupo == 'gerente_contrato':
        contratos = Contrato.objects.filter(lider_contrato__grupo='lider_contrato')
    else:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    search_query = request.GET.get('search', '').strip()
    if search_query:
        contratos = contratos.filter(
            Q(cod_projeto__icontains=search_query) |
            Q(coordenador__username__icontains=search_query) |
            Q(cliente__nome__icontains=search_query) |
            Q(status__icontains=search_query)
        )

    contratos = contratos.order_by('-data_inicio')

    paginator = Paginator(contratos, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {'page_obj': page_obj, 'search_query': search_query}
    return render(request, 'gestao_contratos/lista_contratos.html', context)



@login_required
def lista_clientes(request):
    # Filtro inicial por grupo
    if request.user.grupo in ['suprimento', 'financeiro', 'diretoria']:
        clientes = Cliente.objects.all()
    elif request.user.grupo == 'coordenador':
        clientes = Cliente.objects.filter(contratos__coordenador=request.user).distinct()
    elif request.user.grupo == 'lider_contrato':
        clientes = Cliente.objects.filter(contratos__lider_contrato=request.user).distinct()
    elif request.user.grupo == 'gerente':
        clientes = Cliente.objects.filter(
            contratos__coordenador__centros__in=request.user.centros.all()
        ).distinct()
    elif request.user.grupo == 'gerente_contrato':
        clientes = Cliente.objects.filter(
            contratos__lider_contrato__grupo='lider_contrato'
        ).distinct()
    else:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    # Campo de busca
    search_query = request.GET.get('search', '').strip()
    if search_query:
        clientes = clientes.filter(
            Q(nome__icontains=search_query) |
            Q(cpf_cnpj__icontains=search_query) |
            Q(endereco__icontains=search_query)
        )

    # Ordenação e paginação
    clientes = clientes.order_by('nome')
    paginator = Paginator(clientes, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
    }
    return render(request, 'gestao_contratos/lista_clientes.html', context)


@login_required
def lista_contratos_fornecedor(request):
    # Filtragem base por grupo de usuário
    if request.user.grupo in ['suprimento', 'financeiro', 'diretoria']:
        contratos = ContratoTerceiros.objects.all()
    elif request.user.grupo == 'coordenador':
        contratos = ContratoTerceiros.objects.filter(coordenador=request.user)
    elif request.user.grupo == 'lider_contrato':
        contratos = ContratoTerceiros.objects.filter(lider_contrato=request.user)
    elif request.user.grupo == 'gerente':
        contratos = ContratoTerceiros.objects.filter(
            coordenador__centros__in=request.user.centros.all()
        )
    elif request.user.grupo == 'gerente_contrato':
        contratos = ContratoTerceiros.objects.filter(
            lider_contrato__grupo__in=['lider_contrato','gerente_contrato']
        )
    else:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    # Campo de busca
    search_query = request.GET.get('search', '').strip()
    if search_query:
        contratos = contratos.filter(
            Q(cod_projeto__cod_projeto__icontains=search_query) |
            Q(num_contrato__icontains=search_query) |
            Q(cod_projeto__cliente__nome__icontains=search_query) |
            Q(empresa_terceira__nome__icontains=search_query) |
            Q(coordenador__username__icontains=search_query) |
            Q(status__icontains=search_query) |
            Q(valor_total__icontains=search_query)
        )

    # Ordenar e paginar
    contratos = contratos.order_by('-data_inicio')
    paginator = Paginator(contratos, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
    }

    return render(request, 'gestao_contratos/lista_contratos_fornecedores.html', context)


@login_required
def lista_fornecedores(request):
    # Filtro base por grupo de usuário
    if request.user.grupo in ['suprimento', 'financeiro', 'diretoria']:
        fornecedores = EmpresaTerceira.objects.all()
    elif request.user.grupo == 'coordenador':
        fornecedores = EmpresaTerceira.objects.filter(
            Q(contratos__coordenador=request.user) |
            Q(contratos__os_cadastrada__status__in=['em_execucao', 'finalizada', 'paralizada']) &
            Q(contratos__os_cadastrada__coordenador=request.user)
        ).distinct()
    elif request.user.grupo == 'lider_contrato':
        fornecedores = EmpresaTerceira.objects.filter(
            Q(contratos__lider_contrato=request.user) |
            Q(contratos__os_cadastrada__status__in=['em_execucao', 'finalizada', 'paralizada']) &
            Q(contratos__os_cadastrada__lider_contrato=request.user)
        ).distinct()
    elif request.user.grupo == 'gerente':
        fornecedores = EmpresaTerceira.objects.filter(
            Q(contratos__coordenador__centros__in=request.user.centros.all()) |
            Q(contratos__os_cadastrada__status__in=['em_execucao', 'finalizada', 'paralizada']) &
            Q(contratos__os_cadastrada__coordenador__centros__in=request.user.centros.all())
        ).distinct()
    elif request.user.grupo == 'gerente_contrato':
        fornecedores = EmpresaTerceira.objects.filter(
            Q(contratos__lider_contrato__grupo='lider_contrato') |
            Q(contratos__os_cadastrada__status__in=['em_execucao', 'finalizada', 'paralizada']) &
            Q(contratos__os_cadastrada__lider_contrato__grupo='lider_contrato')
        ).distinct()
    else:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    # Campo de busca
    search_query = request.GET.get('search', '').strip()
    if search_query:
        fornecedores = fornecedores.filter(
            Q(nome__icontains=search_query) |
            Q(cpf_cnpj__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(municipio__icontains=search_query) |
            Q(estado__icontains=search_query)
        )

    guarda_chuva = request.GET.get('guarda_chuva')
    if guarda_chuva == '1':
        fornecedores = fornecedores.filter(contratos__guarda_chuva=True)

    # Ordenação e paginação
    fornecedores = fornecedores.order_by('nome')
    paginator = Paginator(fornecedores, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'guarda_chuva': guarda_chuva,
    }

    return render(request, 'gestao_contratos/lista_fornecedores.html', context)


@login_required
def cadastrar_nf_cliente(request, pk):
    if request.user.grupo not in ["financeiro", "suprimento"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    contrato = get_object_or_404(Contrato, pk=pk)

    if request.method == "POST":
        form = NFClienteForm(request.POST, request.FILES)
        if form.is_valid():
            nf = form.save(commit=False)
            nf.contrato = contrato
            nf.inserido_por = request.user
            nf.save()

            messages.success(request, "Nota Fiscal cadastrada com sucesso!")
        else:
            messages.error(request, "Erro ao salvar Nota Fiscal. Verifique os campos.")

    return redirect("contrato_cliente_detalhe", pk=pk)


@login_required
def contrato_cliente_detalhe(request, pk):
    contrato = get_object_or_404(Contrato, pk=pk)

    # ---- Buscar eventos ligados a esse contrato ----
    eventos = Evento.objects.filter(contrato_terceiro__cod_projeto=contrato)

    total_contrato = contrato.valor_total or 0

    # --- Criar DataFrame para segmentação por fornecedor ---
    df = pd.DataFrame(list(eventos.values(
        'empresa_terceira__nome',
        'valor_previsto',
        'valor_pago'
    )))

    if df.empty:
        resumo = pd.DataFrame(columns=['empresa_terceira__nome', 'valor_previsto', 'valor_pago'])
        total_previsto = total_pago = 0
    else:
        df = df.fillna(0)
        resumo = df.groupby('empresa_terceira__nome')[['valor_previsto', 'valor_pago']].sum().reset_index()
        total_previsto = resumo['valor_previsto'].sum()
        total_pago = resumo['valor_pago'].sum()

    # ---- Calcular percentuais ----
    if total_contrato > 0:
        perc_previsto = (total_previsto / total_contrato) * 100
        perc_pago = (total_pago / total_contrato) * 100
        perc_restante = 100 - max(perc_previsto, perc_pago)
    else:
        perc_previsto = perc_pago = perc_restante = 0

    # ---- Cores diferentes para cada fornecedor ----
    fornecedores = resumo['empresa_terceira__nome'].tolist()
    cores = px.colors.qualitative.Plotly * (len(fornecedores) // 10 + 1)

    # ---- Gráfico de barras ----
    fig = go.Figure()

    # Barra 1: Valor total do contrato
    fig.add_trace(go.Bar(
        x=['Valor Total do Contrato'],
        y=[total_contrato],
        name='Total do Contrato',
        text=[f"R$ {total_contrato:,.2f}"],
        textposition='inside',
        marker_color='#007bff'
    ))

    # Barras empilhadas: Valor Previsto por fornecedor
    for i, row in enumerate(resumo.itertuples()):
        fig.add_trace(go.Bar(
            x=['Valor Previsto para Fornecedores'],
            y=[row.valor_previsto],
            name=f"{row.empresa_terceira__nome}",
            text=[f"R$ {row.valor_previsto:,.2f}"],
            textposition='inside',
            hovertemplate=f"<b>{row.empresa_terceira__nome}</b><br>Previsto: R$ %{{y:,.2f}}<extra></extra>",
            marker_color=cores[i]
        ))

    # Barras empilhadas: Valor Pago por fornecedor
    for i, row in enumerate(resumo.itertuples()):
        fig.add_trace(go.Bar(
            x=['Valor Pago a Fornecedores'],
            y=[row.valor_pago],
            name=f"PAGO - {row.empresa_terceira__nome}",
            text=[f"R$ {row.valor_pago:,.2f}"],
            textposition='inside',
            hovertemplate=f"<b>{row.empresa_terceira__nome}</b><br>Pago: R$ %{{y:,.2f}}<extra></extra>",
            marker_color=cores[i]
        ))

    # ---- Adicionar valor total no topo das barras empilhadas ----
    if not resumo.empty:
        fig.add_annotation(
            x='Valor Previsto para Fornecedores',
            y=total_previsto,
            text=f"R$ {total_previsto:,.2f}",
            showarrow=False,
            yshift=10,
            font=dict(size=12, color='black')
        )
        fig.add_annotation(
            x='Valor Pago a Fornecedores',
            y=total_pago,
            text=f"R$ {total_pago:,.2f}",
            showarrow=False,
            yshift=10,
            font=dict(size=12, color='black')
        )

    fig.update_layout(
        title=f'Resumo Financeiro do Contrato ({contrato.cod_projeto})',
        yaxis_title='Valor (R$)',
        xaxis_title='Categoria',
        template='plotly_white',
        barmode='stack',
        height=500,
        legend=dict(orientation="h", y=-0.3, x=0)
    )

    grafico_contrato = fig.to_html(full_html=False)

    # ---- Texto com resumo percentual ----
    resumo_percentual = {
        'pago': round(perc_pago, 1),
        'previsto': round(perc_previsto, 1),
        'restante': round(perc_restante, 1)
    }

    # ---- Listagem das NFs já cadastradas para esse contrato ----
    open_modal_nf = False
    form_nf = NFClienteForm()
    nf_list = contrato.nota_fiscal.all().order_by("-data_emissao")


    # ---- Controle de edição ----
    if request.user.grupo == "suprimento":
        forms_edit = {}
        for nf in nf_list:
            forms_edit[nf.id] = NFClienteForm(instance=nf, prefix=f"edit_{nf.id}")
        # POST vindo do modal de NF
        if request.method == "POST" and request.user.is_authenticated and "submit_nf" in request.POST:
            form_nf = NFClienteForm(request.POST, request.FILES)
            if form_nf.is_valid():
                nf = form_nf.save(commit=False)
                nf.contrato = contrato
                nf.inserido_por = request.user
                nf.save()
                messages.success(request, "Nota Fiscal cadastrada com sucesso!")
                return redirect("contrato_cliente_detalhe", pk=pk)
            else:
                open_modal_nf = True
                messages.error(request, "Erro ao cadastrar Nota Fiscal. Verifique os campos abaixo.")

        # POST do formulário do contrato
        if request.method == "POST" and request.user.is_authenticated and "submit_contrato" in request.POST:
            form = ContratoForm(request.POST, instance=contrato)
            if form.is_valid():
                form.save()
                messages.success(request, "Contrato atualizado com sucesso!")
                return redirect("lista_contratos")
            else:
                messages.error(request, "Erro ao atualizar contrato.")
        else:
            form = ContratoForm(instance=contrato)

        return render(request, 'contratos/contrato_detail_edit.html', {
            'form': form,
            'contrato': contrato,
            'grafico_contrato': grafico_contrato,
            'resumo_percentual': resumo_percentual,
            'form_nf': form_nf,
            'nf_list': nf_list,
            'open_modal_nf': open_modal_nf,
            'forms_edit': forms_edit,
        })

    if request.user.grupo in ["financeiro"]:
        forms_edit = {}
        for nf in nf_list:
            forms_edit[nf.id] = NFClienteForm(instance=nf, prefix=f"edit_{nf.id}")
        if request.method == "POST" and request.user.is_authenticated:
            # executa validação do form vindo do modal
            form_nf = NFClienteForm(request.POST, request.FILES)
            if form_nf.is_valid():
                nf = form_nf.save(commit=False)
                nf.contrato = contrato
                nf.inserido_por = request.user
                nf.save()
                messages.success(request, "Nota Fiscal cadastrada com sucesso!")
                return redirect("contrato_cliente_detalhe", pk=pk)
            else:
                # manter o modal aberto e mostrar erros
                open_modal_nf = True
                messages.error(request, "Erro ao cadastrar Nota Fiscal. Verifique os campos e corrija os erros abaixo.")

        return render(request, "contratos/contrato_detail.html", {
            'contrato': contrato,
            'grafico_contrato': grafico_contrato,
            'resumo_percentual': resumo_percentual,
            'form_nf': form_nf,
            'nf_list': nf_list,
            'open_modal_nf': open_modal_nf,
            'forms_edit': forms_edit,
        })

    return render(request, "contratos/contrato_detail.html", {
        'contrato': contrato,
        'grafico_contrato': grafico_contrato,
        'resumo_percentual': resumo_percentual,
        'nf_list': nf_list,
    })


@login_required
def editar_nf_cliente(request, pk):
    nf = get_object_or_404(NFCliente, pk=pk)

    if request.user.grupo not in ["suprimento","financeiro"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    if request.method == "POST":
        prefix = f"edit_{nf.id}"
        form = NFClienteForm(request.POST, request.FILES, instance=nf, prefix=prefix)

        if form.is_valid():
            form.save()
            messages.success(request, "NF atualizada com sucesso!")
        else:
            print("ERROS AO EDITAR NF:", form.errors)
            messages.error(request, "Erro ao atualizar a Nota Fiscal.")

    return redirect("contrato_cliente_detalhe", pk=nf.contrato.pk)




@login_required
def excluir_nf_cliente(request, pk):
    nf = get_object_or_404(NFCliente, pk=pk)

    if request.user.grupo not in ["financeiro", "suprimento"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    contrato_pk = nf.contrato.pk
    nf.delete()
    messages.success(request, "Nota Fiscal excluída com sucesso!")

    return redirect("contrato_cliente_detalhe", pk=contrato_pk)


@login_required
def contrato_fornecedor_detalhe(request, pk):
    contrato = get_object_or_404(ContratoTerceiros, pk=pk)
    fornecedor = contrato.empresa_terceira

    indicadores_geral, _ = Indicadores.objects.get_or_create(empresa_terceira=fornecedor)
    indicadores_contrato = contrato
    contratos_fornecedor = ContratoTerceiros.objects.filter(
        empresa_terceira=contrato.empresa_terceira,
        status='ativo'
    )

    ordens_servico = OS.objects.filter(
        contrato=contrato
    ).order_by('-criado_em')


    proposta_fornecedor = None
    if contrato.prospeccao and contrato.prospeccao.fornecedor_escolhido:
        proposta_fornecedor = contrato.prospeccao.propostas.filter(
            fornecedor=contrato.prospeccao.fornecedor_escolhido
        ).first()

    eventos = Evento.objects.filter(contrato_terceiro=contrato).order_by("data_prevista")

    df = pd.DataFrame(list(eventos.values("data_prevista_pagamento", "valor_previsto", "valor_pago", "data_pagamento")))

    plot_div = None
    if not df.empty:
        # Preencher valores nulos com 0
        df["valor_previsto"] = df["valor_previsto"].fillna(0)
        df["valor_pago"] = df["valor_pago"].fillna(0)

        # Ordenar pelas datas
        df = df.sort_values("data_prevista_pagamento")

        # Calcular valores acumulados
        df["valor_previsto_acum"] = df["valor_previsto"].cumsum()
        df["valor_pago_acum"] = df["valor_pago"].cumsum()

        # Criar gráfico
        trace_previsto = go.Scatter(
            x=df["data_prevista_pagamento"],
            y=df["valor_previsto_acum"],
            mode="lines+markers",
            name="Previsto (Acumulado)",
            line=dict(color="orange")
        )

        trace_pago = go.Scatter(
            x=df["data_pagamento"],
            y=df["valor_pago_acum"],
            mode="lines+markers",
            name="Pago (Acumulado)",
            line=dict(color="green")
        )

        layout = go.Layout(
            title="Evolução Acumulada de Pagamentos",
            xaxis=dict(title="Data"),
            yaxis=dict(title="Valor (R$)"),
            template="plotly_white"
        )

        fig = go.Figure(data=[trace_previsto, trace_pago], layout=layout)
        plot_div = plot(fig, auto_open=False, output_type="div")

    #  --- GRÁFICO DE COMPARAÇÃO GERAL ---
    contrato_cliente = contrato.cod_projeto  # contrato com o cliente
    valor_cliente = contrato_cliente.valor_total or 0

    total_previsto = eventos.aggregate(Sum("valor_previsto"))["valor_previsto__sum"] or 0
    total_pago = eventos.aggregate(Sum("valor_pago"))["valor_pago__sum"] or 0

    # Percentuais
    perc_previsto = (total_previsto / valor_cliente * 100) if valor_cliente else 0
    perc_pago = (total_pago / valor_cliente * 100) if valor_cliente else 0

    fig_comp = go.Figure()

    fig_comp.add_trace(go.Bar(
        x=["Valor Contrato Cliente", "Valor Previsto Fornecedor", "Valor Pago Fornecedor"],
        y=[valor_cliente, total_previsto, total_pago],
        text=[
            f"R$ {valor_cliente:,.2f}<br>100%",
            f"R$ {total_previsto:,.2f}<br>{perc_previsto:.1f}%",
            f"R$ {total_pago:,.2f}<br>{perc_pago:.1f}%"
        ],
        textposition="auto",
        marker_color=["#007bff", "#ffc107", "#28a745"]
    ))

    fig_comp.update_layout(
        title="Comparativo Financeiro: Cliente × Fornecedor",
        yaxis_title="Valor (R$)",
        xaxis_title="Categoria",
        template="plotly_white",
        height=450
    )

    comparativo_div = plot(fig_comp, auto_open=False, output_type="div")

    return render(
        request,
        "contratos/contrato_fornecedor_detail.html",
        {
            "contrato": contrato,
            "proposta_fornecedor": proposta_fornecedor,
            "eventos": eventos,
            "plot_div": plot_div,
            "comparativo_div": comparativo_div,
            "indicadores_geral": indicadores_geral,
            "indicadores_contrato": indicadores_contrato,
            "contratos_ativos": contratos_fornecedor.count(),
            "ordens_servico": ordens_servico,
        },
    )


@login_required
def contrato_fornecedor_editar(request, pk):
    contrato = get_object_or_404(ContratoTerceiros, pk=pk)

    # Permissões
    if request.user.grupo not in ["suprimento"]:
        messages.error(request, "❌ Você não tem permissão para editar contratos.")
        return redirect("contrato_fornecedor_detalhe", pk=pk)

    if request.method == "POST":
        # Incluímos request.FILES para que o arquivo seja capturado
        form = ContratoFornecedorForm(request.POST, request.FILES, instance=contrato)
        print("POST:", request.POST)
        print("FILES:", request.FILES)
        if form.is_valid():
            # Salva o formulário e o arquivo enviado
            form.save()
            messages.success(request, "Contrato atualizado com sucesso!")
            return redirect("contrato_fornecedor_detalhe", pk=pk)
        else:
            messages.error(
                request, "❌ Ocorreu um erro ao atualizar o contrato. Verifique os campos."
            )
    else:
        form = ContratoFornecedorForm(instance=contrato)

    return render(
        request,
        "contratos/contrato_fornecedor_detail_edit.html",
        {"form": form, "contrato": contrato},
    )


@login_required
def cliente_detalhe(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    contratos = cliente.contratos.all()  # pega todos os contratos do cliente

    if request.user.grupo in ["suprimento", "financeiro"]:
        if request.method == "POST":
            form = ClienteForm(request.POST, instance=cliente)
            if form.is_valid():
                form.save()
                messages.success(request, "Dados do Cliente atualizado com sucesso!")
                return redirect("lista_clientes")
            else:
                messages.error(request, "❌ Ocorreu um erro ao atualizar o contrato. Verifique os campos e tente novamente.")
        else:
            form = ClienteForm(instance=cliente)
        return render(
            request,
            'clientes/cliente_detail_edit.html',
            {'form': form, 'cliente': cliente, 'contratos': contratos}
        )

    return render(
        request,
        'clientes/cliente_detail.html',
        {'cliente': cliente, 'contratos': contratos}
    )



@login_required
def fornecedor_detalhe(request, pk):
    fornecedor = get_object_or_404(EmpresaTerceira, pk=pk)
    indicadores_geral = Indicadores(empresa_terceira=fornecedor)
    if request.user.grupo in ["suprimento", "financeiro"]:
        contratos = fornecedor.contratos.all()
        os = OS.objects.filter(contrato__empresa_terceira=fornecedor)
    elif request.user.grupo == "coordenador":
        contratos = fornecedor.contratos.filter(coordenador=request.user)
        os = OS.objects.filter(contrato__empresa_terceira=fornecedor, coordenador=request.user)
    elif request.user.grupo == "lider_contrato":
        contratos = fornecedor.contratos.filter(lider_contrato=request.user)
        os = OS.objects.filter(contrato__empresa_terceira=fornecedor, lider_contrato=request.user)
    elif request.user.grupo == "gerente_contrato":
        contratos = fornecedor.contratos.filter(lider_contrato__grupo__in=['lider_contrato', 'gerente_contrato'])
        os = OS.objects.filter(contrato__empresa_terceira=fornecedor, lider_contrato__grupo__in=['lider_contrato', 'gerente_contrato'])
    elif request.user.grupo == "gerente":
        contratos = fornecedor.contratos.filter(coordenador__centros__in=request.user.centros.all())
        os = OS.objects.filter(contrato__empresa_terceira=fornecedor, coordenador__centros__in=request.user.centros.all())
    else:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    if request.user.grupo in ["suprimento", "financeiro"]:
        if request.method == "POST":
            form = FornecedorForm(request.POST, instance=fornecedor)
            if form.is_valid():
                form.save()
                messages.success(request, "Dados do Fornecedor atualizado com sucesso!")
                return redirect("lista_fornecedores")
            else:
                messages.error(request, "❌ Ocorreu um erro ao atualizar os dados do Fornecedor. Verifique os campos e tente novamente.")
        else:
            form = FornecedorForm(instance=fornecedor)
        return render(
            request,
            'fornecedores/fornecedor_detail_edit.html',
            {
                'form': form,
                'fornecedor': fornecedor,
                'contratos': contratos,
                'indicadores_geral': indicadores_geral,
                'os': os.distinct(),
                }
        )

    return render(
        request,
        'fornecedores/fornecedor_detail.html',
        {
            'fornecedor': fornecedor,
            'contratos': contratos,
            'indicadores_geral': indicadores_geral,
            'os': os.distinct(),
            }
    )


@login_required
def nova_solicitacao_contrato(request):
    if request.user.grupo in ['coordenador', 'gerente']:
        if request.method == 'POST':
            form = SolicitacaoContratoForm(request.POST, user=request.user)
            if form.is_valid():
                solicitacao = form.save(commit=False)
                solicitacao.coordenador = request.user
                solicitacao.status = "Solicitação de contratação"
                solicitacao.save()

                suprimentos = User.objects.filter(grupo="suprimento").values_list("email", flat=True)

                if suprimentos:
                    assunto = "Nova solicitação de Contratação"
                    mensagem = (
                        f"O usuário {request.user.get_full_name() or request.user.username} "
                        f"deu início a uma solicitação de contratação. \n\n"
                        f"Detalhes da solicitação:\n"
                        f"- ID: {solicitacao.id}\n"
                        f"- Valor Provisionado: {solicitacao.valor_provisionado}\n"
                        f"- Descrição: {solicitacao.descricao}\n\n"
                        "Acesse o sistema HIDROGestão para mais informações.\n"
                        "https://hidrogestao.pythonanywhere.com/"
                    )
                    try:
                        send_mail(
                            assunto, mensagem,
                            "hidro.gestao25@gmail.com",
                            list(suprimentos),
                            fail_silently=False,
                        )
                    except Exception as e:
                        messages.warning(request, f"Erro ao enviar e-mail para suprimentos: {e}")
                    try:
                        send_mail(
                            assunto, mensagem,
                            "hidro.gestao25@gmail.com",
                            list(solicitacao.lider_contrato.email),
                            fail_silently=False,
                        )
                    except Exception as e:
                        messages.warning(request, f"Erro ao enviar e-mail para o líder de contrato: {e}")
                messages.success(request, "Solicitação de contratação criada com sucesso!")
                return redirect('detalhes_solicitacao_contrato', pk=solicitacao.pk )
            else:
                messages.error(request, "Por favor, corrija os erros abaixo e tente novamente.")
        else:
            form = SolicitacaoContratoForm(user=request.user)
        return render(request, 'fornecedores/nova_solicitacao_contrato.html', {'form':form})
    else:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")


@login_required
def aprovar_solicitacao_contrato(request, pk):
    solicitacao = get_object_or_404(SolicitacaoContrato, pk=pk)

    # Somente gerente pode aprovar
    if request.user.grupo not in ["gerente_contrato", "diretoria"]:
        messages.error(request, "Você não tem permissão para aprovar.")
        return redirect('home')

    if request.method == "POST" and request.user.grupo == "gerente_contrato":
        acao = request.POST.get("acao")

        # Busca todos os usuários do grupo 'suprimento'
        emails_suprimentos = list(
            User.objects.filter(grupo="suprimento")
            .exclude(email__isnull=True)
            .exclude(email__exact="")
            .values_list("email", flat=True)
        )

        # Adiciona o e-mail do coordenador do projeto (se existir)
        if solicitacao.coordenador and solicitacao.coordenador.email:
            emails_suprimentos.append(solicitacao.coordenador.email)
        if solicitacao.lider_contrato and solicitacao.lider_contrato.email:
            emails_suprimentos.append(solicitacao.lider_contrato.email)

        assunto = ""
        mensagem = ""

        # --- Caso APROVADO ---
        if acao == "aprovar":
            solicitacao.aprovacao_fornecedor_gerente = "aprovado"
            solicitacao.aprocacao_fornecedor_gerente_em = timezone.now()
            solicitacao.save()

            messages.success(
                request,
                f"Fornecedor {solicitacao.fornecedor_escolhido.nome} foi aprovado pelo gerente de contrato."
            )

            assunto = f"Fornecedor {solicitacao.fornecedor_escolhido.nome} aprovado pela gerência de contrato"
            mensagem = (
                f"Prezados,\n\n"
                f"O gerente {request.user.username} "
                f"aprovou o fornecedor {solicitacao.fornecedor_escolhido.nome} "
                f"na solicitação #{solicitacao.id}.\n\n"
                f"Contrato: {solicitacao.contrato.cod_projeto}\n"
                f"Cliente: {solicitacao.contrato.cliente.nome}\n"
                f"Status atual: {solicitacao.status}\n\n"
                f"Acesse o sistema para mais detalhes."
            )

        # --- Caso REPROVADO ---
        elif acao == "reprovar":
            solicitacao.status = "Fornecedor reprovado pela gerência"
            solicitacao.aprovacao_fornecedor_gerente = "reprovado"
            solicitacao.aprocacao_fornecedor_gerente_em = timezone.now()
            solicitacao.save()

            messages.warning(request, "Fornecedor reprovado.")

            assunto = f"Fornecedor reprovado pela gerência de contrato"
            mensagem = (
                f"Prezados,\n\n"
                f"O gerente {request.user.get_full_name() or request.user.username} "
                f"reprovou o fornecedor selecionado na solicitação #{solicitacao.id}.\n\n"
                f"Contrato: {solicitacao.contrato.cod_projeto}\n"
                f"Cliente: {solicitacao.contrato.cliente.nome}\n\n"
                f"Acesse o sistema para mais detalhes."
            )

        else:
            messages.error(request, "Ação inválida.")
            return redirect('home')

        # Envia o e-mail para todos os destinatários (se houver)
        if emails_suprimentos:
            try:
                send_mail(
                    assunto,
                    mensagem,
                    "hidro.gestao25@gmail.com",
                    list(set(emails_suprimentos)),  # remove duplicados
                    fail_silently=False,
                )
            except Exception as e:
                messages.warning(request, f"Erro ao enviar e-mail para suprimentos: {e}")

        return redirect('lista_solicitacoes')

    elif request.method == "POST" and request.user.grupo == "diretoria":
        acao = request.POST.get("acao")

        # Busca todos os usuários do grupo 'suprimento'
        emails_suprimentos = list(
            User.objects.filter(grupo="suprimento")
            .exclude(email__isnull=True)
            .exclude(email__exact="")
            .values_list("email", flat=True)
        )

        # Adiciona o e-mail do coordenador do projeto (se existir)
        if solicitacao.coordenador and solicitacao.coordenador.email:
            emails_suprimentos.append(solicitacao.coordenador.email)
        if solicitacao.lider_contrato and solicitacao.lider_contrato.email:
            emails_suprimentos.append(solicitacao.lider_contrato.email)

        assunto = ""
        mensagem = ""

        # --- Caso APROVADO ---
        if acao == "aprovar":
            solicitacao.aprovacao_fornecedor_diretor = "aprovado"
            solicitacao.aprocacao_fornecedor_diretor_em = timezone.now()
            solicitacao.save()

            messages.success(
                request,
                f"Fornecedor {solicitacao.fornecedor_escolhido.nome} foi aprovado pela direção."
            )

            assunto = f"Fornecedor {solicitacao.fornecedor_escolhido.nome} aprovado pela direção"
            mensagem = (
                f"Prezados,\n\n"
                f"O diretor {request.user.username} "
                f"aprovou o fornecedor {solicitacao.fornecedor_escolhido.nome} "
                f"na solicitação #{solicitacao.id}.\n\n"
                f"Contrato: {solicitacao.contrato.cod_projeto}\n"
                f"Cliente: {solicitacao.contrato.cliente.nome}\n"
                f"Status atual: {solicitacao.status}\n\n"
                f"Acesse o sistema para mais detalhes."
            )

        # --- Caso REPROVADO ---
        elif acao == "reprovar":
            solicitacao.status = "Fornecedor reprovado pela diretoria"
            solicitacao.aprovacao_fornecedor_diretor = "reprovado"
            solicitacao.save()

            messages.warning(request, "Fornecedor reprovado.")

            assunto = f"Fornecedor reprovado pela direção"
            mensagem = (
                f"Prezados,\n\n"
                f"O diretor {request.user.get_full_name() or request.user.username} "
                f"reprovou o fornecedor selecionado na solicitação #{solicitacao.id}.\n\n"
                f"Contrato: {solicitacao.contrato.cod_projeto}\n"
                f"Cliente: {solicitacao.contrato.cliente.nome}\n\n"
                f"Acesse o sistema para mais detalhes."
            )

        else:
            messages.error(request, "Ação inválida.")
            return redirect('home')

        # Envia o e-mail para todos os destinatários (se houver)
        if emails_suprimentos:
            try:
                send_mail(
                    assunto,
                    mensagem,
                    "hidro.gestao25@gmail.com",
                    list(set(emails_suprimentos)),  # remove duplicados
                    fail_silently=False,
                )
            except Exception as e:
                messages.warning(request, f"Erro ao enviar e-mail para suprimentos: {e}")

        return redirect('lista_solicitacoes')


    return redirect('home')



@login_required
def nova_solicitacao_prospeccao(request):
    if request.user.grupo in ['coordenador', 'gerente']:
        if request.method == 'POST':
            form = SolicitacaoProspeccaoForm(request.POST, user=request.user)
            if form.is_valid():
                solicitacao = form.save(commit=False)
                solicitacao.coordenador = request.user
                solicitacao.status = "Solicitação de prospecção"
                solicitacao.save()

                suprimentos = User.objects.filter(grupo="suprimento").values_list("email", flat=True)

                if suprimentos:
                    assunto = "Nova Solicitação de Prospecção"
                    mensagem = (
                        f"O usuário {request.user.get_full_name() or request.user.username} "
                        f"solicitou uma prospecção.\n\n"
                        f"Detalhes da solicitação:\n"
                        f"- ID: {solicitacao.id}\n"
                        f"- Valor Provisionado: {solicitacao.valor_provisionado}\n"
                        f"- Descrição: {solicitacao.descricao}\n\n"
                        "Acesse o sistema HIDROGestão para mais informações.\n"
                        "https://hidrogestao.pythonanywhere.com/"
                    )
                    try:
                        send_mail(
                            assunto, mensagem,
                            "hidro.gestao25@gmail.com",
                            list(suprimentos),
                            fail_silently=False,
                        )
                    except Exception as e:
                        messages.warning(request, f"Erro ao enviar e-mail para suprimentos: {e}")
                    try:
                        send_mail(
                            assunto, mensagem,
                            "hidro.gestao25@gmail.com",
                            list(solicitacao.lider_contrato.email),
                            fail_silently=False,
                        )
                    except Exception as e:
                        messages.warning(request, f"Erro ao enviar e-mail para o líder de contrato: {e}")
                messages.success(request, "Solicitação de prospecção criada com sucesso!")
                return redirect('lista_solicitacoes')
            else:
                messages.error(request, "Por favor, corrija os erros abaixo e tente novamente.")
        else:
            form = SolicitacaoProspeccaoForm(user=request.user)
        return render(request, 'fornecedores/nova_solicitacao.html', {'form':form})

    else:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")


@login_required
def solicitar_os(request):
    if request.user.grupo not in ['coordenador', 'gerente']:
        messages.error(request, "Você não tem permissão para isso.")
        return redirect("home")

    if request.method == 'POST':
        form = SolicitacaoOrdemServicoForm(request.POST, user=request.user)
        if form.is_valid():
            os = form.save(commit=False)
            os.solicitante = request.user
            os.status = 'pendente_lider'
            os.save()

            assunto = "Nova Solicitação de O.S."
            mensagem = (
                f"O usuário {request.user.get_full_name() or request.user.username} "
                f"solicitou uma Ordem de Serviço.\n\n"
                f"Detalhes da solicitação:\n"
                f"- ID: {os.id}\n"
                f"- Contrato: {os.cod_projeto}\n"
                f"- Valor Provisionado: {os.valor_previsto or 'Não Informado'}\n"
                f"- Descrição: {os.descricao}\n\n"
                "Acesse o sistema HIDROGestão para mais informações.\n"
                "https://hidrogestao.pythonanywhere.com/"
            )
            suprimentos = User.objects.filter(grupo="suprimento").values_list("email", flat=True)
            try:
                send_mail(
                    assunto, mensagem,
                    "hidro.gestao25@gmail.com",
                    list(suprimentos),
                    fail_silently=False,
                )
            except Exception as e:
                messages.warning(request, f"Erro ao enviar e-mail para suprimentos: {e}")

            try:
                send_mail(
                    assunto, mensagem,
                    "hidro.gestao25@gmail.com",
                    list(os.lider_contrato.email),
                    fail_silently=False,
                )
            except Exception as e:
                messages.warning(request, f"Erro ao enviar e-mail para o líder de contrato: {e}")

            messages.success(request, "Ordem de Serviço enviada para aprovação.")
            return redirect("home")
    else:
        form = SolicitacaoOrdemServicoForm(user=request.user)

    return render(request, 'fornecedores/solicitar_os.html', {'form': form})


@login_required
def editar_ordem_servico(request, pk):
    if request.user.grupo not in ['gerente', 'gerente_contrato', 'suprimento']:
        messages.error(request, "Você não tem permissão para isso.")
        return redirect('home')

    os = get_object_or_404(SolicitacaoOrdemServico, pk=pk)

    if request.user.grupo == 'lider_contrato' and os.lider_contrato != request.user:
        messages.error(request, "Você não tem permissão para editar esta OS.")
        return redirect('detalhe_ordem_servico', pk=os.pk)

    if os.status == 'finalizada':
        messages.warning(request, "Esta OS está finalizada e não pode ser editada.")
        return redirect('detalhe_ordem_servico', pk=os.pk)

    if os.status in ['aprovada', 'finalizada']:
        messages.warning(request, "Esta OS não pode mais ser editada.")
        return redirect('detalhe_ordem_servico', pk=os.pk)

    if request.method == 'POST':
        form = SolicitacaoOrdemServicoForm(request.POST, instance=os)
        if form.is_valid():
            form.save()
            messages.success(request, "Ordem de Serviço atualizada com sucesso!")
            return redirect('detalhe_ordem_servico', pk=os.pk)
    else:
        form = SolicitacaoOrdemServicoForm(instance=os)

    context = {
        'form': form,
        'os': os
    }

    return render(request, 'gestao_contratos/editar_ordem_servico.html', context)


@login_required
def aprovar_os_lider(request, pk, acao):
    os = get_object_or_404(SolicitacaoOrdemServico, pk=pk)

    if request.user.grupo != 'lider_contrato':
        messages.error(request, "Você não tem permissão para esta ação.")
        return redirect('detalhe_ordem_servico', pk=os.pk)

    if os.lider_contrato != request.user:
        messages.error(request, "Você não é o líder responsável por esta OS.")
        return redirect('detalhe_ordem_servico', pk=os.pk)

    if os.status != 'pendente_lider':
        messages.warning(request, "Esta OS não está pendente para o líder.")
        return redirect('detalhe_ordem_servico', pk=os.pk)

    if acao == 'aprovar':
        os.status = 'pendente_suprimento'
        os.aprovacao_lider = request.user.username
        os.aprovado_lider_em = timezone.now()
        os.save()
        messages.success(request, "Ordem de Serviço aprovada e enviada para a Gerência.")

        assunto = f"Ciência e Aprovação do Lider de Contrato - OS {os.id}"
        mensagem = (
            f"O usuário {request.user.get_full_name() or request.user.username} "
            f"tomou ciência e aprovou a Ordem de Serviço {os.id}.\n\n"
            "Acesse o sistema HIDROGestão para mais informações.\n"
            "https://hidrogestao.pythonanywhere.com/"
        )
        try:
            send_mail(
                assunto, mensagem,
                "hidro.gestao25@gmail.com",
                [os.solicitante.email],
                fail_silently=False,
            )
        except Exception as e:
            messages.warning(request, f"Erro ao enviar e-mail para líder técnico: {e}")

        emails_suprimentos = list(
            User.objects.filter(grupo="suprimento")
            .exclude(email__isnull=True)
            .exclude(email__exact="")
            .values_list("email", flat=True)
        )
        assunto = f"Necessidade de avaliação de Solicitação da OS {os.id}"
        mensagem = (
            f"O usuário {request.user.get_full_name() or request.user.username} "
            f"tomou ciência e aprovou a Ordem de Serviço {os.id}. "
            f"Solicitamos o desenvolvimento do contrato da OS.\n\n"
            f"Detalhes da O.S.:\n"
            f"- ID: {os.id}\n"
            f"- Líder Técnico: {os.solicitante.username}\n"
            f"- Título: {os.titulo}\n"
            f"- Descrição: {os.descricao}\n"
            f"- Valor Provisionado: {os.valor_previsto or 'Não informado'}\n\n"
            "Acesse o sistema HIDROGestão para mais informações.\n"
            "https://hidrogestao.pythonanywhere.com/"
        )
        try:
            send_mail(
                assunto, mensagem,
                "hidro.gestao25@gmail.com",
                list(set(emails_suprimentos)),
                fail_silently=False,
            )
        except Exception as e:
            messages.warning(request, f"Erro ao enviar e-mail para a equipe de suprimentos: {e}")

    elif acao == 'reprovar':
        os.status = 'reprovada'
        os.aprovacao_lider = request.user.username
        os.aprovado_lider_em = timezone.now()
        os.save()
        messages.error(request, "Ordem de Serviço reprovada.")

        assunto = f"Ciência e Reprovação do Lider de Contrato - OS {os.id}"
        mensagem = (
            f"O usuário {request.user.get_full_name() or request.user.username} "
            f"tomou ciência, no entanto, a Ordem de Serviço {os.id} foi reprovada.\n\n"
            "Acesse o sistema HIDROGestão para mais informações.\n"
            "https://hidrogestao.pythonanywhere.com/"
        )
        try:
            send_mail(
                assunto, mensagem,
                "hidro.gestao25@gmail.com",
                list(os.solicitante.email),
                fail_silently=False,
            )
        except Exception as e:
            messages.warning(request, f"Erro ao enviar e-mail para líder técnico: {e}")

    else:
        messages.error(request, "Ação inválida.")

    return redirect('detalhe_ordem_servico', pk=os.pk)


@login_required
def upload_contrato_os(request, pk):
    os = get_object_or_404(SolicitacaoOrdemServico, pk=pk)

    if request.user.grupo != 'suprimento':
        messages.error(request, "Você não tem permissão para isso!")
        return redirect('detalhe_ordem_servico', pk=os.pk)

    if os.status != 'pendente_suprimento':
        messages.warning(
            request,
            "O contrato só pode ser anexado quando a OS estiver pendente do suprimento."
        )
        return redirect('detalhe_ordem_servico', pk=os.pk)

    if request.method == 'POST':
        form = UploadContratoOSForm(request.POST, request.FILES, instance=os)
        if form.is_valid():
            form.save()

            os.status = 'pendente_gerente'
            os.save()

            messages.success(request, "Contrato anexado com sucesso!")
            return redirect('detalhe_ordem_servico', pk=os.pk)
    else:
        form = UploadContratoOSForm(instance=os)

    return render(
        request,
        'gestao_contratos/upload_contrato_os.html',
        {'form': form, 'os': os}
    )


@login_required
def aprovar_os_gerente_contrato(request, pk, acao):
    os = get_object_or_404(SolicitacaoOrdemServico, pk=pk)

    if request.user.grupo != 'gerente_contrato':
        messages.error(request, "Você não tem permissão para esta ação.")
        return redirect('detalhe_ordem_servico', pk=os.pk)

    if os.status != 'pendente_gerente':
        messages.warning(request, "Esta OS não está pendente da Gerência de Contrato.")
        return redirect('detalhe_ordem_servico', pk=os.pk)

    if acao == 'aprovar':
        os.status = 'aprovada'
        os.aprovacao_lider = request.user.username
        os.aprovado_lider_em = timezone.now()
        os.save()
        messages.success(
            request,
            "Ordem de Serviço aprovada."
        )

        ordem_servico = OS.objects.create(
            contrato=os.contrato,
            solicitacao=os,
            cod_projeto=os.cod_projeto,
            coordenador=os.solicitante,
            lider_contrato=os.lider_contrato,
            titulo=os.titulo,
            descricao=os.descricao,
            valor=os.valor_previsto if os.valor_previsto else None,
            prazo_execucao=os.prazo_execucao if os.prazo_execucao else None,
            arquivo_os=os.arquivo_os if os.arquivo_os else None,
        )
        print(f"Ordem de Serviço criada: {ordem_servico.id}")

        assunto = f"Aprovação da OS {os.id}"
        mensagem = (
            f"O gerente de contrato, {request.user.get_full_name() or request.user.username}, "
            f"aprovou a Ordem de Serviço {os.id}.\n\n"
            "Acesse o sistema HIDROGestão para mais informações.\n"
            "https://hidrogestao.pythonanywhere.com/"
        )
        try:
            send_mail(
                assunto, mensagem,
                "hidro.gestao25@gmail.com",
                [os.solicitante.email],
                fail_silently=False,
            )
        except Exception as e:
            messages.warning(request, f"Erro ao enviar e-mail para líder técnico: {e}")

        emails_suprimentos = list(
            User.objects.filter(grupo="suprimento")
            .exclude(email__isnull=True)
            .exclude(email__exact="")
            .values_list("email", flat=True)
        )
        try:
            send_mail(
                assunto, mensagem,
                "hidro.gestao25@gmail.com",
                list(set(emails_suprimentos)),
                fail_silently=False,
            )
        except Exception as e:
            messages.warning(request, f"Erro ao enviar e-mail para a equipe de suprimentos: {e}")



    elif acao == 'reprovar':
        os.status = 'reprovada'
        os.aprovacao_lider = request.user.username
        os.aprovado_lider_em = timezone.now()
        os.save()
        messages.error(request, "Ordem de Serviço reprovada pela Gerência de Contrato.")

        assunto = f"Reprovação da OS {os.id}"
        mensagem = (
            f"O gerente de contrato, {request.user.get_full_name() or request.user.username}, "
            f"reprovou a Ordem de Serviço {os.id}.\n\n"
            "Acesse o sistema HIDROGestão para mais informações.\n"
            "https://hidrogestao.pythonanywhere.com/"
        )
        try:
            send_mail(
                assunto, mensagem,
                "hidro.gestao25@gmail.com",
                [os.solicitante.email],
                fail_silently=False,
            )
        except Exception as e:
            messages.warning(request, f"Erro ao enviar e-mail para líder técnico: {e}")

        emails_suprimentos = list(
            User.objects.filter(grupo="suprimento")
            .exclude(email__isnull=True)
            .exclude(email__exact="")
            .values_list("email", flat=True)
        )
        try:
            send_mail(
                assunto, mensagem,
                "hidro.gestao25@gmail.com",
                list(set(emails_suprimentos)),
                fail_silently=False,
            )
        except Exception as e:
            messages.warning(request, f"Erro ao enviar e-mail para a equipe de suprimentos: {e}")

    else:
        messages.error(request, "Ação inválida.")

    return redirect('detalhe_ordem_servico', pk=os.pk)


@login_required
def lista_solicitacoes(request):
    #if request.user.grupo == 'coordenador' or request.user.grupo == 'financeiro':
    if request.user.grupo == 'coordenador':
        solicitacoes = SolicitacaoProspeccao.objects.filter(coordenador=request.user).exclude(status__in=["Onboarding", "Reprovada pelo suprimento"]).order_by('-data_solicitacao')
        solicitacoes_c = SolicitacaoContrato.objects.filter(coordenador=request.user).exclude(status__in=["Onboarding", "Reprovada pelo suprimento"]).order_by('-data_solicitacao')
        os = OS.objects.filter(coordenador=request.user).exclude(status__in=["finalizada", "aprovada", "reprovada"]).order_by('-criado_em')
    elif request.user.grupo == 'lider_contrato':
        solicitacoes = SolicitacaoProspeccao.objects.filter(lider_contrato=request.user).exclude(status__in=["Onboarding", "Reprovada pelo suprimento"]).order_by('-data_solicitacao')
        solicitacoes_c = SolicitacaoContrato.objects.filter(lider_contrato=request.user).exclude(status__in=["Onboarding", "Reprovada pelo suprimento"]).order_by('-data_solicitacao')
        os = OS.objects.filter(lider_contrato=request.user).exclude(status__in=["finalizada", "aprovada", "reprovada"]).order_by('-criado_em')
    elif request.user.grupo in ['suprimento', 'diretoria']:
        solicitacoes = SolicitacaoProspeccao.objects.all().exclude(status__in=["Onboarding", "Reprovada pelo suprimento"]).order_by('-data_solicitacao')
        solicitacoes_c = SolicitacaoContrato.objects.all().exclude(status__in=["Onboarding", "Reprovada pelo suprimento"]).order_by('-data_solicitacao')
        os = OS.objects.all().exclude(status__in=["finalizada", "aprovada", "reprovada"]).order_by('-criado_em')
    elif request.user.grupo == 'gerente':
        centros_do_gerente = request.user.centros.all()
        # filtra solicitações cujo solicitante tenha pelo menos um centro em comum
        solicitacoes = SolicitacaoProspeccao.objects.filter(
            coordenador__centros__in=centros_do_gerente
        ).exclude(status__in=["Onboarding", "Reprovada pelo suprimento"]).distinct().order_by('-data_solicitacao')
        solicitacoes_c = SolicitacaoContrato.objects.filter(coordenador__centros__in=centros_do_gerente).exclude(status__in=["Onboarding", "Reprovada pelo suprimento"]).order_by('-data_solicitacao')
        os = OS.objects.filter(coordenador__centros__in=centros_do_gerente).exclude(status__in=["finalizada", "aprovada", "reprovada"]).order_by('-criado_em')
    elif request.user.grupo == 'gerente_contrato':
        solicitacoes = SolicitacaoProspeccao.objects.filter(
            lider_contrato__grupo__in=['lider_contrato', 'gerente_contrato']
        ).exclude(status__in=["Onboarding", "Reprovada pelo suprimento"]).distinct().order_by('-data_solicitacao')
        solicitacoes_c = SolicitacaoContrato.objects.filter(lider_contrato__grupo__in=['lider_contrato', 'gerente_contrato']).exclude(status__in=["Onboarding", "Reprovada pelo suprimento"]).order_by('-data_solicitacao')
        os = OS.objects.filter(lider_contrato__grupo__in=['lider_contrato', 'gerente_contrato']).exclude(status__in=["finalizada", "aprovada", "reprovada"]).order_by('-criado_em')
    else:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    lista_solicitacoes = []
    for s in solicitacoes:
        proposta_escolhida = PropostaFornecedor.objects.filter(
            solicitacao=s,
            fornecedor=s.fornecedor_escolhido
        ).first()

        contrato = DocumentoContratoTerceiro.objects.filter(solicitacao=s).first()
        lista_solicitacoes.append({
            "solicitacao": s,
            "fornecedor": s.fornecedor_escolhido,
            "proposta": proposta_escolhida,
            "contrato": contrato
        })

    for s in solicitacoes_c:
        proposta_escolhida = None

        contrato = None
        lista_solicitacoes.append({
            "solicitacao": s,
            "fornecedor": s.fornecedor_escolhido,
            "proposta": proposta_escolhida,
            "contrato": contrato
        })

    paginator = Paginator(solicitacoes, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    paginator_c = Paginator(solicitacoes_c, 10)
    page_number_c = request.GET.get('page_c')
    page_obj_c = paginator_c.get_page(page_number_c)

    paginator_os = Paginator(os, 10)
    page_number_os = request.GET.get('page_os')
    page_obj_os = paginator_os.get_page(page_number_os)

    context = {
            'page_obj': page_obj,
            'page_obj_contrato': page_obj_c,
            "lista_solicitacoes": lista_solicitacoes,
            'ordens_servico_page': page_obj_os
        }

    return render(request, 'gestao_contratos/lista_solicitacoes.html', context)


@login_required
def aprovar_solicitacao(request, pk, acao):
    if request.user.grupo not in ["suprimento"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)
    if acao == "aprovar":
        solicitacao.status = "Aprovada pelo suprimento"
        solicitacao.aprovado = True
    elif acao == "reprovar":
        solicitacao.status = "Reprovada pelo suprimento"
        solicitacao.aprovado = False

        coordenador = solicitacao.coordenador
        assunto = "Solicitação reprovada"
        mensagem = (
            f"Olá, {coordenador.username}\n\n"
            f"A solicitação de prospecção foi reprovada. \n\n"
            "Por favor, entre no sistema HIDROGestão para mais informações.\n"
            "https://hidrogestao.pythonanywhere.com/"
        )
        try:
            send_mail(
                assunto, mensagem,
                "hidro.gestao25@gmail.com",
                [coordenador.email],
                fail_silently=False,
            )
        except Exception as e:
            messages.warning(request, f"Erro ao enviar e-mail para {coordenador.username}: {e}")

    solicitacao.data_aprovacao = timezone.now()
    solicitacao.aprovado_por = request.user
    solicitacao.save()

    return redirect('lista_solicitacoes')


@login_required
def triagem_fornecedores(request, pk):
    if request.user.grupo not in ["suprimento"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    condicoes_choices = PropostaFornecedor.CONDICOES_CHOICES
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk, aprovado=True)
    fornecedores = EmpresaTerceira.objects.all().order_by('nome')

    # Mapeia fornecedores -> indicadores
    fornecedores_indicadores = {
        f.id: Indicadores.objects.filter(empresa_terceira=f) or None
        for f in fornecedores
    }

    # Mapeia propostas -> todos os fornecedores
    propostas_dict = {}
    for f in fornecedores:
        try:
            propostas_dict[f.id] = PropostaFornecedor.objects.get(solicitacao=solicitacao, fornecedor=f)
        except PropostaFornecedor.DoesNotExist:
            propostas_dict[f.id] = None

    if request.method == "POST":
        fornecedores_ids = request.POST.getlist("fornecedores")

        if "nenhum_fornecedor" in request.POST:
            solicitacao.fornecedores_selecionados.clear()
            solicitacao.triagem_realizada = False
            solicitacao.status = "Sem fornecedor adequado"
            solicitacao.save()
            messages.info(request, "Nenhum fornecedor foi considerado ideal.")
            return redirect("lista_solicitacoes")

        if fornecedores_ids:
            # Atualiza os fornecedores selecionados
            solicitacao.fornecedores_selecionados.set(fornecedores_ids)
            solicitacao.triagem_realizada = True
            solicitacao.status = "Triagem realizada"
            solicitacao.nenhum_fornecedor_ideal = False
            solicitacao.save()

            # Para cada fornecedor selecionado, salva/atualiza proposta
            for f_id in fornecedores_ids:
                fornecedor = get_object_or_404(EmpresaTerceira, pk=f_id)
                valor = request.POST.get(f"valor_{f_id}")
                prazo_validade = request.POST.get(f"prazo_{f_id}")
                condicao = request.POST.get(f"condicao_{f_id}")
                arquivo = request.FILES.get(f"arquivo_{f_id}")

                if valor or arquivo or condicao or prazo_validade:
                    proposta_obj, _ = PropostaFornecedor.objects.get_or_create(
                        solicitacao=solicitacao,
                        fornecedor=fornecedor,
                    )
                    if valor:
                        try:
                            proposta_obj.valor_proposta = float(valor.replace(",", "."))
                        except ValueError:
                            messages.warning(request, f"Valor inválido para {fornecedor.nome}")
                    if prazo_validade:
                        proposta_obj.prazo_validade = prazo_validade
                    if arquivo:
                        proposta_obj.arquivo_proposta = arquivo
                    if condicao:
                        proposta_obj.condicao_pagamento = condicao
                    proposta_obj.save()

            # Notifica coordenador
            coordenador = solicitacao.coordenador
            #lider = solicitacao.lider_contrato
            assunto = "Triagem de fornecedores realizada"
            mensagem = (
                f"Olá, {coordenador.username}\n\n"
                f"A equipe de suprimentos realizou uma triagem de fornecedores para você. \n\n"
                "Por favor, entre no sistema HIDROGestão para selecionar sua escolha.\n"
                "https://hidrogestao.pythonanywhere.com/"
            )
            try:
                send_mail(
                    assunto, mensagem,
                    "hidro.gestao25@gmail.com",
                    [coordenador.email],
                    fail_silently=False,
                )
            except Exception as e:
                messages.warning(request, f"Erro ao enviar e-mail para {coordenador.username}: {e}")

            #try:
            #    send_mail(
            #        assunto, mensagem,
            #        "hidro.gestao25@gmail.com",
            #        [lider.email],
            #        fail_silently=False,
            #    )
            #except Exception as e:
            #    messages.warning(request, f"Erro ao enviar e-mail para {lider.username}: {e}")
            messages.success(request, "Triagem e propostas salvas com sucesso!")
            return redirect("lista_solicitacoes")

        else:
            solicitacao.fornecedores_selecionados.clear()
            solicitacao.triagem_realizada = False
            messages.warning(request, "Nenhum fornecedor foi selecionado.")
            return redirect("lista_solicitacoes")

    context = {
        'solicitacao': solicitacao,
        'fornecedores': fornecedores,
        'fornecedores_selecionados': solicitacao.fornecedores_selecionados.all(),
        'fornecedores_indicadores': fornecedores_indicadores,
        'propostas_dict': propostas_dict,
        'condicoes_choices': condicoes_choices,
    }
    return render(request, 'fornecedores/triagem_fornecedores.html', context)


@login_required
def nenhum_fornecedor_ideal(request, pk):
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)
    if request.user != solicitacao.lider_contrato:
        messages.error(request, "Você não tem permissão para essa ação.")
        return redirect("lista_solicitacoes")

    if request.method == "POST":
        solicitacao.nenhum_fornecedor_ideal = True
        solicitacao.fornecedores_selecionados.clear()
        solicitacao.triagem_realizada = False
        solicitacao.save()

        suprimentos = User.objects.filter(grupo="suprimento").values_list("email", flat=True)

        if suprimentos:
            assunto = "Triagem declarada ineficaz pelo líder de contrato"
            mensagem = (
                f"Olá,\n\n"
                f"O líder de contrato {solicitacao.lider_contrato.username} declarou que nenhum dos fornecedores é ideal."
                "Acesse o sistema HIDROGestão para mais informações.\n"
                "https://hidrogestao.pythonanywhere.com/"
            )
            try:
                send_mail(
                    assunto, mensagem,
                    "hidro.gestao25@gmail.com",
                    list(suprimentos),
                    fail_silently=False,
                )
            except Exception as e:
                messages.warning(request, f"Erro ao enviar e-mail para suprimentos: {e}")
        messages.success(request, "Solicitação atualizada: nenhum fornecedor é ideal.")
    return redirect("lista_solicitacoes")


@login_required
def detalhes_triagem_fornecedores(request, pk):
    solicitacao = get_object_or_404(
        SolicitacaoProspeccao, pk=pk, aprovado=True, triagem_realizada=True
    )
    fornecedores_selecionados = solicitacao.fornecedores_selecionados.all()

    # Mapeia propostas por fornecedor
    propostas_dict = {}
    propostas = PropostaFornecedor.objects.filter(solicitacao=solicitacao)
    for p in propostas:
        propostas_dict[p.fornecedor.id] = p

    # Coordenador escolhe fornecedor
    #if request.user == solicitacao.coordenador and request.method == "POST":
    if request.user == solicitacao.lider_contrato and request.method == "POST":
        escolhido_id = request.POST.get("fornecedor_escolhido")
        justificativa = request.POST.get("justificativa_fornecedor_escolhido", "").strip()

        if escolhido_id:
            if not justificativa:
                messages.warning(request, "Por favor, insira uma justificativa para a escolha do fornecedor.")
                return redirect('detalhes_triagem_fornecedores', pk=pk)

            fornecedor = get_object_or_404(EmpresaTerceira, pk=escolhido_id)
            solicitacao.fornecedor_escolhido = fornecedor
            solicitacao.justificativa_fornecedor_escolhido = justificativa
            solicitacao.nenhum_fornecedor_ideal = False
            solicitacao.status = 'Fornecedor selecionado'
            solicitacao.aprovacao_gerente = "pendente"
            solicitacao.save()

            # notifica gerente
            gerentes = list(User.objects.filter(
                grupo="gerente_contrato"
            ).distinct().values_list("email", flat=True))

            if gerentes:
                assunto = f"Aprovação necessária - Fornecedor escolhido para {solicitacao.contrato}"
                mensagem = (
                    f"O coordenador {solicitacao.coordenador.username} selecionou o fornecedor {fornecedor.nome}.\n"
                    f"Justificativa: {justificativa}\n\n"
                    f"É necessário que você aprove ou reprove essa escolha.\n"
                    f"Acesse o sistema HIDROGestão para mais informações:\n"
                    f"https://hidrogestao.pythonanywhere.com/"
                )
                try:
                    send_mail(
                        assunto, mensagem,
                        "hidro.gestao25@gmail.com",
                        gerentes,
                        fail_silently=False,
                    )
                except Exception as e:
                    messages.warning(request, f"Erro ao enviar e-mail para gerente: {e}")

            messages.success(request, f"Fornecedor {fornecedor.nome} selecionado. Aguardando aprovação do gerente.")
        return redirect('lista_solicitacoes')

    context = {
        "solicitacao": solicitacao,
        "fornecedores_selecionados": fornecedores_selecionados,
        "propostas_dict": propostas_dict,
    }
    return render(request, "fornecedores/detalhes_triagem_fornecedores.html", context)


@login_required
def aprovar_fornecedor_gerente(request, pk):
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)

    # Somente gerente pode aprovar
    if request.user.grupo != "gerente_contrato":
        messages.error(request, "Você não tem permissão para aprovar.")
        return redirect('home')

    # Verifica se o coordenador já escolheu um fornecedor
    if not solicitacao.fornecedor_escolhido:
        messages.warning(request, "Coordenador ainda não escolheu um fornecedor.")
        return redirect('detalhes_triagem_fornecedores', pk=pk)

    if request.method == "POST":
        acao = request.POST.get("acao")
        justificativa = request.POST.get("justificativa", "")

        # Busca todos os usuários do grupo 'suprimento'
        emails_suprimentos = list(
            User.objects.filter(grupo="suprimento")
            .exclude(email__isnull=True)
            .exclude(email__exact="")
            .values_list("email", flat=True)
        )

        # Adiciona o e-mail do coordenador do projeto (se existir)
        if solicitacao.coordenador and solicitacao.coordenador.email:
            emails_suprimentos.append(solicitacao.coordenador.email)
        if solicitacao.lider_contrato and solicitacao.lider_contrato.email:
            emails_suprimentos.append(solicitacao.lider_contrato.email)

        assunto = ""
        mensagem = ""

        # --- Caso APROVADO ---
        if acao == "aprovar":

            solicitacao.aprovacao_fornecedor_gerente = "aprovado"
            solicitacao.aprocacao_fornecedor_gerente_em = timezone.now()
            solicitacao.save()

            messages.success(
                request,
                f"Fornecedor {solicitacao.fornecedor_escolhido.nome} aprovado pelo gerente de contrato."
            )

            if solicitacao.aprovacao_fornecedor_diretor == "aprovado":
                solicitacao.status = "Fornecedor aprovado"
                solicitacao.save()

                assunto = f"Fornecedor {solicitacao.fornecedor_escolhido.nome} aprovado pela gerência de contrato"
                mensagem = (
                    f"Prezados,\n\n"
                    f"O gerente {request.user.username} "
                    f"aprovou o fornecedor {solicitacao.fornecedor_escolhido.nome} "
                    f"na solicitação #{solicitacao.id}.\n\n"
                    f"Contrato: {solicitacao.contrato.cod_projeto}\n"
                    f"Cliente: {solicitacao.contrato.cliente.nome}\n"
                    f"Status atual: {solicitacao.status}\n\n"
                    f"Acesse o sistema para mais detalhes."
                )

                # Envia o e-mail para todos os destinatários (se houver)
                if emails_suprimentos:
                    try:
                        send_mail(
                            assunto,
                            mensagem,
                            "hidro.gestao25@gmail.com",
                            list(set(emails_suprimentos)),  # remove duplicados
                            fail_silently=False,
                        )
                    except Exception as e:
                        messages.warning(request, f"Erro ao enviar e-mail para suprimentos: {e}")

        # --- Caso REPROVADO ---
        elif acao == "reprovar":
            solicitacao.status = "Fornecedor reprovado pela gerência"
            solicitacao.aprovacao_fornecedor_gerente = "reprovado"
            solicitacao.aprocacao_fornecedor_gerente_em = timezone.now()
            solicitacao.fornecedor_escolhido = None
            solicitacao.triagem_realizada = False
            solicitacao.fornecedores_selecionados.clear()
            solicitacao.justificativa_gerencia = justificativa
            solicitacao.save()

            messages.warning(request, "Fornecedor reprovado. Nova triagem necessária pelo suprimento.")

            assunto = f"Fornecedor reprovado pela gerência de contrato"
            mensagem = (
                f"Prezados,\n\n"
                f"O gerente {request.user.get_full_name() or request.user.username} "
                f"reprovou o fornecedor selecionado na solicitação #{solicitacao.id}.\n\n"
                f"Contrato: {solicitacao.contrato.cod_projeto}\n"
                f"Cliente: {solicitacao.contrato.cliente.nome}\n\n"
                f"Uma nova triagem será necessária pelo setor de suprimentos.\n\n"
                f"Acesse o sistema para mais detalhes."
            )

            # Envia o e-mail para todos os destinatários (se houver)
            if emails_suprimentos:
                try:
                    send_mail(
                        assunto,
                        mensagem,
                        "hidro.gestao25@gmail.com",
                        list(set(emails_suprimentos)),  # remove duplicados
                        fail_silently=False,
                    )
                except Exception as e:
                    messages.warning(request, f"Erro ao enviar e-mail para suprimentos: {e}")

        else:
            messages.error(request, "Ação inválida.")
            return redirect('detalhes_triagem_fornecedores', pk=pk)

        return redirect('lista_solicitacoes')

    return redirect('detalhes_triagem_fornecedores', pk=pk)


@login_required
def aprovar_fornecedor_diretor(request, pk):
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)

    # Somente gerente pode aprovar
    if request.user.grupo != "diretoria":
        messages.error(request, "Você não tem permissão para aprovar.")
        return redirect('home')

    # Verifica se o coordenador já escolheu um fornecedor
    if not solicitacao.fornecedor_escolhido:
        messages.warning(request, "Coordenador ainda não escolheu um fornecedor.")
        return redirect('detalhes_triagem_fornecedores', pk=pk)

    if request.method == "POST":
        acao = request.POST.get("acao")
        justificativa = request.POST.get("justificativa", "")

        # Busca todos os usuários do grupo 'suprimento'
        emails_suprimentos = list(
            User.objects.filter(grupo="suprimento")
            .exclude(email__isnull=True)
            .exclude(email__exact="")
            .values_list("email", flat=True)
        )

        # Adiciona o e-mail do coordenador do projeto (se existir)
        if solicitacao.coordenador and solicitacao.coordenador.email:
            emails_suprimentos.append(solicitacao.coordenador.email)
        if solicitacao.lider_contrato and solicitacao.lider_contrato.email:
            emails_suprimentos.append(solicitacao.lider_contrato.email)

        assunto = ""
        mensagem = ""

        # --- Caso APROVADO ---
        if acao == "aprovar":
            solicitacao.aprovacao_fornecedor_diretor = "aprovado"
            solicitacao.aprocacao_fornecedor_diretor_em = timezone.now()
            solicitacao.save()

            messages.success(
                request,
                f"Fornecedor {solicitacao.fornecedor_escolhido.nome} aprovado pela diretoria de contrato."
            )

            if solicitacao.aprovacao_fornecedor_gerente == "aprovado":
                solicitacao.status = "Fornecedor aprovado"
                solicitacao.save()
                assunto = f"Fornecedor {solicitacao.fornecedor_escolhido.nome} aprovado pela diretoria de contrato"
                mensagem = (
                    f"Prezados,\n\n"
                    f"O diretor {request.user.username} "
                    f"aprovou o fornecedor {solicitacao.fornecedor_escolhido.nome} "
                    f"na solicitação #{solicitacao.id}.\n\n"
                    f"Contrato: {solicitacao.contrato.cod_projeto}\n"
                    f"Cliente: {solicitacao.contrato.cliente.nome}\n"
                    f"Status atual: {solicitacao.status}\n\n"
                    f"Acesse o sistema para mais detalhes."
                )

                # Envia o e-mail para todos os destinatários (se houver)
                if emails_suprimentos:
                    try:
                        send_mail(
                            assunto,
                            mensagem,
                            "hidro.gestao25@gmail.com",
                            list(set(emails_suprimentos)),  # remove duplicados
                            fail_silently=False,
                        )
                    except Exception as e:
                        messages.warning(request, f"Erro ao enviar e-mail para suprimentos: {e}")

        # --- Caso REPROVADO ---
        elif acao == "reprovar":
            solicitacao.status = "Fornecedor reprovado"
            solicitacao.aprovacao_fornecedor_diretor = "reprovado"
            solicitacao.aprocacao_fornecedor_diretor_em = timezone.now()
            solicitacao.fornecedor_escolhido = None
            solicitacao.triagem_realizada = False
            solicitacao.fornecedores_selecionados.clear()
            solicitacao.justificativa_diretoria = justificativa
            solicitacao.save()

            messages.warning(request, "Fornecedor reprovado. Nova triagem necessária pelo suprimento.")

            assunto = f"Fornecedor reprovado pela diretoria de contrato"
            mensagem = (
                f"Prezados,\n\n"
                f"O diretor {request.user.get_full_name() or request.user.username} "
                f"reprovou o fornecedor selecionado na solicitação #{solicitacao.id}.\n\n"
                f"Contrato: {solicitacao.contrato.cod_projeto}\n"
                f"Cliente: {solicitacao.contrato.cliente.nome}\n\n"
                f"Uma nova triagem será necessária pelo setor de suprimentos.\n\n"
                f"Acesse o sistema para mais detalhes."
            )

            # Envia o e-mail para todos os destinatários (se houver)
            if emails_suprimentos:
                try:
                    send_mail(
                        assunto,
                        mensagem,
                        "hidro.gestao25@gmail.com",
                        list(set(emails_suprimentos)),  # remove duplicados
                        fail_silently=False,
                    )
                except Exception as e:
                    messages.warning(request, f"Erro ao enviar e-mail para suprimentos: {e}")

        else:
            messages.error(request, "Ação inválida.")
            return redirect('detalhes_triagem_fornecedores', pk=pk)

        return redirect('lista_solicitacoes')

    return redirect('detalhes_triagem_fornecedores', pk=pk)


@login_required
def detalhes_solicitacao_contrato(request, pk):
    # Busca a solicitação
    solicitacao = get_object_or_404(SolicitacaoContrato, pk=pk)

    status_order = [
        "Solicitação de contratação",
        "Fornecedor aprovado",
        "Planejamento do Contrato",
        "Aprovação do Planejamento",
        "Onboarding",
    ]

    if request.method == "POST":
        acao = request.POST.get("acao")
        justificativa = request.POST.get("justificativa", "")

        # GERENTE DE CONTRATO
        if request.user.grupo == "gerente_contrato":
            if acao == "aprovar":
                solicitacao.aprovacao_fornecedor_gerente = "aprovado"
                solicitacao.aprocacao_fornecedor_gerente_em = timezone.now()
            elif acao == "reprovar":
                solicitacao.aprovacao_fornecedor_gerente = "reprovado"
                solicitacao.aprocacao_fornecedor_gerente_em = timezone.now()
                solicitacao.justificativa_gerencia = justificativa

        # DIRETORIA
        elif request.user.grupo == "diretoria":
            if acao == "aprovar":
                solicitacao.aprovacao_fornecedor_diretor = "aprovado"
                solicitacao.aprocacao_fornecedor_diretor_em = timezone.now()
            elif acao == "reprovar":
                solicitacao.aprovacao_fornecedor_diretor = "reprovado"
                solicitacao.aprocacao_fornecedor_diretor_em = timezone.now()
                solicitacao.justificativa_diretoria = justificativa

        if solicitacao.aprovacao_fornecedor_gerente == "aprovado"  and solicitacao.aprovacao_fornecedor_diretor == "aprovado":
            solicitacao.status = "Fornecedor aprovado"
            solicitacao.save()
            suprimentos = User.objects.filter(grupo="suprimento").values_list("email", flat=True)

            if suprimentos:
                assunto = "Aprovação de Solicitação de Contratação"
                mensagem = (
                    f"O HIDROGestão informa que a Solicitação de Contrato e o Fornecedor escolhido \n"
                    f"foram aprovados pelo Gerente de Contrato e pela Diretoria.\n\n"

                    f"Dessa forma, o processo encontra-se liberado para a etapa de Suprimentos, \n"
                    f"cabendo a este setor a elaboração e inserção no sistema da \n"
                    f"Minuta do BM (Boletim de Medição) e da Minuta do Contrato. \n\n"

                    f"Acesse o sistema HIDROGestão para mais informações.\n"
                    f"https://hidrogestao.pythonanywhere.com/"
                )
                try:
                    send_mail(
                        assunto, mensagem,
                        "hidro.gestao25@gmail.com",
                        list(suprimentos),
                        fail_silently=False,
                    )
                except Exception as e:
                    messages.warning(request, f"Erro ao enviar e-mail para suprimentos: {e}")
        elif solicitacao.aprovacao_fornecedor_gerente == "reprovado" or solicitacao.aprovacao_fornecedor_diretor == "reprovado":
            solicitacao.status = "Solicitação de contratação"
        solicitacao.save()
        return redirect("detalhes_solicitacao_contrato", pk=solicitacao.pk)

    fornecedor_escolhido = solicitacao.fornecedor_escolhido

    proposta_escolhida = None
    indicadores = None

    if fornecedor_escolhido:
        # Busca a proposta do fornecedor escolhido nesta solicitação
        proposta_escolhida = None

        # Busca indicadores do fornecedor escolhido
        indicadores = Indicadores.objects.filter(
            empresa_terceira=fornecedor_escolhido
        )

    eventos = solicitacao.evento_set.all()

    current_index = status_order.index(solicitacao.status)+1 if solicitacao.status in status_order else 0
    progress_percent = "{:.2f}".format((current_index / (len(status_order))) * 100)

    context = {
        "solicitacao": solicitacao,
        "fornecedor_escolhido": fornecedor_escolhido,
        "proposta_escolhida": proposta_escolhida,
        "indicadores": indicadores,
        "status_order": status_order,
        "current_index": current_index,
        "progress_percent": progress_percent,
        "eventos": eventos,
    }

    return render(request, "gestao_contratos/detalhes_solicitacao_contratacao.html", context)


@login_required
def detalhes_solicitacao(request, pk):
    # Busca a solicitação
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)

    status_order = [
        "Solicitação de prospecção",
        "Aprovada pelo suprimento",
        "Triagem realizada",
        "Fornecedor selecionado",
        "Fornecedor aprovado",
        "Planejamento do Contrato",
        "Aprovação do Planejamento",
        "Onboarding",
    ]

    fornecedor_escolhido = solicitacao.fornecedor_escolhido
    fornecedores_selecionados = solicitacao.fornecedores_selecionados.all()

    proposta_escolhida = None
    indicadores = None

    if fornecedor_escolhido:
        # Busca a proposta do fornecedor escolhido nesta solicitação
        proposta_escolhida = PropostaFornecedor.objects.filter(
            solicitacao=solicitacao,
            fornecedor=fornecedor_escolhido
        ).first()

        # Busca indicadores do fornecedor escolhido
        indicadores = Indicadores.objects.filter(
            empresa_terceira=fornecedor_escolhido
        )

    eventos = solicitacao.evento_set.all()

    current_index = status_order.index(solicitacao.status)+1 if solicitacao.status in status_order else 0
    progress_percent = "{:.2f}".format((current_index / (len(status_order))) * 100)

    context = {
        "solicitacao": solicitacao,
        "fornecedor_escolhido": fornecedor_escolhido,
        "proposta_escolhida": proposta_escolhida,
        "fornecedores_selecionados": fornecedores_selecionados,
        "indicadores": indicadores,
        "status_order": status_order,
        "current_index": current_index,
        "progress_percent": progress_percent,
        "eventos": eventos,
    }

    return render(request, "gestao_contratos/detalhes_solicitacao.html", context)


@login_required
def detalhe_os(request, pk):
    if request.user.grupo not in ['suprimento', 'lider_contrato', 'coordenador', 'gerente', 'gerente_contrato']:
        messages.error(request, "Você não tem permissão para isso.")
        return redirect('home')

    os = get_object_or_404(SolicitacaoOrdemServico, pk=pk)

    if request.user.grupo == 'lider_contrato' and os.lider_contrato != request.user:
        messages.error(request, "Você não tem permissão para visualizar esta OS.")
        return redirect('lista_solicitacoes')

    if request.user.grupo == 'coordenador' and os.solicitante != request.user:
        messages.error(request, "Você não tem permissão para visualizar esta OS.")
        return redirect('lista_solicitacoes')

    status_order = [
        'Solicitação de OS',
        'Pendente Líder',
        'Pendente Gerente',
        'Pendente Suprimento',
        'Aprovada',
    ]

    status_map = {
        'solicitacao_os': 0,
        'pendente_lider': 1,
        'pendente_gerente': 2,
        'pendente_suprimento': 3,
        'aprovada': 4,
    }

    current_index = status_map.get(os.status, 0)

    total_steps = len(status_order)

    if total_steps > 1:
        progress_percent = int((current_index / (total_steps - 1)) * 100)
    else:
        progress_percent = 0

    context = {
        'os': os,
        'status_order': status_order,
        'current_index': current_index,
        'total_steps': len(status_order),
        'progress_percent': progress_percent,
    }

    return render(request, 'gestao_contratos/detalhe_os.html', context)


@login_required
def lista_ordens_servico(request):
    if request.user.grupo in ['suprimento', 'financeiro', 'diretoria']:
        os = OS.objects.all()
    elif request.user.grupo == 'coordenador':
        os = OS.objects.filter(coordenador=request.user)
    elif request.user.grupo == 'lider_contrato':
        os = OS.objects.filter(lider_contrato=request.user)
    elif request.user.grupo == 'gerente':
        os = OS.objects.filter(coordenador__centros__in=request.user.centros.all())
    elif request.user.grupo == 'gerente_contrato':
        os = OS.objects.filter(lider_contrato__grupo='lider_contrato')
    else:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    data_limite = timezone.now().date() - timedelta(days=60)
    os = os.exclude(status='finalizada', data_pagamento__lte=data_limite)
    os = os.exclude(status='cancelada', prazo_execucao__lte=data_limite)

    search_query = request.GET.get('search', '').strip()

    if search_query:
        os = os.filter(
            Q(cod_projeto__cod_projeto__icontains=search_query) |
            Q(solicitante__username__icontains=search_query) |
            Q(cod_projeto__cliente__nome__icontains=search_query) |
            Q(titulo__icontains=search) |
            Q(num_contrato__icontains=search_query)
        ).order_by('-criado_em')

    paginator = Paginator(os, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
    }

    return render(request, 'gestao_contratos/lista_ordens_servico.html', context)

@login_required
def propostas_fornecedores(request, pk):
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)

    fornecedores = solicitacao.fornecedores_selecionados.all()
    PropostaFormSet = modelformset_factory( PropostaFornecedor, form=PropostaFornecedorForm, extra=0, can_delete=False)

    for f in fornecedores:
        PropostaFornecedor.objects.get_or_create(solicitacao=solicitacao, fornecedor=f)

    queryset = PropostaFornecedor.objects.filter(solicitacao=solicitacao)
    if request.method == "POST":
        formset = PropostaFormSet(request.POST, request.FILES, queryset=queryset)
        if formset.is_valid():
            formset.save()
            messages.success(request, "Propostas salvas com sucesso!")
            return redirect("lista_solicitacoes")
    else:
        formset = PropostaFormSet(queryset=queryset)

    context = {"solicitacao": solicitacao, "formset": formset}

    return render(request, "fornecedores/propostas_fornecedores.html", context)


@login_required
def cadastrar_propostas(request, pk):
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk, aprovado=True)

    # Apenas comercial pode cadastrar propostas
    if request.user.grupo != "Suprimento":
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    fornecedores = solicitacao.fornecedores_selecionados.all()

    if request.method == "POST":
        for fornecedor in fornecedores:
            valor = request.POST.get(f"valor_{fornecedor.id}")
            prazo = request.POST.get(f"prazo_{fornecedor.id}")
            arquivo = request.FILES.get(f"arquivo_{fornecedor.id}")

            proposta, created = PropostaFornecedor.objects.get_or_create(
                solicitacao=solicitacao,
                fornecedor=fornecedor,
            )

            if valor:
                proposta.valor_total = valor
            if prazo:
                proposta.prazo_validade = prazo
            if arquivo:
                proposta.arquivo_proposta = arquivo

            proposta.save()

        messages.success(request, "Propostas salvas com sucesso!")
        return redirect("lista_solicitacoes")

    context = {
        "solicitacao": solicitacao,
        "fornecedores": fornecedores,
    }
    return render(request, "fornecedores/cadastrar_propostas.html", context)


@login_required
#@user_passes_test(is_financeiro)
def elaboracao_contrato(request):
    solicitacoes = SolicitacaoProspeccao.objects.filter(
        fornecedor_escolhido__isnull=False, aprovacao_fornecedor_gerente="aprovado"
    ).select_related("fornecedor_escolhido").exclude(status="Onboarding")

    lista_solicitacoes = []
    for s in solicitacoes:
        proposta_escolhida = PropostaFornecedor.objects.filter(
            solicitacao=s,
            fornecedor=s.fornecedor_escolhido
        ).first()

        contrato = DocumentoContratoTerceiro.objects.filter(solicitacao=s).first()
        lista_solicitacoes.append({
            "solicitacao": s,
            "fornecedor": s.fornecedor_escolhido,
            "proposta": proposta_escolhida,
            "contrato": contrato
        })

    context = {"lista_solicitacoes": lista_solicitacoes}
    return render(request, "contratos/elaboracao_contrato.html", context)


@login_required
#@user_passes_test(is_financeiro)
def cadastrar_contrato(request, solicitacao_id):
    if request.user.grupo not in ["suprimento"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")
    solicitacao = get_object_or_404(
        SolicitacaoProspeccao,
        id=solicitacao_id,
        fornecedor_escolhido__isnull=False
    )

    contrato_existente = DocumentoContratoTerceiro.objects.filter(solicitacao=solicitacao).first()

    if request.method == "POST":
        form = DocumentoContratoTerceiroForm(request.POST, request.FILES, instance=contrato_existente)

        if form.is_valid():
            contrato = form.save(commit=False)
            contrato.solicitacao = solicitacao
            contrato.status = "Minuta do Contrato Elaborada"

            # mantém arquivo antigo se não foi enviado novo
            if not request.FILES.get("arquivo_contrato") and contrato_existente:
                contrato.arquivo_contrato = contrato_existente.arquivo_contrato

            contrato.save()

            gerente = User.objects.filter(grupo="gerente", centros__in=solicitacao.coordenador.centros.all()).values_list("email", flat=True).distinct()

            if gerente:
                assunto = "Foi anexado uma nova minuta de contrato"
                mensagem = (
                    f"Olá,\n\n"
                    f"A equipe de Suprimento anexou uma nova minuta de contrato para análise.\n\n"
                    "por favor, acesse o sistema HIDROGestão para avaliar a referente minuta.\n"
                    "https://hidrogestao.pythonanywhere.com/"
                )
                try:
                    send_mail(
                        assunto, mensagem,
                        "hidro.gestao25@gmail.com",
                        list(gerente),
                        fail_silently=False,
                    )
                except Exception as e:
                    messages.warning(request, f"Erro ao enviar e-mail para gerente: {e}")
            messages.success(request, "Contrato salvo com sucesso!")
            return redirect("elaboracao_contrato")
        else:
            messages.error(request, f"Erro ao salvar contrato: {form.errors}")
    else:
        form = DocumentoContratoTerceiroForm(instance=contrato_existente)

    context = {
        "form": form,
        "solicitacao": solicitacao,
        "fornecedor": solicitacao.fornecedor_escolhido,
        "contrato": contrato_existente,
    }
    return render(request, "fornecedores/cadastrar_contrato.html", context)


def cadastrar_minuta_contrato(request, solicitacao_id):
    if request.user.grupo not in ["suprimento"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")
    solicitacao = get_object_or_404(
        SolicitacaoContrato,
        id=solicitacao_id,
        fornecedor_escolhido__isnull=False
    )

    contrato_existente = DocumentoContratoTerceiro.objects.filter(solicitacao_contrato=solicitacao).first()

    if request.method == "POST":
        form = DocumentoContratoTerceiroForm(request.POST, request.FILES, instance=contrato_existente)

        if form.is_valid():
            contrato = form.save(commit=False)
            contrato.solicitacao_contrato = solicitacao
            if hasattr(solicitacao, "minuta_boletins_medicao_contrato"):
                contrato.status = "Planejamento do Contrato"

            # mantém arquivo antigo se não foi enviado novo
            if not request.FILES.get("arquivo_contrato") and contrato_existente:
                contrato.arquivo_contrato = contrato_existente.arquivo_contrato

            contrato.save()

            gerente = User.objects.filter(grupo="gerente", centros__in=solicitacao.coordenador.centros.all()).values_list("email", flat=True).distinct()

            if gerente:
                assunto = "Foi anexado uma nova minuta de contrato"
                mensagem = (
                    f"Olá,\n\n"
                    f"A equipe de Suprimento anexou uma nova minuta de contrato para análise.\n\n"
                    "por favor, acesse o sistema HIDROGestão para avaliar a referente minuta.\n"
                    "https://hidrogestao.pythonanywhere.com/"
                )
                try:
                    send_mail(
                        assunto, mensagem,
                        "hidro.gestao25@gmail.com",
                        list(gerente),
                        fail_silently=False,
                    )
                except Exception as e:
                    messages.warning(request, f"Erro ao enviar e-mail para gerente: {e}")
            messages.success(request, "Contrato salvo com sucesso!")
            return redirect("lista_solicitacoes")
        else:
            messages.error(request, f"Erro ao salvar contrato: {form.errors}")
    else:
        form = DocumentoContratoTerceiroForm(instance=contrato_existente)

    context = {
        "form": form,
        "solicitacao": solicitacao,
        "fornecedor": solicitacao.fornecedor_escolhido,
        "contrato": contrato_existente,
    }
    return render(request, "fornecedores/cadastrar_contrato.html", context)


def criar_contrato_se_aprovado(solicitacao):
    try:
        bm = solicitacao.minuta_boletins_medicao
    except DocumentoBM.DoesNotExist:
        print("BM não encontrado")
        return None

    bm_aprovado = bm.aprovado_por_ambos
    contrato_aprovado = solicitacao.aprovacao_gerencia is True

    print(f"Solicitacao {solicitacao.id} - BM aprovado: {bm_aprovado}, Contrato aprovado: {contrato_aprovado}")

    contrato_existente = ContratoTerceiros.objects.filter(prospeccao=solicitacao).first()
    if bm_aprovado and contrato_aprovado and not contrato_existente:
        print("Criando ContratoTerceiro...")
        documento = DocumentoContratoTerceiro.objects.filter(solicitacao=solicitacao).first()
        proposta = PropostaFornecedor.objects.filter(
            solicitacao=solicitacao,
            fornecedor=solicitacao.fornecedor_escolhido
        ).first()

        contrato = ContratoTerceiros.objects.create(
            cod_projeto=solicitacao.contrato,
            prospeccao=solicitacao,
            lider_contrato=solicitacao.lider_contrato,
            num_contrato=documento.numero_contrato if documento else None,
            empresa_terceira=solicitacao.fornecedor_escolhido,
            coordenador=solicitacao.coordenador,
            data_inicio=documento.prazo_inicio if documento else None,
            data_fim=documento.prazo_fim if documento else None,
            valor_total=documento.valor_total if documento else 0,
            objeto=documento.objeto if documento else "",
            condicao_pagamento=proposta.condicao_pagamento if proposta else None,
            status="Ativo",
            num_contrato_arquivo = documento.arquivo_contrato if documento else None,
            observacao=documento.observacao if documento else None,
        )
        print(f"Contrato criado: {contrato.id}")
        Evento.objects.filter(
            prospeccao=solicitacao,
            contrato_terceiro__isnull=True
        ).update(contrato_terceiro=contrato)

        solicitacao.status = "Onboarding"
        solicitacao.save()

        # Envia e-mail
        suprimentos = User.objects.filter(grupo="suprimento").exclude(email__isnull=True).exclude(email__exact="")
        lista_emails = [u.email for u in suprimentos]
        if lista_emails:
            assunto = f"Contrato criado: {contrato.cod_projeto}"
            mensagem = (
                f"Olá, equipe de Suprimentos!\n\n"
                f"O BM e o documento do contrato da solicitação '{solicitacao.id}' foram aprovados.\n\n"
                f"📄 Código do Projeto: {contrato.cod_projeto}\n"
                f"🏢 Fornecedor: {contrato.empresa_terceira}\n"
                f"💰 Valor Total: R$ {contrato.valor_total:,.2f}\n"
                f"📅 Vigência: {contrato.data_inicio.strftime('%d/%m/%Y') if contrato.data_inicio else 'Não definida'} "
                f"a {contrato.data_fim.strftime('%d/%m/%Y') if contrato.data_fim else 'Não definida'}\n\n"
                f"⚠️ Observações: {contrato.observacao or 'Nenhuma'}\n\n"
                "Recomendação: Agendar reunião de onboarding com o fornecedor o quanto antes para alinhamento das responsabilidades.\n\n"
                "Atenciosamente,\n"
                "Sistema de Gestão de Terceiros - HIDROGestão"
            )
            try:
                send_mail(assunto, mensagem, "hidro.gestao25@gmail.com", lista_emails, fail_silently=False)
            except Exception as e:
                print(f"Erro ao enviar e-mail: {e}")

        return contrato

    return None


def criar_contrato_se_aprovado_minuta(solicitacao):
    try:
        bm = solicitacao.minuta_boletins_medicao_contrato
    except DocumentoBM.DoesNotExist:
        print("BM não encontrado")
        return None

    #bm_aprovado = bm.aprovado_por_ambos
    bm_aprovado = bm.status_gerente
    contrato_aprovado = solicitacao.aprovacao_gerencia is True

    print(f"Solicitacao {solicitacao.id} - BM aprovado: {bm_aprovado}, Contrato aprovado: {contrato_aprovado}")

    contrato_existente = ContratoTerceiros.objects.filter(solicitacao=solicitacao).first()
    if bm_aprovado and contrato_aprovado and not contrato_existente:
        print("Criando ContratoTerceiro...")
        documento = DocumentoContratoTerceiro.objects.filter(solicitacao_contrato=solicitacao).first()
        proposta = PropostaFornecedor.objects.filter(
            solicitacao_contrato=solicitacao,
            fornecedor=solicitacao.fornecedor_escolhido
        ).first()

        contrato = ContratoTerceiros.objects.create(
            cod_projeto=solicitacao.contrato,
            solicitacao=solicitacao,
            lider_contrato=solicitacao.lider_contrato,
            num_contrato=documento.numero_contrato if documento else None,
            empresa_terceira=solicitacao.fornecedor_escolhido,
            coordenador=solicitacao.coordenador,
            data_inicio=documento.prazo_inicio if documento else None,
            data_fim=documento.prazo_fim if documento else None,
            valor_total=documento.valor_total if documento else 0,
            objeto=documento.objeto if documento else "",
            condicao_pagamento=proposta.condicao_pagamento if proposta else None,
            status="ativo",
            num_contrato_arquivo = documento.arquivo_contrato if documento else None,
            observacao=documento.observacao if documento else None,
        )
        print(f"Contrato criado: {contrato.id}")
        Evento.objects.filter(
            solicitacao_contrato=solicitacao,
            contrato_terceiro__isnull=True
        ).update(contrato_terceiro=contrato)

        solicitacao.status = "Onboarding"
        solicitacao.save()

        # Envia e-mail
        suprimentos = User.objects.filter(grupo="suprimento").exclude(email__isnull=True).exclude(email__exact="")
        lista_emails = [u.email for u in suprimentos]
        if lista_emails:
            assunto = f"Contrato criado: {contrato.cod_projeto}"
            mensagem = (
                f"Olá, equipe de Suprimentos!\n\n"
                f"O BM e o documento do contrato da solicitação '{solicitacao.id}' foram aprovados.\n\n"
                f"📄 Código do Projeto: {contrato.cod_projeto}\n"
                f"🏢 Fornecedor: {contrato.empresa_terceira}\n"
                f"💰 Valor Total: R$ {contrato.valor_total:,.2f}\n"
                f"📅 Vigência: {contrato.data_inicio.strftime('%d/%m/%Y') if contrato.data_inicio else 'Não definida'} "
                f"a {contrato.data_fim.strftime('%d/%m/%Y') if contrato.data_fim else 'Não definida'}\n\n"
                f"⚠️ Observações: {contrato.observacao or 'Nenhuma'}\n\n"
                "Recomendação: Agendar reunião de onboarding com o fornecedor o quanto antes para alinhamento das responsabilidades.\n\n"
                "Atenciosamente,\n"
                "Sistema de Gestão de Terceiros - HIDROGestão"
            )
            try:
                send_mail(assunto, mensagem, "hidro.gestao25@gmail.com", lista_emails, fail_silently=False)
            except Exception as e:
                print(f"Erro ao enviar e-mail: {e}")

        return contrato

    return None




@login_required
def detalhes_contrato(request, pk):
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)

    contrato_doc = getattr(solicitacao, "contrato_relacionado", None)
    fornecedor_escolhido = solicitacao.fornecedor_escolhido
    proposta_escolhida = None
    if fornecedor_escolhido:
        proposta_escolhida = PropostaFornecedor.objects.filter(
            solicitacao=solicitacao, fornecedor=fornecedor_escolhido
        ).first()
    fornecedores_selecionados = solicitacao.fornecedores_selecionados.all()
    revisoes = solicitacao.revisoes.all()
    origem = solicitacao.solicitacao_origem

    if request.method == "POST" and request.user.grupo == "gerente" and contrato_doc:
        acao = request.POST.get("acao")
        justificativa = request.POST.get("justificativa", "")

        if acao == "aprovar":
            solicitacao.aprovacao_gerencia = True
            solicitacao.reprovacao_gerencia = False
            solicitacao.justificativa_gerencia = ""
            messages.success(request, "Documento do contrato aprovado pela gerência.")
        elif acao == "reprovar":
            solicitacao.aprovacao_gerencia = False
            solicitacao.reprovacao_gerencia = True
            solicitacao.justificativa_gerencia = justificativa
            messages.warning(request, "Documento do contrato reprovado pela gerência.")
        else:
            messages.error(request, "Ação inválida.")

        solicitacao.save()

        # Tenta criar o contrato caso BM e documento do contrato estejam aprovados
        criar_contrato_se_aprovado(solicitacao)

        return redirect("lista_solicitacoes")

    return render(request, "gestao_contratos/detalhes_contrato.html", {
        "solicitacao": solicitacao,
        "contrato_doc": contrato_doc,
        "fornecedor_escolhido": fornecedor_escolhido,
        "proposta_escolhida": proposta_escolhida,
        "fornecedores_selecionados": fornecedores_selecionados,
        "revisoes": revisoes,
        "origem": origem,
    })


@login_required
def detalhes_minuta_contrato(request, pk):
    solicitacao = get_object_or_404(SolicitacaoContrato, pk=pk)

    contrato_doc = getattr(solicitacao, "minuta_contrato", None)
    fornecedor_escolhido = solicitacao.fornecedor_escolhido
    proposta_escolhida = None
    if fornecedor_escolhido:
        proposta_escolhida = PropostaFornecedor.objects.filter(
            solicitacao_contrato=solicitacao
        ).first()

    if request.method == "POST" and request.user.grupo == "gerente_contrato" and contrato_doc:
        acao = request.POST.get("acao")
        justificativa = request.POST.get("justificativa", "")

        if acao == "aprovar":
            solicitacao.aprovacao_gerencia = True
            solicitacao.reprovacao_gerencia = False
            solicitacao.justificativa_gerencia = ""
            messages.success(request, "Documento do contrato aprovado pela gerência.")
        elif acao == "reprovar":
            solicitacao.aprovacao_gerencia = False
            solicitacao.reprovacao_gerencia = True
            solicitacao.justificativa_gerencia = justificativa
            messages.warning(request, "Documento do contrato reprovado pela gerência.")
        else:
            messages.error(request, "Ação inválida.")

        solicitacao.save()

        # Tenta criar o contrato caso BM e documento do contrato estejam aprovados
        criar_contrato_se_aprovado_minuta(solicitacao)

        return redirect("lista_solicitacoes")

    return render(request, "gestao_contratos/detalhes_minuta_contrato.html", {
        "solicitacao": solicitacao,
        "contrato_doc": contrato_doc,
        "fornecedor_escolhido": fornecedor_escolhido,
        "proposta_escolhida": proposta_escolhida,
    })


@login_required
def renegociar_valor(request, pk):
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)
    proposta = PropostaFornecedor.objects.filter(solicitacao=solicitacao).first()

    if not proposta:
        return render(request, "erro.html", {"mensagem": "Nenhuma proposta encontrada para esta solicitação."})

    if request.method == "POST":
        novo_valor = request.POST.get("valor_proposta")
        if novo_valor:
            proposta.valor_proposta = novo_valor
            proposta.save()
            return redirect("detalhes_contrato", pk=solicitacao.pk)

    return render(request, "gestao_contratos/renegociar_valor.html", {"solicitacao": solicitacao, "proposta": proposta})


@login_required
def renegociar_prazo(request, pk):
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)
    contrato = DocumentoContratoTerceiro.objects.filter(solicitacao=solicitacao).first()

    if not contrato:
        return render(request, "erro.html", {"mensagem": "Nenhum contrato encontrado para esta solicitação."})

    if request.method == "POST":
        prazo_inicio = request.POST.get("prazo_inicio")
        prazo_fim = request.POST.get("prazo_fim")

        if prazo_inicio and prazo_fim:
            contrato.prazo_inicio = prazo_inicio
            contrato.prazo_fim = prazo_fim
            contrato.save()
            return redirect("detalhes_contrato", pk=solicitacao.pk)

    return render(request, "gestao_contratos/renegociar_prazo.html", {"solicitacao": solicitacao, "contrato": contrato})


@login_required
def nova_prospeccao(request, pk):
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)

    if request.method == "POST":
        nova_solicitacao = SolicitacaoProspeccao.objects.create(
            contrato=f"{solicitacao.contrato} - Revisão {timezone.now().strftime('%d/%m/%Y %H:%M')}",
            descricao=solicitacao.descricao,
            criado_por=request.user,
            status="Em Prospecção",
            solicitacao_origem=solicitacao
        )
        return redirect("detalhes_contrato", pk=nova_solicitacao.pk)

    return render(request, "nova_prospeccao.html", {"solicitacao": solicitacao})


@login_required
def inserir_minuta_bm(request, pk):
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)

    if request.user.grupo != 'suprimento':
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    # Cria ou recupera a minuta ligada à solicitação
    documento_bm, created = DocumentoBM.objects.get_or_create(solicitacao=solicitacao)

    if request.method == "POST":
        form = DocumentoBMForm(request.POST, request.FILES, instance=documento_bm)
        if form.is_valid():
            form.save()
            solicitacao.status = "Planejamento do Contrato"
            solicitacao.save()
            messages.success(request, "Minuta do Boletim de Medição enviada com sucesso!")
            return redirect('lista_solicitacoes')
    else:
        form = DocumentoBMForm(instance=documento_bm)

    return render(request, 'fornecedores/inserir_minuta_bm.html', {
        'solicitacao': solicitacao,
        'form': form,
    })


@login_required
def inserir_minuta_bm_contrato(request, pk):
    solicitacao = get_object_or_404(SolicitacaoContrato, pk=pk)

    if request.user.grupo != 'suprimento':
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    # Cria ou recupera a minuta ligada à solicitação
    documento_bm, created = DocumentoBM.objects.get_or_create(solicitacao_contrato=solicitacao)

    if request.method == "POST":
        form = DocumentoBMForm(request.POST, request.FILES, instance=documento_bm)
        if form.is_valid():
            form.save()
            if hasattr(solicitacao, "minuta_contrato"):
                solicitacao.status = "Planejamento do Contrato"
            solicitacao.save()
            messages.success(request, "Minuta do Boletim de Medição enviada com sucesso!")
            return redirect('lista_solicitacoes')
    else:
        form = DocumentoBMForm(instance=documento_bm)

    return render(request, 'fornecedores/inserir_minuta_bm.html', {
        'solicitacao': solicitacao,
        'form': form,
    })


@login_required
def detalhe_bm(request, pk):
    if request.user.grupo not in ["gerente_contrato", "lider_contrato"]:
        messages.error(request, "Você não tem permissão para isso.")
        return redirect("home")
    bm = get_object_or_404(DocumentoBM, pk=pk)
    solicitacao = bm.solicitacao
    usuario = request.user

    if request.method == "POST":
        acao = request.POST.get("acao")

        # Avaliação do coordenador
        if usuario.grupo == "lider_contrato":
            if acao == "aprovar":
                bm.status_coordenador = "aprovado"
                bm.data_aprovacao_coordenador = timezone.now()
                messages.success(request, "Minuta BM aprovada pelo coordenador.")
            elif acao == "reprovar":
                bm.status_coordenador = "reprovado"
                bm.data_aprovacao_coordenador = timezone.now()
                messages.warning(request, "Minuta BM reprovada pelo coordenador.")

        # Avaliação do gerente
        elif usuario.grupo == "gerente_contrato":
            if acao == "aprovar":
                bm.status_gerente = "aprovado"
                bm.data_aprovacao_gerente = timezone.now()
                messages.success(request, "Minuta BM aprovada pelo gerente.")
            elif acao == "reprovar":
                bm.status_gerente = "reprovado"
                bm.data_aprovacao_gerente = timezone.now()
                messages.warning(request, "Minuta BM reprovada pelo gerente.")

        bm.save()
        # Tenta criar o contrato caso BM e documento do contrato estejam aprovados
        criar_contrato_se_aprovado(solicitacao)

        return redirect("lista_solicitacoes")

    return render(request, "gestao_contratos/detalhe_bm.html", {
        "bm": bm,
        "solicitacao": solicitacao
    })


@login_required
def detalhe_bm_contrato(request, pk):
    if request.user.grupo not in ["gerente_contrato", "lider_contrato"]:
        messages.error(request, "Você não tem permissão para isso.")
        return redirect("home")
    bm = get_object_or_404(DocumentoBM, pk=pk)
    solicitacao = bm.solicitacao_contrato
    usuario = request.user

    if request.method == "POST":
        acao = request.POST.get("acao")

        # Avaliação do coordenador
        if usuario.grupo == "lider_contrato":
            if acao == "aprovar":
                bm.status_coordenador = "aprovado"
                bm.data_aprovacao_coordenador = timezone.now()
                messages.success(request, "Minuta BM aprovada pelo coordenador.")
            elif acao == "reprovar":
                bm.status_coordenador = "reprovado"
                bm.data_aprovacao_coordenador = timezone.now()
                messages.warning(request, "Minuta BM reprovada pelo coordenador.")

        # Avaliação do gerente
        elif usuario.grupo == "gerente_contrato":
            if acao == "aprovar":
                bm.status_gerente = "aprovado"
                bm.data_aprovacao_gerente = timezone.now()
                messages.success(request, "Minuta BM aprovada pelo gerente.")
            elif acao == "reprovar":
                bm.status_gerente = "reprovado"
                bm.data_aprovacao_gerente = timezone.now()
                messages.warning(request, "Minuta BM reprovada pelo gerente.")

        bm.save()
        # Tenta criar o contrato caso BM e documento do contrato estejam aprovados
        criar_contrato_se_aprovado_minuta(solicitacao)

        return redirect("lista_solicitacoes")

    return render(request, "gestao_contratos/detalhe_bm.html", {
        "bm": bm,
        "solicitacao": solicitacao
    })


@login_required
def aprovar_bm(request, pk, papel):
    bm = get_object_or_404(DocumentoBM, pk=pk)

    if papel == "coordenador" and request.user.groups.filter(name="Coordenador de Contrato").exists():
        bm.status_coordenador = "aprovado"
        bm.data_aprovacao_coordenador = timezone.now()
    elif papel == "gerente" and request.user.groups.filter(name="Gerente de Contrato").exists():
        bm.status_gerente = "aprovado"
        bm.data_aprovacao_gerente = timezone.now()
    else:
        messages.error(request, "Você não tem permissão para aprovar este documento.")
        return redirect("lista_solicitacoes")

    bm.save()
    return redirect("detalhe_bm", pk=bm.pk)


@login_required
def reprovar_bm(request, pk, papel):
    bm = get_object_or_404(DocumentoBM, pk=pk)

    if papel == "coordenador" and request.user.groups.filter(name="Coordenador de Contrato").exists():
        bm.status_coordenador = "reprovado"
    elif papel == "gerente" and request.user.groups.filter(name="Gerente de Contrato").exists():
        bm.status_gerente = "reprovado"
    else:
        messages.error(request, "Você não tem permissão para reprovar este documento.")
        return redirect("lista_solicitacoes")

    bm.save()

    # Se alguém reprovou → exigir novo upload de minuta
    if bm.reprovado_por_alguem:
        messages.warning(request, "A minuta foi reprovada. Suprimentos deve reenviar um novo BM.")

        suprimentos = User.objects.filter(grupo="suprimento").values_list("email", flat=True)

        if suprimentos:
            assunto = "Reprovação do Boletim de Medição"
            mensagem = (
                f"O Boletim de Medição {bm.id}, referente ao evento do {bm.contrato} "
                f"foi reprovado.\n\n"
                "Acesse o sistema HIDROGestão para mais informações.\n"
                "https://hidrogestao.pythonanywhere.com/"
            )
            try:
                send_mail(
                    assunto, mensagem,
                    "hidro.gestao25@gmail.com",
                    list(suprimentos),
                    fail_silently=False,
                )
            except Exception as e:
                messages.warning(request, f"Erro ao enviar e-mail para suprimentos: {e}")

    return redirect("detalhe_bm", pk=bm.pk)


@login_required
def cadastrar_evento(request, pk):
    if request.user.grupo not in ["suprimento", "coordenador", "gerente", "gerente_contrato", "lider_contrato"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)

    if request.method == "POST":
        form = EventoPrevisaoForm(request.POST)
        if form.is_valid():
            evento = form.save(commit=False)
            evento.prospeccao = solicitacao
            evento.empresa_terceira = solicitacao.fornecedor_escolhido  # ajuste se o campo for diferente
            evento.save()
            return redirect("detalhes_solicitacao", pk=pk)
    else:
        form = EventoPrevisaoForm()

    return render(request, "gestao_contratos/cadastrar_evento.html", {
        "form": form,
        "solicitacao": solicitacao,
    })


@login_required
def cadastrar_evento_solicitacao(request, pk):
    if request.user.grupo not in ["suprimento", "coordenador", "gerente", "gerente_contrato", "lider_contrato"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")
    solicitacao = get_object_or_404(SolicitacaoContrato, pk=pk)

    if request.method == "POST":
        form = EventoPrevisaoForm(request.POST)
        if form.is_valid():
            evento = form.save(commit=False)
            evento.solicitacao_contrato = solicitacao
            evento.empresa_terceira = solicitacao.fornecedor_escolhido
            evento.save()
            return redirect("detalhes_solicitacao_contrato", pk=pk)
    else:
        form = EventoPrevisaoForm()

    return render(request, "gestao_contratos/cadastrar_evento.html", {
        "form": form,
        "solicitacao": solicitacao,
    })


@login_required
def cadastrar_evento_contrato(request, pk):
    if request.user.grupo not in ["suprimento", "coordenador", "gerente", "gerente_contrato", "lider_contrato"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    contrato = get_object_or_404(ContratoTerceiros, pk=pk)
    #solicitacao = contrato.prospeccao

    if request.method == "POST":
        form = EventoPrevisaoForm(request.POST)
        if form.is_valid():
            evento = form.save(commit=False)
            #evento.prospeccao = solicitacao
            evento.contrato_terceiro = contrato
            evento.empresa_terceira = contrato.empresa_terceira
            evento.save()
            return redirect("contrato_fornecedor_detalhe", pk=contrato.pk)
    else:
        form = EventoPrevisaoForm()

    return render(request, "gestao_contratos/cadastrar_evento_contrato.html", {
        "form": form,
        "contrato": contrato,
        #"solicitacao": solicitacao,
    })


@login_required
def editar_evento(request, pk):
    if request.user.grupo not in ["suprimento", "coordenador", "gerente", "gerente_contrato", "lider_contrato"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    evento = get_object_or_404(Evento, pk=pk)
    if request.method == "POST":
        form = EventoPrevisaoForm(request.POST, request.FILES, instance=evento)
        if form.is_valid():
            form.save()
            return redirect("detalhes_solicitacao", pk=evento.prospeccao.id)
    else:
        form = EventoPrevisaoForm(instance=evento)
    return render(request, "gestao_contratos/editar_evento.html", {"form": form, "evento": evento})


@login_required
def editar_evento_contrato(request, pk):
    if request.user.grupo not in ["suprimento", "coordenador", "gerente", "gerente_contrato", "lider_contrato"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    evento = get_object_or_404(Evento, pk=pk)
    if request.method == "POST":
        form = EventoPrevisaoForm(request.POST, request.FILES, instance=evento)
        if form.is_valid():
            form.save()
            return redirect("contrato_fornecedor_detalhe", pk=evento.contrato_terceiro.pk)
    else:
        form = EventoPrevisaoForm(instance=evento)
    return render(request, "gestao_contratos/editar_evento_contrato.html", {"form": form, "evento": evento})


@login_required
def excluir_evento(request, pk):
    if request.user.grupo not in ["suprimento"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    evento = get_object_or_404(Evento, pk=pk)
    if request.method == "POST":
        solicitacao_id = evento.prospeccao.id
        evento.delete()
        return redirect("detalhes_solicitacao", pk=solicitacao_id)
    return render(request, "gestao_contratos/excluir_evento.html", {"evento": evento})


@login_required
def excluir_evento_contrato(request, pk):
    if request.user.grupo not in ["suprimento"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    evento = get_object_or_404(Evento, pk=pk)
    if request.method == "POST":
        contrato_id = evento.contrato_terceiro.pk
        evento.delete()
        return redirect("contrato_fornecedor_detalhe", pk=contrato_id)
    return render(request, "gestao_contratos/excluir_evento_contrato.html", {"evento": evento})


@login_required
def registrar_entrega(request, pk):
    if request.user.grupo not in ["suprimento", "coordenador", "gerente"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    evento = get_object_or_404(Evento, pk=pk)
    contrato = evento.contrato_terceiro
    boletins = evento.boletins_medicao.all()
    notas_fiscais = evento.nota_fiscal.all()

    boletins_detalhados = []
    has_reprovacao_coordenador = False
    has_reprovacao_gerente = False

    for bm in boletins:
        if bm.status_coordenador == "aprovado" and bm.status_gerente == "aprovado":
            row_class = "table-success"
        elif bm.status_coordenador == "reprovado" or bm.status_gerente == "reprovado":
            row_class = "table-danger"
        else:
            row_class = "table-warning"

        # Marca se há reprovação para exibir colunas no template
        if bm.status_coordenador == "reprovado":
            has_reprovacao_coordenador = True
        if bm.status_gerente == "reprovado":
            has_reprovacao_gerente = True

        boletins_detalhados.append({
            "bm": bm,
            "row_class": row_class
        })

    if request.method == "POST":
        form = EventoEntregaForm(request.POST, request.FILES, instance=evento)

        if form.is_valid():
            if evento.boletins_medicao.exists() and not form.cleaned_data['data_pagamento']:
                form.add_error('data_pagamento', 'Preencha a Data de Pagamento, pois existem BMs cadastrados.')
            else:
                if request.POST.get("valor_igual") == "on":
                    ev = form.save(commit=False)
                    ev.valor_pago = evento.valor_previsto
                form.save()
                messages.success(request, "Entrega Registrada com sucesso")
                return redirect('contrato_fornecedor_detalhe', pk=contrato.pk)
        else:
            messages.error(request, "Erro ao registrar a entrega!")
    else:
        form = EventoEntregaForm(instance=evento)

    return render(request, "eventos/registrar_entrega.html", {
        "form": form,
        "evento": evento,
        "contrato": contrato,
        "boletins_detalhados": boletins_detalhados,
        "has_reprovacao_coordenador": has_reprovacao_coordenador,
        "has_reprovacao_gerente": has_reprovacao_gerente,
        "notas_fiscais": notas_fiscais,

    })


@login_required
def avaliar_bm(request, bm_id):
    bm = get_object_or_404(BM, id=bm_id)
    usuario = request.user

    # Verifica permissão
    if usuario.grupo not in ["coordenador", "gerente", "diretoria"]:
        messages.error(request, "⚠ Você não tem permissão para isso.")
        return redirect("home")

    acao = request.POST.get("acao")
    justificativa = request.POST.get("justificativa", "").strip()

    if acao not in ["aprovar", "reprovar", "aprovar_pagamento", "reprovar_pagamento"]:
        messages.error(request, "⚠ Ação inválida.")

    # ------------------------------
    # AVALIAÇÃO DO COORDENADOR
    # ------------------------------
    if usuario.grupo == "coordenador":
        bm.status_coordenador = "aprovado" if acao == "aprovar" else "reprovado"
        bm.data_aprovacao_coordenador = timezone.now()

        if acao == "reprovar":
            bm.justificativa_reprovacao_coordenador = justificativa or "Sem justificativa informada."
        else:
            bm.justificativa_reprovacao_coordenador = None

    # ------------------------------
    # AVALIAÇÃO DO GERENTE
    # ------------------------------
    elif usuario.grupo == "gerente":
        bm.status_gerente = "aprovado" if acao == "aprovar" else "reprovado"
        bm.data_aprovacao_gerente = timezone.now()

        if acao == "reprovar":
            bm.justificativa_reprovacao_gerente = justificativa or "Sem justificativa informada."
        else:
            bm.justificativa_reprovacao_gerente = None

    # ------------------------------
    # AVALIAÇÃO DA DIRETORIA
    # ------------------------------
    elif usuario.grupo == "diretoria":

        # Valida sequência
        if bm.status_coordenador != "aprovado" or bm.status_gerente != "aprovado":
            return JsonResponse({
                "success": False,
                "error": "Coordenador e gerente ainda não aprovaram este BM."
            }, status=400)

        # Diretoria aprova pagamento
        if acao == "aprovar_pagamento":
            bm.aprovacao_pagamento = "aprovado"
            bm.data_aprovacao_diretor = timezone.now()
            bm.justificativa_reprovacao_diretor = None

            # dispara e-mail para suprimento + financeiro
            usuarios_destino = User.objects.filter(grupo__in=["suprimento", "financeiro"])
            lista_emails = [u.email for u in usuarios_destino if u.email]

            if not lista_emails:
                return

            assunto = f"Pagamento Aprovado pela Diretoria – BM {bm.id}"
            mensagem = (
                f"Olá, equipe!\n\n"
                f"A diretoria APROVOU o pagamento do BM abaixo:\n\n"
                f"Projeto: {bm.contrato.cod_projeto}\n"
                f"Contrato: {bm.contrato.num_contrato} - {bm.contrato.empresa_terceira}\n"
                f"Evento: {bm.evento.descricao}\n"
                f"Valor BM: R$ {bm.valor_pago}\n\n"
                f"Atenciosamente,\n"
                f"Sistema HIDROGestão"
            )

            send_mail(
                assunto,
                mensagem,
                "hidro.gestao25@gmail.com",
                lista_emails,
                fail_silently=False,
            )

        # Diretoria reprova pagamento
        elif acao == "reprovar_pagamento":
            bm.aprovacao_pagamento = "reprovado"
            bm.data_aprovacao_diretor = timezone.now()
            bm.justificativa_reprovacao_diretor = justificativa or "Sem justificativa informada."


    # SALVA ALTERAÇÕES
    bm.save()

    # ---------------------------------------------------------------
    # ENVIO DE E-MAIL PARA SUPRIMENTO APÓS AVALIAÇÃO DE COORD/GER
    # (Seu fluxo antigo – mantido exatamente igual)
    # ---------------------------------------------------------------
    if usuario.grupo in ['gerente', 'coordenador']:
        try:
            status_coord = bm.status_coordenador
            status_ger = bm.status_gerente

            if status_coord != "pendente" and status_ger != "pendente":

                usuarios_suprimento = User.objects.filter(grupo="suprimento")
                lista_emails = [u.email for u in usuarios_suprimento if u.email]

                if lista_emails:

                    # Ambos aprovaram
                    if status_coord == "aprovado" and status_ger == "aprovado":
                        assunto = f"BM aprovado - Contrato {bm.contrato.num_contrato}"
                        mensagem = (
                            f"Olá, equipe de Suprimentos!\n\n"
                            f"O Boletim de Medição foi APROVADO pelo coordenador e pelo gerente.\n\n"
                            f"Projeto: {bm.contrato.cod_projeto}\n"
                            f"Contrato: {bm.contrato.num_contrato} - {bm.contrato.empresa_terceira}\n"
                            f"Evento: {bm.evento.descricao}\n"
                            f"Valor BM: R$ {bm.valor_pago}\n\n"
                            f"Atenciosamente,\n"
                            f"Sistema HIDROGestão"
                        )

                    # Algum reprovou
                    else:
                        assunto = f"BM reprovado - Contrato {bm.contrato.num_contrato}"
                        mensagem = (
                            f"Olá, equipe de Suprimentos!\n\n"
                            f"O Boletim de Medição foi REPROVADO.\n\n"
                            f"Projeto: {bm.contrato.cod_projeto}\n"
                            f"Contrato: {bm.contrato.num_contrato} - {bm.contrato.empresa_terceira}\n"
                            f"Evento: {bm.evento.descricao}\n\n"
                            f"Justificativas:\n"
                            f"- Coordenador: {bm.justificativa_reprovacao_coordenador or 'Aprovou'}\n"
                            f"- Gerente: {bm.justificativa_reprovacao_gerente or 'Aprovou'}\n\n"
                            f"Atenciosamente,\n"
                            f"Sistema HIDROGestão"
                        )

                    send_mail(
                        assunto,
                        mensagem,
                        "hidro.gestao25@gmail.com",
                        lista_emails,
                        fail_silently=False,
                    )

        except Exception as e:
            print("Erro ao enviar e-mail de avaliação:", e)
            messages.error(request, "⚠ Não foi possível enviar o e-mail para Suprimentos.")


    # ---------------------------------------------------------------
    # RETORNO JSON
    # ---------------------------------------------------------------
    return JsonResponse({
        "success": True,
        "status_coordenador": bm.status_coordenador,
        "status_gerente": bm.status_gerente,
        "justificativa_reprovacao_coordenador": bm.justificativa_reprovacao_coordenador,
        "justificativa_reprovacao_gerente": bm.justificativa_reprovacao_gerente,
        "aprovacao_pagamento": bm.aprovacao_pagamento,
        "justificativa_reprovacao_diretor": bm.justificativa_reprovacao_diretor,
    })



@login_required
def previsao_pagamentos(request):
    if request.user.grupo not in ["suprimento", "gerente", "diretoria", "financeiro", "gerente_contrato"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")
    form = FiltroPrevisaoForm(request.GET or None)
    pagamentos = []
    total_previsto = 0
    total_pago = 0
    grafico_html = None
    grafico_barra = None
    grafico_barras = None
    grafico_barras_projeto = None
    bms = []
    total_bm_pago = None
    total_bm_previsto = None

    if form.is_valid():
        data_limite = form.cleaned_data["data_limite"]
        data_inicial = form.cleaned_data.get("data_inicial")
        coordenador = form.cleaned_data.get("coordenador")

        hoje = timezone.now().date()
        usuario = request.user
        data_inicio_filtro = data_inicial or hoje

        filtros_base = Q(
            Q(data_prevista_pagamento__range=[data_inicio_filtro, data_limite]) |
            Q(data_pagamento__range=[data_inicio_filtro, data_limite])
        )

        filtros_os = Q(
            Q(data_pagamento__range=[data_inicio_filtro, data_limite])
        )

        # === SUPRIMENTO ===
        if usuario.grupo in ["suprimento", "diretoria"]:
            eventos = Evento.objects.filter(filtros_base)
            os_queryset = OS.objects.filter(filtros_os)

        # === GERENTE ===
        elif usuario.grupo == "gerente":
            eventos = Evento.objects.filter(
                filtros_base,
                contrato_terceiro__coordenador__centros__in=usuario.centros.all()
            )
            os_queryset = OS.objects.filter(
                filtros_os,
                coordenador__centros__in=usuario.centros.all()
            )

        # === GERENTE DE CONTRATO ===
        elif usuario.grupo == "gerente_contrato":
            eventos = Evento.objects.filter(
                filtros_base,
                contrato_terceiro__lider_contrato__grupo="lider_contrato",
            )
            os_queryset = OS.objects.filter(
                filtros_os,
                lider_contrato__grupo="lider_contrato"
            )

        else:
            return redirect('home')

        # Aplica o filtro do coordenador se foi selecionado
        if coordenador:
            eventos = eventos.filter(contrato_terceiro__coordenador=coordenador)
            os_queryset = os_queryset.filter(coordenador=coordenador)

        eventos = eventos.order_by('data_prevista_pagamento', 'data_pagamento')

        # ==== TABELA ====
        pagamentos = eventos.values(
            'contrato_terceiro__cod_projeto__cod_projeto',
            'empresa_terceira__nome',
            'contrato_terceiro__coordenador__username',
            'data_prevista_pagamento',
            'valor_previsto',
            'data_pagamento',
            'valor_pago'
        )

        #total_previsto = sum(item['valor_previsto'] or 0 for item in pagamentos)
        total_previsto_eventos = sum(item['valor_previsto'] or 0 for item in pagamentos)
        total_previsto_os = os_queryset.aggregate(
            total=Coalesce(Sum("valor"), Decimal("0.00"))
        )["total"]

        total_previsto = total_previsto_eventos + total_previsto_os

        #total_pago = sum(item['valor_pago'] or 0 for item in pagamentos)
        total_pago_eventos = sum(item['valor_pago'] or 0 for item in pagamentos)
        total_pago_os = os_queryset.aggregate(
            total=Coalesce(Sum("valor_pago"), Decimal("0.00"))
        )["total"]

        total_pago = total_pago_eventos + total_pago_os


        # ==== GRÁFICO 1: LINHA ACUMULADA (EVENTOS + OS) ====

        from collections import defaultdict

        acumulado_previsto_por_data = defaultdict(Decimal)
        acumulado_pago_por_data = defaultdict(Decimal)

        # EVENTOS
        for e in eventos:
            if e.data_prevista_pagamento:
                acumulado_previsto_por_data[e.data_prevista_pagamento] += e.valor_previsto or 0
            if e.data_pagamento:
                acumulado_pago_por_data[e.data_pagamento] += e.valor_pago or 0

        # OS
        for os in os_queryset:
            if os.data_pagamento:
                acumulado_previsto_por_data[os.data_pagamento] += os.valor or 0
                acumulado_pago_por_data[os.data_pagamento] += os.valor_pago or 0

        datas = sorted(set(acumulado_previsto_por_data.keys()) | set(acumulado_pago_por_data.keys()))

        datas_prevista = []
        acumulado_previsto = []
        datas_pago = []
        acumulado_pago = []

        total_prev = Decimal("0.00")
        total_pg = Decimal("0.00")

        for d in datas:
            total_prev += acumulado_previsto_por_data.get(d, 0)
            total_pg += acumulado_pago_por_data.get(d, 0)

            datas_prevista.append(d)
            acumulado_previsto.append(total_prev)

            datas_pago.append(d)
            acumulado_pago.append(total_pg)

        if datas:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=datas_prevista,
                y=acumulado_previsto,
                mode='lines+markers',
                name='Previsto',
                line=dict(color='blue', width=3),
                marker=dict(size=6)
            ))
            fig.add_trace(go.Scatter(
                x=datas_pago,
                y=acumulado_pago,
                mode='lines+markers',
                name='Pago',
                line=dict(color='green', width=3),
                marker=dict(size=6)
            ))
            fig.update_layout(
                title='Previsão x Pagamentos Acumulados (Eventos + OS)',
                xaxis_title='Data',
                yaxis_title='Valor Acumulado (R$)',
                hovermode='x unified'
            )

            grafico_html = plot(fig, auto_open=False, output_type='div')


        # ==== GRÁFICO 2: POR COORDENADOR ====
        calendario = list(CalendarioPagamento.objects.order_by('data_pagamento')
                          .values_list('data_pagamento', flat=True))

        coordenadores = list(set(
            eventos.values_list('contrato_terceiro__coordenador__username', flat=True)
        ))

        fig_barra = go.Figure()
        for coord in coordenadores:
            y_previstos = []
            data_inicio = None

            for data_fim in calendario:
                filtro_periodo = Q(data_prevista_pagamento__lte=data_fim)
                if data_inicio:
                    filtro_periodo &= Q(data_prevista_pagamento__gt=data_inicio)

                if request.user.grupo == 'gerente_contrato':
                    eventos_previsto = Evento.objects.filter(
                        filtro_periodo,
                        contrato_terceiro__coordenador__username=coord,
                        contrato_terceiro__lider_contrato__grupo='lider_contrato'
                    )
                else:
                    eventos_previsto = Evento.objects.filter(
                        filtro_periodo,
                        contrato_terceiro__coordenador__username=coord
                    )

                total_previsto_periodo = eventos_previsto.aggregate(
                    total=Coalesce(Sum('valor_previsto'), Decimal('0.00'))
                )['total']

                y_previstos.append(total_previsto_periodo)
                data_inicio = data_fim

            fig_barra.add_trace(go.Bar(
                name=f"{coord or 'Sem Coordenador'}",
                x=calendario,
                y=y_previstos
            ))

        fig_barra.update_layout(
            barmode='stack',
            title="Pagamentos Previsto (por Coordenador, conforme calendário de pagamento)",
            xaxis_title="Data do Calendário",
            yaxis_title="Valor Previsto (R$)",
            template="plotly_white",
            height=500,
            legend_title="Coordenador"
        )

        grafico_barras = plot(fig_barra, output_type='div')

        # ==== GRÁFICO 2.2: POR PROJETO ====
        calendario = list(CalendarioPagamento.objects.order_by('data_pagamento')
                          .values_list('data_pagamento', flat=True))

        # filtra os projetos conforme coordenador (ou todos se não houver filtro)
        if coordenador:
            if request.user.grupo == 'gerente_contrato':
                projetos = list(Evento.objects.filter(
                    contrato_terceiro__coordenador=coordenador,
                    contrato_terceiro__lider_contrato__grupo='lider_contrato'
                ).values_list('contrato_terceiro__cod_projeto__cod_projeto', flat=True))
            else:
                projetos = list(Evento.objects.filter(
                    contrato_terceiro__coordenador=coordenador
                ).values_list('contrato_terceiro__cod_projeto__cod_projeto', flat=True))
        else:
            if request.user.grupo == 'gerente_contrato':
                projetos = list(Evento.objects.filter(
                    contrato_terceiro__lider_contrato__grupo='lider_contrato'
                ).values_list('contrato_terceiro__cod_projeto__cod_projeto', flat=True))
            else:
                projetos = list(Evento.objects.values_list(
                    'contrato_terceiro__cod_projeto__cod_projeto', flat=True))

        projetos = list(set(projetos))

        fig_barra_proj = go.Figure()
        for proj in projetos:
            y_previstos = []
            data_inicio = None

            for data_fim in calendario:
                filtro_periodo = Q(data_prevista_pagamento__lte=data_fim)
                if data_inicio:
                    filtro_periodo &= Q(data_prevista_pagamento__gt=data_inicio)

                filtro_base = Q(contrato_terceiro__cod_projeto__cod_projeto=proj)
                if coordenador:
                    filtro_base &= Q(contrato_terceiro__coordenador=coordenador)

                eventos_previsto = Evento.objects.filter(filtro_periodo & filtro_base)

                total_previsto_periodo = eventos_previsto.aggregate(
                    total=Coalesce(Sum('valor_previsto'), Decimal('0.00'))
                )['total']

                y_previstos.append(total_previsto_periodo)
                data_inicio = data_fim

            fig_barra_proj.add_trace(go.Bar(
                name=f"{proj or 'Sem Projeto'}",
                x=calendario,
                y=y_previstos
            ))

        fig_barra_proj.update_layout(
            barmode='stack',
            title="Pagamentos Previsto (por Projeto, conforme calendário de pagamento)",
            xaxis_title="Data do Calendário",
            yaxis_title="Valor Previsto (R$)",
            template="plotly_white",
            height=500,
            legend_title="Projeto"
        )

        grafico_barras_projeto = plot(fig_barra_proj, output_type='div')

        # ==== GRÁFICO 3: PREVISTO x PAGO (EVENTOS + OS) ====

        calendario = list(
            CalendarioPagamento.objects.order_by("data_pagamento")
            .values_list("data_pagamento", flat=True)
        )

        y_previstos = []
        y_pagos = []
        data_inicio = None

        for data_fim in calendario:
            filtro_prev_evento = Q(data_prevista_pagamento__lte=data_fim)
            filtro_pago_evento = Q(data_pagamento__lte=data_fim)
            filtro_os = Q(data_pagamento__lte=data_fim)

            if data_inicio:
                filtro_prev_evento &= Q(data_prevista_pagamento__gt=data_inicio)
                filtro_pago_evento &= Q(data_pagamento__gt=data_inicio)
                filtro_os &= Q(data_pagamento__gt=data_inicio)

            if coordenador:
                filtro_prev_evento &= Q(contrato_terceiro__coordenador=coordenador)
                filtro_pago_evento &= Q(contrato_terceiro__coordenador=coordenador)
                filtro_os &= Q(coordenador=coordenador)

            if request.user.grupo == 'gerente_contrato':
                filtro_prev_evento &= Q(contrato_terceiro__lider_contrato__grupo='lider_contrato')
                filtro_pago_evento &= Q(contrato_terceiro__lider_contrato__grupo='lider_contrato')
                filtro_os &= Q(lider_contrato__grupo='lider_contrato')

            total_prev_eventos = Evento.objects.filter(filtro_prev_evento).aggregate(
                total=Coalesce(Sum("valor_previsto"), Decimal("0.00"))
            )["total"]

            total_pago_eventos = Evento.objects.filter(filtro_pago_evento).aggregate(
                total=Coalesce(Sum("valor_pago"), Decimal("0.00"))
            )["total"]

            total_prev_os = os_queryset.filter(filtro_os).aggregate(
                total=Coalesce(Sum("valor"), Decimal("0.00"))
            )["total"]

            total_pago_os = os_queryset.filter(filtro_os).aggregate(
                total=Coalesce(Sum("valor_pago"), Decimal("0.00"))
            )["total"]

            y_previstos.append(total_prev_eventos + total_prev_os)
            y_pagos.append(total_pago_eventos + total_pago_os)

            data_inicio = data_fim

        fig_barra_final = go.Figure(data=[
            go.Bar(name="Previsto", x=calendario, y=y_previstos, marker_color="orange"),
            go.Bar(name="Pago", x=calendario, y=y_pagos, marker_color="green"),
        ])

        fig_barra_final.update_layout(
            barmode="group",
            title="Pagamentos Previsto x Pago (Eventos + OS)",
            xaxis_title="Data",
            yaxis_title="Valor (R$)",
            template="plotly_white",
            height=500,
        )

        grafico_barra = plot(fig_barra_final, output_type="div")


        # ==== TABELA DE BMs ====
        # === FILTRO DE BM (Pagamento OU Período de Medição) ===
        filtro_bm = request.GET.get("filtro_bm", "pagamento")

        if filtro_bm == "medicao":
            # filtra pelo período de medição definido no form
            bms = BM.objects.filter(
                data_inicial_medicao__date__gte=data_inicio_filtro,
                data_final_medicao__date__lte=data_limite
            )
        else:
            # filtro padrão: data de pagamento
            bms = BM.objects.annotate(
                data_ultima_aprovacao=Greatest(
                    'data_aprovacao_coordenador',
                    'data_aprovacao_gerente'
                )
            ).filter(
                data_ultima_aprovacao__date__range=[data_inicio_filtro, data_limite]
            )

        bms = bms.select_related(
            'contrato__cod_projeto',
            'contrato__coordenador',
            'evento'
        ).order_by('-data_pagamento')

        # Se o coordenador foi selecionado, filtra também os BMs
        if coordenador:
            bms = bms.filter(contrato__coordenador=coordenador)

        # Determina status de aprovação (para exibir na tabela)
        for bm in bms:
            # Define o status geral
            if bm.status_coordenador == 'aprovado' and bm.status_gerente == 'aprovado':
                bm.status_geral = '✅ Aprovado'
                bm.falta_aprovar = '-'
            elif bm.status_coordenador == 'reprovado' or bm.status_gerente == 'reprovado':
                bm.status_geral = '❌ Reprovado'
                bm.falta_aprovar = '-'
            else:
                bm.status_geral = '⏳ Aguardando Aprovação'
                faltando = []
                if bm.status_coordenador != 'aprovado':
                    faltando.append('Coordenador')
                if bm.status_gerente != 'aprovado':
                    faltando.append('Gerente')
                bm.falta_aprovar = ', '.join(faltando)

        total_bm_pago = sum(bm.valor_pago or 0 for bm in bms)
        total_bm_previsto = sum(
            (bm.evento.valor_previsto if bm.evento and bm.evento.valor_previsto else 0)
            for bm in bms
        )

    return render(request, "gestao_contratos/previsao_pagamentos.html", {
        "form": form,
        "pagamentos": pagamentos,
        "total_previsto": total_previsto,
        "total_pago": total_pago,
        "grafico_html": grafico_html,
        "grafico_barras": grafico_barras,
        "grafico_barras_projeto": grafico_barras_projeto,
        "grafico_barra": grafico_barra,
        "bms": bms,
        "total_bm_pago": total_bm_pago,
        "total_bm_previsto": total_bm_previsto,
    })


@login_required
def download_bms_aprovados(request):
    if request.user.grupo not in ["suprimento", "diretoria", "gerente", "financeiro", "gerente_contrato"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    data_inicial_str = request.GET.get("data_inicial")
    data_limite_str = request.GET.get("data_limite")
    filtro_bm = request.GET.get("filtro_bm", "pagamento")  # pagto ou medicao
    coordenador = request.GET.get("coordenador")

    if not data_limite_str:
        messages.error(request, "Data limite é obrigatória para o download.")
        return redirect("previsao_pagamentos")


    try:
        data_inicial = datetime.strptime(data_inicial_str, "%Y-%m-%d").date() if data_inicial_str else timezone.now().date()
        data_limite = datetime.strptime(data_limite_str, "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, "Datas inválidas no formato. Use YYYY-MM-DD.")
        return redirect("previsao_pagamentos")

    # === FILTRO PRINCIPAL: APROVADOS ===
    bms_aprovados = BM.objects.filter(
        status_coordenador='aprovado',
        status_gerente='aprovado'
    )

    # === FILTRAR POR PAGAMENTO OU MEDIÇÃO ===
    if filtro_bm == "medicao":
        bms_aprovados = bms_aprovados.filter(
            data_inicial_medicao__date__gte=data_inicial,
            data_final_medicao__date__lte=data_limite
        )
    else:
        # PADRÃO → por pagamento
        bms_aprovados = bms_aprovados.annotate(
            data_ultima_aprovacao=Greatest(
                'data_aprovacao_coordenador',
                'data_aprovacao_gerente'
            )
        ).filter(
            data_ultima_aprovacao__date__range=[data_inicial, data_limite]
        )

    # === FILTRAR POR COORDENADOR, SE APLICADO ===
    if coordenador:
        bms_aprovados = bms_aprovados.filter(contrato__coordenador=coordenador)

    # === APENAS COM ARQUIVO ===
    bms_aprovados = bms_aprovados.exclude(arquivo_bm='')

    if not bms_aprovados.exists():
        messages.error(request, "Nenhum BM aprovado encontrado para download nesse período.")
        return redirect("previsao_pagamentos")

    # === CRIAÇÃO DO ZIP ===
    buffer_zip = BytesIO()
    with zipfile.ZipFile(buffer_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for bm in bms_aprovados:
            if not bm.arquivo_bm:
                continue

            try:
                with bm.arquivo_bm.open('rb') as f:
                    conteudo = f.read()

                nome_projeto = (
                    bm.contrato.cod_projeto.cod_projeto
                    if bm.contrato and bm.contrato.cod_projeto
                    else "SemProjeto"
                )
                nome_original = bm.arquivo_bm.name.split('/')[-1]
                nome_arquivo_zip = f"{nome_projeto}_BM{bm.numero_bm}_{nome_original}"

                zipf.writestr(nome_arquivo_zip, conteudo)

            except Exception as e:
                print(f"⚠️ Erro ao adicionar BM {bm.id} ao ZIP: {e}")

    buffer_zip.seek(0)

    nome_arquivo_zip = f"BMs_Aprovados_{data_inicial.strftime('%Y-%m-%d')}_a_{data_limite.strftime('%Y-%m-%d')}.zip"

    response = HttpResponse(buffer_zip.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename=\"{nome_arquivo_zip}\"'
    return response



@login_required
def exportar_previsao_pagamentos_excel(request):
    if request.user.grupo not in ["suprimento", "diretoria", "gerente", "financeiro", "gerente_contrato"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    form = FiltroPrevisaoForm(request.GET or None)

    if not form.is_valid():
        messages.error(request, "Preencha os filtros corretamente antes de exportar.")
        return redirect('previsao_pagamentos')

    data_limite = form.cleaned_data["data_limite"]
    data_inicial = form.cleaned_data.get("data_inicial")
    coordenador = form.cleaned_data.get("coordenador")

    hoje = timezone.now().date()
    usuario = request.user
    data_inicio_filtro = data_inicial or hoje

    filtros_base = Q(
        Q(data_prevista_pagamento__range=[data_inicio_filtro, data_limite]) |
        Q(data_pagamento__range=[data_inicio_filtro, data_limite])
    )

    # === SUPRIMENTO e DIRETORIA ===
    if usuario.grupo == "suprimento" or usuario.grupo == "diretoria":
        eventos = Evento.objects.filter(filtros_base)

    # === GERENTE ===
    elif usuario.grupo == "gerente":
        eventos = Evento.objects.filter(
            filtros_base,
            contrato_terceiro__coordenador__centros__in=usuario.centros.all()
        )

    else:
        return redirect('home')

    if coordenador:
        eventos = eventos.filter(contrato_terceiro__coordenador=coordenador)

    eventos = eventos.order_by('data_prevista_pagamento', 'data_pagamento')

    # === Criar workbook ===
    wb = Workbook()
    ws = wb.active
    ws.title = "Previsão de Pagamentos"

    # Planilha 1 — Dados completos
    headers = [
        "Data Prevista", "Projeto", "Fornecedor", "Coordenador",
        "Valor Previsto", "Data Pagamento", "Valor Pago"
    ]
    ws.append(headers)

    for e in eventos:
        ws.append([
            e.data_prevista_pagamento.strftime("%d/%m/%Y") if e.data_prevista_pagamento else '',
            e.contrato_terceiro.cod_projeto.cod_projeto if e.contrato_terceiro.cod_projeto else '',
            e.empresa_terceira.nome if e.empresa_terceira else '',
            e.contrato_terceiro.coordenador.username if e.contrato_terceiro.coordenador else '',
            float(e.valor_previsto or 0),
            e.data_pagamento.strftime("%d/%m/%Y") if e.data_pagamento else '',
            float(e.valor_pago or 0)
        ])

    # === Planilha 2 — Por Coordenador (com datas) ===
    ws2 = wb.create_sheet("Por Coordenador")
    ws2.append(["Data Prevista"] + list(set(eventos.values_list("contrato_terceiro__coordenador__username", flat=True))))

    datas = sorted(set(eventos.values_list("data_prevista_pagamento", flat=True)))
    coordenadores = list(set(eventos.values_list("contrato_terceiro__coordenador__username", flat=True)))

    for data in datas:
        linha = [data.strftime("%d/%m/%Y") if data else ""]
        for coord in coordenadores:
            total = eventos.filter(
                data_prevista_pagamento=data,
                contrato_terceiro__coordenador__username=coord
            ).aggregate(total=Sum("valor_previsto"))["total"] or Decimal("0")
            linha.append(float(total))
        ws2.append(linha)

    # Gráfico
    chart1 = BarChart()
    chart1.title = "Valores Previsto por Coordenador (por Data)"
    data = Reference(ws2, min_col=2, max_col=len(coordenadores) + 1, min_row=1, max_row=len(datas) + 1)
    cats = Reference(ws2, min_col=1, min_row=2, max_row=len(datas) + 1)
    chart1.add_data(data, titles_from_data=True)
    chart1.set_categories(cats)
    chart1.x_axis.title = "Data Prevista"
    chart1.y_axis.title = "Valor (R$)"
    chart1.height = 10
    chart1.width = 20
    ws2.add_chart(chart1, "H2")

    # === Planilha 3 — Por Projeto (com datas) ===
    ws3 = wb.create_sheet("Por Projeto")
    ws3.append(["Data Prevista"] + list(set(eventos.values_list("contrato_terceiro__cod_projeto__cod_projeto", flat=True))))

    projetos = list(set(eventos.values_list("contrato_terceiro__cod_projeto__cod_projeto", flat=True)))

    for data in datas:
        linha = [data.strftime("%d/%m/%Y") if data else ""]
        for proj in projetos:
            total = eventos.filter(
                data_prevista_pagamento=data,
                contrato_terceiro__cod_projeto__cod_projeto=proj
            ).aggregate(total=Sum("valor_previsto"))["total"] or Decimal("0")
            linha.append(float(total))
        ws3.append(linha)

    chart2 = BarChart()
    chart2.title = "Valores Previsto por Projeto (por Data)"
    data2 = Reference(ws3, min_col=2, max_col=len(projetos) + 1, min_row=1, max_row=len(datas) + 1)
    cats2 = Reference(ws3, min_col=1, min_row=2, max_row=len(datas) + 1)
    chart2.add_data(data2, titles_from_data=True)
    chart2.set_categories(cats2)
    chart2.x_axis.title = "Data Prevista"
    chart2.y_axis.title = "Valor (R$)"
    chart2.height = 10
    chart2.width = 20
    ws3.add_chart(chart2, "H2")

    # === Planilha 4 — Acumulado (com datas) ===
    ws4 = wb.create_sheet("Acumulado")
    ws4.append(["Data Prevista", "Acumulado (R$)"])

    acumulado = 0
    for data in datas:
        total = eventos.filter(
            data_prevista_pagamento=data
        ).aggregate(total=Sum("valor_previsto"))["total"] or Decimal("0")
        acumulado += total
        ws4.append([data.strftime("%d/%m/%Y"), float(acumulado)])

    chart3 = LineChart()
    chart3.title = "Acumulado por Data Prevista"
    data3 = Reference(ws4, min_col=2, min_row=1, max_row=len(datas) + 1)
    cats3 = Reference(ws4, min_col=1, min_row=2, max_row=len(datas) + 1)
    chart3.add_data(data3, titles_from_data=True)
    chart3.set_categories(cats3)
    chart3.x_axis.title = "Data Prevista"
    chart3.y_axis.title = "Valor Acumulado (R$)"
    chart3.height = 10
    chart3.width = 20
    for serie in chart3.series:
        serie.marker.symbol = "circle"
        serie.marker.size = 6
        serie.graphicalProperties.line.width = 20000

    ws4.add_chart(chart3, "E2")

    # === Exportar Excel ===
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="previsao_pagamentos_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx"'
    )
    wb.save(response)
    return response

@login_required
def ranking_fornecedores(request):
    if request.user.grupo not in ["suprimento", "diretoria", "gerente", "financeiro", "gerente_contrato"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    user = request.user
    contratos_ativos = ContratoTerceiros.objects.filter(status='ativo')

    if user.grupo == 'gerente':
        # Pega os centros de trabalho do gerente
        centros_gerente = user.centros.all()

        # Filtra contratos cujos coordenadores tenham centros em comum
        coordenadores_mesmos_centros = User.objects.filter(
            grupo='coordenador',
            centros__in=centros_gerente
        ).distinct()

        contratos_ativos = contratos_ativos.filter(
            coordenador__in=coordenadores_mesmos_centros
        )

    elif user.grupo in ['suprimento', 'diretoria', 'financeiro', 'gerente_contrato']:
        # Suprimento vê todos os contratos ativos
        pass

    else:
        # Outros grupos não visualizam nada
        contratos_ativos = ContratoTerceiros.objects.none()

    dados = []
    fornecedores = EmpresaTerceira.objects.all()

    for fornecedor in fornecedores:
        contratos = contratos_ativos.filter(empresa_terceira=fornecedor)
        eventos = Evento.objects.filter(empresa_terceira=fornecedor)

        valor_total_contratos = contratos.aggregate(total=Sum('valor_total'))['total'] or 0
        valor_previsto = eventos.aggregate(total=Sum('valor_previsto'))['total'] or 0
        valor_pago = eventos.aggregate(total=Sum('valor_pago'))['total'] or 0

        percentual_execucao = (valor_pago / valor_previsto * 100) if valor_previsto > 0 else 0

        dados.append({
            'id': fornecedor.id,  # 👈 Adiciona o ID
            'fornecedor': fornecedor.nome,
            'valor_total_contratos': valor_total_contratos,
            'valor_previsto': valor_previsto,
            'valor_pago': valor_pago,
            'percentual_execucao': percentual_execucao,
        })

    # Ordenação hierárquica
    dados = sorted(
        dados,
        key=lambda x: (
            x['valor_total_contratos'],
            x['valor_previsto'],
            x['valor_pago']
        ),
        reverse=True
    )

    context = {'dados': dados}
    return render(request, 'gestao_contratos/ranking_fornecedores.html', context)



@login_required
def cadastrar_bm(request, contrato_id, evento_id):
    if request.user.grupo not in ["suprimento"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    contrato = get_object_or_404(ContratoTerceiros, id=contrato_id)
    evento = get_object_or_404(Evento, id=evento_id)

    if request.method == "POST":
        form = BMForm(request.POST, request.FILES)
        if form.is_valid():
            bm = form.save(commit=False)
            bm.contrato = contrato
            bm.evento = evento

            if not bm.valor_pago:
                bm.valor_pago = evento.valor_previsto

            bm.save()

            try:
                emails = set()

                # COORDENADOR
                coordenador = contrato.coordenador
                if coordenador and coordenador.email:
                    emails.add(coordenador.email)

                # GERENTES
                if coordenador:
                    coordenador_centros = coordenador.centros.all()

                    gerentes = User.objects.filter(
                        grupo="gerente",
                        centros__in=coordenador_centros
                    ).distinct()

                    for gerente in gerentes:
                        if gerente.email:
                            emails.add(gerente.email)

                # Se existir alguém para enviar
                if emails:
                    assunto = f"BM cadastrado para avaliação - Projeto {contrato.cod_projeto}"
                    mensagem = (
                        f"Olá,\n\n"
                        f"Um novo Boletim de Medição foi cadastrado e está aguardando avaliação.\n\n"
                        f"📌 Projeto: {contrato.cod_projeto}\n"
                        f"📌 Contrato: {contrato.num_contrato} - {contrato.empresa_terceira}\n"
                        f"📌 Evento: {evento.descricao}\n"
                        f"📌 Valor Previsto: R$ {evento.valor_previsto}\n"
                        f"📌 Valor Informado no BM: R$ {bm.valor_pago}\n\n"
                        f"Acesse o sistema para aprovar ou reprovar o BM.\n\n"
                        f"Atenciosamente,\n"
                        f"Sistema HIDROGestão"
                    )

                    send_mail(
                        assunto,
                        mensagem,
                        "hidro.gestao25@gmail.com",
                        list(emails),
                        fail_silently=False,
                    )

            except Exception as e:
                print("Erro ao enviar e-mail:", e)
                messages.error(request, "⚠ Não foi possível enviar o e-mail aos gestores.")
            return JsonResponse({"success": True})

        else:
            return JsonResponse({
                "success": False,
                "errors": form.errors
            })

    else:
        form = BMForm(initial={
            "valor_pago": evento.valor_previsto,
            "data_pagamento": evento.data_pagamento.strftime('%Y-%m-%d') if evento.data_pagamento else None,
        })

    form = BMForm(initial={
        "valor_pago": evento.valor_previsto,
        "data_pagamento": (
            evento.data_pagamento.strftime('%Y-%m-%d')
            if evento.data_pagamento else None
        ),
    })

    return render(request, "bm/cadastrar_bm_popup.html", {
        "form": form,
        "contrato": contrato,
        "evento": evento,
    })


@login_required
def cadastrar_nf(request, evento_id):
    if request.user.grupo not in ["suprimento", "financeiro"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    evento = get_object_or_404(Evento, id=evento_id)
    contrato = get_object_or_404(ContratoTerceiros, id=evento.contrato_terceiro.id)

    if request.method == "POST":
        form = NFForm(request.POST, request.FILES, evento=evento)
        if form.is_valid():
            nf = form.save(commit=False)
            nf.contrato = contrato
            nf.evento = evento
            nf.save()

            # ==============================
            # ENVIO DE E-MAIL AUTOMÁTICO
            # ==============================
            if request.user.grupo == "financeiro":

                # E-mails do grupo suprimento
                emails_suprimento = list(User.objects.filter(grupo='suprimento', is_active=True).values_list("email", flat=True))

                # Coordenador do contrato
                coordenador = contrato.coordenador
                email_coordenador = [coordenador.email] if coordenador and coordenador.email else []

                assunto = f"NF cadastrada para o evento #{evento.id}"
                mensagem = (
                    f"A nota fiscal do evento '{evento.descricao or 'Sem descrição'}'\n"
                    f"do contrato: {contrato}\n\n"
                    f"Foi cadastrada por: {request.user.get_full_name() or request.user.username} (Financeiro).\n\n"
                    f"Data de pagamento: {evento.data_pagamento}\n"
                    f"Valor: R$ {nf.valor_pago}"
                )

                # Enviar e-mail para suprimento
                try:
                    send_mail(
                        assunto, mensagem,
                        "hidro.gestao24@hmail.com",
                        emails_suprimento,
                        fail_silently=False,
                    )
                except Exception as e:
                    messages.warning(request, f"Erro ao enviar e-mail para suprimentos: {e}")

                try:
                    send_mail(
                        assunto, mensagem,
                        "hidro.gestao24@hotmail.com",
                        email_coordenador,
                        fail_silently=False,
                    )
                except Exception as e:
                    messages.warning(request, f"Erro ao enviar e-mail para o coordenador: {e}")

            return JsonResponse({"success": True})
        else:
            return JsonResponse({"success": False, "errors": form.errors})

    else:
        form = NFForm(
            evento=evento,
            initial={
                "valor_pago": evento.valor_previsto,
                "data_pagamento": evento.data_pagamento or None
            }
        )

    return render(request, "nf/cadastrar_nf_popup.html", {
        "form": form,
        "contrato": contrato,
        "evento": evento,
    })


@login_required
def editar_bm(request, bm_id):
    bm = get_object_or_404(BM, id=bm_id)

    if request.user.grupo != "suprimento":
        return JsonResponse({"success": False, "error": "Sem permissão."}, status=403)

    if request.method == "POST":
        form = BMForm(request.POST, request.FILES, instance=bm)
        if form.is_valid():
            form.save()
            return JsonResponse({"success": True})
        else:
            return JsonResponse({
                "success": False,
                "errors": form.errors
            })

    else:
        form = BMForm(instance=bm)

    return render(request, "bm/editar_bm.html", {"form": form, "bm": bm})


@login_required
def editar_nf(request, nf_id):
    if request.user.grupo not in ["suprimento", "financeiro"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    nf = get_object_or_404(NF, id=nf_id)
    evento = nf.evento

    if request.method == "POST":
        form = NFForm(request.POST, request.FILES, evento=evento, instance=nf)
        if form.is_valid():
            form.save()
            return JsonResponse({"success": True})
        return JsonResponse({"success": False, "errors": form.errors})

    else:
        form = NFForm(
            evento=evento,
            instance=nf,
            initial={
                "valor_pago": nf.valor_pago,
                "data_pagamento": nf.data_pagamento,
            }
        )

    return render(request, "nf/editar_nf_popup.html", {
        "form": form,
        "nf": nf,
        "evento": evento,
        "contrato": nf.contrato,
    })




@login_required
def deletar_bm(request, bm_id):
    bm = get_object_or_404(BM, id=bm_id)

    if request.user.grupo != "suprimento":
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    evento_id = bm.evento.id
    bm.delete()

    messages.success(request, "BM apagado com sucesso!")
    return redirect("registrar_entrega", pk=evento_id)


@login_required
def deletar_nf(request, nf_id):
    if request.user.grupo not in ["suprimento", "financeiro"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    nf = get_object_or_404(NF, id=nf_id)
    evento_id = nf.evento.id


    nf.delete()
    messages.success(request, "NF apagada com sucesso!")
    if request.user.grupo == 'financeiro':
        return redirect("detalhes_entrega", evento_id=evento_id)
    return redirect("registrar_entrega", pk=evento_id)


@login_required
def detalhes_entrega(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    bms = BM.objects.filter(evento=evento).order_by('-data_pagamento')
    notas_fiscais = evento.nota_fiscal.all()

    fornecedor = None
    if hasattr(evento, 'contrato_terceiro') and evento.contrato_terceiro.empresa_terceira:
        fornecedor = evento.contrato_terceiro.empresa_terceira

    tem_reprovacao_coordenador = bms.filter(status_coordenador='reprovado').exists()
    tem_reprovacao_gerente = bms.filter(status_gerente='reprovado').exists()
    tem_reprovacao_diretor = bms.filter(aprovacao_pagamento='reprovado').exists()


    return render(request, 'contratos/detalhes_entrega.html', {
        'evento': evento,
        'fornecedor': fornecedor,
        'bms': bms,
        'tem_reprovacao_coordenador': tem_reprovacao_coordenador,
        'tem_reprovacao_gerente': tem_reprovacao_gerente,
        'tem_reprovacao_diretor': tem_reprovacao_diretor,
        'notas_fiscais':notas_fiscais,
    })

@login_required
def avaliar_evento_fornecedor(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    contrato = evento.contrato_terceiro
    fornecedor = contrato.empresa_terceira

    # Permissão
    if request.user.grupo not in ["coordenador", "gerente"]:
        messages.error(request, "Você não tem permissão para isso!")
        return redirect("home")

    # Se já existe avaliação → bloquear
    avaliacao_existente = AvaliacaoFornecedor.objects.filter(evento=evento).first()

    if request.method == "POST":
        if avaliacao_existente:
            return JsonResponse({"success": False, "error": "Evento já avaliado."})

        nota_gestao = request.POST.get("nota_gestao")
        nota_tecnica = request.POST.get("nota_tecnica")
        nota_entrega = request.POST.get("nota_entrega")
        comentario = request.POST.get("comentario")

        AvaliacaoFornecedor.objects.create(
            empresa_terceira=fornecedor,
            contrato_terceiro=contrato,
            evento=evento,
            area_avaliadora=request.user.grupo,
            avaliador=request.user,
            nota_gestao=nota_gestao,
            nota_tecnica=nota_tecnica,
            nota_entrega=nota_entrega,
            comentario=comentario,
        )

        return redirect('contrato_fornecedor_detalhe', pk=contrato.pk)

    return render(request, "eventos/avaliar_evento.html", {
        "evento": evento,
        "contrato": contrato,
        "fornecedor": fornecedor,
        "avaliacao": avaliacao_existente,
    })


@login_required
def detalhes_os(request, pk):
    if request.user.grupo not in ['suprimento', 'lider_contrato', 'coordenador', 'gerente', 'gerente_contrato']:
        messages.error(request, "Você não tem permissão para isso.")
        return redirect('home')

    os = get_object_or_404(OS, pk=pk)

    fornecedor = os.contrato.empresa_terceira
    indicadores, _ = Indicadores.objects.get_or_create(
        empresa_terceira=fornecedor
    )

    context = {
        'os': os,
        'indicadores': indicadores,
    }

    return render(request, "gestao_contratos/os.html", context)


@login_required
def registrar_entrega_os(request, pk):
    os = get_object_or_404(OS, pk=pk)

    if request.user.grupo == 'coordenador' and request.user != os.coordenador:
        messages.error(request, "Você não tem permissão para isso.")
        return redirect("detalhes_os", pk=os.id)

    elif request.user.grupo == 'gerente' and os.coordenador.centros in request.user.centros.all():
        messages.error(request, "Você não tem permissão para isso.")
        return redirect("detalhes_os", pk=os.id)

    elif request.user.grupo not in ['suprimento', 'gerente', 'coordenador']:
        messages.error(request, "Você não tem permissão para isso.")
        return redirect("detalhes_os", pk=os.id)

    if os.status == "cancelada":
        messages.error(request, "Não é possível registrar entrega de uma OS cancelada.")
        return redirect("detalhes_os", pk=os.id)

    if request.method == "POST":
        form = RegistroEntregaOSForm(request.POST, instance=os)
        if form.is_valid():
            entrega = form.save(commit=False)

            # Verifica atraso
            if entrega.data_entrega and os.prazo_execucao:
                entrega.com_atraso = entrega.data_entrega > os.prazo_execucao

            entrega.realizado = True
            entrega.status = "finalizada"
            entrega.save()

            messages.success(request, "Entrega da OS registrada com sucesso.")
            return redirect("detalhes_os", pk=os.id)
    else:
        form = RegistroEntregaOSForm(instance=os)

    return render(
        request,
        "gestao_contratos/registrar_entrega_os.html",
        {
            "os": os,
            "form": form,
        }
    )
