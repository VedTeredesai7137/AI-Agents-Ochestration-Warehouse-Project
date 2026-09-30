const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function runtime() {
    const nodes = new Map();
    const node = id => {
        if (!nodes.has(id)) nodes.set(id, {style:{}, dataset:{}, classList:{add(){}, remove(){}},
            innerHTML:'', textContent:'', disabled:false});
        return nodes.get(id);
    };
    const context = vm.createContext({document:{getElementById:node, addEventListener(){}},
        console:{log(){},error(){}}, AbortSignal, setTimeout});
    vm.runInContext(fs.readFileSync('frontend/js/OperationCentre.js','utf8'),context);
    return {context,node};
}

test('structured actions, score, fallback and queue render safely', () => {
    const {context,node}=runtime();
    vm.runInContext(`state.orchestrator={active:false,crisis_id:'c1',plan_id:'p1',active_node:'complete',
        affected_robots:[1],validation_score:0.96,validation_status:'VALID',validation_issues:[{level:'WARNING'}],
        fallback_used:true,fallback_reason:'LLM_TIMEOUT',queued_crises:2,
        proposed_plan:{actions:[{robot_id:1,action:'HOLD',hold_steps:8,reason:'<img src=x onerror=alert(1)>'}]}};
        updateOrchestrator();`,context);
    const html=node('orchestrator-content').innerHTML;
    assert.match(html,/Validation Score/);
    assert.match(html,/0 errors \/ 1 warnings/);
    assert.match(html,/FALLBACK ACTIVE/);
    assert.match(html,/Queued crises/);
    assert.match(html,/HOLD/);
    assert.doesNotMatch(html,/<img/);
    assert.match(html,/&lt;img/);
});

test('invalid plans do not show approval overlay', () => {
    const {context,node}=runtime();
    vm.runInContext(`state.orchestrator={active:true,crisis_id:'c',active_node:'generate_plan',
        validation_status:'INVALID',validation_score:null,validation_issues:[{level:'ERROR'}],waiting_for_human:false};
        updateOrchestrator();`,context);
    assert.match(node('orchestrator-content').innerHTML,/PLAN REJECTED BY VALIDATOR/);
    assert.equal(node('hitl-overlay').style.display,'none');
});


test('event categories preserve actual source types',()=>{
 const {context}=runtime();
 for(const [type,expected] of [['LLM_SUCCESS','LLM'],['TASK_AWARDED','CNP'],['BLOCKED_PATH','DEADLOCK'],['LOW_BATTERY','CHARGING'],['VALIDATOR_PASS','ORCH'],['ALL_TASKS_COMPLETED','SYSTEM']])
  assert.equal(vm.runInContext(`category('${type}')`,context),expected);
});

test('malformed state is rejected, not silently treated as a completed run',()=>{
 const {context}=runtime();
 assert.throws(()=>vm.runInContext(`validData('/simulation/status',{running:false})`,context),/Malformed API response/);
 assert.throws(()=>vm.runInContext(`validData('/robots',[{id:1,position:null}])`,context),/Malformed API response/);
});

test('invalid plan cannot expose approval even if waiting flag is inconsistent',()=>{
 const {context,node}=runtime();
 vm.runInContext(`state.orchestrator={active:true,crisis_id:'c',active_node:'validate',validation_status:'INVALID',validation_issues:[{level:'ERROR'}],waiting_for_human:true};updateOrchestrator();`,context);
 assert.equal(node('hitl-overlay').style.display,'none');
});

test('event views remain bounded and pause-follow preserves the reading snapshot',()=>{
 const {context,node}=runtime();
 vm.runInContext(`state.events=Array.from({length:300},(_,i)=>({event_id:'e'+i,event_type:'ACTION_OK',timestamp:i,robot_id:1,reason:'<script>bad</script>'}));renderEvents();`,context);
 const original=node('event-list').innerHTML;
 assert.equal((original.match(/class="event-row"/g)||[]).length,100);
 assert.doesNotMatch(original,/<script>/);
 vm.runInContext(`state.tape.follow=false;state.events=[];renderEvents();`,context);
 assert.equal(node('event-list').innerHTML,original);
 assert.equal(node('tape-follow').textContent,'PAUSED-FOLLOW');
});

test('complete run remains connected and has a non-modal completion banner',()=>{
 const {context,node}=runtime();
 // These functions use only text/style/disabled fields, so the lightweight DOM suffices.
 vm.runInContext(`state.simStatus={running:false,simulation_complete:true,run_id:'run_123',seed:42,current_step:2043,total_tasks:120,unfinished_tasks:0};state.lastGood=Date.now();state.lastSlow=Date.now();updateHeader();updateConnectivity();`,context);
 assert.equal(node('header-sim-status').textContent,'COMPLETE');
 assert.equal(node('connection-status').textContent,'API CONNECTED');
 assert.equal(node('completion-banner').hidden,false);
 assert.equal(node('control-start').disabled,true);
 assert.equal(node('control-reset').disabled,false);
});


test('fallback KPI counts completed orchestrations, excluding routine recovery',()=>{
 const {context,node}=runtime();
 vm.runInContext(`state.simStatus={total_tasks:120,unfinished_tasks:120};state.lastSlow=Date.now();state.events=[{event_type:'FALLBACK_ACTIVATED',reason:'DETERMINISTIC_DEADLOCK'},{event_type:'ORCH_COMPLETE',fallback:true},{event_type:'LLM_REQUEST'}];updateMetrics();`,context);
 assert.equal(node('kpi-llm').textContent,'1 / 1');
});


test('late HITL response cannot overwrite a new run or new plan',async()=>{
 const {context}=runtime();
 vm.runInContext(`state.simStatus={running:false};state.lastGood=Date.now();state.lastSlow=Date.now();state.orchestrator={plan_id:'old',waiting_for_human:true,validation_status:'VALID',validation_issues:[]};globalThis.fetch=()=>new Promise(resolve=>globalThis.finishRequest=resolve);`,context);
 const pending=vm.runInContext('orchestratorOverride(false)',context);
 vm.runInContext(`state.epoch++;state.overrideEpoch++;state.overridePending=false;state.orchestrator={plan_id:'new',waiting_for_human:true};finishRequest({ok:true,json:async()=>({success:true})});`,context);
 await pending;
 assert.equal(vm.runInContext('state.orchestrator.plan_id',context),'new');
 assert.equal(vm.runInContext('state.orchestrator.waiting_for_human',context),true);
});


test('stored layout rejects corrupt, nonnumeric and excessive values',()=>{
 const {context}=runtime();
 for(const raw of ['not-json','null','[]','{"rightPanelWidth":-1,"eventTapeHeight":"200"}','{"rightPanelWidth":100000}'])
  assert.equal(vm.runInContext(`Object.keys(layoutPreferences(${JSON.stringify(raw)})).length`,context),0);
 assert.equal(vm.runInContext(`layoutPreferences('{"rightPanelWidth":420,"eventTapeHeight":180}').rightPanelWidth`,context),420);
});

test('layout clamps retain minimum pane sizes and half-width floor plan',()=>{
 const {context}=runtime();
 for(const [width,height]of [[1366,560],[1440,660],[1920,830]]) {
  vm.runInContext(`globalThis.bounds=layoutBounds(${width},${height});`,context);
  assert.equal(vm.runInContext('clampPane(5,bounds.rightPanelWidth)',context),320);
  assert.ok(vm.runInContext('clampPane(9000,bounds.rightPanelWidth)',context)<=width*.5);
  assert.ok(vm.runInContext('clampPane(9000,bounds.eventTapeHeight)',context)<=height-360);
  assert.equal(vm.runInContext('clampPane(-50,bounds.eventTapeHeight)',context),96);
 }
});

test('semantic attention prioritizes actual faults and successful resolution',()=>{
 const {context,node}=runtime();
 for(const [type,tone]of [['LLM_FAILURE','danger'],['DEADLOCK_RESOLVED','success'],['VALIDATOR_PASS','success'],['HITL_REQUESTED','warning'],['HEALTH','quiet']])
  assert.equal(vm.runInContext(`eventTone('${type}')`,context),tone);
 vm.runInContext(`state.simStatus={total_tasks:120,unfinished_tasks:120};state.orchestrator={active:false,queued_crises:0};updateMetrics();`,context);
 assert.equal(node('kpi-crisis').dataset.tone,'quiet');
 vm.runInContext(`state.orchestrator={active:true,queued_crises:1,fallback_used:true};state.robots=[{id:1,status:'NEEDS_CHARGE',battery:2}];updateMetrics();`,context);
 assert.equal(node('kpi-crisis').dataset.tone,'danger');
 assert.equal(node('kpi-llm').dataset.tone,'warning');
 assert.equal(node('kpi-charging').dataset.tone,'danger');
 assert.equal(node('kpi-charging').textContent,'0 / 1');
 assert.equal(node('charge-label').textContent,'CHARGE / STOP');
});
