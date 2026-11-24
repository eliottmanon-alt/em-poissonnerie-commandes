(()=>{
'use strict';
let csrf=null, gallery=[];
async function jfetch(url,method='GET',body){
  const r=await fetch(url,{method,cache:'no-store',headers:{'Content-Type':'application/json',...(csrf?{'X-CSRF-Token':csrf}:{})},...(body?{body:JSON.stringify(body)}:{})});
  if(!r.ok) throw new Error('HTTP '+r.status);
  return r.json();
}
function displayURL(url){return /^\/api\/appearance\/media\/[a-f0-9]{64}$/.test(url||'')?url+'/display.webp':url}
function compressImage(file,max=1800,q=.84){
  return new Promise((resolve,reject)=>{
    const im=new Image(),u=URL.createObjectURL(file);
    im.onload=()=>{
      let w=im.naturalWidth,h=im.naturalHeight,s=Math.min(1,max/Math.max(w,h));
      w=Math.max(1,Math.round(w*s));h=Math.max(1,Math.round(h*s));
      const keepAlpha=/image\/png/i.test(file.type),mime=keepAlpha?'image/png':'image/jpeg';
      const c=document.createElement('canvas');c.width=w;c.height=h;
      const ctx=c.getContext('2d',{alpha:keepAlpha});
      if(!keepAlpha){ctx.fillStyle='#fff';ctx.fillRect(0,0,w,h)}
      ctx.drawImage(im,0,0,w,h);
      c.toBlob(b=>{URL.revokeObjectURL(u);b?resolve(b):reject(new Error('compression'))},mime,keepAlpha?undefined:q);
    };
    im.onerror=()=>{URL.revokeObjectURL(u);reject(new Error('image'))};
    im.src=u;
  });
}
function blobDataURL(blob){return new Promise(resolve=>{const fr=new FileReader();fr.onload=()=>resolve(fr.result);fr.readAsDataURL(blob)})}
async function upload(blob){
  const d=await blobDataURL(blob);
  return (await jfetch('/api/admin/media','POST',{data:String(d).split(',')[1]})).url;
}
function renderPublic(){
  const track=document.getElementById('galleryTrack');if(!track)return;
  if(!gallery.length){track.innerHTML='<div class="gallery-empty">Galerie en cours de préparation.</div>';return}
  track.innerHTML='';
  gallery.forEach((g,i)=>{
    const btn=document.createElement('button');btn.className='gallery-item';btn.type='button';btn.setAttribute('aria-label','Agrandir la photo '+(i+1));
    const img=document.createElement('img');img.loading='lazy';img.decoding='async';img.alt='EM Poissonnerie — photo '+(i+1);img.src=displayURL(g.url);
    btn.appendChild(img);
    btn.onclick=()=>{const lb=document.getElementById('galleryLightbox'),li=document.getElementById('galleryLightboxImage');if(lb&&li){li.src=displayURL(g.url);lb.classList.add('open');lb.setAttribute('aria-hidden','false');document.body.style.overflow='hidden'}};
    track.appendChild(btn);
  });
}
function renderAdmin(){
  const box=document.getElementById('emGalleryAdmin');if(!box)return;
  if(!gallery.length){box.innerHTML='<div class="em-admin-help">Aucune photo dans la galerie.</div>';return}
  box.innerHTML=gallery.map((g,i)=>
    '<div class="em-banner-row">'+
    '<button class="em-banner-select" type="button"><span>'+(i+1)+'</span>Photo '+(i+1)+'</button>'+
    '<button type="button" data-ga="up" data-i="'+i+'" '+(i===0?'disabled':'')+'>↑</button>'+
    '<button type="button" data-ga="down" data-i="'+i+'" '+(i===gallery.length-1?'disabled':'')+'>↓</button>'+
    '<button type="button" data-ga="delete" data-i="'+i+'">✕</button></div>'
  ).join('');
}
async function saveGallery(message){
  const doc=await jfetch('/api/appearance');
  const result=await jfetch('/api/admin/gallery','PUT',{revision:doc.revision,gallery});
  gallery=Array.isArray(result.gallery)?result.gallery:gallery;
  const status=document.getElementById('emSaveStatus');if(status)status.textContent=message||'Galerie enregistrée';
  renderAdmin();renderPublic();
}
async function onFiles(e){
  const files=[...(e.target.files||[])];e.target.value='';if(!files.length)return;
  if(gallery.length+files.length>40){alert('40 photos maximum dans la galerie.');return}
  const status=document.getElementById('emSaveStatus');if(status)status.textContent='Ajout des photos…';
  try{
    for(const file of files){
      const blob=await compressImage(file);
      const url=await upload(blob);
      gallery.push({id:'gallery-'+crypto.randomUUID(),url});
    }
    await saveGallery('Photos ajoutées à la galerie');
  }catch(err){console.error(err);if(status)status.textContent='Ajout de la galerie impossible'}
}
async function action(e){
  const b=e.target.closest('[data-ga]');if(!b)return;
  const i=+b.dataset.i,a=b.dataset.ga;
  if(a==='add'){document.getElementById('emGalleryFiles')?.click();return}
  if(!gallery[i])return;
  if(a==='up'&&i>0)[gallery[i-1],gallery[i]]=[gallery[i],gallery[i-1]];
  if(a==='down'&&i<gallery.length-1)[gallery[i+1],gallery[i]]=[gallery[i],gallery[i+1]];
  if(a==='delete'){if(!confirm('Supprimer cette photo de la galerie ?'))return;gallery.splice(i,1)}
  renderAdmin();renderPublic();
  try{await saveGallery(a==='delete'?'Photo supprimée de la galerie':'Ordre de la galerie enregistré')}catch(err){console.error(err)}
}
async function mount(){
  const session=await jfetch('/api/admin/session').catch(()=>null);
  if(!session?.authenticated)return;
  csrf=session.csrf;
  const doc=await jfetch('/api/appearance');
  gallery=Array.isArray(doc.gallery)?doc.gallery:[];
  let tries=0;
  const timer=setInterval(()=>{
    const body=document.querySelector('#emAdminPanel .em-admin-body');
    if(!body){if(++tries>40)clearInterval(timer);return}
    clearInterval(timer);
    const section=document.createElement('div');section.className='em-admin-section';section.innerHTML=
      '<h4>Galerie photos</h4><div id="emGalleryAdmin"></div>'+
      '<div class="em-admin-row one"><button class="em-admin-btn primary" type="button" data-ga="add">＋ Ajouter des photos</button>'+
      '<input id="emGalleryFiles" type="file" accept="image/*" multiple hidden></div>'+
      '<div class="em-admin-help">Ajoutez, supprimez et réordonnez librement les photos. La galerie est enregistrée sur le serveur.</div>';
    const pageSection=[...body.querySelectorAll('.em-admin-section')].find(x=>x.querySelector('#emSel'));
    body.insertBefore(section,pageSection||body.lastElementChild);
    section.addEventListener('click',action);
    section.querySelector('#emGalleryFiles').addEventListener('change',onFiles);
    renderAdmin();renderPublic();
  },150);
}
document.addEventListener('DOMContentLoaded',()=>setTimeout(mount,200));
})();