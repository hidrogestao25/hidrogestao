/* Confirma a transição para paga, mantendo os endpoints e formulários atuais. */
(() => {
  function confirmPayment(event, form, resume) {
    if (!form || form.dataset.readOnly === 'true' || form.dataset.nfInitialPaid === 'true') return;
    if (form.dataset.nfConfirmed === event.type) { delete form.dataset.nfConfirmed; return; }
    if (!form.hasAttribute('data-ledger-payment-form') && !form.querySelector('[name="financeiro_autorizou"]')?.checked) return;
    const panel = form.querySelector('[data-nf-confirm-panel]');
    if (!panel) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (!panel.hidden) { panel.focus(); return; }
    if (!form.reportValidity()) return;
    const amount = form.querySelector('[name="valor"],[name="valor_pago"]')?.value || '';
    const day = form.querySelector('[name="data_pagamento"]')?.value || '';
    const bm = form.querySelector('[name="bm"] option:checked')?.textContent || '';
    panel.querySelector('[data-nf-confirm-summary]').textContent = `Valor informado: R$ ${amount} · Data: ${day} · ${bm}`;
    const enabled = [...form.querySelectorAll('input,select,textarea')].filter(field => !field.disabled);
    enabled.forEach(field => { field.disabled = true; });
    const restore = () => { enabled.forEach(field => { field.disabled = false; }); panel.hidden = true; };
    panel.querySelector('[data-nf-confirm-cancel]').onclick = () => { restore(); };
    panel.querySelector('[data-nf-confirm-accept]').onclick = () => {
      restore();
      if (!form.isConnected) return;
      form.dataset.nfConfirmed = event.type;
      resume();
    };
    panel.hidden = false;
    panel.scrollIntoView({block:'nearest'});
    panel.focus();
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('#btnSalvarNF');
    if (!button) return;
    const form = button.closest('.modal')?.querySelector('form[data-nf-payment-form]') || document.querySelector('form[data-nf-payment-form]');
    confirmPayment(event, form, () => button.click());
  }, true);
  document.addEventListener('submit', event => {
    const form = event.target;
    if (form.matches('form[data-nf-payment-form]')) confirmPayment(event, form, () => form.requestSubmit());
  }, true);
})();
