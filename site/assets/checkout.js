/* Server-confirmed order submission, with optional hosted card deposit. */
(() => {
  'use strict';
  const stylesheet = document.createElement('link');
  stylesheet.rel = 'stylesheet';
  stylesheet.href = '/assets/deposit.css?v=20261124';
  document.head.append(stylesheet);
  const initializeCheckout = () => {
  const button = document.getElementById('validateBtn');
  const success = document.getElementById('success');
  const originalLabel = button.textContent;
  const moneyCents = cents => (cents / 100).toLocaleString('fr-FR', {style:'currency',currency:'EUR'});
  const error = document.createElement('p');
  error.setAttribute('role', 'alert');
  error.style.color = '#a32626';
  error.hidden = true;
  button.after(error);
  const info = document.createElement('div');
  info.className = 'em-deposit-info';
  info.hidden = true;
  info.innerHTML = '<h2>Votre réservation, en toute simplicité</h2><p>L’acompte de 20 % confirme votre réservation et nous permet d’anticiper les achats de produits frais et la préparation de votre plateau.</p><dl><div><dt>Acompte de 20 % à payer maintenant</dt><dd id="emDepositAmount"></dd></div><div><dt>Solde à régler au retrait</dt><dd id="emBalanceAmount"></dd></div></dl><p>Le solde sera à régler au retrait, par carte bancaire ou en espèces.</p><p class="em-deposit-security"><b>Paiement sécurisé par Stripe.</b> Vous serez redirigé vers la page de paiement Stripe. Vos coordonnées de carte bancaire ne transitent pas par notre site et n’y sont pas enregistrées.</p><p class="em-deposit-special" hidden>Les pièces sur demande, dont le prix reste à confirmer, ne sont pas incluses dans le calcul de l’acompte.</p><p class="em-deposit-email" hidden>Une adresse e-mail est nécessaire pour recevoir la confirmation après paiement. Revenez à vos informations pour la renseigner.</p>';
  button.closest('.final-actions').before(info);
  const notice = document.querySelector('.notice');
  if (notice) notice.textContent = 'Votre commande sera confirmée après validation par le serveur. Conservez votre référence de commande.';
  const clearCart = () => {
    ['emPoissonnerieOrder','emPoissonnerieCustomer','emPoissonnerieCheckout','emPoissonnerieSubmission'].forEach(key => localStorage.removeItem(key));
  };
  const fingerprint = JSON.stringify({order,customer});
  let requestState;
  try { requestState = JSON.parse(localStorage.getItem('emPoissonnerieSubmission') || 'null'); } catch (_) {}
  if (!requestState || requestState.fingerprint !== fingerprint) {
    requestState = {fingerprint,requestId:crypto.randomUUID()};
    try { localStorage.setItem('emPoissonnerieSubmission',JSON.stringify(requestState)); } catch (_) {}
  }
  const showError = message => { error.textContent = message; error.hidden = false; };
  const showSuccess = (id, payment, isTest = false) => {
    success.querySelector('strong').textContent = payment ? 'Acompte payé — commande confirmée' : 'Commande enregistrée ✓';
    success.querySelector('span').textContent = 'Votre commande a bien été transmise à EM Poissonnerie. Référence : ' + id + '.' + (payment ? ' Acompte payé : ' + moneyCents(payment.deposit_paid_cents) + '. Solde au retrait : ' + moneyCents(payment.balance_due_cents) + ', par carte bancaire ou en espèces. La confirmation par e-mail est envoyée après validation du paiement.' : '');
    if (isTest) {
      success.querySelector('strong').textContent = 'Commande TEST enregistrée — NE PAS PRÉPARER';
      success.querySelector('span').textContent = 'Aucun paiement effectué. E-mails de test demandés et commande disponible pour la synchronisation du logiciel. Référence : ' + id + '.';
    }
    if (notice) notice.textContent = isTest ? 'Commande de test, sans acompte ni solde à encaisser.' : 'Votre commande est confirmée. Conservez votre référence.';
    success.classList.add('show');
    button.disabled = true;
    button.textContent = payment ? 'Acompte payé ✓' : 'Commande validée ✓';
    if (isTest) button.textContent = 'Commande TEST enregistrée ✓';
    button.style.opacity = '.72';
    try {
      localStorage.setItem('emPoissonnerieFinalOrder',JSON.stringify({order,customer,order_id:id,payment,is_test:isTest,confirmedAt:new Date().toISOString()}));
      clearCart();
    } catch (_) {}
    if (payment) {
      const pendingSession = new URLSearchParams(location.search).get('session_id');
      // Preserve the opaque receipt URL for safe reloads; never clear on cancel/failure.
      if (!pendingSession) history.replaceState(null,'',location.pathname);
    }
  };
  const params = new URLSearchParams(location.search);
  async function checkPayment(sessionId) {
    button.disabled = true;
    button.textContent = 'Vérification du paiement…';
    if (notice) notice.textContent = 'Nous attendons la confirmation sécurisée du paiement. Ne payez pas une seconde fois.';
    for (let attempt = 0; attempt < 10; attempt++) {
      try {
        const response = await fetch('/api/payments/status?session_id=' + encodeURIComponent(sessionId), {cache:'no-store',signal:AbortSignal.timeout(15000)});
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error('Le statut du paiement n’est pas encore accessible.');
        if (result.paid && result.order_id) { showSuccess(result.order_id,result); return; }
      } catch (_) { /* A transient failure must not offer a second charge. */ }
      await new Promise(resolve => setTimeout(resolve,2000));
    }
    button.textContent = 'Revérifier le paiement';
    button.disabled = false;
    button.onclick = () => checkPayment(sessionId);
    showError('La confirmation du paiement est encore en cours. Votre panier est conservé. Cliquez sur « Revérifier le paiement » ; ne payez pas une seconde fois.');
  }
  if (params.get('session_id')) { checkPayment(params.get('session_id')); return; }
  let receipt;
  try { receipt = JSON.parse(localStorage.getItem('emPoissonnerieFinalOrder') || 'null'); } catch (_) {}
  if (!localStorage.getItem('emPoissonnerieOrder') && receipt?.order_id) { showSuccess(receipt.order_id,receipt.payment,receipt.is_test); return; }
  if (requestState.orderId) { showSuccess(requestState.orderId); return; }
  let config;
  let testOrder = false;
  let testCsrf = '';
  const testIdentity = String(customer.lastName || '').trim().toUpperCase() === 'TEST' && String(customer.email || '').trim().toLowerCase() === 'eliott.manon@empoissonnerie.com';
  button.disabled = true;
  button.textContent = 'Chargement…';
  async function initialize() {
    try {
      const response = await fetch('/api/payments/config',{cache:'no-store',signal:AbortSignal.timeout(15000)});
      config = await response.json();
      if (!response.ok || !config.ok) throw new Error();
      if (testIdentity) {
        const authResponse = await fetch('/api/admin/session', {cache:'no-store', signal:AbortSignal.timeout(15000)});
        const auth = await authResponse.json();
        if (!authResponse.ok || !auth.authenticated || !auth.csrf) {
          button.textContent = 'Connexion Admin requise pour le test';
          showError('Pour une commande TEST sans paiement, connectez-vous à ADMIN puis rechargez cette page.');
          return;
        }
        testOrder = true;
        testCsrf = auth.csrf;
        info.hidden = false;
        info.textContent = 'MODE TEST — NE PAS PRÉPARER. Aucun débit Stripe. La commande sera marquée TEST dans les e-mails et lors de la synchronisation du logiciel.';
        button.textContent = 'Envoyer la commande TEST sans paiement';
        if (notice) notice.textContent = 'Réservé à votre session Admin et à votre adresse professionnelle.';
        button.disabled = false;
        return;
      }
      if (config.enabled) {
        info.hidden = false;
        const total = Math.round(Number(order.total || 0) * 100);
        const deposit = Math.round(total * .2);
        document.getElementById('emDepositAmount').textContent = moneyCents(deposit);
        document.getElementById('emBalanceAmount').textContent = moneyCents(total - deposit);
        info.querySelector('.em-deposit-special').hidden = !(order.specialRequests || []).length;
        info.querySelector('.em-deposit-email').hidden = !!customer.email;
        button.textContent = 'Payer l’acompte de ' + moneyCents(deposit);
        if (notice) notice.textContent = 'Votre commande est validée après paiement de l’acompte. Une confirmation vous sera envoyée par e-mail.';
        if (config.mode === 'test') {
          const test = document.createElement('p');
          test.className = 'em-deposit-test';
          test.textContent = 'Mode test : aucun paiement réel n’est effectué.';
          info.append(test);
        }
        if (!config.ready || !customer.email || deposit < 50) {
          showError(!config.ready ? 'Le paiement en ligne n’est pas encore disponible.' : !customer.email ? 'Renseignez votre e-mail dans vos informations avant de payer.' : 'Le montant de l’acompte doit être au moins de 0,50 €.');
          return;
        }
      } else button.textContent = originalLabel;
      if (params.has('payment_cancelled')) showError('Paiement interrompu : votre commande n’est pas encore validée. Votre panier est conservé.');
      button.disabled = false;
    } catch (_) {
      showError('Le service de commande est temporairement indisponible. Rechargez la page pour réessayer ; votre panier est conservé.');
      button.textContent = 'Service temporairement indisponible';
    }
  }
  button.onclick = async () => {
    if (button.disabled || !config) return;
    button.disabled = true;
    const label = button.textContent;
    button.textContent = testOrder ? 'Enregistrement de la commande TEST…' : config.enabled ? 'Ouverture du paiement sécurisé…' : 'Enregistrement en cours…';
    error.hidden = true;
    try {
      const response = await fetch(testOrder ? '/api/admin/test-order' : config.enabled ? '/api/payments/checkout' : '/api/orders', {
        method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':requestState.requestId,...(testOrder ? {'X-CSRF-Token':testCsrf} : {})},
        body:JSON.stringify({order,customer}),signal:AbortSignal.timeout(25000)
      });
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Le serveur ne peut pas traiter la commande pour le moment. Votre panier est conservé ; réessayez dans un instant.');
      const result = await response.json();
      if (!response.ok || !result.ok) {
        if (result.error === 'payment_expired') {
          requestState.requestId = crypto.randomUUID();
          try { localStorage.setItem('emPoissonnerieSubmission',JSON.stringify(requestState)); } catch (_) {}
        }
        throw new Error(result.message || 'La commande n’a pas pu être validée. Réessayez.');
      }
      if (testOrder) {
        if (!result.is_test || !result.order_id) throw new Error('Confirmation de test manquante.');
        showSuccess(result.order_id, undefined, true);
        return;
      }
      if (config.enabled) {
        if (result.paid && result.session_id) { await checkPayment(result.session_id); return; }
        const target = new URL(result.checkout_url);
        if (target.protocol !== 'https:' || target.hostname !== 'checkout.stripe.com') throw new Error('Adresse de paiement non reconnue.');
        location.assign(target.href);
        return;
      }
      if (!result.order_id) throw new Error('La confirmation de commande est manquante.');
      requestState.orderId = result.order_id;
      showSuccess(result.order_id);
    } catch (exception) {
      showError(exception.name === 'TimeoutError' || exception.name === 'TypeError' ? 'La réponse du serveur n’a pas été reçue. Votre panier est conservé. Réessayez sans créer une nouvelle commande.' : exception.message);
      button.disabled = false;
      button.textContent = label;
    }
  };
  initialize();
  };
  // Let the existing Admin assign its stable identifiers before adding payment copy.
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => queueMicrotask(initializeCheckout));
  else queueMicrotask(initializeCheckout);
})();
