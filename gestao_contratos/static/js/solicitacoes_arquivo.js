document.addEventListener('change', function (event) {
    if (event.target.matches('input[name="arquivar"]')) {
        const button = event.target.form.querySelector('[data-cancelar-label]');
        if (button) button.textContent = event.target.checked ? 'Cancelar e arquivar' : 'Cancelar';
    }
});
