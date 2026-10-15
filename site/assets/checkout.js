/* Real submission; preserve the V10.6 confirmation layout and admin. */
(() => {
  const button = document.getElementById('validateBtn');
  const success = document.getElementById('success');
  const originalLabel = button.textContent;
  const error = document.createElement('p');
  error.setAttribute('role', 'alert');
  error.style.color = '#a32626';
  error.hidden = true;
  button.insertAdjacentElement('afterend', error);
  const clearCart = () => {
    ['emPoissonnerieOrder', 'emPoissonnerieCustomer', 'emPoissonnerieCheckout', 'emPoissonnerieSubmission'].forEach(key => localStorage.removeItem(key));
  };
  const fingerprint = JSON.stringify({order, customer});
  let requestState;
  try { requestState = JSON.parse(localStorage.getItem('emPoissonnerieSubmission') || 'null'); } catch (_) {}
  if (!requestState || requestState.fingerprint !== fingerprint) {
    requestState = {fingerprint, requestId: crypto.randomUUID()};
    localStorage.setItem('emPoissonnerieSubmission', JSON.stringify(requestState));
  }
  const showSuccess = id => {
    success.querySelector('span').textContent = 'Votre commande a bien été transmise à EM Poissonnerie. Référence : ' + id + '.';
    success.classList.add('show');
    button.disabled = true;
    button.textContent = 'Commande validée ✓';
    button.style.opacity = '.72';
    try { clearCart(); } catch (_) {}
  };
  // Reloading the receipt must never create a second order.
  if (!localStorage.getItem('emPoissonnerieOrder')) {
    let receipt;
    try { receipt = JSON.parse(localStorage.getItem('emPoissonnerieFinalOrder') || 'null'); } catch (_) {}
    if (receipt && receipt.order_id) {
      showSuccess(receipt.order_id);
      return;
    }
  };
  if (requestState.orderId) showSuccess(requestState.orderId);
  button.onclick = async () => {
    if (button.disabled) return;
    button.disabled = true;
    button.textContent = 'Enregistrement en cours…';
    error.hidden = true;
    try {
      const response = await fetch('/api/orders', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Idempotency-Key': requestState.requestId},
        body: JSON.stringify({order, customer, confirmedAt: new Date().toISOString()}),
        signal: AbortSignal.timeout(25000)
      });
      const result = await response.json();
      if (!response.ok || !result.ok || !result.order_id) {
        throw new Error(result.message || 'La commande n’a pas pu être enregistrée. Réessayez.');
      }
      requestState.orderId = result.order_id;
      // The server is the source of truth; a local quota error must not hide success.
      try {
        localStorage.setItem('emPoissonnerieSubmission', JSON.stringify(requestState));
        localStorage.setItem('emPoissonnerieFinalOrder', JSON.stringify({order, customer, order_id:result.order_id, confirmedAt:new Date().toISOString()}));
      } catch (_) {}
      showSuccess(result.order_id);
    } catch (exception) {
      error.textContent = exception.name === 'TimeoutError' || exception.name === 'TypeError'
        ? 'La réponse du serveur n’a pas été reçue. Réessayez : votre commande ne sera pas enregistrée deux fois.'
        : exception.message;
      error.hidden = false;
      button.disabled = false;
      button.textContent = originalLabel;
    }
  };
})();
