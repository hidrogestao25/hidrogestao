/* A mesma confirmação atende Eventos, OS e consulta financeira do BM. */
(() => {
  const modal = document.getElementById('decisaoPagamentoBMModal');
  if (!modal) return;
  const form = modal.querySelector('[data-bm-payment-form]');
  const reason = form.elements.namedItem('justificativa');
  const action = form.elements.namedItem('acao');
  const error = modal.querySelector('[data-bm-payment-error]');
  const submit = modal.querySelector('[data-bm-payment-submit]');
  let busy = false;
  reason.addEventListener('input', () => reason.setCustomValidity(''));
  modal.addEventListener('hide.bs.modal', event => { if (busy) event.preventDefault(); });
  document.addEventListener('click', event => {
    const trigger = event.target.closest('[data-bm-payment-action]');
    if (!trigger || trigger.disabled || busy || !window.bootstrap) return;
    event.preventDefault();
    const decision = trigger.dataset.bmPaymentAction;
    if (!['aprovar_pagamento', 'reprovar_pagamento'].includes(decision)) return;
    const url = new URL(trigger.dataset.bmPaymentUrl, location.href);
    if (url.origin !== location.origin) return;
    const rejecting = decision === 'reprovar_pagamento';
    form.reset();form.action = url.href;action.value = decision;
    reason.required = rejecting;reason.setCustomValidity('');
    modal.querySelector('[data-bm-payment-label]').textContent = rejecting ? 'Justificativa da reprovação (obrigatória)' : 'Justificativa da aprovação (opcional)';
    document.getElementById('decisaoPagamentoBMTitle').textContent = `${rejecting ? 'Reprovar' : 'Aprovar'} pagamento · BM ${trigger.dataset.bmPaymentNumber}`;
    submit.className = `btn ${rejecting ? 'btn-danger' : 'btn-success'}`;
    submit.textContent = rejecting ? 'Confirmar reprovação' : 'Confirmar aprovação';
    error.classList.add('d-none');
    bootstrap.Modal.getOrCreateInstance(modal).show();
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    reason.setCustomValidity(action.value === 'reprovar_pagamento' && !reason.value.trim() ? 'Informe a justificativa da reprovação.' : '');
    if (!form.reportValidity()) return;
    busy = true;submit.disabled = true;form.setAttribute('aria-busy', 'true');error.classList.add('d-none');
    try {
      const response = await fetch(form.action, {method: 'POST', credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}, body: new URLSearchParams(new FormData(form))});
      const result = await response.json();
      if (response.ok && result.success) { location.reload();return; }
      error.textContent = result.error || 'Não foi possível registrar a decisão. Atualize a página e confira o estado do BM.';
      error.classList.remove('d-none');
    } catch (_) {
      error.textContent = 'Não foi possível confirmar a operação. Atualize a página para conferir o estado do BM antes de repetir.';
      error.classList.remove('d-none');
    } finally { busy = false;submit.disabled = false;form.removeAttribute('aria-busy'); }
  });
})();
