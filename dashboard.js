/* Additional workspace views subscribe to successful state refreshes. */
const workspaceUI = { libraryOffset: 0, filters: {}, pageSize: 6, epoch: 0 };
const collectionInput=node('input');collectionInput.id='doc-collection';collectionInput.placeholder='Collection (optional)';collectionInput.maxLength=60;collectionInput.setAttribute('aria-label','Collection');
const tagsInput=node('input');tagsInput.id='doc-tags';tagsInput.placeholder='Tags, separated by commas (up to 12)';tagsInput.setAttribute('aria-label','Tags');
$('doc-body').before(collectionInput,tagsInput);
const originalOpenEditor=openEditor;
openEditor=function(doc){originalOpenEditor(doc);collectionInput.value=doc?.collection||'';tagsInput.value=doc?JSON.parse(doc.tags||'[]').join(', '):''};
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
const trashPanel=node('div',undefined,'utility-panel');trashPanel.hidden=true;libraryPager.after(trashPanel);
libraryTools.append(control('button','My trash',async()=>{
  trashPanel.hidden=!trashPanel.hidden;
  if(!trashPanel.hidden)await renderTrash();
}));
async function renderTrash(){
  const result=await api('trash',{});trashPanel.replaceChildren(node('h3','Your deleted sources'));
  trashPanel.append(node('p','Deleted sources and their citations are hidden until restored. History is retained locally.','section-note'));
  for(const doc of result.docs){
    const row=node('div',undefined,'history-row');row.append(node('span',doc.title+' · v'+doc.version),control('button','Restore',async()=>{await api('restore',{id:doc.id});await refresh();await renderTrash()}));trashPanel.append(row);
  }
  if(!result.docs.length)trashPanel.append(node('p','Your trash is empty.','section-note'));
}
async function renderLibrary(){
  const epoch=workspaceUI.epoch;
  const [page,bookmarks]=await Promise.all([api('library',{filters:workspaceUI.filters,offset:workspaceUI.libraryOffset,limit:workspaceUI.pageSize}),api('bookmarks',{})]);
  if(epoch!==workspaceUI.epoch)return;
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
window.addEventListener('papertrail-state',()=>{renderLibrary().catch(e=>toast(e.message));if(!trashPanel.hidden)renderTrash().catch(e=>toast(e.message))});

const sourceDialog=node('dialog',undefined,'source-dialog');
sourceDialog.setAttribute('aria-label','Source details and version history');
document.body.append(sourceDialog);
async function showSource(id, version){
  const epoch=workspaceUI.epoch;
  const [detail,history]=await Promise.all([api('source',{id,...(version?{version}:{})}),api('history',{id})]);
  if(epoch!==workspaceUI.epoch)return;
  const doc=detail.source;
  sourceDialog.replaceChildren();
  const top=node('div',undefined,'section-title');
  top.append(node('span','SOURCE #'+id+' · VERSION '+doc.version,'eyebrow'),control('button','Close',()=>sourceDialog.close()));
  sourceDialog.append(top,node('h2',doc.title),node('p',doc.owner+' · '+doc.workspace+' · '+doc.visibility,'section-note'));
  const text=node('pre',doc.body,'source-body');sourceDialog.append(text);
  const latest=history.versions[0]?.version;
  if(doc.version!==latest){
    const actions=node('div',undefined,'toolbar');
    actions.append(control('button','Compare with current',async()=>{
      const current=(await api('source',{id})).source;
      const comparison=node('div',undefined,'comparison');
      const previous=node('div');previous.append(node('h3','Viewing version '+doc.version),node('pre',doc.body,'source-body'));
      const now=node('div');now.append(node('h3','Current version '+current.version),node('pre',current.body,'source-body'));
      comparison.append(previous,now);text.replaceWith(comparison);
    }));
    if(doc.owner===state.actor)actions.append(control('button','Restore this revision',async()=>{
      if(!confirm('Create a new current version using this content? Current visibility will be preserved.'))return;
      const result=await api('restore-revision',{id,version:doc.version});
      $('answer').hidden=true;await refresh();await showSource(id,result.version);toast('Historical content restored as version '+result.version+'.');
    }));
    sourceDialog.append(actions);
  }
  sourceDialog.append(node('h3','Version history'));
  const versions=node('div',undefined,'history-list');
  for(const entry of history.versions){
    const row=node('div',undefined,'history-row');
    row.append(control('button','Version '+entry.version,()=>showSource(id,entry.version)),node('span',entry.title),node('small',entry.created+' UTC'));
    if(entry.version===doc.version)row.append(node('span','Viewing','badge'));
    versions.append(row);
  }
  sourceDialog.append(versions);
  if(!sourceDialog.open)sourceDialog.showModal();
}
$('persona').addEventListener('change',()=>{
  workspaceUI.epoch++;workspaceUI.libraryOffset=0;workspaceUI.filters={};
  collectionFilter.value='';tagFilter.value='';bookmarkFilter.checked=false;
  sourceDialog.close();sourceDialog.replaceChildren();trashPanel.hidden=true;
});
