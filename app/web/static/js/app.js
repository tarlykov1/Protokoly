document.addEventListener('click',(e)=>{const t=e.target.closest('[data-toggle-sidebar]');if(t){document.querySelector('.sidebar')?.classList.toggle('open')}});
