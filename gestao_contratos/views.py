from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic.edit import CreateView
from .models import Contrato, Cliente, EmpresaTerceira, ContratoTerceiros, SolicitacaoProspeccao, Indicadores, PropostaFornecedor, DocumentoContratoTerceiro
from .forms import ContratoForm, ClienteForm, FornecedorForm, ContratoFornecedorForm, SolicitacaoProspeccaoForm, DocumentoContratoTerceiroForm


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

    if request.user.grupo == "suprimento" or request.user.grupo == 'financeiro':
        if request.method == 'POST':
            form = ContratoFornecedorForm(request.POST, instance=contrato)
            if form.is_valid():
                form.save()
                messages.success(request, "Contrato do Fornecedor atualizado com sucesso!")
                return redirect("lista_contratos_fornecedores")
            else:
                messages.error(request, "❌ Ocorreu um erro ao atualizar o contrato. Verifique os campos e tente novamente.")
        else:
            form = ContratoFornecedorForm(instance=contrato)
        return render(request, 'contratos/contrato_fornecedor_detail_edit.html', {'form': form, 'contrato': contrato})
    return render(request, 'contratos/contrato_fornecedor_detail.html', {'contrato': contrato})


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
        solicitacoes = SolicitacaoProspeccao.objects.filter(coordenador=request.user).order_by('-data_solicitacao')
    elif request.user.grupo == 'suprimento':
        solicitacoes = SolicitacaoProspeccao.objects.all().order_by('-data_solicitacao')
    elif request.user.grupo == 'gerente':
        centros_do_gerente = request.user.centros.all()
        # filtra solicitações cujo solicitante tenha pelo menos um centro em comum
        solicitacoes = SolicitacaoProspeccao.objects.filter(
            coordenador__centros__in=centros_do_gerente
        ).distinct().order_by('-data_solicitacao')


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
        solicitacao.aprovado = True
    elif acao == "reprovar":
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

    # Mapeia fornecedores para seus indicadores
    fornecedores_indicadores = {}
    for f in fornecedores:
        indicadores = Indicadores.objects.filter(empresa_terceira=f)
        fornecedores_indicadores[f.id] = indicadores if indicadores.exists() else None

    # Mapeia propostas de cada fornecedor da solicitação
    propostas_dict = {}
    for f in solicitacao.fornecedores_selecionados.all():
        try:
            prop = PropostaFornecedor.objects.get(solicitacao=solicitacao, fornecedor=f)
            propostas_dict[f.id] = prop
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

            # Para cada fornecedor selecionado, salva valor e arquivo
            for f_id in fornecedores_ids:
                fornecedor = get_object_or_404(EmpresaTerceira, pk=f_id)
                valor = request.POST.get(f"valor_{f_id}")
                prazo_validade = request.POST.get(f"prazo_{f_id}")
                condicao = request.POST.get(f"condicao_{f_id}")
                arquivo = request.FILES.get(f"arquivo_{f_id}")

                # Só cria ou atualiza a proposta se tiver algum valor ou arquivo
                if valor or arquivo or condicao or prazo_validade:
                    proposta_obj, _ = PropostaFornecedor.objects.get_or_create(
                        solicitacao=solicitacao,
                        fornecedor=fornecedor,

                    )
                    if valor:
                        try:
                            # Converte para float
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

    # Se coordenador estiver escolhendo o fornecedor
    if request.user == solicitacao.coordenador and request.method == "POST":
        escolhido_id = request.POST.get("fornecedor_escolhido")
        if escolhido_id:
            fornecedor = get_object_or_404(EmpresaTerceira, pk=escolhido_id)
            solicitacao.fornecedor_escolhido = fornecedor
            solicitacao.nenhum_fornecedor_ideal = False
            solicitacao.status = 'Fornecedor Selecionado'
            solicitacao.save()

            suprimentos = User.objects.filter(grupo="suprimento").values_list("email", flat=True)

            if suprimentos:
                assunto = f"Fornecedor escolhido pelo coordenador {solicitacao.coordenador.username}"
                mensagem = (
                    f"Olá,\n\n"
                    f"O coordenador {solicitacao.coordenador.username} selecionou o fornecedor {fornecedor.nome} da triagem como ideal./n"
                    "Acesse o sistema HIDROGestão para mais informações.\n"
                    "https://hidrogestao.pythonanywhere.com/"
                )
                send_mail(
                    assunto, mensagem,
                    "hidro.gestao25@gmail.com",
                    list(suprimentos),
                    fail_silently=False,
                )

            messages.success(request, f"Fornecedor do {solicitacao.contrato} escolhido: {fornecedor.nome}")
        return redirect('lista_solicitacoes')

    context = {
        "solicitacao": solicitacao,
        "fornecedores_selecionados": fornecedores_selecionados,
        "propostas_dict": propostas_dict,
    }
    return render(request, "fornecedores/detalhes_triagem_fornecedores.html", context)


@login_required
def detalhes_solicitacao(request, pk):
    # Busca a solicitação
    solicitacao = get_object_or_404(SolicitacaoProspeccao, pk=pk)

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

    context = {
        "solicitacao": solicitacao,
        "fornecedor_escolhido": fornecedor_escolhido,
        "proposta_escolhida": proposta_escolhida,
        "fornecedores_selecionados": fornecedores_selecionados,
        "indicadores": indicadores,
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
        fornecedor_escolhido__isnull=False
    ).select_related("fornecedor_escolhido")

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
            solicitacao.status = "Aguardando boletim"

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
