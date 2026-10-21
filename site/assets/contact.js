(() => {
  const form = document.getElementById('emContactForm');
  if (!form) return;
  const button = document.getElementById('emContactSubmit');
  const status = document.getElementById('emContactStatus');
  let pending = null;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (button.disabled || !form.reportValidity()) return;
    const fields = Object.fromEntries(new FormData(form));
    const fingerprint = JSON.stringify(fields);
    if (!pending || pending.fingerprint !== fingerprint) pending = {fingerprint, id: crypto.randomUUID()};
    button.disabled = true;
    button.textContent = 'Envoi en cours…';
    status.hidden = true;
    form.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch('/api/contact', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': pending.id},
        body: JSON.stringify(fields), signal: AbortSignal.timeout(25000)
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.message || 'Le message n’a pas pu être envoyé. Réessayez dans un instant.');
      status.textContent = 'Merci ! Votre message a bien été envoyé à EM Poissonnerie. Nous vous répondrons dès que possible.';
      status.dataset.error = 'false';
      form.reset();
      pending = null;
    } catch (error) {
      status.dataset.error = 'true';
      status.textContent = error.name === 'TimeoutError' || error.name === 'TypeError'
        ? 'La confirmation du serveur n’a pas été reçue. Vos champs sont conservés : réessayez, votre message ne sera pas envoyé deux fois.'
        : error.message;
    } finally {
      button.disabled = false;
      button.textContent = 'Envoyer le message';
      form.removeAttribute('aria-busy');
      status.hidden = false;
      status.focus();
    }
  });
})();
