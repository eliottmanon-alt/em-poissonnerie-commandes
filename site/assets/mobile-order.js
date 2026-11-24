/* Enhance the existing controls; keep one cart and one checkout path. */
(() => {
  'use strict';
  document.addEventListener('DOMContentLoaded', () => {
    const cart = document.querySelector('.cart');
    const panel = document.getElementById('plateaux');
    if (!cart || !panel) return;
    const mobile = matchMedia('(max-width:650px)');
    const cards = [...document.querySelectorAll('.product-card[data-index]')];
    const special = [...document.querySelectorAll('.special-product')];
    cards.forEach((card, index) => {
      const name = card.querySelector('h3').textContent.trim();
      const input = card.querySelector('.qty input');
      input.setAttribute('aria-label', 'Quantité : ' + name);
      input.setAttribute('inputmode', 'numeric');
      card.querySelector('.minus').setAttribute('aria-label', 'Retirer : ' + name);
      card.querySelector('.plus').setAttribute('aria-label', 'Ajouter : ' + name);
      const price = document.createElement('span');
      price.className = 'em-mobile-price';
      price.textContent = card.querySelector('.price-chip').textContent.trim().replace(/\s+/g, ' ');
      card.querySelector('.title-wrap h3').after(price);
      const tags = [...card.querySelectorAll('.tag')];
      if (tags.length) {
        const details = document.createElement('button');
        details.className = 'em-mobile-details';
        details.type = 'button';
        details.textContent = 'Détails';
        details.setAttribute('aria-label', 'Détails : ' + name);
        details.setAttribute('aria-expanded', 'false');
        tags.forEach((tag, i) => { tag.id = 'em-product-detail-' + index + '-' + i; });
        details.setAttribute('aria-controls', tags.map(tag => tag.id).join(' '));
        details.onclick = () => {
          const expanded = card.classList.toggle('em-details-open');
          details.setAttribute('aria-expanded', String(expanded));
          details.textContent = expanded ? 'Masquer les détails' : 'Détails';
        };
        price.after(details);
      }
    });
    const bar = document.createElement('div');
    bar.className = 'em-mobile-cartbar';
    bar.setAttribute('aria-label', 'Votre plateau');
    bar.innerHTML = '<div role="status" aria-live="polite" aria-atomic="true"><small id="emMobileCount">Votre plateau est vide</small><strong id="emMobileTotal">0,00 €</strong></div><button type="button" aria-haspopup="dialog" aria-expanded="false">Voir mon plateau</button>';
    const shade = document.createElement('div');
    shade.className = 'em-cart-shade';
    const close = document.createElement('button');
    close.className = 'em-cart-close';
    close.type = 'button';
    close.setAttribute('aria-label', 'Fermer le récapitulatif');
    close.textContent = '×';
    cart.prepend(close);
    const heading = cart.querySelector('h3');
    heading.id = 'emCartTitle';
    document.body.append(shade, bar);
    const trigger = bar.querySelector('button');
    const total = bar.querySelector('#emMobileTotal');
    const count = bar.querySelector('#emMobileCount');
    let returnFocus = null;
    let inerted = [];
    const setText = (node, value) => { if (node.textContent !== value) node.textContent = value; };
    function closeCart(restoreFocus = true) {
      document.body.classList.remove('em-cart-open');
      cart.removeAttribute('role');
      cart.removeAttribute('aria-modal');
      cart.removeAttribute('aria-labelledby');
      trigger.setAttribute('aria-expanded', 'false');
      inerted.forEach(node => { node.inert = false; });
      inerted = [];
      if (restoreFocus && returnFocus && mobile.matches) returnFocus.focus({preventScroll:true});
    }
    function openCart() {
      if (!mobile.matches || !panel.classList.contains('active')) return;
      returnFocus = document.activeElement;
      document.body.classList.add('em-cart-open');
      cart.setAttribute('role', 'dialog');
      cart.setAttribute('aria-modal', 'true');
      cart.setAttribute('aria-labelledby', heading.id);
      trigger.setAttribute('aria-expanded', 'true');
      // Isolate the existing cart without copying or rebuilding its controls.
      for (let node = cart; node && node !== document.body; node = node.parentElement) {
        [...node.parentElement.children].forEach(sibling => {
          if (sibling !== node && sibling !== shade && !sibling.inert && !['SCRIPT','STYLE','LINK'].includes(sibling.tagName)) {
            sibling.inert = true;
            inerted.push(sibling);
          }
        });
      }
      cart.scrollTop = 0;
      close.focus({preventScroll:true});
    }
    trigger.onclick = openCart;
    close.onclick = () => closeCart();
    shade.onclick = () => closeCart();
    document.addEventListener('keydown', event => {
      if (!document.body.classList.contains('em-cart-open')) return;
      if (event.key === 'Escape') { event.preventDefault(); closeCart(); }
      if (event.key !== 'Tab') return;
      const focusable = [...cart.querySelectorAll('button,a[href],input,[tabindex="0"]')].filter(el => !el.disabled && el.getClientRects().length);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    function sync() {
      const active = panel.classList.contains('active');
      bar.hidden = !active;
      if (!active || !mobile.matches) closeCart(false);
      const quantity = document.getElementById('itemCount').textContent;
      const requests = special.filter(card => card.querySelector('.ask-btn.added')).length;
      let label = Number(quantity) ? quantity + (Number(quantity) === 1 ? ' portion / article' : ' portions / articles') : 'Votre plateau est vide';
      if (requests) label = (Number(quantity) ? label + ' · ' : '') + requests + (requests === 1 ? ' pièce sur demande' : ' pièces sur demande');
      setText(count, label);
      setText(total, document.getElementById('grandTotal').textContent);
      cards.forEach(card => card.classList.toggle('em-selected', Number(card.querySelector('input').value) > 0));
    }
    new MutationObserver(sync).observe(cart, {subtree:true,childList:true,characterData:true});
    new MutationObserver(sync).observe(panel, {attributes:true,attributeFilter:['class']});
    document.querySelectorAll('.ask-btn').forEach(button => button.addEventListener('click', sync));
    mobile.addEventListener('change', sync);
    sync();
    document.body.classList.add('em-mobile-ready');
  });
})();
