from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic.edit import CreateView
from .models import Contrato, Cliente, EmpresaTerceira, ContratoTerceiros, SolicitacaoProspeccao, Indicadores, PropostaFornecedor, DocumentoContratoTerceiro, DocumentoBM, Evento
from .forms import ContratoForm, ClienteForm, FornecedorForm, ContratoFornecedorForm, SolicitacaoProspeccaoForm, DocumentoContratoTerceiroForm, DocumentoBMForm, EventoPrevisaoForm, EventoEntregaForm, FiltroPrevisaoForm


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


def is_financeiro(user):
    return user.is_authenticated and getattr(user, "grupo", None) == "financeiro"


def home(request):
    return render(request, 'home.html')


def logout(request):
    return render(request, 'logged_out.html')


@login_required
def lista_contratos(request):
    if request.user.grupo == 'suprimento' or request.user.grupo == 'financeiro':
        contratos = Contrato.objects.all().order_by('-data_inicio')

    elif request.user.grupo == 'coordenador':
        contratos = Contrato.objects.filter(coordenador=request.user).order_by('-data_inicio')

    elif request.user.grupo =='gerente':
        contratos = Contrato.objects.filter(coordenador__centros__in=request.user.centros.all()).order_by('-data_inicio')

    else:
        return redirect('home')

    paginator = Paginator(contratos, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    context = {'page_obj': page_obj}

    return render(request, 'gestao_contratos/lista_contratos.html', context)


@login_required
def lista_clientes(request):
    if request.user.grupo == 'suprimento' or request.user.grupo == 'financeiro':
        clientes = Cliente.objects.all().order_by('nome')
    elif request.user.grupo == 'coordenador':
        clientes = Cliente.objects.filter(contrato__coordenador=request.user).distinct().order_by('nome')

    elif request.user.grupo == 'gerente':
        clientes = Cliente.objects.filter(contrato__coordenador__centros__in=request.user.centros.all()).distinct().order_by('nome')

    else:
        return redirect('home')
    paginator = Paginator(clientes, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    context = {'page_obj': page_obj}

    return render(request, 'gestao_contratos/lista_clientes.html', context)


@login_required
def lista_contratos_fornecedor(request):

    if request.user.grupo == 'suprimento' or request.user.grupo == 'financeiro':
        contratos = ContratoTerceiros.objects.all().order_by('-data_inicio')

    elif request.user.grupo == 'coordenador':
        contratos = ContratoTerceiros.objects.filter(coordenador=request.user).order_by('-data_inicio')

    elif request.user.grupo == 'gerente':
        contratos = ContratoTerceiros.objects.filter(coordenador__centros__in=request.user.centros.all()).order_by('-data_inicio')


    else:
        return redirect('home')
    paginator = Paginator(contratos, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    context = {'page_obj': page_obj}

    return render(request, 'gestao_contratos/lista_contratos_fornecedores.html', context)


@login_required
def lista_fornecedores(request):
    if request.user.grupo == 'suprimento' or request.user.grupo == 'financeiro':
        fornecedores = EmpresaTerceira.objects.all().order_by('nome')
    elif request.user.grupo == 'coordenador':
        fornecedores = EmpresaTerceira.objects.filter(contratoterceiros__coordenador=request.user).distinct().order_by('nome')
    elif request.user.grupo == 'gerente':
        fornecedores = EmpresaTerceira.objects.filter(contratoterceiros__coordenador__centros__in=request.user.centros.all()). distinct().order_by('nome')
    else:
        return redirect('home')

    paginator = Paginator(fornecedores, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    context = {'page_obj': page_obj}

    return render(request, 'gestao_contratos/lista_fornecedores.html', context)


@login_required
def contrato_cliente_detalhe(request, pk):
    contrato = get_object_or_404(Contrato, pk=pk)

    if request.user.grupo == "suprimento" or request.user.grupo == 'financeiro':
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
        return render(request, 'contratos/contrato_detail_edit.html', {'form': form, 'contrato': contrato})
    return render(request, "contratos/contrato_detail.html", {'contrato': contrato})


@login_required
def contrato_fornecedor_detalhe(request, pk):
    contrato = get_object_or_404(ContratoTerceiros, pk=pk)

    proposta_fornecedor = None
    if contrato.prospeccao and contrato.prospeccao.fornecedor_escolhido:
        proposta_fornecedor = contrato.prospeccao.propostas.filter(
            fornecedor=contrato.prospeccao.fornecedor_escolhido
        ).first()

    eventos = Evento.objects.filter(contrato_terceiro=contrato).order_by("data_prevista")

    return render(
        request,
        "contratos/contrato_fornecedor_detail.html",
        {
            "contrato": contrato,
            "proposta_fornecedor": proposta_fornecedor,
            "eventos": eventos,
        },
    )


@login_required
def contrato_fornecedor_editar(request, pk):
    contrato = get_object_or_404(ContratoTerceiros, pk=pk)

    if request.user.grupo not in ["suprimento", "financeiro"]:
        messages.error(request, "❌ Você não tem permissão para editar contratos.")
        return redirect("contrato_fornecedor_detalhe", pk=pk)

    if request.method == "POST":
        form = ContratoFornecedorForm(request.POST, instance=contrato)
        if form.is_valid():
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

    if request.user.grupo == "suprimento" or request.user.grupo == 'financeiro':
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
        return render(request, 'clientes/cliente_detail_edit.html', {'form': form, 'cliente':cliente})
    return render(request, 'clientes/cliente_detail.html', {'cliente': cliente})


@login_required
def fornecedor_detalhe(request, pk):
    fornecedor = get_object_or_404(EmpresaTerceira, pk=pk)

    if request.user.grupo == "suprimento" or request.user.grupo == 'financeiro':
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
        return render(request, 'fornecedores/fornecedor_detail_edit.html', {'form': form, 'fornecedor':fornecedor})
    return render(request, 'fornecedores/fornecedor_detail.html', {'fornecedor': fornecedor})


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
        solicitacoes = SolicitacaoProspeccao.objects.filter(coordenador=request.user).exclude(status="Finalizada").order_by('-data_solicitacao')
    elif request.user.grupo == 'suprimento':
        solicitacoes = SolicitacaoProspeccao.objects.all().exclude(status="Finalizada").order_by('-data_solicitacao')
    elif request.user.grupo == 'gerente':
        centros_do_gerente = request.user.centros.all()
        # filtra solicitações cujo solicitante tenha pelo menos um centro em comum
        solicitacoes = SolicitacaoProspeccao.objects.filter(
            coordenador__centros__in=centros_do_gerente
        ).exclude(status="Finalizada").distinct().order_by('-data_solicitacao')


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

    if request.user.grupo != "gerente":
        messages.error(request, "Você não tem permissão para aprovar.")
        return redirect('home')

    if not solicitacao.fornecedor_escolhido:
        messages.warning(request, "Coordenador ainda não escolheu um fornecedor.")
        return redirect('detalhes_triagem_fornecedores', pk=pk)

    if request.method == "POST":
        acao = request.POST.get("acao")
        if acao == "aprovar":
            solicitacao.status = "Fornecedor aprovado"
            solicitacao.aprovacao_fornecedor_gerente = "aprovado"
            solicitacao.aprocacao_fornecedor_gerente_em = timezone.now()
            messages.success(request, f"Fornecedor {solicitacao.fornecedor_escolhido.nome} aprovado pelo gerente.")
        elif acao == "reprovar":
            solicitacao.status = "Fornecedor reprovado pela gerência"
            solicitacao.aprovacao_fornecedor_gerente = "reprovado"
            solicitacao.fornecedor_escolhido = None
            solicitacao.triagem_realizada = False
            solicitacao.fornecedores_selecionados.clear()
            messages.warning(request, "Fornecedor reprovado. Nova triagem necessária pelo suprimento.")
        else:
            messages.error(request, "Ação inválida.")
            return redirect('detalhes_triagem_fornecedores', pk=pk)

        solicitacao.save()
        return redirect('lista_solicitacoes')

    return redirect('detalhes_triagem_fornecedores', pk=pk)

@login_required
def detalhes_solicitacao(request, pk):
    # Busca a solicitação
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)

    status_order = [
        "Solicitação de prospeccao",
        "Aprovada pelo suprimento",
        "Triagem realizada",
        "Fornecedor selecionado",
        "Fornecedor aprovado",
        "Planejamento do BM",
        "Aprovação do Planejamento",
        "Finalizada",
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
    ).select_related("fornecedor_escolhido").exclude(status="Finalizada")

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
            solicitacao.status = "Planejamento do BM"

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
            solicitacao.status = "Planejamento do BM"
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
        # Se ambos aprovaram → cria contrato e finaliza solicitação
        if (bm.status_coordenador=="aprovado") and (bm.status_gerente=="aprovado"):
            contrato, created = ContratoTerceiros.objects.get_or_create(
                cod_projeto=solicitacao.contrato,
                prospeccao=solicitacao,
                empresa_terceira=solicitacao.fornecedor_escolhido,
                coordenador=solicitacao.coordenador,
                data_inicio=documento.prazo_inicio if documento else None,
                data_fim=documento.prazo_fim if documento else None,
                valor_total=documento.valor_total if documento else 0,
                objeto=documento.objeto if documento else "",
                status="Em execução",
            )
            Evento.objects.filter(prospeccao=solicitacao, contrato_terceiro__isnull=True).update(contrato_terceiro=contrato)
            solicitacao.status = "Finalizada"
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

    if request.method == "POST":
        form = EventoEntregaForm(request.POST, request.FILES, instance=evento)
        if form.is_valid():
            form.save()
            return redirect('contrato_fornecedor_detalhe', pk=evento.contrato_terceiro.pk)
    else:
        form = EventoEntregaForm(instance=evento)

    return render(request, "eventos/registrar_entrega.html", {
        "form": form,
        "evento": evento,
        "contrato": evento.contrato_terceiro,
    })


@login_required
def previsao_pagamentos(request):
    pagamentos = None
    total = 0
    form = FiltroPrevisaoForm(request.GET or None)

    if form.is_valid():
        data_limite = form.cleaned_data["data_limite"]

        # Filtra todos eventos previstos até a data
        pagamentos = (
            Evento.objects.filter(data_pagamento__lte=data_limite)
            .values("contrato_terceiro__cod_projeto__cod_projeto","empresa_terceira__nome")
            .annotate(total_pago=Sum("valor_previsto"))
            .order_by("empresa_terceira__nome")
        )

        total = sum(p["total_pago"] for p in pagamentos)

    return render(request, "gestao_contratos/previsao_pagamentos.html", {
        "form": form,
        "pagamentos": pagamentos,
        "total": total,
    })
