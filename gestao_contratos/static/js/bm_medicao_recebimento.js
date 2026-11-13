/* Edição pelo Financeiro, com versão para impedir sobrescritas de outro usuário. */
(() => {
  const modal = document.getElementById('medicaoRecebimentoBMModal');
  if (!modal) return;
  const form = modal.querySelector('[data-bm-recebimento-form]');
  const fields = ['sobre_medicao', 'sobre_medicao_recebimento'].map(name => form.elements.namedItem(name));
  const error = modal.querySelector('[data-bm-recebimento-error]');
  const submit = modal.querySelector('[data-bm-recebimento-submit]');
  let saving = false, sequence = 0, controller;
  const showError = message => { error.textContent = message;error.classList.remove('d-none'); };
  fields.forEach(field => field.addEventListener('input', () => field.setCustomValidity('')));
  modal.addEventListener('hide.bs.modal', event => {
    if (saving) { event.preventDefault();return; }
    sequence += 1;
    if (controller) controller.abort();
  });
  document.addEventListener('click', async event => {
    const trigger = event.target.closest('[data-bm-recebimento-action]');
    if (!trigger || saving || !window.bootstrap) return;
    const action = trigger.dataset.bmRecebimentoAction;
    if (!['salvar', 'excluir'].includes(action)) return;
    const url = new URL(trigger.dataset.bmRecebimentoUrl, location.href);
    if (url.origin !== location.origin) return;
    event.preventDefault();
    if (controller) controller.abort();
    controller = new AbortController();
    const current = ++sequence;
    form.reset();form.action = url.href;form.elements.namedItem('acao').value = action;
    fields.forEach(field => { field.disabled = true;field.setCustomValidity(''); });
    submit.disabled = true;submit.className = `btn ${action === 'excluir' ? 'btn-danger' : 'btn-primary'}`;
    submit.textContent = action === 'excluir' ? 'Confirmar exclusão' : 'Salvar informações';
    const supplier = (trigger.dataset.bmSupplier || '').trim();
    const project = (trigger.dataset.bmProject || '').trim();
    const context = [supplier, project && project !== '-' ? `Projeto ${project}` : ''].filter(Boolean);
    document.getElementById('medicaoRecebimentoBMTitle').textContent = [
      `${action === 'excluir' ? 'Excluir informação' : 'Medição e recebimento'} · BM ${trigger.dataset.bmNumber}`,
      ...context,
    ].join(' · ');
    modal.querySelector('[data-bm-recebimento-delete]').classList.toggle('d-none', action !== 'excluir');
    modal.querySelector('[data-bm-recebimento-author]').textContent = 'Carregando informações…';
    error.classList.add('d-none');
    bootstrap.Modal.getOrCreateInstance(modal).show();
    try {
      const response = await fetch(url.href, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
        headers: {'X-Requested-With': 'XMLHttpRequest'}});
      const result = await response.json();
      if (current !== sequence) return;
      if (!response.ok || !result.success) throw new Error(result.error || 'Não foi possível carregar as informações.');
      const info = result.informacao;
      form.elements.namedItem('versao').value = result.versao;
      fields.forEach(field => { field.value = info ? info[field.name] : '';field.disabled = action === 'excluir'; });
      modal.querySelector('[data-bm-recebimento-author]').textContent = info ? `Inserido por ${info.identificacao_criador}. Última alteração por ${info.identificacao_editor}.` : 'Preencha os dois campos obrigatórios.';
      if (action === 'excluir' && !info) { showError('Esta informação já foi excluída. Atualize a página.');return; }
      submit.disabled = false;
    } catch (failure) {
      if (failure.name !== 'AbortError' && current === sequence) showError(failure.message || 'Não foi possível carregar as informações.');
    }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (saving || submit.disabled) return;
    const deleting = form.elements.namedItem('acao').value === 'excluir';
    if (!deleting) fields.forEach(field => field.setCustomValidity(field.value.trim() ? '' : 'Preencha este campo obrigatório.'));
    if (!form.reportValidity()) return;
    saving = true;submit.disabled = true;form.setAttribute('aria-busy', 'true');error.classList.add('d-none');
    try {
      const response = await fetch(form.action, {method: 'POST', credentials: 'same-origin',
        headers: {'X-Requested-With': 'XMLHttpRequest'}, body: new URLSearchParams(new FormData(form))});
      const result = await response.json();
      if (response.ok && result.success) { location.reload();return; }
      showError(result.error || 'Não foi possível salvar as informações.');
    } catch (_) {
      showError('Não foi possível confirmar a operação. Atualize a página para conferir as informações antes de repetir.');
    } finally { saving = false;submit.disabled = false;form.removeAttribute('aria-busy'); }
  });
})();
