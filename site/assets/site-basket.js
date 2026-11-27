(()=>{
'use strict';
const key='emPoissonnerieOrder';
const builder=()=>window.emCartBuilder;
const money=v=>Number(v||0).toLocaleString('fr-FR',{style:'currency',currency:'EUR'});
const read=()=>{try{return JSON.parse(localStorage.getItem(key)||'null')||{items:[],specialRequests:[],total:0};}catch{return {items:[],specialRequests:[],total:0};}};
const css=document.createElement('style');css.textContent=`
.em-site-basket-host{position:relative;display:flex;align-items:center;justify-content:center;gap:12px;padding:12px;min-width:0}
.em-site-basket-host>.contact,.em-site-basket-host>.header-contact{padding:0!important;min-width:0!important;width:auto!important}
header .header-inner.em-basket-layout{grid-template-columns:170px minmax(0,1fr) auto!important}
#emSiteBasketToggle{border:1px solid #d0dde3;background:#f4f8fa;color:#173b50;border-radius:9px;padding:10px 12px;display:flex;gap:8px;align-items:center;white-space:nowrap;cursor:pointer;font:600 13px Arial,sans-serif}
#emSiteBasketToggle span{font:600 13px Arial,sans-serif}#emSiteBasketToggle b{font:700 11px Arial,sans-serif;color:white;background:#183c50;border-radius:20px;min-width:19px;padding:4px;text-align:center}
#emSiteBasket{position:fixed;right:16px;top:80px;width:min(385px,calc(100vw - 28px));z-index:10001;border:1px solid #d6e0e5;border-radius:14px;background:#fff;color:#183748;box-shadow:0 12px 40px #102f422e;overflow:hidden;font:14px Arial,sans-serif;text-align:left}
#emSiteBasket[hidden],#emSiteBasketFloat[hidden]{display:none!important}
#emSiteBasket *{box-sizing:border-box;font-family:Arial,sans-serif;font-weight:400}
#emSiteBasket .eb-head{display:flex;align-items:center;justify-content:space-between;padding:18px 20px;background:#eef4f7;border-bottom:1px solid #dde7eb}
#emSiteBasket .eb-title{font-size:21px;font-weight:700;color:#183748}
#emSiteBasket button{cursor:pointer;border:0;background:transparent;color:inherit;font:600 13px Arial,sans-serif}
#emSiteBasket .eb-close{font-size:24px;padding:0 4px;line-height:1}
#emSiteBasket .eb-lines{max-height:38vh;overflow:auto;padding:0 20px}
#emSiteBasket .eb-row{display:flex;align-items:center;gap:12px;padding:14px 0;border-bottom:1px solid #e6edf0}
#emSiteBasket .eb-name{font-weight:600;line-height:1.35;overflow-wrap:anywhere}
#emSiteBasket .eb-meta{font-size:12px;color:#577080;margin-top:5px}
#emSiteBasket .eb-price{font-weight:700;white-space:nowrap;margin-left:auto}
#emSiteBasket .eb-remove{color:#607987;padding:6px;font-size:19px}
#emSiteBasket .eb-empty{text-align:center;padding:30px 8px;color:#526b79;line-height:1.6}
#emSiteBasket .eb-foot{padding:16px 20px 20px;background:#f8fafb}
#emSiteBasket .eb-total{display:flex;justify-content:space-between;font-size:16px;font-weight:700;margin-bottom:14px}
#emSiteBasket .eb-total b{font-weight:700}
#emSiteBasket .eb-next{display:block;width:100%;background:#173b50;color:white;border-radius:8px;padding:14px 8px;font-size:14px}
#emSiteBasket .eb-next:disabled{opacity:.45;cursor:default}
#emSiteBasket .eb-links{display:flex;justify-content:center;gap:14px;margin-top:12px;flex-wrap:wrap}
#emSiteBasket .eb-links button{color:#305d73;text-decoration:underline;text-underline-offset:3px;font-size:12px}
#emSiteBasketFloat{position:fixed;top:14px;right:16px;z-index:10000;display:flex;gap:7px;align-items:center;background:#173b50;color:white;border:1px solid #52788b;border-radius:10px;padding:11px 15px;box-shadow:0 5px 20px #173b5030;cursor:pointer;font:600 13px Arial,sans-serif}
#emSiteBasketFloat b{background:#fff;color:#173b50;padding:3px 6px;border-radius:20px;font:700 11px Arial,sans-serif}
@media(max-width:980px){header .header-inner.em-basket-layout{grid-template-columns:125px minmax(0,1fr) auto!important}.em-site-basket-host>.contact,.em-site-basket-host>.header-contact{display:none!important}}
@media(max-width:650px){header .header-inner.em-basket-layout{display:block!important;position:relative}.em-site-basket-host{position:absolute;right:10px;top:10px;padding:0;z-index:3}#emSiteBasketToggle{padding:8px}#emSiteBasketToggle span{display:none}#emSiteBasket{right:12px;width:calc(100vw - 24px)}}
#emSiteBasket .eb-composition{margin:8px 0 0;font-size:12px;color:#577080;line-height:1.55}
#emSiteBasket .eb-composition summary{cursor:pointer;color:#305d73;text-decoration:underline}
#emSiteBasket .eb-composition ul{padding-left:17px;margin:6px 0}
#emBasketToast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:10002;background:#173b50;color:white;padding:13px 20px;border-radius:10px;box-shadow:0 4px 20px #0003;font:600 14px Arial,sans-serif;text-align:center;max-width:90vw;pointer-events:none}
#emBasketToast[hidden]{display:none}
.promo-buy.em-added{background:#23734c!important;color:white!important}
`;document.head.append(css);
const svg='<svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M2 3h3l3 13h11l3-9H6"/><circle cx="9" cy="21" r="1"/><circle cx="19" cy="21" r="1"/></svg>';
const host=document.createElement('div');host.className='em-site-basket-host';
const header=document.querySelector('header .header-inner');if(!header)return;
const contact=header.querySelector('.contact,.header-contact');if(contact){contact.before(host);host.append(contact);}else header.append(host);
header.classList.add('em-basket-layout');
const toggle=document.createElement('button');toggle.type='button';toggle.id='emSiteBasketToggle';toggle.setAttribute('aria-label','Mon panier');toggle.setAttribute('aria-expanded','false');toggle.innerHTML=svg+'<span>Mon panier</span><b>0</b>';host.append(toggle);
const floating=document.createElement('button');floating.type='button';floating.id='emSiteBasketFloat';floating.hidden=true;floating.setAttribute('aria-label','Mon panier');floating.innerHTML=svg+' Mon panier <b>0</b>';document.body.append(floating);
const panel=document.createElement('div');panel.id='emSiteBasket';panel.hidden=true;panel.setAttribute('role','region');panel.setAttribute('aria-label','Mon panier');
panel.innerHTML='<div class="eb-head"><div class="eb-title">Mon panier</div><button type="button" class="eb-close" aria-label="Fermer">×</button></div><div class="eb-lines" aria-live="polite"></div><div class="eb-foot"><div class="eb-total"><span>Total</span><b>0,00 €</b></div><button type="button" class="eb-next">Continuer ma commande →</button><div class="eb-links"><button type="button" data-module="plateaux">Composer un plateau</button><button type="button" data-module="promo">Voir les promotions</button></div></div>';document.body.append(panel);
const lines=panel.querySelector('.eb-lines'),next=panel.querySelector('.eb-next');
function remove(item){
 if(item.plateau){
   const o=read(), parts=[...(o.items||[]).filter(x=>!x.promoId),...(o.specialRequests||[]).map(name=>({name,special:true}))];
   if(builder()){parts.forEach(x=>builder().remove(x));return;}
   o.items=(o.items||[]).filter(x=>x.promoId);o.specialRequests=[];o.plateauTotal=0;o.average=0;o.giftUnlocked=false;o.guests=1;o.total=o.items.reduce((n,x)=>n+Number(x.lineTotal||0),0);
   localStorage.setItem(key,JSON.stringify(o));
   if(location.pathname.includes('/commandes/'))location.href='/commandes/index.html';else refresh();return;
 }
 if(builder()){builder().remove(item);return;}
 const o=read();if(item.special)o.specialRequests=(o.specialRequests||[]).filter(s=>s!==item.name);else o.items=(o.items||[]).filter(x=>item.promoId?x.promoId!==item.promoId:x.promoId||x.name!==item.name);
 const plate=(o.items||[]).filter(x=>!x.promoId);o.plateauTotal=plate.reduce((n,x)=>n+Number(x.lineTotal||0),0);o.total=(o.items||[]).reduce((n,x)=>n+Number(x.lineTotal||0),0);o.average=o.plateauTotal/Math.max(1,o.guests||1);o.giftUnlocked=o.plateauTotal>=80;
 localStorage.setItem(key,JSON.stringify(o));
 if(location.pathname.includes('/commandes/'))location.href='/commandes/index.html';else refresh();
}
const toast=document.createElement('div');toast.id='emBasketToast';toast.hidden=true;toast.setAttribute('role','status');document.body.append(toast);
let toastTimer, previousPromos=new Map((read().items||[]).filter(x=>x.promoId).map(x=>[x.promoId,Number(x.quantity)]));
const buttonTimers=new WeakMap();
function refresh(){
 const o=read(),plate=(o.items||[]).filter(x=>!x.promoId),special=o.specialRequests||[],promos=(o.items||[]).filter(x=>x.promoId);
 const items=[...(plate.length||special.length?[{name:'Plateau de fruits de mer',plateau:true,lineTotal:plate.reduce((n,x)=>n+Number(x.lineTotal||0),0)}]:[]),...promos];
 if(builder())for(const p of promos){if(Number(p.quantity)>(previousPromos.get(p.promoId)||0)){
   toast.textContent='✓ '+p.name+' ajouté au panier';toast.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{toast.hidden=true;},2500);
   const btn=[...document.querySelectorAll('[data-promo-id]')].find(el=>el.dataset.promoId===String(p.promoId))?.querySelector('.promo-buy');
   if(btn){clearTimeout(buttonTimers.get(btn));btn.textContent='✓ Ajouté au panier';btn.classList.add('em-added');buttonTimers.set(btn,setTimeout(()=>{btn.textContent='Ajouter au panier';btn.classList.remove('em-added');},1800));}
 }}
 previousPromos=new Map(promos.map(x=>[x.promoId,Number(x.quantity)]));
 const expanded=!!lines.querySelector('details[open]');
 toggle.querySelector('b').textContent=items.length;floating.querySelector('b').textContent=items.length;lines.replaceChildren();
 if(!items.length){const empty=document.createElement('div');empty.className='eb-empty';empty.textContent='Votre panier est vide. Découvrez nos plateaux et promotions.';lines.append(empty);}
 for(const x of items){
 const row=document.createElement('div');row.className='eb-row';const info=document.createElement('div');info.style.minWidth='0';
 const name=document.createElement('div');name.className='eb-name';name.textContent=x.name;
 const meta=document.createElement('div');meta.className='eb-meta';meta.textContent=x.plateau?((o.guests||1)+' personne(s) · Plateau personnalisé'):('Promotion · '+x.quantity+' × '+x.unit);info.append(name,meta);
 if(x.plateau){const details=document.createElement('details');details.className='eb-composition';details.open=expanded;const summary=document.createElement('summary');summary.textContent='Voir la composition';const ul=document.createElement('ul');
 for(const p of plate){const li=document.createElement('li');li.textContent=p.name+' · '+p.quantity+' × '+p.unit;ul.append(li);}
 for(const p of special){const li=document.createElement('li');li.textContent=p+' · Sur demande';ul.append(li);}
 if(o.giftUnlocked){const li=document.createElement('li');li.textContent='Bouteille offerte';ul.append(li);}
 details.append(summary,ul);info.append(details);}
 const price=document.createElement('div');price.className='eb-price';price.textContent=money(x.lineTotal);const del=document.createElement('button');del.type='button';del.className='eb-remove';del.setAttribute('aria-label','Retirer '+x.name);del.textContent='×';del.onclick=()=>remove(x);row.append(info,price,del);lines.append(row);}
 panel.querySelector('.eb-total b').textContent=money(o.total);next.disabled=!items.length;
}
function position(){const rect=toggle.getBoundingClientRect();const visible=rect.bottom>0&&rect.top<innerHeight;floating.hidden=visible;const anchor=visible?toggle:floating;const r=anchor.getBoundingClientRect();panel.style.top=Math.max(8,Math.min(r.bottom+10,innerHeight-100))+'px';panel.style.right=Math.max(12,innerWidth-r.right)+'px';}
function open(value){panel.hidden=!value;toggle.setAttribute('aria-expanded',String(value));floating.setAttribute('aria-expanded',String(value));if(value){refresh();position();}}
toggle.onclick=()=>open(panel.hidden);floating.onclick=()=>open(panel.hidden);panel.querySelector('.eb-close').onclick=()=>open(false);
panel.querySelectorAll('[data-module]').forEach(b=>b.onclick=()=>{open(false);if(builder())builder().module(b.dataset.module);else location.href='/commandes/index.html#'+b.dataset.module;});
next.onclick=()=>{if(builder())builder().proceed();else if(location.pathname.endsWith('/confirmation.html'))open(false);else location.href='/commandes/informations.html';};
document.addEventListener('keydown',e=>{if(e.key==='Escape')open(false);});document.addEventListener('click',e=>{if(!panel.contains(e.target)&&!toggle.contains(e.target)&&!floating.contains(e.target))open(false);});
window.addEventListener('scroll',position,{passive:true});window.addEventListener('resize',position);window.addEventListener('storage',refresh);window.addEventListener('pageshow',refresh);window.addEventListener('em-cart-change',refresh);
window.emSiteBasket={open,notify(){refresh();}};refresh();position();
})();