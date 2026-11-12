import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import OperacaoSolicitacaoForm
from .solicitacao_services import MODELOS, alterar_solicitacao

logger = logging.getLogger(__name__)


@login_required
@require_POST
def operar_solicitacao(request, tipo, pk, operacao):
    model = MODELOS.get(tipo)
    if model is None or operacao not in {"arquivar", "desarquivar", "cancelar"}:
        raise Http404
    form = OperacaoSolicitacaoForm(request.POST, operacao=operacao)
    if not form.is_valid():
        messages.error(request, " ".join(error for errors in form.errors.values() for error in errors))
        return redirect("lista_solicitacoes")
    try:
        solicitacao, alterada = alterar_solicitacao(
            model=model, pk=pk, user=request.user, operacao=operacao,
            motivo=form.cleaned_data["motivo"], arquivar=form.cleaned_data["arquivar"],
            token=str(form.cleaned_data["token"]),
        )
    except model.DoesNotExist:
        raise Http404 from None
    except PermissionDenied:
        raise
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    except DatabaseError:
        logger.exception("Falha na operação de solicitação %s #%s", tipo, pk)
        messages.error(request, "Não foi possível concluir a operação. Nenhuma alteração foi confirmada. Tente novamente.")
    else:
        if not alterada:
            messages.info(request, "Esta operação já foi processada ou a solicitação já está nesse estado.")
        else:
            text = {"arquivar": "Solicitação arquivada com sucesso.",
                    "desarquivar": "Solicitação desarquivada com sucesso.",
                    "cancelar": "Solicitação cancelada com sucesso."}[operacao]
            if operacao == "cancelar" and form.cleaned_data["arquivar"]:
                text = "Solicitação cancelada e arquivada com sucesso."
            messages.success(request, text)
    # Mesmo validador de destinos locais utilizado pelas aprovações existentes.
    from .views import approval_return_url
    return redirect(approval_return_url(request, reverse("lista_solicitacoes")))
