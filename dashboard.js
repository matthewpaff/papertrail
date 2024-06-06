/* Additional workspace views subscribe to successful state refreshes. */
const workspaceUI = { libraryOffset: 0, filters: {}, pageSize: 6 };
function control(tag, text, handler, cls='secondary') {
  const element = node(tag, text, cls);
  if (handler) element.addEventListener('click', () => Promise.resolve(handler()).catch(error => toast(error.message)));
  return element;
}
const libraryTools = node('div', undefined, 'toolbar');
const collectionFilter = node('input'); collectionFilter.placeholder = 'Filter collection'; collectionFilter.setAttribute('aria-label','Filter collection');
const tagFilter = node('input'); tagFilter.placeholder = 'Filter tag'; tagFilter.setAttribute('aria-label','Filter tag');
const bookmarkFilter = node('input'); bookmarkFilter.type='checkbox';
const bookmarkLabel = node('label','Bookmarked'); bookmarkLabel.prepend(bookmarkFilter);
libraryTools.append(collectionFilter,tagFilter,bookmarkLabel,control('button','Apply',async()=>{
  workspaceUI.filters={collection:collectionFilter.value.trim(),tag:tagFilter.value.trim(),bookmarked:bookmarkFilter.checked};
  workspaceUI.libraryOffset=0; await renderLibrary();
}),control('button','Clear',async()=>{
  collectionFilter.value='';tagFilter.value='';bookmarkFilter.checked=false;workspaceUI.filters={};workspaceUI.libraryOffset=0;await renderLibrary();
}));
$('documents').before(libraryTools);
const libraryPager=node('div',undefined,'toolbar');$('documents').after(libraryPager);
async function renderLibrary(){
  const [page,bookmarks]=await Promise.all([api('library',{filters:workspaceUI.filters,offset:workspaceUI.libraryOffset,limit:workspaceUI.pageSize}),api('bookmarks',{})]);
  $('documents').replaceChildren();
  for(const d of page.docs){
    const card=node('article',undefined,'doc');
    card.append(node('span','▤','doc-icon'),node('h3',d.title),node('p',d.body.slice(0,110)+(d.body.length>110?'…':'')));
    card.append(node('p',(d.collection||'Unfiled')+' · '+JSON.parse(d.tags).join(', '),'doc-meta'));
    card.append(node('small',d.owner+' · '+d.visibility+' · version '+d.version));
    const actions=node('div',undefined,'doc-actions');
    actions.append(control('button','Read source',()=>showSource(d.id)),control('button',bookmarks.ids.includes(d.id)?'★ Saved':'☆ Save',async()=>{await api('bookmark',{id:d.id,enabled:!bookmarks.ids.includes(d.id)});await renderLibrary()}));
    if(d.owner===state.actor)actions.append(control('button','Edit',()=>openEditor(d)),control('button','Trash',async()=>{if(confirm('Move this source to your trash? Historical citations will be unavailable until restored.')){await api('delete',{id:d.id});$('answer').hidden=true;await refresh()}}));
    card.append(actions);$('documents').append(card);
  }
  if(!page.docs.length)$('documents').append(node('p','No sources match these filters.','section-note'));
  libraryPager.replaceChildren(node('span',page.total+' accessible sources · page '+(Math.floor(workspaceUI.libraryOffset/workspaceUI.pageSize)+1)));
  const previous=control('button','← Previous',async()=>{workspaceUI.libraryOffset=Math.max(0,workspaceUI.libraryOffset-workspaceUI.pageSize);await renderLibrary()});previous.disabled=workspaceUI.libraryOffset===0;
  const next=control('button','Next →',async()=>{workspaceUI.libraryOffset+=workspaceUI.pageSize;await renderLibrary()});next.disabled=workspaceUI.libraryOffset+workspaceUI.pageSize>=page.total;
  libraryPager.append(previous,next);
}
window.addEventListener('papertrail-state',()=>renderLibrary().catch(e=>toast(e.message)));
