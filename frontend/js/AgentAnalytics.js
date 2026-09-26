'use strict';

// Read-only observability. Samples describe browser observations, never simulated reasoning.
const analytics={status:null,grid:null,gridKey:null,robots:[],tasks:[],agents:[],taskAgents:[],
    events:[],messages:[],auctions:[],samples:[],observations:[],selected:null,
    lastGood:0,lastDetail:0,error:null,detailError:null,follow:true,traceRobot:null};
const $=id=>document.getElementById(id);
const arr=value=>Array.isArray(value)?value:[];
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=value=>typeof value==='number'&&Number.isFinite(value);
const point=p=>Array.isArray(p)&&p.length===2&&p.every(num);
const coords=p=>p?`(${p.x}, ${p.y})`:'—';
const path=r=>arr(r?.path).filter(point);
const time=t=>num(t)?new Date(t*1000).toLocaleTimeString([],{hour12:false}):'—';
const cache=new Map();
function text(id,value){$(id).textContent=value??'—';}
function html(id,value){if(cache.get(id)!==value){$(id).innerHTML=value;cache.set(id,value);}}
function tone(id,value){$(id).dataset.tone=value;}
function empty(title,body){return `<div class="empty"><strong>${esc(title)}</strong><p>${esc(body)}</p></div>`;}
function facts(rows){return `<dl>${rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v??'—')}</dd>`).join('')}</dl>`;}
function agent(r){return analytics.agents.find(a=>a.robot_id===r.id);}
function held(r){return Boolean(r.orchestration_held||r.hold_steps_remaining>0||r.yield_to_robot_id!=null);}
function blocked(r){return !held(r)&&['MOVING','DELIVERING'].includes(r.status)&&path(r).length>1&&agent(r)?.beliefs?.path_blocked===true;}
function atBay(r){return analytics.grid?.grid[r.position.y]?.[r.position.x]==='C';}
function chargingHere(r){return r.status==='CHARGING'&&atBay(r)&&path(r).length<=1;}
function robotTone(r){return r.status==='NEEDS_CHARGE'||r.battery<15?'error':r.orchestration_held?'ai':blocked(r)||held(r)?'blocked':r.status==='CHARGING'?'charging':r.status==='DELIVERING'?'healthy':r.status==='MOVING'?'active':'quiet';}
function robotState(r){return r.orchestration_held?'ORCH HOLD':r.hold_steps_remaining>0?'HOLD':r.yield_to_robot_id!=null?'YIELD':blocked(r)?'BLOCKED':r.status;}
function eventTone(type){return /FAIL|ERROR|INVALID/.test(type)?'error':/LLM|ORCH/.test(type)?'ai':/BLOCK|DEADLOCK|REAUCTION|FALLBACK/.test(type)?'blocked':/BATTERY|CHARG/.test(type)?'charging':/COMPLETED|ACTION_OK|RESOLVED/.test(type)?'healthy':/PROPOSAL|CFP|AWARDED/.test(type)?'active':'quiet';}
function mergeRows(old,rows,key,limit){const map=new Map(old.map(e=>[e[key],e]));rows.forEach(e=>map.set(e[key],e));return [...map.values()].sort((a,b)=>(a.timestamp??0)-(b.timestamp??0)).slice(-limit);}
function valid(url,data){
    let ok=data&&typeof data==='object';
    if(url==='/simulation/status')ok&&=typeof data.run_id==='string'&&num(data.current_step)&&typeof data.running==='boolean'&&typeof data.simulation_complete==='boolean';
    if(url==='/robots')ok=Array.isArray(data)&&data.every(r=>r&&num(r.id)&&num(r.position?.x)&&num(r.position?.y)&&num(r.battery)&&typeof r.status==='string');
    if(url==='/tasks')ok=Array.isArray(data)&&data.every(t=>t&&num(t.id)&&typeof t.completed==='boolean');
    if(url==='/agents/status')ok&&=Array.isArray(data.agents)&&data.agents.every(a=>a&&num(a.robot_id)&&a.beliefs&&typeof a.beliefs==='object');
    if(url==='/tasks/agents')ok&&=Array.isArray(data.task_agents)&&data.task_agents.every(t=>t&&num(t.task_id));
    if(url==='/agents/message-history')ok&&=typeof data.session_id==='string'&&Array.isArray(data.messages)&&data.messages.every(m=>m&&num(m.id)&&typeof m.type==='string');
    if(url==='/auction/logs')ok=Array.isArray(data)&&data.every(a=>a&&num(a.task_id)&&Array.isArray(a.bids));
    if(url.startsWith('/orchestrator/events'))ok&&=typeof data.run_id==='string'&&Array.isArray(data.events)&&data.events.every(e=>e&&typeof e.event_type==='string'&&typeof e.event_id==='string');
    if(url==='/warehouse/grid')ok&&=Number.isInteger(data.width)&&data.width>0&&Number.isInteger(data.height)&&data.height>0&&Array.isArray(data.grid)&&data.grid.length===data.height&&data.grid.every(row=>Array.isArray(row)&&row.length===data.width);
    if(!ok)throw Error(`Malformed response: ${url}`);return data;
}
async function get(url){const r=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(8000)});if(!r.ok)throw Error(`${url}: HTTP ${r.status}`);return valid(url,await r.json());}
function accept(status,robots,tasks,agents,grid,details){
    const reset=analytics.status&&(analytics.status.run_id!==status.run_id||status.current_step<analytics.status.current_step);
    if(reset){analytics.samples=[];analytics.observations=[];analytics.events=[];analytics.messages=[];analytics.taskAgents=[];analytics.auctions=[];analytics.selected=null;analytics.traceRobot=null;analytics.follow=true;analytics.lastDetail=0;}
    const previous=new Map((reset?[]:analytics.robots).map(r=>[r.id,r]));
    analytics.status=status;analytics.robots=robots;analytics.tasks=tasks;analytics.agents=agents;analytics.grid=grid;
    if(analytics.selected!=null&&!robots.some(r=>r.id===analytics.selected))analytics.selected=null;
    if(details){
        analytics.events=mergeRows(analytics.events,details.events.filter(e=>e.run_id===status.run_id),'event_id',1000);
        analytics.messages=mergeRows(analytics.messages,details.messages,'id',1000);
        analytics.auctions=details.auctions.slice(-300);analytics.taskAgents=details.taskAgents;
        analytics.lastDetail=Date.now();analytics.detailError=null;
    }
    const last=analytics.samples.at(-1);
    if(!last||last.step!==status.current_step){
        const sample={step:status.current_step,complete:tasks.filter(t=>t.completed).length,
            occupied:robots.map(r=>[r.position.x,r.position.y]),blocked:robots.filter(blocked).map(r=>[r.position.x,r.position.y])};
        analytics.samples.push(sample);analytics.samples=analytics.samples.slice(-120);
        for(const r of robots){
            const old=previous.get(r.id);if(!old)continue;
            const changes=[];
            if(old.position.x!==r.position.x||old.position.y!==r.position.y)changes.push(`position ${coords(old.position)} → ${coords(r.position)} (between polls)`);
            if(old.status!==r.status)changes.push(`status ${old.status} → ${r.status}`);
            if(old.current_task!==r.current_task)changes.push(`task ${old.current_task??'none'} → ${r.current_task??'none'}`);
            if(changes.length)analytics.observations.push({robot_id:r.id,timestamp:Date.now()/1000,step:status.current_step,type:'OBSERVED',detail:changes.join(' · ')});
        }
        analytics.observations=analytics.observations.slice(-1200);
    }
}
function fleetRows(){
    const filter=$('fleet-filter').value,sort=$('fleet-sort').value;
    const rows=analytics.robots.filter(r=>filter==='all'||filter==='moving'&&['MOVING','DELIVERING'].includes(r.status)||filter==='charging'&&r.status==='CHARGING'||filter==='idle'&&r.status==='IDLE'||filter==='blocked'&&(blocked(r)||held(r))||filter==='low'&&r.battery<30);
    const compare={id:(a,b)=>a.id-b.id,'battery-up':(a,b)=>a.battery-b.battery,'battery-down':(a,b)=>b.battery-a.battery,status:(a,b)=>a.status.localeCompare(b.status),task:(a,b)=>(a.current_task??Infinity)-(b.current_task??Infinity)}[sort];
    return rows.sort((a,b)=>(compare||((a,b)=>a.id-b.id))(a,b)||a.id-b.id);
}
function renderHeader(){
    const s=analytics.status;if(!s)return;
    text('run-id',s.run_id);text('seed',s.seed);text('step',s.current_step);text('header-fleet',analytics.robots.length);
    text('sim-status',s.simulation_complete?'COMPLETE':s.running?'RUNNING':'PAUSED');tone('sim-status',s.simulation_complete?'healthy':'quiet');
    const robots=analytics.robots,charging=robots.filter(r=>r.status==='CHARGING'),here=charging.filter(chargingHere).length,blocks=robots.filter(blocked).length,holds=robots.filter(held).length;
    const avg=robots.length?robots.reduce((n,r)=>n+r.battery,0)/robots.length:null,done=analytics.tasks.filter(t=>t.completed).length;
    text('kpi-fleet',robots.length);text('kpi-moving',robots.filter(r=>['MOVING','DELIVERING'].includes(r.status)).length);
    text('kpi-idle',robots.filter(r=>r.status==='IDLE').length);text('kpi-charging',charging.length);text('charge-caption',`${here} at bay / ${charging.length-here} travelling or waiting`);
    text('kpi-blocked',`${blocks} / ${holds}`);text('kpi-battery',avg==null?'—':`${avg.toFixed(1)}%`);text('kpi-tasks',`${done} / ${analytics.tasks.length}`);text('task-caption',`${analytics.tasks.length-done} remaining`);
    tone('metric-charging',charging.length?'charging':'quiet');tone('metric-blocked',blocks||holds?'blocked':'quiet');tone('metric-battery',avg==null?'quiet':avg<15?'error':avg<30?'charging':'healthy');tone('metric-tasks',done?'healthy':'quiet');
}
function renderFleet(){
    const rows=fleetRows();text('fleet-count',`${rows.length} / ${analytics.robots.length}`);
    html('fleet-list',rows.map(r=>`<button class="fleet-row" data-robot="${r.id}" aria-pressed="${analytics.selected===r.id}" aria-label="Inspect robot ${r.id}"><span><strong>R${r.id}</strong><small data-tone="${robotTone(r)}">${esc(robotState(r))}</small></span><span data-tone="${r.battery<15?'error':r.battery<30?'charging':'quiet'}">${r.battery.toFixed(0)}%<span class="battery-track"><i style="width:${Math.max(0,Math.min(100,r.battery))}%"></i></span></span><span>${r.current_task==null?'—':'T'+r.current_task}<small>${esc(coords(r.position))}</small></span></button>`).join('')||empty('NO MATCHING ROBOTS','Choose another fleet filter.'));
}
function renderThroughput(){
    const rows=analytics.samples,first=rows[0],last=rows.at(-1);text('sample-count',`${rows.length} / 120 samples`);
    if(!first){html('throughput-chart','<text class="chart-label" x="12" y="42">Awaiting first sample</text>');return;}
    const delta=last.step-first.step,rate=delta>0?(last.complete-first.complete)*100/delta:null;
    text('throughput-rate',rate==null?'Collecting samples':`${rate.toFixed(1)} / 100 steps`);
    text('throughput-window',`Steps ${first.step}–${last.step} · +${last.complete-first.complete} delivered`);
    const maximum=Math.max(1,...rows.map(r=>r.complete));
    const positions=rows.map(r=>[32+(r.step-first.step)/Math.max(1,delta)*556,74-r.complete/maximum*62]);
    html('throughput-chart',`<path class="chart-axis" d="M32 10 V74 H588"/><text class="chart-label" x="2" y="16">${maximum}</text><text class="chart-label" x="16" y="77">0</text><polyline class="chart-line" points="${positions.map(p=>p.join(',')).join(' ')}"/><circle class="chart-dot" cx="${positions.at(-1)[0]}" cy="${positions.at(-1)[1]}" r="2.5"/><text class="chart-label" x="32" y="90">${first.step}</text><text class="chart-label" text-anchor="end" x="588" y="90">${last.step}</text>`);
}
function renderHeatFloor(){
    const g=analytics.grid;if(!g)return;$('heatmap').setAttribute('viewBox',`0 0 ${g.width*20} ${g.height*20}`);
    html('heat-floor',g.grid.map((row,y)=>row.map((c,x)=>`<rect x="${x*20}" y="${y*20}" width="20" height="20" class="${c==='S'?'heat-shelf':c==='C'?'heat-charger':'heat-floor'}"/>`).join('')).join(''));
}
function renderHeat(){
    const mode=$('heat-mode').value,counts=new Map();
    for(const sample of analytics.samples)for(const p of sample[mode==='blocked'?'blocked':'occupied']){const key=p.join(',');counts.set(key,(counts.get(key)||0)+1);}
    const max=Math.max(1,...counts.values());
    html('heat-cells',[...counts].map(([key,count])=>{const [x,y]=key.split(',').map(Number);return `<rect class="heat-cell ${mode==='presence'?'presence':''}" x="${x*20}" y="${y*20}" width="20" height="20" fill-opacity="${.2+.65*count/max}"><title>(${x}, ${y}): ${count} ${mode==='blocked'?'blocked':'occupied'} samples</title></rect>`;}).join(''));
    html('heat-robots',analytics.robots.map(r=>`<circle class="map-robot ${r.id===analytics.selected?'selected':''}" cx="${r.position.x*20+10}" cy="${r.position.y*20+10}" r="${r.id===analytics.selected?7:5}" data-robot="${r.id}" role="button" tabindex="0" aria-label="Inspect robot ${r.id}"><title>R${r.id} · ${esc(robotState(r))} · ${coords(r.position)}</title></circle>`).join(''));
    text('heat-caption',`${mode==='blocked'?'Blocked robot positions; belief-based observations, not failed-move counts.':'Sampled robot presence, not proven congestion.'} ${analytics.samples.length} distinct-step samples · peak ${counts.size?max:0}.`);
}
function renderChargers(){
    if(!analytics.grid)return;
    const bays=[];analytics.grid.grid.forEach((row,y)=>row.forEach((c,x)=>{if(c==='C')bays.push([x,y]);}));
    let occupied=0;
    html('charger-bays',bays.map(([x,y])=>{
        const robot=analytics.robots.find(r=>r.position.x===x&&r.position.y===y);
        const inbound=analytics.robots.filter(r=>r.status==='CHARGING'&&!(r.position.x===x&&r.position.y===y)&&path(r).at(-1)?.[0]===x&&path(r).at(-1)?.[1]===y);
        if(robot)occupied++;
        return `<div class="bay"><span>(${x},${y})</span><b data-tone="${robot?'charging':'quiet'}">${robot?'R'+robot.id+(chargingHere(robot)?' charging':' occupied'):'free'}</b><span>${inbound.length} inbound</span></div>`;
    }).join('')||'<p class="caption">No charger cells exposed.</p>');
    text('charger-summary',`${occupied} / ${bays.length} occupied`);
}
function explanation(r){
    if(r.orchestration_held)return 'An active orchestration hold is intentionally preventing movement. Review the crisis desk for its plan.';
    if(r.hold_steps_remaining>0)return `Intentional HOLD: ${r.hold_steps_remaining} steps remain.`;
    if(r.yield_to_robot_id!=null)return `Temporary YIELD gives R${r.yield_to_robot_id} priority.`;
    if(r.status==='NEEDS_CHARGE')return 'Energy recovery state: charging or movement could not proceed safely. Consult the retained failure and recovery evidence below.';
    if(chargingHere(r))return 'Charging state at a real charger cell, with the route at its endpoint.';
    if(r.status==='CHARGING')return 'Charging state away from an arrived bay. The current route may be a charging or recovery leg.';
    if(blocked(r))return 'The agent reports its next path cell blocked. This is contention evidence, not proof of a persistent deadlock.';
    if(r.current_task!=null)return `Owns task T${r.current_task}; reported goal ${agent(r)?.goal??'not available'}. Current state and route are shown below.`;
    return path(r).length>1?'No task owned; a current route is present. The API does not expose the exact decision that created it.':'No task owned. Current reported state is '+r.status+'.';
}
function renderAgent(){
    const r=analytics.robots.find(r=>r.id===analytics.selected);
    text('selected-label',r?'R'+r.id:'NONE');
    if(!r){html('agent-summary',empty('NO AGENT SELECTED','Select a robot from the fleet or warehouse observations to inspect its state and coordination evidence.'));renderTrace(null);return;}
    const a=agent(r),route=path(r),task=analytics.tasks.find(t=>t.id===r.current_task),destination=route.at(-1);
    const remaining=route.length?(route[0][0]===r.position.x&&route[0][1]===r.position.y?route.length-1:route.length):0;
    const auction=[...analytics.auctions].reverse().find(log=>arr(log.bids).some(b=>b.robot_id===r.id));
    const bid=auction?.bids.find(b=>b.robot_id===r.id);
    html('agent-summary',`<div class="agent-name"><strong>R${r.id}</strong><span data-tone="${robotTone(r)}">${esc(robotState(r))}</span></div><p class="agent-explanation">${esc(explanation(r))}</p>`+
        facts([['Battery',`${r.battery.toFixed(1)}%`],['Goal',a?.goal??'Not exposed'],['Current task',r.current_task==null?'None':'T'+r.current_task],['Position',coords(r.position)],['Route endpoint',destination?`(${destination.join(', ')})`:'No current route'],['Remaining route',`${remaining} edges`],['Charge state',chargingHere(r)?'At bay':r.status==='CHARGING'?'Travelling / waiting':r.status],['Intentional hold',r.orchestration_held?'Active orchestration':r.hold_steps_remaining>0?`${r.hold_steps_remaining} steps`:r.yield_to_robot_id!=null?`Yield to R${r.yield_to_robot_id}`:'None'],['Path blocked',a?String(Boolean(a.beliefs.path_blocked)):'Not observed']])+
        (task?`<p class="caption">Task T${task.id}: (${task.pickup_x}, ${task.pickup_y}) → (${task.delivery_x}, ${task.delivery_y}). Route endpoint may be an intermediate leg.</p>`:'')+
        '<p class="cycle">PROCESS MESSAGES → PERCEIVE → DECIDE → ACT</p>'+
        `<details><summary>Beliefs / communication / route</summary>${facts([['Battery low',a?String(Boolean(a.beliefs.battery_low)):'—'],['Carrying item',a?String(Boolean(a.beliefs.carrying_item)):'—'],['At charger',a?String(Boolean(a.beliefs.at_charger)):'—'],['Pending inbox',a?.pending_messages],['Memory entries',a?.memory_size]])}<p class="route-cells">${route.length?esc(route.slice(0,150).map(p=>`(${p.join(',')})`).join(' → ')):'No path exposed'}${route.length>150?' …':''}</p></details>`+
        `<details><summary>Latest retained CNP bid</summary>${auction?facts([['Task','T'+auction.task_id],['Bid cost',num(bid?.bid)?bid.bid.toFixed(2):'—'],['Awarded robot','R'+auction.winner],['Proposals',auction.bids.length]])+'<p class="caption">Historical auction outcome; not current ownership.</p>':'<p class="caption">No retained auction involving this robot.</p>'}</details>`);
    renderTrace(r);
}
function messageDetail(m){const p=m.payload||{};return [m.sender+' → '+m.recipient,p.task_id!=null?'task T'+p.task_id:null,p.estimated_cost!=null?'bid='+p.estimated_cost:null,p.reason,p.cell?'cell='+JSON.stringify(p.cell):null].filter(Boolean).join(' · ');}
function traceRows(r){
    const id='robot_'+r.id;
    const events=analytics.events.filter(e=>e.robot_id===r.id||arr(e.affected).includes(r.id)).map(e=>({timestamp:e.timestamp,step:e.step,type:e.event_type,source:'EVENT',detail:[e.action,e.reason,e.error_code,e.task_id!=null?'task T'+e.task_id:null,e.other_robot_id!=null?'peer R'+e.other_robot_id:null,e.cell?'cell '+JSON.stringify(e.cell):null].filter(Boolean).join(' · ')||'Recorded event'}));
    const messages=analytics.messages.filter(m=>m.sender===id||m.recipient===id).map(m=>({timestamp:m.timestamp,type:m.type,source:'MESSAGE',detail:messageDetail(m)}));
    // Broadcast CFP publication is visible, but not asserted to have been consumed by this robot.
    const broadcasts=analytics.messages.filter(m=>m.recipient==='ALL'&&['CFP','EMERGENCY_CFP'].includes(m.type)).slice(-8).map(m=>({timestamp:m.timestamp,type:m.type,source:'BROADCAST',detail:messageDetail(m)+' · publication only'}));
    return [...events,...messages,...broadcasts,...analytics.observations.filter(e=>e.robot_id===r.id).map(e=>({...e,source:'SAMPLE'}))].sort((a,b)=>a.timestamp-b.timestamp).slice(-100);
}
function renderTrace(r){
    if(analytics.traceRobot!==r?.id){analytics.traceRobot=r?.id;analytics.follow=true;}
    text('trace-follow',analytics.follow?'LIVE':'PAUSED-FOLLOW');$('trace-follow').setAttribute('aria-pressed',String(analytics.follow));
    if(!analytics.follow)return;
    const rows=r?traceRows(r):[];
    html('agent-trace',rows.map(e=>`<div class="trace-entry"><div><b data-tone="${eventTone(e.type)}">${esc(e.type)}</b><time>${esc(e.step!=null?'step '+e.step:time(e.timestamp))}</time></div><p>${esc(e.detail)}</p><small>${esc(e.source??'SAMPLE')}</small></div>`).join('')||empty(r?'NO RETAINED EVIDENCE':'AWAITING SELECTION',r?'Messages and events will appear here. Internal memory contents and exact decision tags are not exposed by this API.':'The trace connects an agent’s observed state to real messages and events.'));
    $('agent-trace').scrollTop=$('agent-trace').scrollHeight;
}
function taskState(t){
    if(t.completed)return 'COMPLETE';
    if(t.assigned_robot==null)return analytics.taskAgents.find(a=>a.task_id===t.id)?.status==='CFP_SENT'?'AUCTION':'WAITING';
    const r=analytics.robots.find(r=>r.id===t.assigned_robot&&r.current_task===t.id);
    if(r?.status==='DELIVERING'||r&&agent(r)?.beliefs.carrying_item)return 'DELIVERY';
    if(r?.status==='MOVING')return 'PICKUP';
    return 'ASSIGNED';
}
function releases(){const result=new Map();for(const e of analytics.events)if(e.event_type==='TASK_REAUCTIONED'&&e.task_id!=null)result.set(e.task_id,(result.get(e.task_id)||0)+1);return result;}
function renderTasks(){
    const filter=$('task-filter').value,released=releases();
    const rows=analytics.tasks.filter(t=>filter==='all'||filter==='waiting'&&['WAITING','AUCTION'].includes(taskState(t))||filter==='assigned'&&!t.completed&&t.assigned_robot!=null||filter==='pickup'&&taskState(t)==='PICKUP'||filter==='delivery'&&taskState(t)==='DELIVERY'||filter==='complete'&&t.completed||filter==='released'&&released.has(t.id));
    text('task-count',`${rows.length} / ${analytics.tasks.length}`);
    html('task-rows',rows.map(t=>{const state=taskState(t),a=analytics.taskAgents.find(a=>a.task_id===t.id);return `<tr><td>T${t.id}${t.priority==='CRITICAL'?' !':''}</td><td data-tone="${state==='COMPLETE'?'healthy':state==='WAITING'||state==='AUCTION'?'quiet':'active'}">${state}</td><td>${t.assigned_robot==null?'—':`<button data-robot="${t.assigned_robot}">R${t.assigned_robot}</button>`}</td><td>(${t.pickup_x},${t.pickup_y}) → (${t.delivery_x},${t.delivery_y})</td><td>${esc(a?.status??'—')} / ${esc(a?.proposal_count??'—')}</td><td>${released.has(t.id)?released.get(t.id)+' observed':'None retained'}</td></tr>`;}).join('')||'<tr><td colspan="6">No tasks match this filter.</td></tr>');
}
function renderAnomalies(){
    const current=[];
    for(const r of analytics.robots){
        if(r.status==='NEEDS_CHARGE'||blocked(r)||held(r)||r.battery<30)current.push({label:`R${r.id} · ${robotState(r)}`,tone:robotTone(r),detail:r.battery<30?`Battery ${r.battery.toFixed(1)}% · below the 30% display threshold. ${held(r)?'Intentional hold active.':''}`:explanation(r),when:'CURRENT SNAPSHOT'});
    }
    const retained=analytics.events.filter(e=>/DEADLOCK|TASK_REAUCTIONED|FAIL|ERROR|FALLBACK/.test(e.event_type)).slice(-50).reverse().map(e=>({label:e.event_type,tone:eventTone(e.event_type),detail:[e.robot_id!=null?'R'+e.robot_id:null,e.task_id!=null?'T'+e.task_id:null,e.reason,e.error_code].filter(Boolean).join(' · ')||'Recorded operational event',when:'EVENT · step '+(e.step??'—')}));
    const rows=[...current,...retained].slice(0,90);text('anomaly-count',`${current.length} current / ${retained.length} recent`);
    html('anomalies',rows.map(e=>`<div class="anomaly"><div><b data-tone="${e.tone}">${esc(e.label)}</b><small>${esc(e.when)}</small></div><p>${esc(e.detail)}</p></div>`).join('')||empty('NO OBSERVED ANOMALIES','Current state and retained events contain no matching energy, blocking, hold or recovery signals.'));
}
function render(){renderHeader();renderFleet();renderThroughput();renderHeat();renderChargers();renderAgent();renderTasks();renderAnomalies();freshness();}
function freshness(){
    const age=analytics.lastGood?(Date.now()-analytics.lastGood)/1000:null;
    const stale=age==null||age>4||analytics.error;
    text('connection',stale?(age==null?'API CONNECTING / RETRYING':`STALE ${age.toFixed(1)}s · RECONNECTING`):'API CONNECTED');tone('connection',stale?'charging':'healthy');
    text('freshness',analytics.error?'API ERROR · '+analytics.error:age==null?'Awaiting telemetry':`State age ${age.toFixed(1)}s · 1s polling`);
    text('diagnostic-freshness',analytics.detailError?'EVIDENCE STALE · '+analytics.detailError:analytics.lastDetail?`Evidence age ${((Date.now()-analytics.lastDetail)/1000).toFixed(1)}s · bounded windows`:'Evidence awaiting API');
}
async function poll(){
    try{
        const before=await get('/simulation/status');
        const newRun=before.run_id!==analytics.status?.run_id;
        const core=Promise.all([get('/robots'),get('/tasks'),get('/agents/status')]);
        const needsDetail=newRun||Date.now()-analytics.lastDetail>2000;
        const detail=needsDetail?Promise.all([get('/orchestrator/events?limit=500'),get('/agents/message-history'),get('/auction/logs'),get('/tasks/agents')]).then(([events,bus,auctions,tasks])=>({run:events.run_id,events:events.events,messages:bus.messages,auctions,taskAgents:tasks.task_agents})).catch(error=>({error:error.message})):Promise.resolve(null);
        const key=`${before.run_id}:${before.grid_revision}`;
        const gridPromise=analytics.gridKey!==key?get('/warehouse/grid'):Promise.resolve(analytics.grid);
        const [[robots,tasks,agents],details,grid]=await Promise.all([core,detail,gridPromise]);
        const after=await get('/simulation/status');
        if(before.run_id!==after.run_id||before.grid_revision!==after.grid_revision||details?.run&&details.run!==after.run_id)throw Error('Run/grid changed during snapshot; refreshing');
        accept(after,robots,tasks,agents.agents,grid,details&&!details.error?details:null);
        if(details?.error){if(analytics.detailError!==details.error)console.warn('[UI][EVIDENCE_ERROR]',details.error);analytics.detailError=details.error;}
        if(analytics.gridKey!==key){analytics.gridKey=key;renderHeatFloor();}
        analytics.lastGood=Date.now();if(analytics.error)console.info('[UI][API_RECOVERED] Agent analytics');analytics.error=null;render();
    }catch(error){if(analytics.error!==error.message)console.warn('[UI][API_ERROR]',error.message);analytics.error=error.message;freshness();}
}
function selectRobot(id){if(!analytics.robots.some(r=>r.id===id))return;analytics.selected=id;analytics.follow=true;renderFleet();renderHeat();renderAgent();}
document.addEventListener('DOMContentLoaded',()=>{
    for(const id of ['fleet-filter','fleet-sort'])$(id).addEventListener('change',renderFleet);
    $('task-filter').addEventListener('change',renderTasks);$('heat-mode').addEventListener('change',renderHeat);
    const choose=e=>{const row=e.target.closest('[data-robot]');if(row)selectRobot(Number(row.dataset.robot));};
    for(const id of ['fleet-list','task-rows','heat-robots'])$(id).addEventListener('click',choose);
    $('heat-robots').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(e);}});
    $('agent-trace').addEventListener('scroll',()=>{const el=$('agent-trace');if(el.scrollHeight-el.scrollTop-el.clientHeight>24){analytics.follow=false;text('trace-follow','PAUSED-FOLLOW');$('trace-follow').setAttribute('aria-pressed','false');}});
    $('trace-follow').addEventListener('click',()=>{analytics.follow=!analytics.follow;renderTrace(analytics.robots.find(r=>r.id===analytics.selected));});
    render();console.info('[UI][BOOT] Agent Analytics');
    const loop=async()=>{await poll();setTimeout(loop,1000);};loop();setInterval(freshness,1000);
});
