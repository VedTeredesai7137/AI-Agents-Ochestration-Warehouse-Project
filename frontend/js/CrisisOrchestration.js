'use strict';

// A read model for the desk, not a second orchestrator. Events prove transitions;
// snapshots supply plan details only while the backend still retains them.
const desk = {
    status:null, orchestrator:null, grid:null, robots:[], tasks:[], events:[], records:new Map(),
    selected:null, robot:null, fullFloor:false, followActive:true, followTrace:true, traceKey:null,
    lastGood:0, failure:null, busy:false, polling:false, epoch:0, gridKey:null
};
const $ = id => document.getElementById(id);
const list = value => Array.isArray(value) ? value : [];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const shortId = value => value ? String(value).split(':').pop() : '—';
const number = value => typeof value === 'number' && Number.isFinite(value);
const score = value => number(value) ? value.toFixed(2) : '—';
const duration = value => number(value) ? `${(value/1000).toFixed(2)}s` : '—';
const clock = value => number(value) ? new Date(value*1000).toLocaleTimeString([], {hour12:false}) : '—';
const point = value => Array.isArray(value) && value.length === 2 && value.every(number);
const cells = value => list(value).filter(point);
const rendered = new Map();
const empty = (title, message) => `<div class="empty-state"><strong>${esc(title)}</strong><p>${esc(message)}</p></div>`;
function text(id, value) { $(id).textContent = value ?? '—'; }
function html(id, value) {
    // Compare input, not live DOM: native details/open and scroll/focus are user state.
    if (rendered.get(id) !== value) { $(id).innerHTML = value; rendered.set(id,value); }
}
function tone(id, value) { $(id).dataset.tone = value; }
function pairs(values) { return `<dl>${values.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v ?? '—')}</dd>`).join('')}</dl>`; }
function last(rows, type) { return rows.filter(e=>e.event_type === type).at(-1); }
function eventTone(type) {
    if (/FAIL|INVALID/.test(type)) return 'error';
    if (/FALLBACK/.test(type)) return 'fallback';
    if (/REGENERAT|REJECT|HITL_REQUEST|QUEUED/.test(type)) return 'warning';
    if (/PASS|ACTION_OK|RECOVERED|COMPLETE|APPROVED/.test(type)) return 'success';
    if (/LLM|ORCH|DIAGNOSE|PLAN_PARSED/.test(type)) return 'ai';
    if (/CRISIS_CREATED|DEADLOCK/.test(type)) return 'crisis';
    return 'quiet';
}
function validatePayload(path, data) {
    let ok = data && typeof data === 'object';
    if (path === '/simulation/status') ok &&= typeof data.run_id === 'string' && number(data.current_step) && typeof data.running === 'boolean' && typeof data.simulation_complete === 'boolean';
    if (path === '/orchestrator/state') ok &&= typeof data.run_id === 'string' && typeof data.active === 'boolean' && number(data.queued_crises) && (!data.proposed_plan || Array.isArray(data.proposed_plan.actions)) && (!data.validation_issues || Array.isArray(data.validation_issues));
    if (path.startsWith('/orchestrator/events')) ok &&= typeof data.run_id === 'string' && Array.isArray(data.events) && data.events.every(e=>e && typeof e.event_id === 'string' && typeof e.event_type === 'string');
    if (path === '/robots') ok = Array.isArray(data) && data.every(r=>r && number(r.id) && number(r.position?.x) && number(r.position?.y));
    if (path === '/tasks') ok = Array.isArray(data) && data.every(t=>t && number(t.id));
    if (path === '/warehouse/grid') ok &&= Number.isInteger(data.width) && data.width>0 && Number.isInteger(data.height) && data.height>0 && Array.isArray(data.grid) && data.grid.length === data.height && data.grid.every(row=>Array.isArray(row) && row.length === data.width);
    if (!ok) throw new Error(`Malformed response: ${path}`);
    return data;
}
async function api(path, body) {
    const response = await fetch(path, {cache:'no-store', signal:AbortSignal.timeout(8000),
        ...(body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})});
    if (!response.ok) {
        let detail;
        try { detail = (await response.json()).detail; } catch (_) { /* HTTP status remains useful. */ }
        throw new Error(`${path}: ${response.status}${typeof detail === 'string' ? ' · '+detail : ''}`);
    }
    const data = await response.json();
    return body === undefined ? validatePayload(path, data) : data;
}
function ingest(status, orchestrator, events) {
    if (desk.status && desk.status.run_id !== status.run_id) {
        desk.records.clear(); desk.events=[]; desk.selected=null; desk.robot=null;
        desk.traceKey=null; desk.followTrace=true; desk.followActive=true; desk.epoch++;
    }
    desk.status=status; desk.orchestrator=orchestrator;
    const merged=new Map(desk.events.map(e=>[e.event_id,e]));
    events.filter(e=>e.run_id === status.run_id).forEach(e=>merged.set(e.event_id,e));
    desk.events=[...merged.values()].sort((a,b)=>(a.timestamp-b.timestamp) || a.event_id.localeCompare(b.event_id)).slice(-2000);
    function record(id) {
        if (!desk.records.has(id)) desk.records.set(id,{id, state:null, events:[], seen:0});
        return desk.records.get(id);
    }
    desk.records.forEach(r=>{r.events=[];r.queued=false;r.active=false;});
    for (const e of desk.events) {
        if (!e.crisis_id) continue;
        const r=record(e.crisis_id); r.events.push(e); r.seen=Math.max(r.seen,e.timestamp || 0);
    }
    for (const id of list(orchestrator.queued_crisis_ids)) record(id).queued=true;
    if (orchestrator.crisis_id) {
        const r=record(orchestrator.crisis_id);
        // Detached snapshot is replaced, not merged: a retry must not inherit an old plan.
        r.state=structuredClone(orchestrator); r.active=orchestrator.active;
    }
    const ordered=[...desk.records.values()].sort((a,b)=>(b.active-a.active)||(b.queued-a.queued)||(b.seen-a.seen));
    // Protect selection and active/pending entries. Bound even a long-running browser tab.
    const keep=new Set(ordered.slice(0,39).map(r=>r.id));
    if (desk.selected) keep.add(desk.selected);
    desk.records.forEach((r,id)=>{if(!keep.has(id))desk.records.delete(id);});
    if (desk.followActive && orchestrator.active) desk.selected=orchestrator.crisis_id;
    if (!desk.selected || !desk.records.has(desk.selected)) desk.selected=ordered[0]?.id ?? null;
}
function recordView(r) {
    if (!r) return null;
    const events=r.events, created=last(events,'CRISIS_CREATED'), start=last(events,'ORCH_START');
    let s=r.state || {};
    const latestRequest=last(events,'LLM_REQUEST');
    // Backend plan IDs have increasing, zero-padded attempt suffixes within a crisis.
    const planId=[s.plan_id,latestRequest?.plan_id].filter(Boolean).sort().at(-1);
    if (s.plan_id && planId!==s.plan_id) {
        // A retry can finish between polls. Never attach an older snapshot to its events.
        s={...s,plan_id:planId,proposed_plan:null,validation_status:'PENDING',
            validation_score:null,validation_issues:[],validation_report:null,
            human_approved:null,approval_source:null,regeneration_count:undefined,
            error:null,error_code:null};
    }
    const complete=last(events,'ORCH_COMPLETE'), recovered=last(events,'CRISIS_RECOVERED');
    const fallback=last(events,'FALLBACK_ACTIVATED') || last(events,'FALLBACK_HELD');
    const dropped=last(events,'STALE_DROPPED');
    const usedFallback=Boolean(s.fallback_used || fallback || complete?.fallback);
    let status='HISTORY', tint='quiet';
    if (r.active) {status=s.waiting_for_human?'REVIEW':usedFallback?'FALLBACK':'ACTIVE';tint=s.waiting_for_human?'warning':usedFallback?'fallback':'crisis';}
    else if (r.queued) {status='QUEUED';tint='warning';}
    else if (dropped) {status='STALE DROPPED';}
    else if (complete || s.active_node==='complete') {status=usedFallback?'FALLBACK':'COMPLETE';tint=usedFallback?'fallback':'success';}
    else if (recovered) {status='RECOVERED';tint='success';}
    else if (usedFallback) {status='FALLBACK USED';tint='fallback';}
    const planEvents=events.filter(e=>!e.plan_id || e.plan_id === planId);
    return {...r, s, events, planEvents, planId, status, tint, usedFallback,
        kind:s.crisis_kind || start?.crisis_kind || created?.crisis_kind || (created?'STRUCTURAL_COLLAPSE':'TYPE NOT RETAINED'),
        affected:list(s.affected_robots ?? created?.affected ?? start?.affected),
        coords:cells(s.crisis_location ?? created?.crisis_location),
        step:created?.step ?? start?.step ?? events[0]?.step,
        complete, recovered, fallback, dropped,
        model:planEvents.filter(e=>e.model).at(-1)?.model,
        request:last(planEvents,'LLM_REQUEST'), response:planEvents.filter(e=>['LLM_SUCCESS','LLM_FAILURE'].includes(e.event_type)).at(-1),
        parsed:last(planEvents,'PLAN_PARSED'), validation:planEvents.filter(e=>['VALIDATOR_PASS','INVALID_PLAN'].includes(e.event_type)).at(-1)
    };
}
function selection() { return recordView(desk.records.get(desk.selected)); }
function canReview(v=selection()) {
    const o=desk.orchestrator;
    return Boolean(v && o && typeof o.plan_id==='string' && o.plan_id && v.id===o.crisis_id && v.planId===o.plan_id && o.active && o.waiting_for_human &&
        o.validation_status==='VALID' && list(o.proposed_plan?.actions).length && !list(o.validation_issues).some(i=>i?.level==='ERROR') &&
        o.run_id===desk.status?.run_id && !desk.busy && !desk.failure && Date.now()-desk.lastGood<4000);
}
function renderHeader() {
    const s=desk.status, o=desk.orchestrator;
    if (!s || !o) return;
    text('run-id',s.run_id);$('run-id').title=s.run_id;
    text('seed',s.seed);text('header-step',s.current_step);
    text('model-name',o.model || desk.events.filter(e=>e.model && e.event_type.startsWith('LLM_')).at(-1)?.model || 'Awaiting model event');
    text('provider-name',(o.llm_provider || 'configured LLM').toUpperCase());
    text('budget-summary',number(s.crisis_budget)?`BUDGET ${s.crises_submitted} / ${s.crisis_budget} · ${s.crises_completed} terminal · ${s.crises_remaining} remaining`:'Run budget not retained');
    tone('model-name','ai');text('simulation-state',s.simulation_complete?'COMPLETE':s.running?'RUNNING':'PAUSED');
    tone('simulation-state',s.simulation_complete?'success':'quiet');
    text('kpi-active',o.active ? shortId(o.crisis_id) : 'NONE');text('active-kind',o.active ? o.crisis_kind : 'system nominal');tone('metric-active',o.active?'crisis':'quiet');
    text('kpi-queue',`${o.queued_crises} / ${o.max_pending_crisis ?? '—'}`);tone('metric-queue',o.queued_crises?'warning':'quiet');
    text('kpi-affected',o.active?list(o.affected_robots).length:0);tone('metric-affected',o.active?'crisis':'quiet');
    text('kpi-node',o.active ? o.active_node : 'IDLE');tone('metric-node',o.active?'ai':'quiet');
    text('kpi-validation',o.active?score(o.validation_score):'—');text('validation-caption',o.active?o.validation_status:'no active plan');tone('metric-validation',o.active?(o.validation_status==='VALID'?'success':o.validation_status==='INVALID'?'error':'quiet'):'quiet');
    const response=desk.events.filter(e=>['LLM_SUCCESS','LLM_FAILURE'].includes(e.event_type)).at(-1);
    text('kpi-latency',duration(response?.latency_ms));tone('metric-latency',response?'ai':'quiet');
    text('kpi-review',o.active?(o.waiting_for_human?'HITL WAIT':o.fallback_used?'FALLBACK':o.regeneration_count?'REGENERATING':'MONITORING'):'STANDBY');
    text('review-caption',o.active?`regenerations ${o.regeneration_count ?? 0}`:'no operator action');tone('metric-review',o.active?(o.fallback_used?'fallback':o.waiting_for_human || o.regeneration_count?'warning':'quiet'):'quiet');
    document.querySelectorAll('[data-control]').forEach(b=>{
        const action=b.dataset.control;
        b.disabled=desk.busy || Boolean(desk.failure) || Date.now()-desk.lastGood>4000 || (action==='start' && (s.running || s.simulation_complete)) || (action==='pause' && !s.running) || (action==='step' && (s.running || s.simulation_complete));
    });
}
function renderTimeline() {
    const rows=[...desk.records.values()].map(recordView).sort((a,b)=>(b.active-a.active)||(b.queued-a.queued)||(b.seen-a.seen));
    text('incident-count',rows.length);
    html('timeline',rows.map(v=>`<button class="incident-item" data-crisis="${esc(v.id)}" aria-pressed="${v.id===desk.selected}" title="${esc(v.id)}"><header><span>${esc(shortId(v.id))}</span><span data-tone="${v.tint}">${esc(v.status)}</span></header><strong>${esc(v.kind.replaceAll('_',' '))}</strong><small>STEP ${esc(v.step ?? '—')} · ${v.affected.length} known robots</small><small>${v.coords.length?esc(v.coords.map(p=>`(${p.join(',')})`).join(' ')):'Location not retained'}</small></button>`).join('') || empty('NO INCIDENTS RECORDED','The desk is ready. New incidents appear here when detected.'));
    $('follow-active').setAttribute('aria-pressed',String(desk.followActive));
    const outcomes=rows.filter(v=>!v.active && !v.queued).slice(0,12);
    html('outcomes',outcomes.map(v=>`<button class="outcome-item" data-crisis="${esc(v.id)}"><header><strong>${esc(shortId(v.id))}</strong><span data-tone="${v.tint}">${esc(v.status)}</span></header><p>${esc(duration(v.complete?.duration_ms))} orchestration · ${esc(v.complete?.executed_actions ?? v.s.executed_actions ?? '—')} actions</p><small>${v.recovered?'First movement recovery recorded':v.complete?'Graph ended; physical recovery tracked separately':'Partial retained history'}</small></button>`).join('') || empty('NO COMPLETED INCIDENTS','Outcomes appear from retained completion, fallback and recovery events.'));
}
function pipelineStages(v) {
    const reached=type=>Boolean(v?.events.some(e=>e.event_type===type));
    const p=v?.planEvents || [], node=v?.active ? v.s.active_node : null;
    const stage=(name,done,active,error,caption)=>({name,tone:error?'error':active?'ai':done?'success':'quiet',caption});
    const stages=[
        stage('DIAGNOSE',reached('DIAGNOSE'),node==='diagnose',false,reached('DIAGNOSE')?'observed':'not observed'),
        stage('GENERATE PLAN',!!v?.parsed,node==='generate_plan' || node==='regenerating',v?.response?.event_type==='LLM_FAILURE',v?.parsed?'JSON parsed':v?.response?.event_type==='LLM_FAILURE'?'request failed':v?.request?'LLM requested':'awaiting event'),
        stage('VALIDATE',v?.validation?.event_type==='VALIDATOR_PASS',node==='validate',v?.validation?.event_type==='INVALID_PLAN' && v.validation.graph_node==='validate',v?.validation?.event_type==='VALIDATOR_PASS'?'safety pass':v?.validation?.graph_node==='validate'?'plan rejected':'not observed'),
        stage('EXECUTE',p.some(e=>e.event_type==='ACTION_OK'),['execute','executing'].includes(node),p.some(e=>e.event_type==='ACTION_FAILED'),p.some(e=>e.event_type==='ACTION_OK')?'action committed':'not observed'),
        stage('COMPLETE',!!v?.complete || v?.s.active_node==='complete',false,false,v?.complete?duration(v.complete.duration_ms):'not observed')
    ];
    if (v?.active && v.s.waiting_for_human) stages[3]={name:'EXECUTE',tone:'warning',caption:'HITL interrupt'};
    return stages;
}
function renderIncident() {
    const v=selection();
    text('selected-id',v?shortId(v.id):'NO SELECTION');$('selected-id').title=v?.id || '';
    text('incident-headline',v?v.kind.replaceAll('_',' '):desk.status?'SYSTEM NOMINAL':'CONNECTING TO WAREHOUSE');
    tone('incident-headline',v?v.tint:'success');text('incident-status',v?v.status:'IDLE');tone('incident-status',v?v.tint:'success');
    text('incident-subtitle',v?`Step ${v.step ?? '—'} · ${v.affected.length} affected robots · ${v.coords.length} known cells`:desk.status?'No active crisis. Deterministic operations continue.':'Awaiting the first valid API snapshot.');
    html('pipeline',pipelineStages(v).map(s=>`<li data-tone="${s.tone}"><b>${s.name}</b><span>${esc(s.caption)}</span></li>`).join(''));
    let branch='Local inference handles exceptional recovery. Movement stays deterministic.', branchTone='quiet';
    if (v?.queued) {branch='QUEUED · no inference or orchestration holds until activation';branchTone='warning';}
    else if (v?.usedFallback) {branch=`FALLBACK · ${v.s.fallback_reason || v.fallback?.reason || 'deterministic recovery recorded'}`;branchTone='fallback';}
    else if (v?.s.waiting_for_human && v.active) {branch='VALIDATED → OPERATOR REVIEW → EXECUTE or REGENERATE';branchTone='warning';}
    else if (v?.dropped) {branch=`STALE DROPPED · ${v.dropped.reason || 'incident no longer current'}`;}
    else if (v && (v.s.regeneration_count || last(v.events,'PLAN_REGENERATED'))) {branch=`REGENERATION · ${v.s.regeneration_count ?? last(v.events,'PLAN_REGENERATED')?.attempt} additional request(s) · ${v.active?'validation runs again':'recorded retry history'}`;branchTone='warning';}
    else if (v?.s.approval_source==='policy') {branch='AUTO-EXECUTION POLICY · validated plan met configured safety policy';branchTone='success';}
    text('branch-state',branch);tone('branch-state',branchTone);
    renderPlan(v);renderMap(v);renderTrace(v);
}
function renderPlan(v) {
    const s=v?.s || {}, response=v?.response, request=v?.request;
    html('model-detail',pairs([
        ['Provider',response?.provider || request?.provider || s.llm_provider || 'Not observed'],
        ['Model',v?.model || s.model || 'Not observed'],['Request',request?clock(request.timestamp):'No retained request'],
        ['Response',response?`${response.event_type==='LLM_SUCCESS'?'SCHEMA VALID':'FAILED'} · ${clock(response.timestamp)}`:request && v.active?'IN FLIGHT':'Not retained'],
        ['HTTP status',response?.http_status ?? s.http_status ?? 'No HTTP receipt'],
        ['Latency',duration(response?.latency_ms ?? s.llm_latency_ms)]
    ])+(response?.error_code?`<p class="meta" data-tone="error">${esc(response.failure_type || response.error_code)} · ${esc(response.provider_error || response.reason || '')}</p>`:''));
    text('parse-state',v?.parsed?'PARSED':response?.error_code || 'AWAITING');tone('parse-state',v?.parsed?'success':response?'error':'quiet');
    const actions=list(s.proposed_plan?.actions).filter(a=>a && typeof a==='object');
    html('plan-detail',actions.length?`<p class="meta" title="${esc(v.planId)}">${esc(shortId(v.planId))} · ${actions.length} executable proposals</p>`+actions.map(a=>{
        const receipt=v.planEvents.find(e=>e.event_type==='ACTION_OK' && e.robot_id===a.robot_id && e.action===a.action);
        const params=[a.hold_steps!=null?`${a.hold_steps} steps`:null,a.yield_to_robot_id!=null?`priority → R${a.yield_to_robot_id}`:null,a.task_id!=null?`task ${a.task_id}`:null,a.waypoint?`via (${a.waypoint.x}, ${a.waypoint.y})`:null].filter(Boolean).join(' · ');
        return `<article class="action"><header><b>R${esc(a.robot_id)}</b><strong>${esc(a.action)}</strong><span data-tone="${receipt?'success':'quiet'}">${receipt?'ACTION_OK':'PROPOSED'}</span></header><p class="parameters">${esc(params || 'ChargingManager route')}</p><p>${esc(a.reason)}</p></article>`;
    }).join('')+(s.proposed_plan.rationale?`<p class="meta">${esc(s.proposed_plan.rationale)}</p>`:''): `<p>${v?.parsed?'Plan parsed; full action parameters were not retained.':v?.queued?'Waiting for activation. No plan generated yet.':'No structured plan available.'}</p>`);
    const report=s.validation_report;
    // A report can linger in the backend during a retry; use it only with the current validation result.
    const validated=s.validation_status && s.validation_status!=='PENDING';
    const status=validated?s.validation_status:v?.validation?.event_type==='VALIDATOR_PASS'?'VALID':v?.validation?'INVALID':'PENDING';
    const issues=list(s.validation_issues).filter(i=>i && typeof i==='object');
    const value=validated?s.validation_score:v?.validation?.validation_score;
    const errors=validated?issues.filter(i=>i.level==='ERROR').length:v?.validation?.errors;
    const warnings=validated?issues.filter(i=>i.level==='WARNING').length:v?.validation?.warnings;
    const schemaFailed=['LLM_INVALID_JSON','LLM_SCHEMA_ERROR'].includes(response?.error_code);
    const transportFailed=['LLM_UNAVAILABLE','LLM_TIMEOUT','LLM_INTERNAL_ERROR'].includes(response?.error_code);
    const label=transportFailed?'NO PLAN / MODEL FAILURE':schemaFailed?'SCHEMA REJECTED':status==='VALID'?'PASS':status==='INVALID'?'REJECTED':'NOT YET VALIDATED';
    html('validation-detail',`<div class="validation-head"><strong data-tone="${status==='VALID'?'success':status==='INVALID'?'error':'quiet'}">${label}</strong><span>${score(value)} / 1.00</span></div><p class="meta">Execution readiness, not model confidence. Errors prevent execution.</p><p class="meta">${esc(errors ?? '—')} errors · ${esc(warnings ?? '—')} warnings</p>`+
        issues.map(i=>`<div class="issue" data-tone="${i.level==='ERROR'?'error':'warning'}"><b>${esc(i.level)} · ${esc(i.code)}${i.robot_id!=null?' · R'+esc(i.robot_id):''}</b><p>${esc(i.message)}</p></div>`).join('')+
        (!issues.length && list(v?.validation?.codes).length?`<p class="meta">${esc(v.validation.codes.join(' · '))}</p>`:'')+
        (validated && report?.metrics && s.validation_score!=null?`<details class="metric-list"><summary>Measured validator components</summary>${pairs(Object.entries(report.metrics).filter(([key])=>key.endsWith('_ratio')).map(([key,val])=>[key,score(val)]))}</details>`:''));
    $('hitl-review').hidden=!(v?.active && s.waiting_for_human && s.validation_status==='VALID' && actions.length && !issues.some(i=>i.level==='ERROR'));
    $('approve-plan').disabled=!canReview(v);$('reject-plan').disabled=!canReview(v);
    const receipts=list(v?.events).filter(e=>['ACTION_OK','ACTION_FAILED'].includes(e.event_type));
    html('execution-detail',pairs([
        ['Approval',s.approval_source==='human'?(s.human_approved?'HUMAN APPROVED':'REJECTED → REGENERATE'):s.approval_source==='policy'?'AUTOMATIC POLICY':v?.active && s.waiting_for_human?'WAITING FOR OPERATOR':'Not observed'],
        ['Retries',s.regeneration_count ?? last(v?.events || [],'PLAN_REGENERATED')?.attempt ?? '—'],
        ['Fallback',v?.usedFallback?(s.fallback_reason || v.fallback?.reason || 'Used'):'No retained fallback'],
        ['Graph time',duration(v?.complete?.duration_ms)],
        ['Recovery',v?.recovered?`${v.recovered.recovery_steps} steps to first movement`:'Not recorded']
    ])+(s.error_code?`<p class="meta" data-tone="error">${esc(s.error_code)} · ${esc(s.error || '')}</p>`:'')+
        receipts.slice(-20).map(e=>`<p class="meta"><span data-tone="${eventTone(e.event_type)}">${esc(e.event_type)}</span> · ${esc(shortId(e.plan_id))} · R${esc(e.robot_id ?? '—')} ${esc(e.action || '')}${e.error_code?' · '+esc(e.error_code):''}</p>`).join(''));
}
function renderFloor() {
    const g=desk.grid;if(!g)return;
    $('impact-map').setAttribute('viewBox',`0 0 ${g.width*20} ${g.height*20}`);
    $('impact-map').setAttribute('preserveAspectRatio','xMidYMid meet');
    let floor='';
    g.grid.forEach((row,y)=>row.forEach((cell,x)=>{
        floor+=`<rect x="${x*20}" y="${y*20}" width="20" height="20" class="${cell==='S'?'shelf-cell':cell==='C'?'charger-cell':'floor-cell'}"/>`;
        if(cell==='C')floor+=`<text class="charger-mark" x="${x*20+10}" y="${y*20+14}">C</text>`;
    }));html('floor-layer',floor);
}
function renderMap(v) {
    const affected=v?.affected || [], selected=desk.robots.find(r=>r.id===desk.robot);
    const relevant=desk.robots.filter(r=>affected.includes(r.id));
    // Focus actual affected positions/cells; keep square geometry and unchanged (x,y).
    // Full-floor view remains available. Historical views always use current positions.
    if(desk.grid) {
        const g=desk.grid, focus=[...(v?.coords || []),...relevant.map(r=>[r.position.x,r.position.y])];
        if(selected)focus.push([selected.position.x,selected.position.y],...cells(selected.path));
        let x=0,y=0,right=g.width,bottom=g.height;
        if(!desk.fullFloor && focus.length) {
            x=Math.max(0,Math.min(...focus.map(p=>p[0]))-3);y=Math.max(0,Math.min(...focus.map(p=>p[1]))-3);
            right=Math.min(g.width,Math.max(...focus.map(p=>p[0]))+4);bottom=Math.min(g.height,Math.max(...focus.map(p=>p[1]))+4);
        }
        $('impact-map').setAttribute('viewBox',`${x*20} ${y*20} ${(right-x)*20} ${(bottom-y)*20}`);
    }
    $('map-fit').setAttribute('aria-pressed',String(desk.fullFloor));
    html('map-robot','<option value="">All affected</option>'+relevant.map(r=>`<option value="${r.id}">R${r.id} · ${esc(r.status)}</option>`).join('')+(selected && !affected.includes(selected.id)?`<option value="${selected.id}">R${selected.id} · selected</option>`:''));
    $('map-robot').value=desk.robot==null?'':String(desk.robot);
    text('map-caption',v && !v.active && !v.queued?'HISTORICAL INCIDENT · CURRENT POSITIONS':'CURRENT WAREHOUSE · (x, y)');
    html('crisis-layer',(v?.coords || []).map(([x,y])=>`<rect class="crisis-cell" x="${x*20}" y="${y*20}" width="20" height="20"><title>Incident cell (${x}, ${y})</title></rect>`).join(''));
    let route='';
    if(selected) {
        const path=[[selected.position.x,selected.position.y],...cells(selected.path)];
        route=`<polyline class="selected-route ${selected.status==='CHARGING'?'charging':''}" points="${path.map(([x,y])=>`${x*20+10},${y*20+10}`).join(' ')}"/>`;
        const action=list(v?.s.proposed_plan?.actions).find(a=>a?.robot_id===selected.id && a.waypoint);
        if(number(action?.waypoint?.x) && number(action?.waypoint?.y))route+=`<circle class="waypoint" cx="${action.waypoint.x*20+10}" cy="${action.waypoint.y*20+10}" r="6"><title>Proposed waypoint, not proof of execution</title></circle>`;
        const task=desk.tasks.find(t=>t.id===selected.current_task);
        if(task)for(const [label,x,y] of [['P',task.pickup_x,task.pickup_y],['D',task.delivery_x,task.delivery_y]])if(number(x)&&number(y))route+=`<text class="task-marker" x="${x*20+10}" y="${y*20+14}">${label}</text>`;
        text('robot-detail',`R${selected.id} · ${selected.status} · battery ${number(selected.battery)?selected.battery.toFixed(0):'—'}% · task ${selected.current_task ?? '—'} · (${selected.position.x}, ${selected.position.y})${selected.orchestration_held?' · ACTIVE CRISIS HOLD':''} · current route`);
    } else text('robot-detail',affected.length?`Affected: ${affected.map(id=>'R'+id).join(', ')} · select a marker for its current route`:'No affected robots selected. Warehouse activity is shown at reduced contrast.');
    html('route-layer',route);
    html('robot-layer',desk.robots.map(r=>`<g class="robot ${affected.includes(r.id)?'affected':'unrelated'} ${r.id===desk.robot?'selected':''}" transform="translate(${r.position.x*20},${r.position.y*20})" data-robot="${r.id}" role="button" tabindex="0" aria-label="Robot ${r.id}, ${esc(r.status)}${affected.includes(r.id)?', affected':''}"><title>R${r.id} · ${esc(r.status)} · ${esc(r.battery)}%</title><rect x="2" y="2" width="16" height="16" rx="2"/><text x="10" y="14">${r.id}</text></g>`).join(''));
}
function traceDetail(e) {
    return [e.provider,e.model,e.http_status!=null?`HTTP ${e.http_status}`:null,e.failure_type,e.provider_error,e.action,e.latency_ms!=null?`${e.latency_ms}ms`:null,
        e.validation_score!=null?`score=${e.validation_score}`:null,e.actions!=null?`actions=${e.actions}`:null,
        e.errors!=null?`errors=${e.errors}`:null,e.warnings!=null?`warnings=${e.warnings}`:null,
        e.attempt!=null?`attempt=${e.attempt}`:null,e.duration_ms!=null?`duration=${duration(e.duration_ms)}`:null,
        e.executed_actions!=null?`executed=${e.executed_actions}`:null,e.error_code,e.reason,
        list(e.codes).join(', '),e.affected?`affected=${list(e.affected).join(',')}`:null,
        e.depth!=null?`queue=${e.depth}`:null].filter(x=>x!==null && x!==undefined && x!=='').join(' · ') || e.graph_node || 'Recorded';
}
function renderTrace(v) {
    if(desk.traceKey!==v?.id) {desk.traceKey=v?.id;desk.followTrace=true;}
    text('trace-follow',desk.followTrace?'LIVE':'PAUSED-FOLLOW');$('trace-follow').setAttribute('aria-pressed',String(desk.followTrace));
    if(!desk.followTrace)return;
    const rows=(v?.events || []).slice(-200);
    text('trace-count',`${rows.length} retained events · selected incident`);
    html('trace',rows.map(e=>`<div class="trace-row"><time>${esc(clock(e.timestamp))}</time><span class="step">[${esc(e.step ?? '—')}]</span><b data-tone="${eventTone(e.event_type)}">${esc(e.event_type)}</b><span class="entity" title="${esc(e.plan_id || e.crisis_id)}">${esc(e.robot_id!=null?'R'+e.robot_id:shortId(e.plan_id || e.crisis_id))}</span><span class="message">${esc(traceDetail(e))}</span></div>`).join('') || empty('AWAITING ORCHESTRATION EVENTS','Select an incident to follow detection, requests, parsing, validation and committed actions.'));
    $('trace').scrollTop=$('trace').scrollHeight;
}
function render() {renderHeader();renderTimeline();renderIncident();freshness();}
function freshness() {
    const age=desk.lastGood?(Date.now()-desk.lastGood)/1000:null, stale=age===null || age>4 || Boolean(desk.failure);
    text('connection',stale?(age===null?'API CONNECTING / RETRYING':`STALE ${age.toFixed(1)}s · RECONNECTING`):'API CONNECTED');tone('connection',stale?'warning':'success');
    text('freshness',desk.failure?`API ERROR · ${desk.failure}`:age===null?'Awaiting telemetry':`Snapshot age ${age.toFixed(1)}s · polling 1s`);
    $('approve-plan').disabled=!canReview();$('reject-plan').disabled=!canReview();
    $('inject-crisis').disabled=desk.busy || stale;
    renderHeader();
}
async function poll() {
    if(desk.polling)return;desk.polling=true;
    const epoch=desk.epoch;
    try {
        const before=await api('/simulation/status');
        const [o,e,robots,tasks]=await Promise.all([api('/orchestrator/state'),api('/orchestrator/events?limit=1000'),api('/robots'),api('/tasks')]);
        const key=`${before.run_id}:${before.grid_revision}`;
        const grid=desk.gridKey===key?desk.grid:await api('/warehouse/grid');
        const after=await api('/simulation/status');
        if(epoch!==desk.epoch)return;
        if(before.run_id!==after.run_id || before.grid_revision!==after.grid_revision || o.run_id!==after.run_id || e.run_id!==after.run_id) throw new Error('Run/grid changed during snapshot; refreshing');
        ingest(after,o,e.events);desk.robots=robots;desk.tasks=tasks;
        if(desk.gridKey!==key) {desk.grid=grid;desk.gridKey=key;renderFloor();}
        desk.lastGood=Date.now();
        if(desk.failure)console.info('[UI][API_RECOVERED] Crisis desk');
        desk.failure=null;render();
    } catch(error) {
        if(epoch!==desk.epoch)return;
        if(desk.failure!==error.message)console.warn('[UI][API_ERROR]',error.message);
        desk.failure=error.message;freshness();
    } finally {desk.polling=false;}
}
function notify(message) {text('notice',message);$('notice').hidden=!message;}
async function control(action) {
    if(desk.busy || desk.failure || !desk.lastGood || Date.now()-desk.lastGood>4000)return;
    if(['reset','crisis'].includes(action) && !window.confirm(action==='reset'?'Reset this run and cancel active orchestration?':'Inject this incident? It consumes one slot from the shared run budget.'))return;
    desk.busy=true;freshness();
    try {
        await api(`/simulation/${action}`,action==='crisis'?{kind:$('crisis-kind').value}:{});
        console.info('[UI][CONTROL]',action);notify(action==='crisis'?'Incident submitted. Queued effects wait for activation.':`Simulation ${action} accepted.`);
        if(action==='reset') {desk.epoch++;desk.gridKey=null;desk.lastGood=0;desk.orchestrator=null;}
    } catch(error) {notify(error.message);}
    finally {desk.busy=false;await poll();freshness();}
}
async function override(approved) {
    if(!canReview())return;
    const v=selection(), run=desk.status.run_id, plan=v.planId, epoch=desk.epoch;
    desk.busy=true;freshness();
    try {
        // Recheck identity after the click; the server also rejects stale plan IDs.
        const live=await api('/orchestrator/state');
        if(epoch!==desk.epoch || live.run_id!==run || live.plan_id!==plan || !live.active || !live.waiting_for_human || live.validation_status!=='VALID')throw new Error('Plan changed. Review the current plan before submitting.');
        await api('/orchestrator/override',{approved,plan_id:plan});
        if(epoch===desk.epoch) {
            desk.orchestrator.waiting_for_human=false;
            notify(approved?'Approval accepted. Execution revalidates live safety.':'Rejection accepted. Regeneration follows the existing retry budget.');
            console.info('[UI][HITL]',approved?'APPROVED':'REJECTED',plan);
        }
    } catch(error) {if(epoch===desk.epoch)notify(error.message);}
    finally {desk.busy=false;await poll();freshness();}
}
function selectCrisis(id) {
    if(!desk.records.has(id))return;
    desk.selected=id;desk.followActive=false;desk.robot=null;desk.followTrace=true;render();
}
document.addEventListener('DOMContentLoaded',()=>{
    document.querySelectorAll('[data-control]').forEach(b=>{b.disabled=true;b.addEventListener('click',()=>control(b.dataset.control));});
    for(const id of ['timeline','outcomes'])$(id).addEventListener('click',e=>{const item=e.target.closest('[data-crisis]');if(item)selectCrisis(item.dataset.crisis);});
    $('follow-active').addEventListener('click',()=>{desk.followActive=true;if(desk.orchestrator?.active)desk.selected=desk.orchestrator.crisis_id;desk.robot=null;render();});
    $('inject-crisis').addEventListener('click',()=>control('crisis'));
    $('approve-plan').addEventListener('click',()=>override(true));$('reject-plan').addEventListener('click',()=>override(false));
    $('map-robot').addEventListener('change',e=>{desk.robot=e.target.value===''?null:Number(e.target.value);renderMap(selection());});
    $('map-fit').addEventListener('click',()=>{desk.fullFloor=!desk.fullFloor;renderMap(selection());});
    const selectRobot=e=>{const marker=e.target.closest('[data-robot]');if(marker){desk.robot=Number(marker.dataset.robot);renderMap(selection());}};
    $('robot-layer').addEventListener('click',selectRobot);
    $('robot-layer').addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();selectRobot(e);}});
    $('trace').addEventListener('scroll',()=>{const el=$('trace');if(el.scrollHeight-el.scrollTop-el.clientHeight>24){desk.followTrace=false;text('trace-follow','PAUSED-FOLLOW');$('trace-follow').setAttribute('aria-pressed','false');}});
    $('trace-follow').addEventListener('click',()=>{desk.followTrace=!desk.followTrace;renderTrace(selection());});
    new ResizeObserver(()=>{if(desk.followTrace)$('trace').scrollTop=$('trace').scrollHeight;}).observe($('trace'));
    render();console.info('[UI][BOOT] Crisis + Orchestration desk');
    const loop=async()=>{await poll();setTimeout(loop,1000);};loop();setInterval(freshness,1000);
});
