from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Sum, Q, DecimalField
from decimal import Decimal
from django.db.models.functions import Coalesce
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic.edit import CreateView
from .models import Contrato, Cliente, EmpresaTerceira, ContratoTerceiros, SolicitacaoProspeccao, Indicadores, PropostaFornecedor, DocumentoContratoTerceiro, DocumentoBM, Evento, CalendarioPagamento, BM
from .forms import ContratoForm, ClienteForm, FornecedorForm, ContratoFornecedorForm, SolicitacaoProspeccaoForm, DocumentoContratoTerceiroForm, DocumentoBMForm, EventoPrevisaoForm, EventoEntregaForm, FiltroPrevisaoForm, BMForm

import plotly.graph_objs as go
import pandas as pd
from plotly.offline import plot
import plotly.colors as pc

import openpyxl
from django.http import HttpResponse, JsonResponse
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference, LineChart
from openpyxl.styles import Font
from io import BytesIO
from datetime import datetime

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


def is_financeiro(user):
    return user.is_authenticated and getattr(user, "grupo", None) == "financeiro"


def home(request):
    return render(request, 'home.html')


def logout(request):
    return render(request, 'logged_out.html')


@login_required
def lista_contratos(request):
    if request.user.grupo in ['suprimento', 'financeiro']:
        contratos = Contrato.objects.all()
    elif request.user.grupo == 'coordenador':
        contratos = Contrato.objects.filter(coordenador=request.user)
    elif request.user.grupo == 'gerente':
        contratos = Contrato.objects.filter(coordenador__centros__in=request.user.centros.all())
    else:
        return redirect('home')

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
    if request.user.grupo in ['suprimento', 'financeiro']:
        clientes = Cliente.objects.all()
    elif request.user.grupo == 'coordenador':
        clientes = Cliente.objects.filter(contratos__coordenador=request.user).distinct()
    elif request.user.grupo == 'gerente':
        clientes = Cliente.objects.filter(
            contratos__coordenador__centros__in=request.user.centros.all()
        ).distinct()
    else:
        return redirect('home')

    # 🔍 Campo de busca
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
    if request.user.grupo in ['suprimento', 'financeiro']:
        contratos = ContratoTerceiros.objects.all()
    elif request.user.grupo == 'coordenador':
        contratos = ContratoTerceiros.objects.filter(coordenador=request.user)
    elif request.user.grupo == 'gerente':
        contratos = ContratoTerceiros.objects.filter(
            coordenador__centros__in=request.user.centros.all()
        )
    else:
        return redirect('home')

    # 🔍 Campo de busca
    search_query = request.GET.get('search', '').strip()
    if search_query:
        contratos = contratos.filter(
            Q(cod_projeto__cod_projeto__icontains=search_query) |
            Q(num_contrato__icontains=search_query) |
            Q(cod_projeto__cliente__nome__icontains=search_query) |
            Q(empresa_terceira__nome__icontains=search_query) |
            Q(coordenador__username__icontains=search_query) |
            Q(status__icontains=search_query) |
            Q(num_contrato__icontains=search_query) |
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
    # 🔹 Filtro base por grupo de usuário
    if request.user.grupo in ['suprimento', 'financeiro']:
        fornecedores = EmpresaTerceira.objects.all()
    elif request.user.grupo == 'coordenador':
        fornecedores = EmpresaTerceira.objects.filter(
            contratos__coordenador=request.user
        ).distinct()
    elif request.user.grupo == 'gerente':
        fornecedores = EmpresaTerceira.objects.filter(
            contratos__coordenador__centros__in=request.user.centros.all()
        ).distinct()
    else:
        return redirect('home')

    # 🔍 Campo de busca
    search_query = request.GET.get('search', '').strip()
    if search_query:
        fornecedores = fornecedores.filter(
            Q(nome__icontains=search_query) |
            Q(cpf_cnpj__icontains=search_query) |  # campo genérico para CPF ou CNPJ
            Q(email__icontains=search_query) |
            Q(municipio__icontains=search_query) |
            Q(estado__icontains=search_query)
        )

    # 🔸 Ordenação e paginação
    fornecedores = fornecedores.order_by('nome')
    paginator = Paginator(fornecedores, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
    }

    return render(request, 'gestao_contratos/lista_fornecedores.html', context)


@login_required
def contrato_cliente_detalhe(request, pk):
    import plotly.graph_objects as go
    import pandas as pd

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
    import plotly.express as px
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

    # ---- Controle de edição ----
    if request.user.grupo in ["suprimento", "financeiro"]:
        if request.method == 'POST':
            form = ContratoForm(request.POST, instance=contrato)
            if form.is_valid():
                form.save()
                messages.success(request, "Contrato do Cliente atualizado com sucesso!")
                return redirect("lista_contratos")
            else:
                messages.error(request, "❌ Ocorreu um erro ao atualizar o contrato. Verifique os campos e tente novamente.")
        else:
            form = ContratoForm(instance=contrato)
        return render(request, 'contratos/contrato_detail_edit.html', {
            'form': form,
            'contrato': contrato,
            'grafico_contrato': grafico_contrato,
            'resumo_percentual': resumo_percentual,
        })

    return render(request, "contratos/contrato_detail.html", {
        'contrato': contrato,
        'grafico_contrato': grafico_contrato,
        'resumo_percentual': resumo_percentual,
    })



@login_required
def contrato_fornecedor_detalhe(request, pk):
    contrato = get_object_or_404(ContratoTerceiros, pk=pk)

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
        },
    )


@login_required
def contrato_fornecedor_editar(request, pk):
    contrato = get_object_or_404(ContratoTerceiros, pk=pk)

    # Permissões
    if request.user.grupo not in ["suprimento", "financeiro"]:
        messages.error(request, "❌ Você não tem permissão para editar contratos.")
        return redirect("contrato_fornecedor_detalhe", pk=pk)

    if request.method == "POST":
        # ⚠️ Incluímos request.FILES para que o arquivo seja capturado
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
    if request.user.grupo in ["suprimento", "financeiro"]:
        contratos = fornecedor.contratos.all()  # busca todos os contratos vinculados a este fornecedor
    elif request.user.grupo == "coordenador":
        contratos = fornecedor.contratos.filter(coordenador=request.user)
    else:
        contratos = fornecedor.contratos.filter(coordenador__centros__in=request.user.centros.all())

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
            {'form': form, 'fornecedor': fornecedor, 'contratos': contratos}
        )

    return render(
        request,
        'fornecedores/fornecedor_detail.html',
        {'fornecedor': fornecedor, 'contratos': contratos}
    )


@login_required
def nova_solicitacao_prospeccao(request):
    if request.user.grupo == 'coordenador' or request.user.grupo == 'financeiro' or request.user.grupo == 'gerente':
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
                    send_mail(
                        assunto, mensagem,
                        "hidro.gestao25@gmail.com",
                        list(suprimentos),
                        fail_silently=False,
                    )
                messages.success(request, "Solicitação de prospecção criada com sucesso!")
                return redirect('lista_solicitacoes')
            else:
                messages.error(request, "Por favor, corrija os erros abaixo e tente novamente.")
        else:
            form = SolicitacaoProspeccaoForm(user=request.user)
        return render(request, 'fornecedores/nova_solicitacao.html', {'form':form})
    return redirect('home')


@login_required
def lista_solicitacoes(request):
    if request.user.grupo == 'coordenador' or request.user.grupo == 'financeiro':
        solicitacoes = SolicitacaoProspeccao.objects.filter(coordenador=request.user).exclude(status="Onboarding").order_by('-data_solicitacao')
    elif request.user.grupo == 'suprimento':
        solicitacoes = SolicitacaoProspeccao.objects.all().exclude(status="Onboarding").order_by('-data_solicitacao')
    elif request.user.grupo == 'gerente':
        centros_do_gerente = request.user.centros.all()
        # filtra solicitações cujo solicitante tenha pelo menos um centro em comum
        solicitacoes = SolicitacaoProspeccao.objects.filter(
            coordenador__centros__in=centros_do_gerente
        ).exclude(status="Onboarding").distinct().order_by('-data_solicitacao')


    paginator = Paginator(solicitacoes, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {'page_obj': page_obj}

    return render(request, 'gestao_contratos/lista_solicitacoes.html', context)


@login_required
def aprovar_solicitacao(request, pk, acao):
    if request.user.grupo != 'suprimento':
        return redirect('home')

    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)
    if acao == "aprovar":
        solicitacao.status = "Aprovada pelo suprimento"
        solicitacao.aprovado = True
    elif acao == "reprovar":
        solicitacao.status = "Reprovada pelo suprimento"
        solicitacao.aprovado = False
    solicitacao.data_aprovacao = timezone.now()
    solicitacao.aprovado_por = request.user
    solicitacao.save()

    return redirect('lista_solicitacoes')


@login_required
def triagem_fornecedores(request, pk):
    if request.user.grupo != 'suprimento':
        return redirect('home')

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
            assunto = "Triagem de fornecedores realizada"
            mensagem = (
                f"Olá, {coordenador.username}\n\n"
                f"A equipe de suprimentos realizou uma triagem de fornecedores para você. \n\n"
                "Por favor, entre no sistema HIDROGestão para selecionar sua escolha.\n"
                "https://hidrogestao.pythonanywhere.com/"
            )
            send_mail(
                assunto, mensagem,
                "hidro.gestao25@gmail.com",
                [coordenador.email],
                fail_silently=False,
            )

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
    if request.user != solicitacao.coordenador:
        messages.error(request, "Você não tem permissão para essa ação.")
        return redirect("lista_solicitacoes")

    if request.method == "POST":
        solicitacao.nenhum_fornecedor_ideal = True
        solicitacao.fornecedores_selecionados.clear()
        solicitacao.triagem_realizada = False
        solicitacao.save()

        suprimentos = User.objects.filter(grupo="suprimento").values_list("email", flat=True)

        if suprimentos:
            assunto = "Triagem declarada ineficaz pelo coordenador"
            mensagem = (
                f"Olá,\n\n"
                f"O coordenador {solicitacao.coordenador.username} declarou que nenhum dos fornecedores é ideal."
                "Acesse o sistema HIDROGestão para mais informações.\n"
                "https://hidrogestao.pythonanywhere.com/"
            )
            send_mail(
                assunto, mensagem,
                "hidro.gestao25@gmail.com",
                list(suprimentos),
                fail_silently=False,
            )

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
    if request.user == solicitacao.coordenador and request.method == "POST":
        escolhido_id = request.POST.get("fornecedor_escolhido")
        if escolhido_id:
            fornecedor = get_object_or_404(EmpresaTerceira, pk=escolhido_id)
            solicitacao.fornecedor_escolhido = fornecedor
            solicitacao.nenhum_fornecedor_ideal = False
            solicitacao.status = 'Fornecedor selecionado'
            solicitacao.aprovacao_gerente = "pendente"
            solicitacao.save()

            # notifica gerente
            gerentes = list(User.objects.filter(grupo="gerente", centros__in=solicitacao.coordenador.centros.all()).distinct().values_list("email", flat=True))
            if gerentes:
                assunto = f"Aprovação necessária - Fornecedor escolhido para {solicitacao.contrato}"
                mensagem = (
                    f"O coordenador {solicitacao.coordenador.username} selecionou o fornecedor {fornecedor.nome}.\n\n"
                    f"É necessário que você aprove ou reprove essa escolha.\n"
                    f"Acesse o sistema HIDROGestão para mais informações:\n"
                    f"https://hidrogestao.pythonanywhere.com/"
                )
                send_mail(
                    assunto, mensagem,
                    "hidro.gestao25@gmail.com",
                    gerentes,
                    fail_silently=False,
                )

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
    if request.user.grupo != "gerente":
        messages.error(request, "Você não tem permissão para aprovar.")
        return redirect('home')

    # Verifica se o coordenador já escolheu um fornecedor
    if not solicitacao.fornecedor_escolhido:
        messages.warning(request, "Coordenador ainda não escolheu um fornecedor.")
        return redirect('detalhes_triagem_fornecedores', pk=pk)

    if request.method == "POST":
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

        assunto = ""
        mensagem = ""

        # --- Caso APROVADO ---
        if acao == "aprovar":
            solicitacao.status = "Fornecedor aprovado"
            solicitacao.aprovacao_fornecedor_gerente = "aprovado"
            solicitacao.aprocacao_fornecedor_gerente_em = timezone.now()
            solicitacao.save()

            messages.success(
                request,
                f"Fornecedor {solicitacao.fornecedor_escolhido.nome} aprovado pelo gerente."
            )

            assunto = f"Fornecedor {solicitacao.fornecedor_escolhido.nome} aprovado pela gerência"
            mensagem = (
                f"Prezados,\n\n"
                f"O gerente {request.user.get_full_name() or request.user.username} "
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
            solicitacao.fornecedor_escolhido = None
            solicitacao.triagem_realizada = False
            solicitacao.fornecedores_selecionados.clear()
            solicitacao.save()

            messages.warning(request, "Fornecedor reprovado. Nova triagem necessária pelo suprimento.")

            assunto = f"Fornecedor reprovado pela gerência"
            mensagem = (
                f"Prezados,\n\n"
                f"O gerente {request.user.get_full_name() or request.user.username} "
                f"reprovou o fornecedor selecionado na solicitação #{solicitacao.id}.\n\n"
                f"Contrato: {solicitacao.contrato.cod_projeto}\n"
                f"Cliente: {solicitacao.contrato.cliente.nome}\n\n"
                f"Uma nova triagem será necessária pelo setor de suprimentos.\n\n"
                f"Acesse o sistema para mais detalhes."
            )

        else:
            messages.error(request, "Ação inválida.")
            return redirect('detalhes_triagem_fornecedores', pk=pk)

        # Envia o e-mail para todos os destinatários (se houver)
        if emails_suprimentos:
            try:
                send_mail(
                    assunto,
                    mensagem,
                    settings.DEFAULT_FROM_EMAIL,
                    list(set(emails_suprimentos)),  # remove duplicados
                    fail_silently=False,
                )
            except Exception as e:
                messages.warning(request, f"Erro ao enviar e-mail: {e}")

        return redirect('lista_solicitacoes')

    return redirect('detalhes_triagem_fornecedores', pk=pk)

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
        "Planejamento do Contrato", #Planejamento do Contrato
        "Aprovação do Planejamento",
        "Onboarding", #Onboarding
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
                send_mail(
                    assunto, mensagem,
                    "hidro.gestao25@gmail.com",
                    list(gerente),
                    fail_silently=False,
                )

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


@login_required
def detalhes_contrato(request, pk):
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)

    # Busca o documento de contrato, se existir
    contrato_doc = getattr(solicitacao, "contrato_relacionado", None)

    # Busca o fornecedor escolhido e sua proposta
    fornecedor_escolhido = solicitacao.fornecedor_escolhido
    proposta_escolhida = None
    if fornecedor_escolhido:
        proposta_escolhida = PropostaFornecedor.objects.filter(
            solicitacao=solicitacao, fornecedor=fornecedor_escolhido
        ).first()

    # Fornecedores selecionados na triagem
    fornecedores_selecionados = solicitacao.fornecedores_selecionados.all()

    # Histórico: revisões feitas a partir desta
    revisoes = solicitacao.revisoes.all()
    # Se esta solicitação for uma revisão, mostramos também a origem
    origem = solicitacao.solicitacao_origem

    # Aprovação pelo gerente
    if request.method == "POST" and request.user.grupo == "gerente" and contrato_doc:
        acao = request.POST.get("acao")
        justificativa = request.POST.get("justificativa", "")

        if acao == "aprovar":
            solicitacao.aprovacao_gerencia = True
            solicitacao.reprovacao_gerencia = False
            solicitacao.justificativa_gerencia = ""
            solicitacao.status = "Planejamento do Contrato"

            coordenador = solicitacao.coordenador
            suprimentos = User.objects.filter(grupo="suprimento").values_list("email", flat=True)
            assunto = "A minuta de contrato foi APROVADA pela Gerência"
            mensagem = (
                f"Olá,\n\n"
                f"A minuta de contrato foi aprovada pela Gerência. \n\n"
                "Por favor, acompanhe o andamento no sistema HIDROGestão.\n"
                "https://hidrogestao.pythonanywhere.com/"
            )
            send_mail(
                assunto, mensagem,
                "hidro.gestao25@gmail.com",
                list(suprimentos),
                fail_silently=False,
            )
            mensagem = (
                f"Olá, {coordenador.username}\n\n"
                f"A minuta de contrato de contratação de terceiro foi aprovada pela Gerência. \n\n"
                "Por favor, acompanhe o andamento no sistema HIDROGestão.\n"
                "https://hidrogestao.pythonanywhere.com/"
            )
            send_mail(
                assunto, mensagem,
                "hidro.gestao25@gmail.com",
                [coordenador.email],
                fail_silently=False,
            )
            messages.success(
                request, f"Solicitação {solicitacao.id} aprovada com sucesso!"
            )

        elif acao == "reprovar":
            solicitacao.aprovacao_gerencia = False
            solicitacao.reprovacao_gerencia = True
            solicitacao.justificativa_gerencia = justificativa
            coordenador = solicitacao.coordenador
            suprimentos = User.objects.filter(grupo="suprimento").values_list("email", flat=True)
            assunto = "A minuta de contrato foi REPROVADA pela Gerência"
            mensagem = (
                f"Olá,\n\n"
                f"A minuta de contrato foi reprovada pela Gerência. \n\n"
                f"A justificativa para a reprovação foi:\n"
                f'"{solicitacao.justificativa_gerencia}"\n\n'
                "Por favor, acompanhe o andamento no sistema HIDROGestão.\n"
                "https://hidrogestao.pythonanywhere.com/"
            )
            send_mail(
                assunto, mensagem,
                "hidro.gestao25@gmail.com",
                list(suprimentos),
                fail_silently=False,
            )
            mensagem = (
                f"Olá, {coordenador.username}\n\n"
                f"A minuta de contrato para a contratação de terceiro foi reprovada pela Gerência e encaminhada para revisão. \n\n"
                "Por favor, acompanhe o andamento no sistema HIDROGestão.\n"
                "https://hidrogestao.pythonanywhere.com/"
            )
            send_mail(
                assunto, mensagem,
                "hidro.gestao25@gmail.com",
                [coordenador.email],
                fail_silently=False,
            )
            solicitacao.status = "Reprovado pela gerência"
            messages.warning(request, f"Solicitação {solicitacao.id} reprovada.")
        else:
            messages.error(request, "Ação inválida.")

        solicitacao.aprovado_por = request.user
        solicitacao.data_aprovacao = timezone.now()
        solicitacao.save()
        return redirect("lista_solicitacoes")

    context = {
        "solicitacao": solicitacao,
        "contrato_doc": contrato_doc,
        "fornecedor_escolhido": fornecedor_escolhido,
        "proposta_escolhida": proposta_escolhida,
        "fornecedores_selecionados": fornecedores_selecionados,
        "revisoes": revisoes,
        "origem": origem,
    }

    return render(request, "gestao_contratos/detalhes_contrato.html", context)


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

    # Garante que só o suprimento pode acessar
    if request.user.grupo != 'suprimento':
        return redirect('home')

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
def detalhe_bm(request, pk):
    bm = get_object_or_404(DocumentoBM, pk=pk)

    solicitacao = bm.solicitacao

    if request.method == "POST":
        acao = request.POST.get("acao")
        usuario = request.user

        # Se coordenador avaliando
        if usuario.grupo == "coordenador":
            if acao == "aprovar":
                bm.status_coordenador = "aprovado"
                bm.data_aprovacao_coordenador = timezone.now()

        # Se gerente avaliando
        elif usuario.grupo == "gerente":
            if acao == "aprovar":
                bm.status_gerente = "aprovado"
                bm.data_aprovacao_gerente = timezone.now()

        bm.save()

        try:
            documento = DocumentoContratoTerceiro.objects.get(solicitacao=solicitacao)
        except DocumentoContratoTerceiro.DoesNotExist:
            documento = None

        proposta = PropostaFornecedor.objects.filter(
            solicitacao=solicitacao,
            fornecedor=solicitacao.fornecedor_escolhido
        ).first()
        # Se ambos aprovaram → cria contrato e finaliza solicitação
        if (bm.status_coordenador=="aprovado") and (bm.status_gerente=="aprovado"):
            contrato, created = ContratoTerceiros.objects.get_or_create(
                cod_projeto=solicitacao.contrato,
                prospeccao=solicitacao,
                num_contrato=documento.numero_contrato if documento else None,
                empresa_terceira=solicitacao.fornecedor_escolhido,
                coordenador=solicitacao.coordenador,
                data_inicio=documento.prazo_inicio if documento else None,
                data_fim=documento.prazo_fim if documento else None,
                valor_total=documento.valor_total if documento else 0,
                objeto=documento.objeto if documento else "",
                condicao_pagamento=proposta.condicao_pagamento if proposta else None,
                status="Ativo",
                observacao=documento.observacao if documento else None,
            )
            Evento.objects.filter(prospeccao=solicitacao, contrato_terceiro__isnull=True).update(contrato_terceiro=contrato)
            solicitacao.status = "Onboarding"
            solicitacao.save()

        return redirect("lista_solicitacoes")

    return render(request, "gestao_contratos/detalhe_bm.html", {"bm": bm, "solicitacao": solicitacao})


@login_required
def aprovar_bm(request, pk, papel):
    bm = get_object_or_404(DocumentoBM, pk=pk)

    if papel == "coordenador" and request.user.groups.filter(name="Coordenador de Contrato").exists():
        bm.status_coordenador = "aprovado"
    elif papel == "gerente" and request.user.groups.filter(name="Gerente de Contrato").exists():
        bm.status_gerente = "aprovado"
    else:
        messages.error(request, "Você não tem permissão para aprovar este documento.")
        return redirect("lista_solicitacoes")

    bm.save()

    """# Se ambos aprovaram → criar ContratoTerceiros
    if bm.aprovado_por_ambos:
        ContratoTerceiros.objects.get_or_create(
            cod_projeto=bm.solicitacao.contrato,
            prospeccao=bm.solicitacao,
            empresa_terceira=bm.solicitacao.fornecedor,
            coordenador=bm.solicitacao.coordenador,
            data_inicio=date.today(),
            data_fim=date.today() + timedelta(days=365),  # ajustar regra real
            valor_total=Decimal("0.00"),  # ajustar conforme necessidade
            objeto="Contrato aprovado a partir do BM",
            status="aguardando_assinatura",
        )"""

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

    return redirect("detalhe_bm", pk=bm.pk)

@login_required
def cadastrar_evento(request, pk):
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
def cadastrar_evento_contrato(request, pk):
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
    evento = get_object_or_404(Evento, pk=pk)
    if request.method == "POST":
        solicitacao_id = evento.prospeccao.id
        evento.delete()
        return redirect("detalhes_solicitacao", pk=solicitacao_id)
    return render(request, "gestao_contratos/excluir_evento.html", {"evento": evento})


@login_required
def excluir_evento_contrato(request, pk):
    evento = get_object_or_404(Evento, pk=pk)
    if request.method == "POST":
        contrato_id = evento.contrato_terceiro.pk
        evento.delete()
        return redirect("contrato_fornecedor_detalhe", pk=contrato_id)
    return render(request, "gestao_contratos/excluir_evento_contrato.html", {"evento": evento})


@login_required
def registrar_entrega(request, pk):
    evento = get_object_or_404(Evento, pk=pk)
    contrato = evento.contrato_terceiro
    boletins = evento.boletins_medicao.all()

    if request.method == "POST":
        form = EventoEntregaForm(request.POST, request.FILES, instance=evento)

        # Se checkbox de "valor igual" estiver marcado, sobrescreve valor_pago
        valor_igual = request.POST.get("check_valor_igual") == "on"
        if valor_igual:
            form.data = form.data.copy()
            form.data['valor_pago'] = str(evento.valor_previsto)

        if form.is_valid():
            # Se houver BMs cadastrados, data_pagamento é obrigatório
            if evento.contrato_terceiro.boletins_medicao.exists() and not form.cleaned_data['data_pagamento']:
                form.add_error('data_pagamento', 'Preencha a Data de Pagamento, pois existem BMs cadastrados.')
            else:
                form.save()
                return redirect('contrato_fornecedor_detalhe', pk=contrato.pk)
    else:
        form = EventoEntregaForm(instance=evento)

    return render(request, "eventos/registrar_entrega.html", {
        "form": form,
        "evento": evento,
        "contrato": contrato,
        "boletins":boletins,
    })




@login_required
def previsao_pagamentos(request):
    form = FiltroPrevisaoForm(request.GET or None)
    pagamentos = []
    total_previsto = 0
    total_pago = 0
    grafico_html = None
    grafico_barra = None
    grafico_barras = None
    grafico_barras_projeto = None

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

        # === SUPRIMENTO ===
        if usuario.grupo == "suprimento":
            eventos = Evento.objects.filter(filtros_base)

        # === GERENTE ===
        elif usuario.grupo == "gerente":
            eventos = Evento.objects.filter(
                filtros_base,
                contrato_terceiro__coordenador__centros__in=usuario.centros.all()
            )

        else:
            return redirect('home')

        # Aplica o filtro do coordenador se foi selecionado
        if coordenador:
            eventos = eventos.filter(contrato_terceiro__coordenador=coordenador)

        eventos = eventos.order_by('data_prevista_pagamento', 'data_pagamento')

        # Tabela destrinchada
        pagamentos = eventos.values(
            'contrato_terceiro__cod_projeto__cod_projeto',
            'empresa_terceira__nome',
            'contrato_terceiro__coordenador__username',
            'data_prevista_pagamento',
            'valor_previsto',
            'data_pagamento',
            'valor_pago'
        )

        total_previsto = sum(item['valor_previsto'] or 0 for item in pagamentos)
        total_pago = sum(item['valor_pago'] or 0 for item in pagamentos)

        # ==== GRÁFICO 1: LINHA ACUMULADA ====
        eventos_previstos = eventos.filter(data_prevista_pagamento__isnull=False) \
            .annotate(valor=Coalesce('valor_previsto', 0, output_field=DecimalField())) \
            .order_by('data_prevista_pagamento')

        pagamentos_por_data_prevista = eventos_previstos.values('data_prevista_pagamento') \
            .annotate(total=Sum('valor')) \
            .order_by('data_prevista_pagamento')

        datas_prevista = []
        acumulado_previsto = []
        total_acumulado = 0
        for item in pagamentos_por_data_prevista:
            datas_prevista.append(item['data_prevista_pagamento'])
            total_acumulado += item['total']
            acumulado_previsto.append(total_acumulado)

        eventos_pagos = eventos.filter(data_pagamento__isnull=False) \
            .annotate(valor=Coalesce('valor_pago', 0, output_field=DecimalField())) \
            .order_by('data_pagamento')

        pagamentos_por_data_pago = eventos_pagos.values('data_pagamento') \
            .annotate(total=Sum('valor')) \
            .order_by('data_pagamento')

        datas_pago = []
        acumulado_pago = []
        total_acumulado_pago = 0
        for item in pagamentos_por_data_pago:
            datas_pago.append(item['data_pagamento'])
            total_acumulado_pago += item['total']
            acumulado_pago.append(total_acumulado_pago)

        if datas_prevista or datas_pago:
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
                title='Previsão x Pagamentos Acumulados',
                xaxis_title='Data',
                yaxis_title='Valor Acumulado (R$)',
                xaxis_tickformat='%d/%m/%Y',
                hovermode='x unified'
            )
            grafico_html = plot(fig, auto_open=False, output_type='div')

        # ==== GRÁFICO 2: BARRA PELO CALENDÁRIO (DIVIDIDO POR COORDENADOR) ====
        calendario = list(CalendarioPagamento.objects.order_by('data_pagamento').values_list('data_pagamento', flat=True))

        # Obtém todos os coordenadores envolvidos nos eventos filtrados
        coordenadores = list(set(
            eventos.values_list('contrato_terceiro__coordenador__username', flat=True)
        ))

        fig_barra = go.Figure()
        data_inicio = None

        # Para cada coordenador, gera uma série de barras empilhadas
        for coord in coordenadores:
            y_previstos = []
            data_inicio = None

            for data_fim in calendario:
                if data_inicio is None:
                    eventos_previsto = Evento.objects.filter(
                        data_prevista_pagamento__lte=data_fim,
                        contrato_terceiro__coordenador__username=coord
                    )
                else:
                    eventos_previsto = Evento.objects.filter(
                        data_prevista_pagamento__gt=data_inicio,
                        data_prevista_pagamento__lte=data_fim,
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

        # Layout empilhado e estilizado
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

        # ==== GRÁFICO 2.2: BARRA PELO CALENDÁRIO (DIVIDIDO POR PROJETO) ====
        calendario = list(CalendarioPagamento.objects.order_by('data_pagamento').values_list('data_pagamento', flat=True))

        # Obtém todos os coordenadores envolvidos nos eventos filtrados
        projetos = list(set(
            eventos.values_list('contrato_terceiro__cod_projeto__cod_projeto', flat=True)
        ))

        fig_barra_proj = go.Figure()
        data_inicio = None

        # Para cada coordenador, gera uma série de barras empilhadas
        for proj in projetos:
            y_previstos = []
            data_inicio = None

            for data_fim in calendario:
                if data_inicio is None:
                    eventos_previsto = Evento.objects.filter(
                        data_prevista_pagamento__lte=data_fim,
                        contrato_terceiro__cod_projeto__cod_projeto=proj
                    )
                else:
                    eventos_previsto = Evento.objects.filter(
                        data_prevista_pagamento__gt=data_inicio,
                        data_prevista_pagamento__lte=data_fim,
                        contrato_terceiro__cod_projeto__cod_projeto=proj
                    )

                total_previsto_periodo = eventos_previsto.aggregate(
                    total=Coalesce(Sum('valor_previsto'), Decimal('0.00'))
                )['total']

                y_previstos.append(total_previsto_periodo)
                data_inicio = data_fim

            fig_barra_proj.add_trace(go.Bar(
                name=f"{proj or 'Sem Coordenador'}",
                x=calendario,
                y=y_previstos
            ))

        # Layout empilhado e estilizado
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

        # ==== GRÁFICO 3: BARRA PELO CALENDÁRIO ====
        # Pega as datas do calendário do banco
        calendario = list(CalendarioPagamento.objects.order_by('data_pagamento').values_list('data_pagamento', flat=True))

        y_previstos = []
        y_pagos = []
        data_inicio = None

        for data_fim in calendario:
            if data_inicio is None:
                eventos_previsto = Evento.objects.filter(data_prevista_pagamento__lte=data_fim)
                eventos_pago = Evento.objects.filter(data_pagamento__lte=data_fim)
            else:
                eventos_previsto = Evento.objects.filter(
                    data_prevista_pagamento__gt=data_inicio,
                    data_prevista_pagamento__lte=data_fim
                )
                eventos_pago = Evento.objects.filter(
                    data_pagamento__gt=data_inicio,
                    data_pagamento__lte=data_fim
                )

            total_previsto_periodo = eventos_previsto.aggregate(
                total=Coalesce(Sum('valor_previsto'), Decimal('0.00'))
            )['total']

            total_pago_periodo = eventos_pago.aggregate(
                total=Coalesce(Sum('valor_pago'), Decimal('0.00'))
            )['total']

            y_previstos.append(total_previsto_periodo)
            y_pagos.append(total_pago_periodo)
            data_inicio = data_fim

        fig_barra = go.Figure(data=[
            go.Bar(name='Previsto', x=calendario, y=y_previstos, marker_color='orange'),
            go.Bar(name='Pago', x=calendario, y=y_pagos, marker_color='green')
        ])

        fig_barra.update_layout(
            barmode='group',
            title="Pagamentos Previsto x Pago (Calendário de pagamento)",
            xaxis_title="Data",
            yaxis_title="Valor (R$)",
            template="plotly_white",
            height=500
        )

        grafico_barra = plot(fig_barra, output_type='div')

    return render(request, "gestao_contratos/previsao_pagamentos.html", {
        "form": form,
        "pagamentos": pagamentos,
        "total_previsto": total_previsto,
        "total_pago": total_pago,
        "grafico_html": grafico_html,
        "grafico_barras": grafico_barras,
        "grafico_barras_projeto": grafico_barras_projeto,
        "grafico_barra": grafico_barra,
    })


@login_required
def exportar_previsao_pagamentos_excel(request):
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

    # === SUPRIMENTO ===
    if usuario.grupo == "suprimento":
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

    elif user.grupo == 'suprimento':
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
            return JsonResponse({"success": True})
        else:
            print(form.errors)
            return JsonResponse({"success": False, "errors": form.errors}, status=400)
    else:
        form = BMForm(initial={
            "valor_pago": evento.valor_previsto,
            "data_pagamento": evento.data_pagamento.strftime('%Y-%m-%d') if evento.data_pagamento else None,
        })
        return render(request, "bm/cadastrar_bm_popup.html", {
            "form": form,
            "contrato": contrato,
            "evento": evento,
        })


@login_required
def detalhes_entrega(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    bms = BM.objects.filter(evento=evento).order_by('-data_pagamento')

    return render(request, 'contratos/detalhes_entrega.html', {
        'evento': evento,
        'bms': bms,
    })
