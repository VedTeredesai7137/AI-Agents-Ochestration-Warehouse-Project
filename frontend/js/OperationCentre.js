// Live Operations. Real API snapshots; no simulation decisions live in this file.
const state = {
 grid:null, robots:[], tasks:[], agentStatus:[], messages:[], auctions:[], negotiations:[], events:[],
 simStatus:null, orchestrator:null, selectedRobotId:null, metrics:{totalMessages:0},
 renderedMessageIds:new Set(), messageSession:null, displayedMessageId:null,
 overridePending:false, overrideEpoch:0, epoch:0, polling:false, slowPolling:false,
 controlPending:false, lastGood:0, lastSlow:0, errors:new Map(), zoom:1,
 tab:'crisis', layers:{robots:true,chargers:true,paths:true,crisis:true},
 tape:{filter:'ALL',follow:true}, context:{filter:'ALL',follow:true}, robotNodes:new Map(),
 gridVersion:null, messageRun:null
};
const $ = id => document.getElementById(id);
const UI = {
 gridContainer:$('grid-container'), inspectorContent:$('agent-inspector-content'),
 messageBusContent:$('message-bus-content'), auctionContent:$('auction-content'),
 negotiationContent:$('negotiation-content'), orchestratorPanel:$('orchestrator-panel'),
 orchestratorContent:$('orchestrator-content'), orchestratorStatusBadge:$('orchestrator-status-badge'),
 hitlOverlay:$('hitl-overlay'), hitlDetails:$('hitl-details')
};
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function text(id,value){const el=$(id);if(el && el.textContent!==String(value))el.textContent=String(value);}
function html(el,value){if(el && el.innerHTML!==value)el.innerHTML=value;}
const row=(label,value)=>`<div class="orch-detail-row"><span class="label">${escapeHtml(label)}</span><span class="val">${escapeHtml(value ?? '--')}</span></div>`;
const coord=p=>Array.isArray(p)?`(${p[0]}, ${p[1]})`:p?`(${p.x}, ${p.y})`:'--';
function fail(endpoint,error){if(!state.errors.has(endpoint))console.error(`[UI][API_ERROR] endpoint=${endpoint} ${error.message}`);state.errors.set(endpoint,error.message);}
async function json(endpoint,options){try{const res=await apiFetch(endpoint,options);return await res.json();}catch(e){fail(endpoint,e);throw e;}}
function validData(endpoint,data){
 let valid=true;
 if(endpoint==='/simulation/status')valid=typeof data?.running==='boolean' && Number.isInteger(data.current_step) && typeof data.run_id==='string' && Number.isInteger(data.total_tasks);
 if(endpoint==='/robots')valid=Array.isArray(data)&&data.every(r=>Number.isInteger(r.id)&&Number.isFinite(r.battery)&&Number.isInteger(r.position?.x)&&Number.isInteger(r.position?.y)&&typeof r.status==='string'&&Array.isArray(r.path));
 if(endpoint==='/tasks')valid=Array.isArray(data)&&data.every(t=>Number.isInteger(t.id)&&typeof t.completed==='boolean'&&['pickup_x','pickup_y','delivery_x','delivery_y'].every(k=>Number.isInteger(t[k])));
 if(endpoint==='/warehouse/grid')valid=Number.isInteger(data?.width)&&Number.isInteger(data.height)&&Array.isArray(data.grid)&&data.grid.length===data.height&&data.grid.every(r=>Array.isArray(r)&&r.length===data.width);
 if(endpoint==='/agents/status')valid=Array.isArray(data?.agents);
 if(endpoint==='/orchestrator/state')valid=typeof data?.active==='boolean'&&Array.isArray(data.affected_robots)&&Array.isArray(data.validation_issues);
 if(endpoint.startsWith('/orchestrator/events'))valid=Array.isArray(data?.events)&&typeof data.run_id==='string';
 if(endpoint==='/agents/message-history')valid=Array.isArray(data?.messages);
 if(endpoint==='/auction/logs'||endpoint==='/negotiation/logs')valid=Array.isArray(data);
 if(!valid){const e=new Error('Malformed API response');fail(endpoint,e);throw e;}
 state.errors.delete(endpoint);return data;
}
async function read(endpoint){return validData(endpoint,await json(endpoint));}
function clearRun(){
 state.epoch++;state.overrideEpoch++;state.overridePending=false;state.reviewPlan=null;state.selectedRobotId=null;state.agentStatus=[];state.messages=[];state.events=[];
 state.auctions=[];state.negotiations=[];state.orchestrator=null;state.lastSlow=0;
 state.renderedMessageIds.clear();state.displayedMessageId=null;state.messageSession=null;state.messageRun=null;
 state.tape.follow=state.context.follow=true;state.robotNodes.clear();$('robot-layer').replaceChildren();
 UI.messageBusContent.replaceChildren();UI.hitlOverlay.style.display='none';
 text('model-name','Awaiting model event');text('crisis-feedback','');text('hitl-feedback','');
 updateOrchestrator();renderEvents();
}
async function pollData(){
 if(state.polling||state.controlPending)return;state.polling=true;
 const epoch=state.epoch;
 try{
  const status=await read('/simulation/status');
  const [robots,tasks]=await Promise.all([read('/robots'),read('/tasks')]);
  const version=`${status.run_id}:${status.grid_revision}`;
  const grid=(!state.grid||version!==state.gridVersion)?await read('/warehouse/grid'):state.grid;
  // Endpoints are individual snapshots. Do not draw new-run robots on an old grid
  // if an external reset/collapse crossed this polling batch.
  const end=await read('/simulation/status');
  if(epoch!==state.epoch||end.run_id!==status.run_id||end.grid_revision!==status.grid_revision||end.current_step<status.current_step)return;
  const reset=state.simStatus&&(status.run_id!==state.simStatus.run_id||status.current_step<state.simStatus.current_step);
  if(reset){console.log('[UI][RESET DETECTED] refreshing run and grid');clearRun();}
  if(grid!==state.grid){state.grid=grid;state.gridVersion=version;createGrid();console.log('[GRID REFRESH] current warehouse loaded');}
  state.simStatus=status;state.robots=robots;state.tasks=tasks;state.lastGood=Date.now();updateUI();
 }catch(e){/* Last good map remains visible; freshness communicates the failure. */}
 finally{state.polling=false;updateConnectivity();}
}
async function pollSlow(){
 if(state.slowPolling||state.controlPending||!state.simStatus)return;state.slowPolling=true;
 const epoch=state.epoch, overrideEpoch=state.overrideEpoch, run=state.simStatus.run_id;
 const endpoints=['/orchestrator/state','/orchestrator/events?limit=300','/agents/status','/agents/message-history'];
 try{
  const results=await Promise.allSettled(endpoints.map(read));
  if(epoch!==state.epoch||run!==state.simStatus?.run_id)return;
  const [orch,events,agents,messages]=results;
  if(orch.status==='fulfilled'&&orch.value.run_id===run&&overrideEpoch===state.overrideEpoch&&!state.overridePending)state.orchestrator=orch.value;
  if(events.status==='fulfilled'&&events.value.run_id===run){state.events=events.value.events.slice(-300);state.lastSlow=Date.now();}
  if(agents.status==='fulfilled')state.agentStatus=agents.value.agents;
  if(messages.status==='fulfilled'){
   if(state.messageSession!==messages.value.session_id){state.renderedMessageIds.clear();state.displayedMessageId=null;UI.messageBusContent.replaceChildren();}
   state.messageSession=messages.value.session_id;state.messages=messages.value.messages.slice(-200);
  }
  const model=[...state.events].reverse().find(e=>e.model)?.model;if(model)text('model-name',model);
  updateOrchestrator();updateMetrics();renderInspector();updateGrid();renderEvents();
  if($('diagnostics').open)await loadDiagnostics();
 }finally{state.slowPolling=false;updateConnectivity();}
}
function updateConnectivity(){
 const age=state.lastGood?(Date.now()-state.lastGood)/1000:Infinity;
 const coreError=['/simulation/status','/robots','/tasks','/warehouse/grid'].some(k=>state.errors.has(k));
 const stale=age>3;
 text('connection-status',!state.lastGood?'API CONNECTING':coreError?'API RECONNECTING':stale?`STALE ${age.toFixed(1)}s`:'API CONNECTED');
 $('connection-status').style.color=coreError||stale?'var(--charging)':'var(--healthy)';
 if(coreError)text('connection-status',state.lastGood?'API RECONNECTING':'API ERROR');
 const slowAge=state.lastSlow?(Date.now()-state.lastSlow)/1000:Infinity;
 text('data-freshness',`STATE ${Number.isFinite(age)?age.toFixed(1)+'s ago':'PENDING'} / EVENTS ${Number.isFinite(slowAge)?slowAge.toFixed(1)+'s ago':'PENDING'}${state.errors.size?' / API ERROR':''}`);
 // Stale telemetry must never silently enable a control or an old plan approval.
 updateControls();
 if(!state.overridePending){const blocked=coreError||stale||slowAge>4||state.errors.has('/orchestrator/state');$('hitl-approve').disabled=blocked;$('hitl-reject').disabled=blocked;}
}
function updateControls(){
 const s=state.simStatus,disabled=state.controlPending||state.overridePending||!s||Date.now()-state.lastGood>3000||['/simulation/status','/robots','/tasks','/warehouse/grid'].some(k=>state.errors.has(k));
 for(const name of ['start','pause','step','reset'])$('control-'+name).disabled=disabled;
 if(s){$('control-start').disabled=disabled||s.running||s.simulation_complete;$('control-pause').disabled=disabled||!s.running;$('control-step').disabled=disabled||s.running||s.simulation_complete;}
 $('inject-crisis').disabled=disabled||Boolean(s?.simulation_complete);
}
function updateHeader(){
 const s=state.simStatus;if(!s)return;
 const failed=!s.running&&state.events.some(e=>e.event_type==='SIMULATION_FAILED');
 text('header-sim-status',s.simulation_complete?'COMPLETE':failed?'ERROR':s.running?'RUNNING':'PAUSED');
 $('header-sim-status').style.color=s.simulation_complete?'var(--healthy)':failed?'var(--danger)':s.running?'var(--activity)':'var(--secondary)';
 text('header-step',s.current_step.toLocaleString());text('run-id',s.run_id.slice(0,8));$('run-id').title=s.run_id;text('seed',s.seed);
 $('completion-banner').hidden=!s.simulation_complete;
 text('completion-detail',`${s.total_tasks-s.unfinished_tasks} / ${s.total_tasks} tasks delivered | Step ${s.current_step}`);
 updateControls();
}
function isHeld(r){return r.orchestration_held||r.hold_steps_remaining>0||r.yield_to_robot_id!=null;}
function atBay(r){return r.status==='CHARGING'&&state.grid?.grid[r.position.y]?.[r.position.x]==='C'&&r.path.length<=1;}
function tone(id,value){const el=$(id);if(el)el.dataset.tone=value;}
function eventTone(type) {
 if(/FAIL|ERROR|INVALID|CRISIS_CREATED/.test(type))return 'danger';
 if(/RESOLVED|RECOVERED|SUCCESS|ACTION_OK|VALIDATOR_PASS|ALL_TASKS_COMPLETED/.test(type))return 'success';
 if(/BLOCKED|DEADLOCK|CHARG|BATTERY|FALLBACK|WAIT|HITL_REQUEST|REGENERAT/.test(type))return 'warning';
 return category(type)==='SYSTEM'?'quiet':'focus';
}
function updateMetrics(){
 const s=state.simStatus;if(!s)return;
 const charging=state.robots.filter(r=>r.status==='CHARGING');
 const blocked=state.agentStatus.filter(a=>a.beliefs?.path_blocked&&state.robots.some(r=>r.id===a.robot_id&&!isHeld(r)&&['MOVING','DELIVERING'].includes(r.status))).length;
 const done=s.total_tasks-s.unfinished_tasks;
 text('kpi-tasks',`${done} / ${s.total_tasks}`);text('kpi-remaining',`${s.unfinished_tasks} remaining`);$('task-progress').max=s.total_tasks||1;$('task-progress').value=done;
 text('kpi-moving',state.robots.filter(r=>['MOVING','DELIVERING'].includes(r.status)&&!isHeld(r)).length);
 text('kpi-charging',charging.length);text('charge-detail',`${charging.filter(atBay).length} at bay / ${charging.filter(r=>!atBay(r)).length} en route`);
 text('kpi-idle',state.robots.filter(r=>r.status==='IDLE').length);text('kpi-blocked',state.agentStatus.length?blocked:'--');
 const o=state.orchestrator;text('kpi-crisis',o?`${o.active?1:0} / ${o.queued_crises}`:'-- / --');text('crisis-tab-count',o?.active?1:0);
 text('crisis-detail',o?.waiting_for_human?'OPERATOR REVIEW':o?.active?o.active_node:'no active orchestration');
 text('kpi-llm',state.lastSlow?`${state.events.filter(e=>e.event_type==='LLM_REQUEST').length} / ${state.events.filter(e=>e.event_type==='ORCH_COMPLETE'&&e.fallback===true).length}`:'-- / --');
 text('kpi-battery',state.robots.length?`${Math.round(state.robots.reduce((s,r)=>s+r.battery,0)/state.robots.length)}%`:'--');text('fleet-size',`${state.robots.length} robots`);
 const energyStops=state.robots.filter(r=>r.status==='NEEDS_CHARGE').length;
 text('charge-label',energyStops?'CHARGE / STOP':'CHARGING');
 if(energyStops){text('kpi-charging',`${charging.length} / ${energyStops}`);text('charge-detail','charging / energy stopped');}
 tone('kpi-charging',energyStops?'danger':charging.length?'charging':'quiet');
 tone('kpi-blocked',blocked?'warning':'quiet');
 tone('kpi-crisis',o?.active?'danger':o?.queued_crises?'warning':'quiet');
 tone('kpi-llm',o?.active?(o.fallback_used?'warning':'orchestration'):'quiet');
 tone('kpi-tasks',s.simulation_complete?'success':'normal');
}
function svgNode(tag,attrs={}){const el=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))el.setAttribute(k,v);return el;}
function createGrid(){
 const {width,height,grid}=state.grid, floor=$('floor-layer'),chargers=$('charger-layer');
 floor.replaceChildren();chargers.replaceChildren();$('warehouse-map').setAttribute('viewBox',`-12 -12 ${width*20+24} ${height*20+24}`);
 for(let y=0;y<height;y++)for(let x=0;x<width;x++){
  floor.append(svgNode('rect',{x:x*20,y:y*20,width:20,height:20,class:`floor-cell ${grid[y][x]==='S'?'shelf':grid[y][x]==='X'?'wall':''}`}));
  if(grid[y][x]==='C'){
   chargers.append(svgNode('rect',{x:x*20+1,y:y*20+1,width:18,height:18,class:'charger-cell'}));
   const label=svgNode('text',{x:x*20+10,y:y*20+14,class:'charger-symbol'});label.textContent='C';chargers.append(label);
  }
 }
 text('grid-size',`${width} x ${height} / GRID (x, y)`);fitMap();
}
function fitMap(){
 if(!state.grid)return;const viewport=$('map-viewport'),svg=$('warehouse-map');
 const w=state.grid.width*20+24,h=state.grid.height*20+24;
 const mapWidth=Math.max(100,viewport.clientWidth-28)*state.zoom;
 const mapHeight=Math.max(60,viewport.clientHeight-28)*state.zoom;
 svg.setAttribute('preserveAspectRatio','none');
 svg.style.width=`${mapWidth}px`;svg.style.height=`${mapHeight}px`;
 // Keep labels inside their logical cell even when the tape leaves a shallow map.
 // Zoom and the inspector provide detail when Fit must compress the fleet.
 svg.style.setProperty('--marker-font',`${Math.min(16,Math.max(11,10*h/mapHeight))}px`);
 text('map-zoom',`${Math.round(state.zoom*100)}%`);
}
function selectRobot(id){state.selectedRobotId=id;selectTab('robot');renderInspector();updateGrid();}
function updateGrid(){
 if(!state.grid)return;const layer=$('robot-layer'),seen=new Set(),affected=new Set(state.orchestrator?.active?state.orchestrator.affected_robots:[]);
 for(const r of state.robots){
  const blocked=!isHeld(r)&&['MOVING','DELIVERING'].includes(r.status)&&state.agentStatus.some(a=>a.robot_id===r.id&&a.beliefs?.path_blocked);
  seen.add(r.id);let el=state.robotNodes.get(r.id);
  if(!el){el=svgNode('g',{role:'button',tabindex:'0','data-robot-id':r.id});el.append(svgNode('rect',{x:1,y:1,width:18,height:18,rx:2}),svgNode('text',{x:10,y:10,textLength:12,lengthAdjust:'spacingAndGlyphs'}),svgNode('title'));
   el.addEventListener('click',()=>selectRobot(r.id));el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectRobot(r.id);}});layer.append(el);state.robotNodes.set(r.id,el);}
  el.setAttribute('transform',`translate(${r.position.x*20},${r.position.y*20})`);
  el.setAttribute('class',`robot ${r.status.toLowerCase()}${atBay(r)?' at-bay':''}${isHeld(r)?' held':''}${blocked?' blocked':''}${r.status==='NEEDS_CHARGE'?' danger':''}${affected.has(r.id)?' affected':''}${r.id===state.selectedRobotId?' selected':''}`);
  el.setAttribute('aria-label',`Robot ${r.id}, ${r.status}, battery ${Math.round(r.battery)} percent`);
  el.children[1].setAttribute('textLength',String(r.id).length>1?12:7);el.children[1].textContent=r.id;el.children[2].textContent=`R${r.id} | ${r.status} | ${Math.round(r.battery)}% | ${coord(r.position)}`;
 }
 for(const [id,el]of state.robotNodes)if(!seen.has(id)){el.remove();state.robotNodes.delete(id);}
 const selected=state.robots.find(r=>r.id===state.selectedRobotId),path=$('path-layer');
 const points=selected?.path||[];let pathMarkup='';
 if(selected&&points.length)pathMarkup=`<polyline class="selected-route${selected.status==='CHARGING'?' charging-route':''}" points="${[[selected.position.x,selected.position.y],...points].map(p=>`${p[0]*20+10},${p[1]*20+10}`).join(' ')}"/>`;
 const task=state.tasks.find(t=>t.id===selected?.current_task);
 if(task)for(const [symbol,x,y]of [['P',task.pickup_x,task.pickup_y],['D',task.delivery_x,task.delivery_y]])pathMarkup+=`<circle class="endpoint" cx="${x*20+10}" cy="${y*20+10}" r="9"/><text class="endpoint-label" x="${x*20+10}" y="${y*20+10}">${symbol}</text>`;
 html(path,pathMarkup);
 // Crisis locations come from the current/last incident and retained structural events.
 const coords=new Map();for(const e of state.events)if(e.event_type==='CRISIS_CREATED')for(const p of e.crisis_location||[])coords.set(p.join(','),p);
 for(const p of state.orchestrator?.crisis_location||[])coords.set(p.join(','),p);
 html($('crisis-layer'),[...coords.values()].filter(p=>state.grid.grid[p[1]]?.[p[0]]==='S').map(p=>`<rect class="crisis-cell" x="${p[0]*20+1}" y="${p[1]*20+1}" width="18" height="18"/>`).join(''));
 for(const [name,id]of Object.entries({robots:'robot-layer',chargers:'charger-layer',paths:'path-layer',crisis:'crisis-layer'}))$(id).style.display=state.layers[name]?'':'none';
 text('map-selection',selected?`R${selected.id} / ${coord(selected.position)} / ${selected.status}`:'Select a robot to trace its route');
 const select=$('robot-select'),options='<option value="">Select robot</option>'+state.robots.map(r=>`<option value="${r.id}">Robot ${r.id}</option>`).join('');html(select,options);select.value=state.selectedRobotId??'';
}
function renderInspector(){
 const r=state.robots.find(r=>r.id===state.selectedRobotId);
 if(!r){html(UI.inspectorContent,'<div class="empty-state"><strong>NO ROBOT SELECTED</strong><p>Select a numbered marker on the warehouse floor.</p></div>');return;}
 const a=state.agentStatus.find(a=>a.robot_id===r.id),task=state.tasks.find(t=>t.id===r.current_task);
 const destination=r.path.at(-1),held=r.orchestration_held?`Active crisis ${state.orchestrator?.crisis_id||''}`:r.hold_steps_remaining?`HOLD / ${r.hold_steps_remaining} steps`:r.yield_to_robot_id!=null?`YIELD to R${r.yield_to_robot_id}`:a?.beliefs?.path_blocked?'Next cell blocked':'None reported';
 const recent=eventRows().filter(e=>e.robot===r.id).slice(0,5);
 const beliefsOpen=UI.inspectorContent.querySelector('details')?.open;
 html(UI.inspectorContent,`<h2>ROBOT ${r.id} <span class="muted">/ ${escapeHtml(r.status)}</span></h2>${row('Battery',Math.round(r.battery)+'%')}<div class="battery-meter"><span style="width:${Math.max(0,Math.min(100,r.battery))}%"></span></div>${row('Position',coord(r.position))}${row('Task',r.current_task==null?'None':`T${r.current_task}`)}${row('Route destination',coord(destination))}${row('Goal',a?.goal||'Pending agent state')}${row('Charging',r.status==='CHARGING'?(atBay(r)?'At charging bay':`Travelling to ${coord(destination)}`):'Not charging')}${row('Hold / blockage',held)}${task?row('Pickup / delivery',`${coord([task.pickup_x,task.pickup_y])} / ${coord([task.delivery_x,task.delivery_y])}`):''}<h3>RECENT TRACE</h3>${recent.map(e=>`<div class="trace-line">${escapeHtml(e.type)}<br><span class="muted">${escapeHtml(e.detail)}</span></div>`).join('')||'<p class="muted">No recent events for this robot in the retained window.</p>'}<details><summary>Agent beliefs &amp; messages</summary>${Object.entries(a?.beliefs||{}).map(([k,v])=>row(k,Array.isArray(v)?v.join(', '):v)).join('')}${row('Pending messages',a?.pending_messages)}${row('Memory events',a?.memory_size)}</details>`);
 if(beliefsOpen)UI.inspectorContent.querySelector('details').open=true;
}
function category(type){
 if(/DEADLOCK|BLOCKED_PATH/.test(type))return 'DEADLOCK';
 if(/CHARG|BATTERY/.test(type))return 'CHARGING';
 if(/LLM/.test(type))return 'LLM';
 if(/CFP|PROPOSAL|TASK_|AUCTION/.test(type)&&type!=='ALL_TASKS_COMPLETED')return 'CNP';
 if(/ORCH|CRISIS|PLAN|VALIDAT|ACTION|HITL|FALLBACK|REGENERAT|DEDUP|STALE_DROPPED|BACKPRESSURE/.test(type))return 'ORCH';return 'SYSTEM';
}
function eventRows(){
 const rows=state.events.map(e=>({id:e.event_id,time:e.timestamp,step:e.step,type:e.event_type,robot:e.robot_id,detail:Object.entries(e).filter(([k,v])=>!['run_id','event_id','timestamp','step','event_type'].includes(k)&&v!=null).map(([k,v])=>`${k}=${typeof v==='object'?JSON.stringify(v):v}`).join(' ')}));
 for(const m of state.messages)rows.push({id:`message:${m.id}`,time:m.timestamp,step:null,type:m.type,robot:m.payload?.robot_id??(/^robot_/.test(m.sender)?Number(m.sender.slice(6)):null),detail:`${m.sender} > ${m.recipient} ${JSON.stringify(m.payload)}`});
 return rows.sort((a,b)=>(b.time||0)-(a.time||0)).slice(0,400);
}
function renderEvents(){
 const rows=eventRows();text('event-count',`${state.events.length} structured / ${state.messages.length} messages`);
 for(const [key,id,button]of [['tape','event-list','tape-follow'],['context','context-event-list','context-follow']]){
  const view=state[key];text(button,view.follow?'LIVE':'PAUSED-FOLLOW');if(!view.follow)continue;
  const filtered=rows.filter(e=>view.filter==='ALL'||category(e.type)===view.filter).slice(0,100);
  html($(id),filtered.map(e=>`<div class="event-row" data-category="${category(e.type)}" data-tone="${eventTone(e.type)}" data-event-type="${escapeHtml(e.type)}"><time>${e.step!=null?'['+e.step+']':new Date((e.time||0)*1000).toLocaleTimeString('en-GB')}</time><b>${escapeHtml(e.type)}</b><span title="${escapeHtml(e.detail)}">${escapeHtml(e.detail)}</span></div>`).join('')||'<div class="event-empty">No events in this category yet.</div>');
 }
}
function selectTab(tab){state.tab=tab;for(const name of ['crisis','robot','events']){$('context-'+name).hidden=name!==tab;$('tab-'+name).setAttribute('aria-selected',String(name===tab));$('tab-'+name).tabIndex=name===tab?0:-1;}if(tab==='robot')renderInspector();if(tab==='events')renderEvents();}
function updateUI(){updateHeader();updateMetrics();updateGrid();renderInspector();}
function updateOrchestrator(){
 if(state.overridePending)return;const o=state.orchestrator;
 if(!o){text('orchestrator-status-badge','SYNCING');html(UI.orchestratorContent,'<div class="empty-state"><strong>AWAITING CRISIS STATE</strong><p>Fetching orchestration for the current run.</p></div>');UI.hitlOverlay.style.display='none';return;}
 const active=o.active||o.waiting_for_human;
 const badge=o.waiting_for_human?'AWAITING HUMAN':o.active?(o.fallback_used?'FALLBACK ACTIVE':'ACTIVE'):'INACTIVE';
 text('orchestrator-status-badge',badge);
 const nodes=['diagnose','generate_plan','validate','execute'],node=o.active_node;
 const mapped=['regenerating','rejected'].includes(node)?'generate_plan':['waiting_for_human'].includes(node)?'validate':['executing','human_approved'].includes(node)?'execute':node;
 const progress=nodes.map((n,i)=>`<div class="orch-node ${active?(n===mapped?'active':i<nodes.indexOf(mapped)?'completed':''):''}">${['Diagnose','Plan','Validate','Execute'][i]}</div>`).join('');
 const issues=o.validation_issues||[],errors=issues.filter(i=>i.level==='ERROR').length,warnings=issues.filter(i=>i.level==='WARNING').length;
 const plan=(o.proposed_plan?.actions||[]).map(a=>`<div class="plan-action"><strong>R${escapeHtml(a.robot_id)} / ${escapeHtml(a.action)}</strong>${escapeHtml(a.waypoint?' via '+coord(a.waypoint):a.hold_steps?' / '+a.hold_steps+' steps':a.task_id!=null?' / T'+a.task_id:a.yield_to_robot_id!=null?' / yield to R'+a.yield_to_robot_id:'')}<p>${escapeHtml(a.reason)}</p></div>`).join('');
 const status=o.validation_status==='INVALID'?'PLAN REJECTED BY VALIDATOR. Regenerating...':o.validation_status||'PENDING';
 const details=o.crisis_id?`${!active?'<h3>LAST INCIDENT / COMPLETED</h3>':''}<div class="orch-node-progress">${progress}</div>${row('Crisis ID',o.crisis_id)}${row('Type',o.crisis_kind)}${row('Location',(o.crisis_location||[]).map(coord).join(' '))}${row('Affected robots',(o.affected_robots||[]).map(id=>'R'+id).join(', ')||'None')}${row('Graph node',node||'Idle')}${row('Plan ID',o.plan_id)}${row('Validation Score',o.validation_score==null?'Pending':`${Math.round(o.validation_score*100)}%`)}${row('Validation',status)}${row('Issues',`${errors} errors / ${warnings} warnings`)}${row('Regenerations',o.regeneration_count||0)}${row('Queued crises',o.queued_crises||0)}${o.fallback_used?`<div class="issue"><strong>FALLBACK ACTIVE${!active?' DURING LAST INCIDENT':''}</strong><br>${escapeHtml(o.fallback_reason)}</div>`:''}${issues.map(i=>`<div class="issue">${escapeHtml(i.level)} / ${escapeHtml(i.code)}: ${escapeHtml(i.message)}</div>`).join('')}${plan?'<h3>STRUCTURED ACTIONS</h3>'+plan:''}${o.error?`<p class="issue">${escapeHtml(o.error)}</p>`:''}`:'';
 html(UI.orchestratorContent,`${!active?'<div class="empty-state"><strong>NO ACTIVE CRISIS</strong><p>Fleet safety and routine recovery are handled by the deterministic layer.</p></div>':''}${details}`);
 const key=`${o.crisis_id}:${node}:${o.waiting_for_human}`;
 if(state.orchestratorLogKey!==key){console.log(`[UI][CRISIS] id=${o.crisis_id} state=${node}`);state.orchestratorLogKey=key;}
 // Invalid plans never expose approval, even if a malformed payload claims waiting.
 const review=o.waiting_for_human&&o.validation_status==='VALID'&&!errors;
 UI.hitlOverlay.style.display=review?'flex':'none';
 if(review&&state.reviewPlan!==o.plan_id){state.reviewPlan=o.plan_id;text('hitl-feedback','');selectTab('crisis');}
 if(UI.hitlDetails)html(UI.hitlDetails,plan);
}
async function control(action){
 if(state.controlPending||state.overridePending)return;if(action==='reset'&&!window.confirm('Reset this run? Tasks, history and active orchestration will be cleared.'))return;
 state.controlPending=true;state.epoch++;state.overrideEpoch++;updateControls();console.log(`[UI][CONTROL] action=${action.toUpperCase()}`);
 try{await json('/simulation/'+action,{method:'POST'});$('notice').hidden=true;if(action==='reset'){state.gridVersion=null;}}
 catch(e){text('notice',`${action.toUpperCase()} could not be confirmed: ${e.message}. Refreshing current state.`);$('notice').hidden=false;}
 finally{state.controlPending=false;await pollData();await pollSlow();}
}
async function injectCrisis(){
 if(!window.confirm('Collapse eligible aisle cells? This changes the warehouse for the current run.'))return;
 $('inject-crisis').disabled=true;
 try{const r=await json('/simulation/crisis',{method:'POST'});text('crisis-feedback',`Injected ${r.crisis_id}`);await pollData();await pollSlow();}
 catch(e){text('crisis-feedback',`Injection failed: ${e.message}`);}finally{updateControls();}
}
async function loadDiagnostics(){
 const run=state.simStatus?.run_id,epoch=state.epoch;
 const results=await Promise.allSettled(['/auction/logs','/negotiation/logs'].map(read));if(epoch!==state.epoch||run!==state.simStatus?.run_id)return;
 if(results[0].status==='fulfilled')state.auctions=results[0].value;
 if(results[1].status==='fulfilled')state.negotiations=results[1].value;
 html(UI.auctionContent,[...state.auctions].reverse().slice(0,10).map(l=>`<div class="log-card"><div class="log-title">Task ${escapeHtml(l.task_id)} / Winner R${escapeHtml(l.winner)}</div><p class="log-detail">${(l.bids||[]).map(b=>`R${escapeHtml(b.robot_id)} (${Number(b.bid).toFixed(1)})`).join(', ')}</p></div>`).join('')||'<p class="muted">No recent auctions</p>');
 html(UI.negotiationContent,[...state.negotiations].reverse().slice(0,20).map(l=>`<div class="log-card"><div class="log-title">${escapeHtml(l.event)}</div><p>${escapeHtml(l.reasoning)}</p><p class="log-detail">${escapeHtml(l.decision)}</p></div>`).join('')||'<p class="muted">No negotiations logged</p>');updateMessages();
}

function updateMessages(showLatest = false) {
    const container = UI.messageBusContent;
    const latestId = state.messages.at(-1)?.id || 0;
    const button = document.getElementById('message-feed-latest');
    const status = document.getElementById('message-feed-status');

    // A reading snapshot survives even when the whole server history rolls over.
    // Only the first nonempty batch and an explicit click may change these cards.
    if (showLatest || (state.displayedMessageId === null && state.messages.length)) {
        const recent = state.messages.slice(-100);
        const keep = new Set(recent.map(msg => String(msg.id)));
        for (const card of [...container.children]) {
            if (!keep.has(card.dataset.messageId)) card.remove();
        }
        for (const msg of recent) {
            if (state.renderedMessageIds.has(msg.id)) continue;
            const card = document.createElement('div');
            card.className = `message-card msg-${msg.type}`;
            card.dataset.messageId = String(msg.id);
            const header = document.createElement('div');
            header.className = 'msg-header';
            header.textContent = `${msg.type} | ID: ${msg.id}`;
            const body = document.createElement('div');
            body.className = 'msg-body';
            body.textContent = `From ${msg.sender} to ${msg.recipient}: ${JSON.stringify(msg.payload)}`;
            card.append(header, body);
            container.prepend(card);
        }
        state.renderedMessageIds = new Set(recent.map(msg => msg.id));
        state.displayedMessageId = latestId;
        container.scrollTop = 0;
    }

    const pending = Math.max(0, latestId - (state.displayedMessageId || 0));
    const label = pending ? `Show latest (${pending} new)` : 'Show latest';
    if (button.textContent !== label) button.textContent = label;
    button.disabled = pending === 0;
    const description = state.displayedMessageId === null
        ? 'Waiting for messages. New messages are collected live.'
        : 'View held for reading. Show latest to load the most recent 100 messages.';
    if (status.textContent !== description) status.textContent = description;
}

function showLatestMessages() {
    updateMessages(true);
}


async function orchestratorOverride(approved) {
 const plan=state.orchestrator;
 if(state.overridePending||!plan?.waiting_for_human||plan.validation_status!=='VALID'||plan.validation_issues?.some(i=>i.level==='ERROR'))return;
 const token=++state.overrideEpoch,epoch=state.epoch;
 state.overridePending=true;updateControls();
 console.log(`[UI][HITL] decision=${approved?'APPROVE':'REJECT'} plan=${plan.plan_id}`);
 const approveBtn=$('hitl-approve'),rejectBtn=$('hitl-reject'),feedback=$('hitl-feedback');
 approveBtn.disabled=rejectBtn.disabled=true;
 feedback.textContent=approved?'Submitting approval...':'Requesting a new plan...';
 try{
  const res=await apiFetch('/orchestrator/override',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved,plan_id:plan.plan_id})});
  const data=await res.json();
  if(token!==state.overrideEpoch||epoch!==state.epoch)return;
  if(!data.success)throw new Error(data.message||'Decision was not accepted.');
  state.orchestrator={...plan,waiting_for_human:false,active_node:approved?'executing':'regenerating'};
  UI.hitlOverlay.style.display='none';feedback.textContent='';
 }catch(error){
  if(token!==state.overrideEpoch||epoch!==state.epoch)return;
  feedback.textContent=`Decision could not be confirmed: ${error.message}. Check the current plan before retrying.`;
  UI.hitlOverlay.style.display='flex';
 }finally{
  if(token===state.overrideEpoch){state.overridePending=false;state.overrideEpoch++;updateConnectivity();}
 }
}

async function apiFetch(url, options = {}) {
    const response = await fetch(url, {...options, signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return response;
}


// Pure bounds/storage helpers keep split-pane behavior reusable and testable.
const LAYOUT_KEY = 'warehouse-swarm-operation-layout';
function layoutPreferences(raw) {
    try {
        const data = JSON.parse(raw);
        if (!data || typeof data !== 'object' || Array.isArray(data)) return {};
        return Object.fromEntries(['rightPanelWidth','eventTapeHeight']
            .filter(key => Number.isFinite(data[key]) && data[key] > 0 && data[key] < 10000)
            .map(key => [key, data[key]]));
    } catch { return {}; }
}
function layoutBounds(width, height, shortScreen = false) {
    const usableWidth = Math.max(0, width - 6);
    const usableHeight = Math.max(0, height - 6);
    return {
        rightPanelWidth: {min:320, max:Math.max(320, usableWidth * .5), default:usableWidth * .32},
        eventTapeHeight: {min:96, max:Math.max(96, Math.min(usableHeight * .45, usableHeight - 360)),
            default:shortScreen ? 100 : width >= 1700 ? 166 : 142}
    };
}
function clampPane(value, bounds) {
    return Math.round(Math.min(bounds.max, Math.max(bounds.min,
        Number.isFinite(value) ? value : bounds.default)));
}
// Native separator behavior is independent of page content and can serve future panes.
function bindSplitter(handle, {axis, getValue, setValue, reset, commit, enabled}) {
    let drag = null, frame = 0, next = null;
    const flush = () => {
        frame = 0;
        if (next !== null) { setValue(next); next = null; }
    };
    const finish = () => {
        if (!drag) return;
        if (frame) cancelAnimationFrame(frame);
        flush();
        const pointer = drag.pointer;
        drag = null;
        handle.classList.remove('dragging');
        document.body.classList.remove('resizing');
        document.body.style.removeProperty('--resize-cursor');
        if (handle.hasPointerCapture(pointer)) handle.releasePointerCapture(pointer);
        commit();
    };
    handle.addEventListener('pointerdown', event => {
        if (!enabled() || event.button !== 0 || drag) return;
        event.preventDefault();
        handle.focus();
        drag = {pointer:event.pointerId, start:axis === 'x' ? event.clientX : event.clientY, value:getValue()};
        handle.setPointerCapture(event.pointerId);
        handle.classList.add('dragging');
        document.body.classList.add('resizing');
        document.body.style.setProperty('--resize-cursor', axis === 'x' ? 'col-resize' : 'row-resize');
    });
    handle.addEventListener('pointermove', event => {
        if (!drag || event.pointerId !== drag.pointer) return;
        // Both trailing panes grow when their boundary moves toward the start.
        next = drag.value + drag.start - (axis === 'x' ? event.clientX : event.clientY);
        if (!frame) frame = requestAnimationFrame(flush);
    });
    for (const name of ['pointerup','pointercancel','lostpointercapture']) handle.addEventListener(name, finish);
    window.addEventListener('blur', finish);
    handle.addEventListener('dblclick', () => { if (enabled()) { reset(); commit(); } });
    handle.addEventListener('keydown', event => {
        if (!enabled()) return;
        const decrease = axis === 'x' ? 'ArrowRight' : 'ArrowDown';
        const increase = axis === 'x' ? 'ArrowLeft' : 'ArrowUp';
        if (event.key === 'Home') { event.preventDefault(); reset(); commit(); }
        if (event.key === decrease || event.key === increase) {
            event.preventDefault();
            setValue(getValue() + (event.key === increase ? 1 : -1) * (event.shiftKey ? 40 : 10));
            commit();
        }
    });
    return finish;
}
function setupWorkspaceLayout() {
    const workspace = $('operations-workspace');
    const desktop = window.matchMedia('(min-width:1051px) and (min-height:650px)');
    let preferences = {}, bounds = {}, actual = {}, frame = 0;
    try { preferences = layoutPreferences(localStorage.getItem(LAYOUT_KEY)); } catch { /* Private/blocked storage: session-only resizing. */ }
    const handles = {rightPanelWidth:$('context-divider'), eventTapeHeight:$('events-divider')};
    const properties = {rightPanelWidth:'--right-panel-width', eventTapeHeight:'--event-tape-height'};
    function save() {
        try {
            if (Object.keys(preferences).length) localStorage.setItem(LAYOUT_KEY, JSON.stringify(preferences));
            else localStorage.removeItem(LAYOUT_KEY);
        } catch { /* Storage is optional; never interrupt operation. */ }
    }
    function apply() {
        frame = 0;
        workspace.classList.toggle('split-enabled', desktop.matches);
        if (!desktop.matches) return;
        bounds = layoutBounds(workspace.clientWidth, workspace.clientHeight, window.innerHeight <= 800);
        for (const key of Object.keys(handles)) {
            actual[key] = clampPane(preferences[key], bounds[key]);
            workspace.style.setProperty(properties[key], `${actual[key]}px`);
            handles[key].setAttribute('aria-valuemin', Math.round(bounds[key].min));
            handles[key].setAttribute('aria-valuemax', Math.floor(bounds[key].max));
            handles[key].setAttribute('aria-valuenow', actual[key]);
            handles[key].setAttribute('aria-valuetext', `${actual[key]} pixels`);
        }
    }
    const queue = () => { if (!frame) frame = requestAnimationFrame(apply); };
    const finishers = Object.entries(handles).map(([key, handle]) => bindSplitter(handle, {
        axis:key === 'rightPanelWidth' ? 'x' : 'y', enabled:() => desktop.matches,
        getValue:() => actual[key],
        setValue:value => { preferences[key] = clampPane(value, bounds[key]); apply(); },
        reset:() => { delete preferences[key]; apply(); }, commit:save
    }));
    $('reset-layout').addEventListener('click', () => {
        finishers.forEach(finish => finish()); preferences = {}; save(); apply();
    });
    desktop.addEventListener('change', () => { finishers.forEach(finish => finish()); queue(); });
    window.addEventListener('resize', queue);
    new ResizeObserver(queue).observe(workspace);
    apply();
}

async function run(){
 console.log('[UI][BOOT] Live Operations');
 setupWorkspaceLayout();
 document.querySelectorAll('[data-control]').forEach(b=>b.addEventListener('click',()=>control(b.dataset.control)));
 document.querySelectorAll('[data-tab]').forEach(b=>{b.addEventListener('click',()=>selectTab(b.dataset.tab));b.addEventListener('keydown',e=>{const names=['crisis','robot','events'];if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const i=names.indexOf(b.dataset.tab),next=e.key==='Home'?0:e.key==='End'?2:(i+(e.key==='ArrowRight'?1:2))%3;selectTab(names[next]);$('tab-'+names[next]).focus();}});});
 document.querySelectorAll('[data-layer]').forEach(c=>c.addEventListener('change',()=>{state.layers[c.dataset.layer]=c.checked;updateGrid();}));
 $('map-fit').addEventListener('click',()=>{state.zoom=1;fitMap();$('map-viewport').scrollTo(0,0);});
 for(const [id,delta]of [['map-plus',.25],['map-minus',-.25]])$(id).addEventListener('click',()=>{state.zoom=Math.min(3,Math.max(1,state.zoom+delta));fitMap();});
 new ResizeObserver(fitMap).observe($('map-viewport'));
 $('robot-select').addEventListener('change',e=>selectRobot(e.target.value===''?null:Number(e.target.value)));
 document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{state.tape.filter=b.dataset.filter;state.tape.follow=true;$('event-list').scrollTop=0;document.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));renderEvents();}));
 $('context-filter').addEventListener('change',e=>{state.context.filter=e.target.value;state.context.follow=true;$('context-event-list').scrollTop=0;renderEvents();});
 for(const [key,id,button]of [['tape','event-list','tape-follow'],['context','context-event-list','context-follow']]){
  $(id).addEventListener('scroll',()=>{if($(id).scrollTop>8&&state[key].follow){state[key].follow=false;renderEvents();}});
  $(button).addEventListener('click',()=>{state[key].follow=!state[key].follow;if(state[key].follow)$(id).scrollTop=0;renderEvents();});
 }
 $('diagnostics-open').addEventListener('click',()=>{$('diagnostics').showModal();loadDiagnostics();});$('diagnostics-close').addEventListener('click',()=>$('diagnostics').close());
 $('message-feed-latest').addEventListener('click',showLatestMessages);
 $('hitl-approve').addEventListener('click',()=>orchestratorOverride(true));$('hitl-reject').addEventListener('click',()=>orchestratorOverride(false));$('inject-crisis').addEventListener('click',injectCrisis);
 updateControls();
 async function fast(){await pollData();setTimeout(fast,400);}
 async function slow(){await pollSlow();setTimeout(slow,1000);}
 await pollData();slow();fast();setInterval(updateConnectivity,500);
}
document.addEventListener('DOMContentLoaded',run);
