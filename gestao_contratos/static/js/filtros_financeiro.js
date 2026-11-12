/* Atualiza apenas as opções; os resultados seguem o botão Aplicar filtros. */
(() => {
  document.querySelectorAll('form[data-financial-filters-url]').forEach(form => {
    const order = ['lider_contrato', 'fornecedor', 'projeto', 'contrato'];
    const fields = Object.fromEntries(order.map(name => [name, form.elements.namedItem(name)]));
    const status = form.querySelector('[data-financial-filters-status]');
    const submits = form.querySelectorAll('[type="submit"]');
    let controller, sequence = 0;
    order.slice(0, -1).forEach(name => fields[name].addEventListener('change', async () => {
      const version = ++sequence;
      controller?.abort();
      controller = new AbortController();
      const descendants = order.slice(order.indexOf(name) + 1);
      descendants.forEach(child => {
        fields[child].replaceChildren(new Option('---------', ''));
        fields[child].disabled = true;
      });
      status.textContent = 'Atualizando opções…';
      status.className = 'small mt-2 mb-0 text-muted';
      form.setAttribute('aria-busy', 'true');
      submits.forEach(button => button.disabled = true);
      const url = new URL(form.dataset.financialFiltersUrl, location.href);
      if (url.origin !== location.origin) return;
      order.forEach(key => { if (fields[key].value) url.searchParams.set(key, fields[key].value); });
      const selected = Object.fromEntries(order.map(key => [key, fields[key].value]));
      try {
        const response = await fetch(url, {credentials: 'same-origin', signal: controller.signal,
          headers: {'X-Requested-With': 'XMLHttpRequest'}});
        if (!response.ok || response.redirected) throw new Error();
        const data = await response.json();
        if (version !== sequence) return;
        for (const key of order.slice(1)) {
          const options = data.options[key];
          if (!Array.isArray(options)) throw new Error();
          fields[key].replaceChildren(new Option('---------', ''),
            ...options.map(option => new Option(option.label, option.value)));
          fields[key].value = options.some(option => option.value === selected[key]) ? selected[key] : '';
          fields[key].disabled = options.length === 0;
        }
        status.textContent = 'Opções atualizadas. Clique em Aplicar filtros para atualizar o painel.';
      } catch (error) {
        if (error.name === 'AbortError' || version !== sequence) return;
        status.className = 'small mt-2 mb-0 text-danger';
        status.textContent = 'Não foi possível atualizar as opções. Use Aplicar filtros para atualizar pela página.';
      } finally {
        if (version === sequence) {
          form.removeAttribute('aria-busy');
          submits.forEach(button => button.disabled = false);
        }
      }
    }));
  });
})();
