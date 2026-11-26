/* Promotion orders use order wording without changing the shared cart or Admin IDs. */
(() => {
  'use strict';
  const initialize = () => {
    let order;
    try {
      order = JSON.parse(localStorage.getItem('emPoissonnerieOrder') || 'null') || JSON.parse(localStorage.getItem('emPoissonnerieFinalOrder') || 'null')?.order;
    } catch (_) { return; }
    const items = order?.items || [];
    if (!items.length || !items.every(item => item.promoId || item.promotion === true)) return;
    const main = document.querySelector('main');
    if (!main) return;
    const replacements = [
      [/Votre plateau/g, 'Votre commande'],
      [/Votre Plateau/g, 'Votre commande'],
      [/Total du plateau/g, 'Total de la commande'],
      [/Modifier mon plateau/g, 'Modifier ma commande'],
      [/contenu du plateau/g, 'contenu de la commande'],
      [/votre plateau/g, 'votre commande'],
      [/Retournez au plateau/g, 'Retournez aux promotions'],
      [/plateau pour un anniversaire/g, 'précision sur les produits commandés']
    ];
    function apply() {
      const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        if (node.parentElement.closest('script,style,textarea,input,.detail,.order-items,.pickup-card,.pickup-summary,.success,[contenteditable="true"]')) continue;
        let text = node.nodeValue;
        for (const [pattern, value] of replacements) text = text.replace(pattern, value);
        if (text !== node.nodeValue) node.nodeValue = text;
      }
      for (const id of ['sumGuests','guests','average']) {
        const element = document.getElementById(id);
        const row = element?.closest('.summary-meta,.sumrow');
        if (row) { row.hidden = true; row.style.display = 'none'; }
      }
      const average = main.querySelector('.avg-box');
      if (average) { average.hidden = true; average.style.display = 'none'; }
      for (const id of ['sumItems','articleCount']) {
        const count = document.getElementById(id);
        if (count && count.textContent !== String(items.length)) count.textContent = String(items.length);
      }
      const comment = document.getElementById('comment');
      if (comment?.tagName === 'TEXTAREA') comment.placeholder = 'Demande particulière ou précision sur votre commande…';
    }
    apply();
    if (document.getElementById('customerForm')) {
      const back = document.getElementById('backBtn');
      if (back) back.onclick = () => { location.href = 'index.html#promo'; };
    }
    // Shared Admin text can be reapplied after images hydrate or edits are restored.
    new MutationObserver(apply).observe(main, {subtree:true, childList:true, characterData:true});
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize);
  else initialize();
})();
