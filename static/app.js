'use strict';
// A small enhancement layer. Flask handles all local persistence.
const sidebar = document.getElementById('sidebar');
const backdrop = document.getElementById('sidebar-backdrop');
const menuToggle = document.getElementById('menu-toggle');
function setSidebar(open){sidebar?.classList.toggle('show',open);backdrop?.classList.toggle('show',open);menuToggle?.setAttribute('aria-expanded',String(open));}
menuToggle?.addEventListener('click',()=>{
  const opening=!sidebar.classList.contains('show');
  setSidebar(opening);
  if(opening)(sidebar.querySelector('[aria-current="page"]') || sidebar.querySelector('nav a'))?.focus();
});
backdrop?.addEventListener('click',()=>{
  setSidebar(false);
  menuToggle?.focus();
});
const notificationBtn=document.getElementById('notification-btn');
const notificationBox=document.getElementById('notification-box');
notificationBtn?.addEventListener('click',()=>{notificationBox.hidden=!notificationBox.hidden;notificationBtn.setAttribute('aria-expanded',String(!notificationBox.hidden));});

document.querySelectorAll('[data-dismiss="flash"]').forEach(b=>b.addEventListener('click',()=>b.parentElement?.remove()));
function dialogOpen(dialog){if(dialog && !dialog.open)dialog.showModal();}
function dialogClose(dialog){if(dialog?.open)dialog.close();}
const questModal=document.getElementById('quest-modal');
const questForm=document.getElementById('quest-form');
const archiveForm=document.getElementById('archive-quest');
function openQuest(button){
  if(!questModal||!questForm)return;
  const editing=button.dataset.questModal==='edit';
  questForm.reset();
  questForm.action=editing?`/habits/${encodeURIComponent(button.dataset.id)}/edit`:'/habits';
  document.getElementById('quest-modal-title').textContent=editing?'Edit Item':'New Item';
  document.getElementById('save-quest').textContent=editing?'Update Quest →':'Save Quest →';
  if(editing){
    questForm.elements.title.value=button.dataset.title;
    questForm.elements.category.value=button.dataset.category;
    questForm.elements.scheduled_time.value=button.dataset.clock;
    questForm.elements.xp.value=button.dataset.xp;
    questForm.elements.duration_minutes.value=button.dataset.duration || "30";
    archiveForm.action=`/habits/${encodeURIComponent(button.dataset.id)}/archive`;
    archiveForm.hidden=false;
  }else{archiveForm.hidden=true;}
  questForm.elements.kind.value=button.dataset.kind || 'habit';
  questForm.querySelectorAll('[name="repeat_days"]').forEach(input=>{input.checked=(button.dataset.days || '0,1,2,3,4,5,6').split(',').includes(input.value);});
  for(const [field,key] of [['weekly_target','target'],['due_on','due'],['minimum_action','minimum'],['first_step','step'],['routine_id','routine']]) questForm.elements[field].value=editing?(button.dataset[key] || ''):'';
  updateQuestType();
  dialogOpen(questModal);
  questForm.elements.title.focus();
}
document.querySelectorAll('[data-quest-modal]').forEach(b=>b.addEventListener('click',()=>openQuest(b)));
archiveForm?.addEventListener('submit',event=>{if(!window.confirm('Archive this quest? Your past XP and history will be preserved.'))event.preventDefault();});
const routineModal=document.getElementById('routine-modal');
const routineForm=document.getElementById('routine-form');
const removeRoutine=document.getElementById('remove-routine');
function openRoutine(button){
  if(!routineModal||!routineForm)return;
  const editing=button.dataset.routineModal==='edit';
  routineForm.reset();
  routineForm.action=editing?`/routine/${encodeURIComponent(button.dataset.id)}/edit`:'/routine/add';
  document.getElementById('routine-modal-title').textContent=editing?'Edit Routine':'Add Routine';
  if(editing){
    routineForm.elements.title.value=button.dataset.title;
    routineForm.elements.scheduled_time.value=button.dataset.clock;
    routineForm.elements.symbol.value=button.dataset.symbol;
    removeRoutine.action=`/routine/${encodeURIComponent(button.dataset.id)}/remove`;
    removeRoutine.hidden=false;
  }else{removeRoutine.hidden=true;}
  dialogOpen(routineModal);routineForm.elements.title.focus();
}
document.querySelectorAll('[data-routine-modal]').forEach(b=>b.addEventListener('click',()=>openRoutine(b)));
removeRoutine?.addEventListener('submit',event=>{if(!window.confirm('Remove this routine activity?'))event.preventDefault();});
document.querySelectorAll('.close-modal').forEach(b=>b.addEventListener('click',()=>dialogClose(b.closest('dialog'))));
document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('click',e=>{if(e.target===dialog)dialogClose(dialog);}));
document.addEventListener('keydown',event=>{
  if(event.key!=='Escape')return;
  if(sidebar?.classList.contains('show')){
    setSidebar(false);
    menuToggle?.focus();
  }
  if(notificationBox && !notificationBox.hidden){
    notificationBox.hidden=true;
    notificationBtn.setAttribute('aria-expanded','false');
    notificationBtn.focus();
  }
});

function updateQuestType(){
  const isHabit=questForm?.elements.kind.value==='habit';
  const repeat=document.getElementById('repeat-fields');
  const due=document.getElementById('due-fields');
  if(repeat)repeat.hidden=!isHabit;
  if(due)due.hidden=isHabit;
  // Hidden inputs should not block native constraint validation.
  repeat?.querySelectorAll('input').forEach(i=>i.disabled=!isHabit);
  due?.querySelectorAll('input').forEach(i=>i.disabled=isHabit);
}
questForm?.elements.kind.addEventListener('change',updateQuestType);
updateQuestType();
// Preserve the page and viewport after a normal Flask form submission.
const scrollKey='monoquest-scroll:'+location.pathname+location.search;
try{const saved=sessionStorage.getItem(scrollKey);if(saved!==null){requestAnimationFrame(()=>window.scrollTo(0,Number(saved)));sessionStorage.removeItem(scrollKey);}}catch(_e){}
document.querySelectorAll('form[method="post"]').forEach(form=>{
  if(!form.elements.return_to){const input=document.createElement('input');input.type='hidden';input.name='return_to';input.value=location.pathname+location.search;form.append(input);}
  form.addEventListener('submit',()=>{try{sessionStorage.setItem(scrollKey,String(window.scrollY));}catch(_e){}});
});
const focusClock=document.getElementById('focus-clock');
if(focusClock){
  const initial=Number(focusClock.dataset.remaining);
  const started=Date.now();
  let announced=false;
  function tick(){
    const left=Math.max(0,initial-(focusClock.dataset.running==='yes'?Math.floor((Date.now()-started)/1000):0));
    focusClock.textContent=String(Math.floor(left/60)).padStart(2,'0')+':'+String(left%60).padStart(2,'0');
    document.title=focusClock.textContent+' · Focus · MONOQUEST';
    if(left===0 && !announced){announced=true;document.getElementById('focus-message').textContent='Session complete. Finish & save time when you are ready.';}
  }
  tick();setInterval(tick,1000);
}

// The server emits this reward once, only after a real increase in earned XP.
const celebration=document.getElementById('quest-celebration');
if(celebration){
  const dismiss=()=>celebration.remove();
  celebration.querySelector('.celebration-close')?.addEventListener('click',dismiss);
  document.addEventListener('keydown',event=>{if(event.key==='Escape')dismiss();},{once:true});
  let rewardTimeout=setTimeout(dismiss,5500);
  celebration.addEventListener('mouseenter',()=>clearTimeout(rewardTimeout));
  celebration.addEventListener('mouseleave',()=>{rewardTimeout=setTimeout(dismiss,2500);});
  celebration.addEventListener('focusin',()=>clearTimeout(rewardTimeout));
  celebration.addEventListener('focusout',()=>{rewardTimeout=setTimeout(dismiss,2500);});
}
