/* Reutiliza os endpoints existentes, sem outra rotina de pagamento. */
(() => {
  const modalElement = document.getElementById('financeModal');
  if (!modalElement) return;
  const content = modalElement.querySelector('[data-finance-modal-content]');
  const errors = modalElement.querySelector('[data-finance-modal-errors]');
  const showError = message => { errors.textContent = message; errors.classList.remove('d-none'); };
  let currentUrl = '', busy = false, loadId = 0;
  async function save(event) {
    event.preventDefault();
    const form = content.querySelector('form');
    if (!form || busy || form.dataset.readOnly === 'true' || !form.reportValidity()) return;
    busy = true;
    errors.classList.add('d-none');
    const buttons = content.querySelectorAll('button');
    buttons.forEach(b => b.disabled = true);
    try {
      const response = await fetch(currentUrl, {method:'POST', body:new FormData(form), credentials:'same-origin', headers:{'X-Requested-With':'XMLHttpRequest'}});
      const data = await response.json();
      if (response.ok && data.success) { window.location.reload(); return; }
      const messages = Object.entries(data.errors || {}).flatMap(([field,items]) => (Array.isArray(items) ? items : [items]).map(item => `${form.elements.namedItem(field)?.labels?.[0]?.textContent || 'Formulário'}: ${typeof item === 'string' ? item : item.message || 'Revise o campo.'}`));
      showError(data.error || messages.join(' ') || 'Não foi possível salvar. Revise o formulário.');
    } catch (_) { showError('Não foi possível concluir a operação. Atualize a página e tente novamente.'); }
    finally { busy = false; buttons.forEach(b => b.disabled = false); }
  }
  document.addEventListener('click', async event => {
    const trigger = event.target.closest('[data-finance-modal-url]');
    if (!trigger) return;
    event.preventDefault();
    if (!window.bootstrap) return;
    const url = new URL(trigger.dataset.financeModalUrl, location.href);
    if (url.origin !== location.origin) return;
    const id = ++loadId;
    currentUrl = url.href; busy = false;
    content.textContent = 'Carregando formulário…'; errors.classList.add('d-none');
    document.getElementById('financeModalTitle').textContent = trigger.dataset.financeModalTitle || 'Lançamento financeiro';
    bootstrap.Modal.getOrCreateInstance(modalElement).show();
    try {
      const response = await fetch(currentUrl, {credentials:'same-origin', headers:{'X-Requested-With':'XMLHttpRequest'}});
      if (!response.ok || response.redirected) throw new Error();
      const html = await response.text();
      if (id !== loadId) return;
      const parsed = new DOMParser().parseFromString(html,'text/html');
      parsed.querySelectorAll('script:not([type="application/json"])').forEach(s => s.remove());
      if (!parsed.querySelector('form')) throw new Error();
      content.replaceChildren(...Array.from(parsed.body.childNodes));
      const form = content.querySelector('form');
      form.addEventListener('submit',save);
      content.querySelectorAll('#btnSalvarNF,#btnSalvarBM').forEach(b => b.addEventListener('click',save));
      if (window.flatpickr) flatpickr(content.querySelectorAll('.datepicker'), {dateFormat:'d-m-Y',allowInput:true});
    } catch (_) { content.textContent = ''; showError('Não foi possível abrir o formulário. Verifique sua sessão e tente novamente.'); }
  });
  document.addEventListener('submit',event => {
    const message = event.target.dataset.financeConfirm;
    if (message && !window.confirm(message)) event.preventDefault();
  });
})();
