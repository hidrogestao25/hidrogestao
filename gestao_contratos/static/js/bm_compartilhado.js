document.addEventListener('submit', async event => {
  const form = event.target;
  if (!form.matches('form[data-bm-shared-decision]')) return;
  event.preventDefault();
  if (form.dataset.submitting === 'true') return;
  const action = event.submitter?.value;
  const message = form.querySelector('[data-bm-decision-message]');
  if (action === 'reprovar' && !form.elements.justificativa.value.trim()) {
    message.textContent = 'Informe a justificativa da reprovação.';
    form.elements.justificativa.focus();
    return;
  }
  const data = new FormData(form);
  data.set('acao', action);
  form.dataset.submitting = 'true';
  form.querySelectorAll('button').forEach(button => { button.disabled = true; });
  try {
    const response = await fetch(form.action, {method: 'POST', body: data, credentials: 'same-origin'});
    const result = await response.json();
    if (!response.ok || !result.success) {
      message.textContent = result.error || 'Não foi possível registrar a decisão. Atualize a página e confira a situação.';
      return;
    }
    window.location.reload();
  } catch (_) {
    message.textContent = 'Não foi possível confirmar a decisão. Atualize a página antes de tentar novamente.';
  } finally {
    form.dataset.submitting = 'false';
    form.querySelectorAll('button').forEach(button => { button.disabled = false; });
  }
});
