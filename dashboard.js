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
async function scopedAPI(action,data){
  const epoch=workspaceUI.epoch;
  const result=await api(action,data);
  if(epoch!==workspaceUI.epoch)throw Error('Persona changed; retry in your current workspace.');
  return result;
}
const libraryTools = node('div', undefined, 'toolbar');
const librarySearch=node('input');librarySearch.placeholder='Search notes; use "exact phrases"';librarySearch.setAttribute('aria-label','Search source library');
const collectionFilter = node('input'); collectionFilter.placeholder = 'Filter collection'; collectionFilter.setAttribute('aria-label','Filter collection');
const tagFilter = node('input'); tagFilter.placeholder = 'Filter tag'; tagFilter.setAttribute('aria-label','Filter tag');
const bookmarkFilter = node('input'); bookmarkFilter.type='checkbox';
const bookmarkLabel = node('label','Bookmarked'); bookmarkLabel.prepend(bookmarkFilter);
libraryTools.append(librarySearch,collectionFilter,tagFilter,bookmarkLabel,control('button','Apply',async()=>{
  workspaceUI.filters={collection:collectionFilter.value.trim(),tag:tagFilter.value.trim(),bookmarked:bookmarkFilter.checked};
  workspaceUI.libraryOffset=0; await renderLibrary();
}),control('button','Clear',async()=>{
  librarySearch.value='';collectionFilter.value='';tagFilter.value='';bookmarkFilter.checked=false;workspaceUI.filters={};workspaceUI.libraryOffset=0;await renderLibrary();
}));
$('documents').before(libraryTools);
const libraryPager=node('div',undefined,'toolbar');$('documents').after(libraryPager);
const trashPanel=node('div',undefined,'utility-panel');trashPanel.hidden=true;libraryPager.after(trashPanel);
libraryTools.append(control('button','My trash',async()=>{
  trashPanel.hidden=!trashPanel.hidden;
  if(!trashPanel.hidden)await renderTrash();
}));
async function renderTrash(){
  const result=await scopedAPI('trash',{});trashPanel.replaceChildren(node('h3','Your deleted sources'));
  trashPanel.append(node('p','Deleted sources and their citations are hidden until restored. History is retained locally.','section-note'));
  for(const doc of result.docs){
    const row=node('div',undefined,'history-row');row.append(node('span',doc.title+' · v'+doc.version),control('button','Restore',async()=>{await api('restore',{id:doc.id});await refresh();await renderTrash()}));trashPanel.append(row);
  }
  if(!result.docs.length)trashPanel.append(node('p','Your trash is empty.','section-note'));
}
async function renderLibrary(){
  const epoch=workspaceUI.epoch;
  const searching=!!librarySearch.value.trim();
  const [page,bookmarks]=await Promise.all([api(searching?'search':'library',{...(searching?{query:librarySearch.value}:{}),filters:workspaceUI.filters,offset:workspaceUI.libraryOffset,limit:workspaceUI.pageSize}),api('bookmarks',{})]);
  if(epoch!==workspaceUI.epoch)return;
  $('documents').replaceChildren();
  const documents=searching?page.sources.map(s=>({...s,body:s.snippet,tags:JSON.stringify(s.tags)})):page.docs;
  for(const d of documents){
    const card=node('article',undefined,'doc');
    card.append(node('span','▤','doc-icon'),node('h3',d.title),node('p',d.body.slice(0,110)+(d.body.length>110?'…':'')));
    card.append(node('p',(d.collection||'Unfiled')+' · '+JSON.parse(d.tags).join(', '),'doc-meta'));
    card.append(node('small',searching?'Relevance '+d.score+' · version '+d.version:d.owner+' · '+d.visibility+' · version '+d.version));
    const actions=node('div',undefined,'doc-actions');
    actions.append(control('button','Read source',()=>showSource(d.id)),control('button',bookmarks.ids.includes(d.id)?'★ Saved':'☆ Save',async()=>{await api('bookmark',{id:d.id,enabled:!bookmarks.ids.includes(d.id)});await renderLibrary()}));
    if(d.owner===state.actor)actions.append(control('button','Edit',()=>openEditor(d)),control('button','Trash',async()=>{if(confirm('Move this source to your trash? Historical citations will be unavailable until restored.')){await api('delete',{id:d.id});$('answer').hidden=true;await refresh()}}));
    card.append(actions);$('documents').append(card);
  }
  if(!documents.length)$('documents').append(node('p','No sources match these filters.','section-note'));
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
      const current=(await scopedAPI('source',{id})).source;
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
  librarySearch.value='';collectionFilter.value='';tagFilter.value='';bookmarkFilter.checked=false;
  sourceDialog.close();sourceDialog.replaceChildren();trashPanel.hidden=true;
});

const dueInput=node('input');dueInput.type='date';dueInput.id='task-due';dueInput.setAttribute('aria-label','Proposed task due date');
$('task-form').append(node('label','Due date (optional)'),dueInput);
const taskTools=node('div',undefined,'toolbar');
const taskStatus=node('select');taskStatus.setAttribute('aria-label','Task status filter');
for(const value of ['all','open','complete']){const option=node('option',value[0].toUpperCase()+value.slice(1));option.value=value;taskStatus.append(option)}
const dueBefore=node('input');dueBefore.type='date';dueBefore.setAttribute('aria-label','Tasks due on or before');
taskTools.append(taskStatus,node('span','Due by'),dueBefore,control('button','Filter',()=>renderTasks()));$('task-list').before(taskTools);
async function renderTasks(){
  const epoch=workspaceUI.epoch;
  const result=await api('tasks',{status:taskStatus.value,due_before:dueBefore.value});
  if(epoch!==workspaceUI.epoch)return;
  $('task-list').replaceChildren();
  for(const task of result.tasks){
    const row=node('div',undefined,'task-item');
    row.append(node('strong',(task.status==='complete'?'✓ ':'○ ')+task.title),node('p',task.due?'Due '+task.due:'No due date','section-note'));
    row.append(control('button',task.status==='open'?'Complete':'Reopen',async()=>{await api('task-status',{id:task.id,status:task.status==='open'?'complete':'open'});await refresh()}));
    const date=node('input');date.type='date';date.value=task.due;date.setAttribute('aria-label','Due date for '+task.title);
    row.append(date,control('button','Save date',async()=>{await api('task-due',{id:task.id,due:date.value});await refresh()}));$('task-list').append(row);
  }
  if(!result.tasks.length)$('task-list').append(node('p','No tasks match this view.','section-note'));
}
window.addEventListener('papertrail-state',()=>renderTasks().catch(e=>toast(e.message)));

async function renderProposals(){
  const epoch=workspaceUI.epoch;
  const result=await api('pending-proposals',{});
  if(epoch!==workspaceUI.epoch)return;
  $('proposal').replaceChildren(node('h3','Awaiting your approval'));
  $('proposal').hidden=!result.proposals.length;
  for(const proposal of result.proposals){
    const row=node('div',undefined,'pending-row');
    row.append(node('strong',proposal.title),node('p',proposal.workspace+' · '+(proposal.due?'due '+proposal.due+' · ':'')+'expires '+new Date(proposal.expires*1000).toLocaleTimeString(),'section-note'));
    row.append(node('p','Approval creates one personal task in this local database.','section-note'));
    row.append(control('button','Approve & create',async()=>{await api('approve',{proposal:proposal.proposal});await refresh();toast('Approved personal task created.')}),control('button','Cancel proposal',async()=>{await api('cancel-proposal',{proposal:proposal.proposal});await refresh()}));
    $('proposal').append(row);
  }
}
$('task-form').onsubmit=async event=>{
  event.preventDefault();
  try{await api('propose',{title:$('task-title').value,due:dueInput.value});$('task-title').value='';dueInput.value='';await refresh()}
  catch(error){toast(error.message)}
};
window.addEventListener('papertrail-state',()=>renderProposals().catch(e=>toast(e.message)));

const savedPanel=node('div',undefined,'utility-panel');
savedPanel.append(node('h3','Keep a useful search'),node('p','Save the library search and its current filters. Saved searches are personal to this demo persona.','section-note'));
const savedName=node('input');savedName.placeholder='Name this search';savedName.maxLength=80;savedName.setAttribute('aria-label','Saved search name');
const savedList=node('div',undefined,'saved-list');
savedPanel.append(savedName,control('button','Save current search',async()=>{
  await api('save-query',{name:savedName.value,query:librarySearch.value,filters:workspaceUI.filters});savedName.value='';await renderSavedQueries();
}),savedList);trashPanel.after(savedPanel);
async function renderSavedQueries(){
  const epoch=workspaceUI.epoch;
  const result=await api('saved-queries',{});if(epoch!==workspaceUI.epoch)return;
  savedList.replaceChildren();
  for(const query of result.queries){
    const row=node('div',undefined,'history-row');
    row.append(control('button',query.name,async()=>{
      workspaceUI.filters=JSON.parse(query.filters);librarySearch.value=query.query;
      collectionFilter.value=workspaceUI.filters.collection||'';tagFilter.value=workspaceUI.filters.tag||'';bookmarkFilter.checked=!!workspaceUI.filters.bookmarked;
      workspaceUI.libraryOffset=0;await renderLibrary();$('library').scrollIntoView({behavior:'smooth'});
    }),node('span',query.query),control('button','Remove',async()=>{await api('delete-query',{id:query.id});await renderSavedQueries()}));savedList.append(row);
  }
  if(!result.queries.length)savedList.append(node('p','No saved searches yet.','section-note'));
}
window.addEventListener('papertrail-state',()=>renderSavedQueries().catch(e=>toast(e.message)));

function downloadJSON(value,name){
  const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
  const link=node('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
const archivePanel=node('details',undefined,'utility-panel');archivePanel.append(node('summary','Import & export your documents'));
archivePanel.append(node('p','Export contains your active owned sources only. Paste a Papertrail JSON archive to preview it. Imported sources belong to your current persona and workspace.','section-note'));
archivePanel.append(control('button','Download my sources',async()=>downloadJSON(await api('export-documents',{}),'papertrail-'+state.actor+'.json')));
const archiveText=node('textarea');archiveText.placeholder='Paste a papertrail.documents.v1 JSON archive';archiveText.maxLength=8200000;archiveText.setAttribute('aria-label','JSON document archive');
const importPreview=node('div');let reviewedArchive=null;
const importButton=control('button','Import reviewed sources',async()=>{
  if(!reviewedArchive)return;
  const result=await api('import-documents',{archive:reviewedArchive});reviewedArchive=null;importButton.hidden=true;archiveText.value='';importPreview.replaceChildren(node('p',result.created.length+' created · '+result.skipped+' duplicates skipped'));await refresh();
});importButton.hidden=true;
archiveText.addEventListener('input',()=>{reviewedArchive=null;importButton.hidden=true;importPreview.replaceChildren()});
archivePanel.append(archiveText,control('button','Preview import',async()=>{
  const archive=JSON.parse(archiveText.value);const result=await api('preview-import',{archive});reviewedArchive=archive;
  importPreview.replaceChildren(node('h3',result.create_count+' sources to create · '+result.skip_count+' duplicates to skip'));
  for(const entry of result.entries)importPreview.append(node('p',(entry.duplicate?'Skip: ':'Create: ')+entry.title+' · '+entry.visibility,'section-note'));
  importButton.hidden=!result.create_count;
}),importPreview,importButton);savedPanel.after(archivePanel);
$('persona').addEventListener('change',()=>{reviewedArchive=null;archiveText.value='';importPreview.replaceChildren();importButton.hidden=true;archivePanel.open=false});

const collectionPanel=node('details',undefined,'utility-panel');collectionPanel.append(node('summary','Organize your collections'));
collectionPanel.append(node('p','Renaming updates only sources you own. Merging into an existing collection requires explicit permission. Empty target clears the collection.','section-note'));
const collectionSource=node('select');collectionSource.setAttribute('aria-label','Owned collection to rename');
const collectionTarget=node('input');collectionTarget.placeholder='New collection name';collectionTarget.maxLength=60;collectionTarget.setAttribute('aria-label','New collection name');
const mergeBox=node('input');mergeBox.type='checkbox';const mergeLabel=node('label','Allow merging into an existing collection');mergeLabel.prepend(mergeBox);
collectionPanel.append(collectionSource,collectionTarget,mergeLabel,control('button','Update my sources',async()=>{
  if(!confirm('Update this collection on your owned sources? Each change creates a version.'))return;
  const result=await api('rename-collection',{source:collectionSource.value,target:collectionTarget.value,merge:mergeBox.checked});collectionTarget.value='';mergeBox.checked=false;await refresh();toast(result.updated+' owned sources updated.');
}));archivePanel.after(collectionPanel);
async function renderCollections(){
  const result=await scopedAPI('collections',{});collectionSource.replaceChildren();
  for(const collection of result.collections){const option=node('option',collection.name+' ('+collection.count+')');option.value=collection.name;collectionSource.append(option)}
}
window.addEventListener('papertrail-state',()=>renderCollections().catch(e=>toast(e.message)));

let activityOffset=0;
const activityTools=node('div',undefined,'toolbar');
const activityFilter=node('input');activityFilter.placeholder='Action, e.g. denied';activityFilter.maxLength=40;activityFilter.setAttribute('aria-label','Activity action filter');
activityTools.append(activityFilter,control('button','Filter activity',async()=>{activityOffset=0;await renderActivity()}),control('button','Export redacted activity',async()=>downloadJSON(await scopedAPI('export-activity',{action:activityFilter.value.trim()}),'papertrail-activity-'+state.actor+'.json')));
$('audit').before(activityTools);const activityPager=node('div',undefined,'toolbar');$('audit').after(activityPager);
async function renderActivity(){
  const result=await scopedAPI('activity',{action:activityFilter.value.trim(),offset:activityOffset,limit:8});
  $('audit').replaceChildren();
  for(const event of result.events){const row=node('div',undefined,'audit-row');row.append(node('strong',event.action),node('span',event.detail),node('time',event.created+' UTC'));$('audit').append(row)}
  if(!result.events.length)$('audit').append(node('p','No activity matches this filter.','section-note'));
  const previous=control('button','← Previous',async()=>{activityOffset=Math.max(0,activityOffset-8);await renderActivity()});previous.disabled=activityOffset===0;
  const next=control('button','Next →',async()=>{activityOffset+=8;await renderActivity()});next.disabled=activityOffset+8>=result.total;
  activityPager.replaceChildren(node('span',result.total+' personal activity records'),previous,next);
}
window.addEventListener('papertrail-state',()=>renderActivity().catch(e=>toast(e.message)));
$('persona').addEventListener('change',()=>{activityOffset=0;activityFilter.value='';taskStatus.value='all';dueBefore.value=''});
