/* Decisões na previsão e no detalhe, com recarga após cada gravação. */
(() => {
  const modal = document.getElementById('decisaoPagamentoBMModal');
  if (!modal) return;
  const form = modal.querySelector('[data-bm-payment-form]');
  const reason = form.elements.namedItem('justificativa');
  const action = form.elements.namedItem('acao');
  const token = form.elements.namedItem('token');
  const error = modal.querySelector('[data-bm-payment-error]');
  const submit = modal.querySelector('[data-bm-payment-submit]');
  let busy = false;
  reason.addEventListener('input', () => reason.setCustomValidity(''));
  modal.addEventListener('hide.bs.modal', event => { if (busy) event.preventDefault(); });
  async function send(url, values, feedback, controls) {
    if (busy) return;
    busy = true;
    controls.forEach(control => { control.disabled = true; });
    feedback.classList.add('d-none'); form.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}, body: values});
      const result = await response.json();
      if (response.ok && result.success) { location.reload(); return; }
      feedback.textContent = result.error || 'Não foi possível registrar a operação. Atualize a página e confira o BM.';
      feedback.classList.remove('d-none');
    } catch (_) {
      feedback.textContent = 'Não foi possível confirmar. Atualize a página para conferir o estado do BM antes de repetir.';
      feedback.classList.remove('d-none');
    } finally { busy = false; controls.forEach(control => { control.disabled = false; }); form.removeAttribute('aria-busy'); }
  }
  function open(url, operation, text, number, context, currentToken = '') {
    const rejecting = operation === 'reprovar_pagamento', editing = operation === 'salvar_justificativa';
    const description = modal.querySelector('[data-bm-payment-description]');
    if (description) description.textContent = editing ? 'Registre a justificativa da Diretoria para este BM.' : 'Esta decisão autoriza ou bloqueia novas liquidações. O pagamento efetivo é registrado pelo Financeiro, com saldo e comprovante próprios.';
    form.reset(); form.action = url.href; action.value = operation; token.value = currentToken;
    reason.value = text; reason.required = rejecting || editing; reason.setCustomValidity('');
    modal.querySelector('[data-bm-payment-label]').textContent = rejecting ? 'Justificativa da reprovação (obrigatória)' : editing ? 'Justificativa' : 'Justificativa da aprovação (opcional)';
    document.getElementById('decisaoPagamentoBMTitle').textContent = `${editing ? 'Justificativa' : rejecting ? 'Reprovar pagamento' : 'Aprovar pagamento'} · BM ${number}${context ? ' · ' + context : ''}`;
    submit.className = `btn ${rejecting ? 'btn-danger' : 'btn-success'}`;
    submit.textContent = editing ? 'Salvar justificativa' : rejecting ? 'Confirmar reprovação' : 'Confirmar aprovação';
    error.classList.add('d-none'); bootstrap.Modal.getOrCreateInstance(modal).show();
  }
  document.addEventListener('click', event => {
    const forecast = event.target.closest('[data-bm-forecast-action]');
    const trigger = forecast || event.target.closest('[data-bm-payment-action]');
    if (!trigger || trigger.disabled || busy || !window.bootstrap) return;
    event.preventDefault();
    if (forecast) {
      const row = forecast.closest('[data-bm-forecast-row]');
      const url = new URL(row.dataset.bmForecastUrl, location.href);
      if (url.origin !== location.origin) return;
      const operation = forecast.dataset.bmForecastAction;
      if (!['aprovar_pagamento', 'reprovar_pagamento', 'salvar_justificativa', 'excluir_justificativa'].includes(operation)) return;
      const text = (row.querySelector('[data-bm-current-justification]')?.innerText || '').trim();
      if (operation === 'salvar_justificativa' || (operation === 'reprovar_pagamento' && !text)) {
        open(url, operation, text, row.dataset.bmForecastNumber, row.dataset.bmForecastContext, row.dataset.bmForecastToken);
      } else {
        const values = new URLSearchParams({acao: operation, justificativa: text, token: row.dataset.bmForecastToken, csrfmiddlewaretoken: form.elements.namedItem('csrfmiddlewaretoken').value});
        send(url.href, values, row.querySelector('[data-bm-forecast-error]'), [...row.querySelectorAll('[data-bm-forecast-action]')]);
      }
      return;
    }
    const operation = trigger.dataset.bmPaymentAction;
    if (!['aprovar_pagamento', 'reprovar_pagamento'].includes(operation)) return;
    const url = new URL(trigger.dataset.bmPaymentUrl, location.href);
    if (url.origin === location.origin) open(url, operation, trigger.dataset.bmPaymentReason || '', trigger.dataset.bmPaymentNumber, '');
  });
  form.addEventListener('submit', event => {
    event.preventDefault();
    reason.setCustomValidity(['reprovar_pagamento', 'salvar_justificativa'].includes(action.value) && !reason.value.trim() ? 'Informe a justificativa.' : '');
    if (busy || !form.reportValidity()) return;
    send(form.action, new URLSearchParams(new FormData(form)), error, [submit]);
  });
})();
