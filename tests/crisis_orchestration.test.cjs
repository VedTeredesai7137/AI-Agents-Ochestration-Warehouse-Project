const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function runtime(){
 const nodes=new Map();const node=id=>{if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',dataset:{},hidden:false,disabled:false,setAttribute(){},scrollHeight:0,scrollTop:0});return nodes.get(id);};
 const context=vm.createContext({document:{getElementById:node,addEventListener(){},querySelectorAll(){return[];}},structuredClone,Date,AbortSignal,console});
 vm.runInContext(fs.readFileSync('frontend/js/CrisisOrchestration.js','utf8'),context);
 const run=code=>vm.runInContext(code,context);
 run(`const base={run_id:'r',current_step:10,running:false,simulation_complete:false};
 const orch={run_id:'r',active:true,crisis_id:'r:c1',plan_id:'r:c1:p1',crisis_kind:'STRUCTURAL_COLLAPSE',
 queued_crises:0,affected_robots:[1],crisis_location:[[3,4]],active_node:'waiting_for_human',
 validation_status:'VALID',validation_score:0.96,validation_issues:[{level:'WARNING',code:'LONG_HOLD',message:'Review'}],
 waiting_for_human:true,proposed_plan:{actions:[{robot_id:1,action:'HOLD',hold_steps:8,reason:'<img src=x onerror=alert(1)>'}]}};
 const ev=(type,n,extra={})=>({run_id:'r',event_id:'e'+String(n).padStart(6,'0'),timestamp:n,event_type:type,crisis_id:'r:c1',plan_id:'r:c1:p1',...extra});
 ingest(base,orch,[ev('LLM_REQUEST',1,{model:'gemma4:12b'}),ev('LLM_SUCCESS',2,{latency_ms:14000}),ev('PLAN_PARSED',3),ev('VALIDATOR_PASS',4,{validation_score:.96})]);desk.lastGood=Date.now();`);
 return {run,node};
}
test('plan rendering escapes model text and distinguishes proposal from commit',()=>{
 const {run,node}=runtime();run('renderIncident()');
 assert.match(node('plan-detail').innerHTML,/PROPOSED/);assert.doesNotMatch(node('plan-detail').innerHTML,/<img/);assert.match(node('plan-detail').innerHTML,/&lt;img/);
 run(`desk.events.push(ev('ACTION_OK',5,{robot_id:1,action:'HOLD'}));ingest(base,orch,desk.events);renderIncident()`);
 assert.match(node('plan-detail').innerHTML,/ACTION_OK/);
});
test('HITL requires fresh valid active exact plan and no errors',()=>{
 const {run}=runtime();assert.equal(run('canReview()'),true);
 for(const change of ["desk.failure='offline'","desk.lastGood=0","desk.orchestrator.active=false","desk.orchestrator.validation_status='INVALID'","desk.orchestrator.plan_id='different'","desk.orchestrator.validation_issues=[{level:'ERROR'}]"]){
 const r=runtime();r.run(change);assert.equal(r.run('canReview()'),false,change);
 }
});
test('historical plan remains inspectable but cannot be approved',()=>{
 const {run}=runtime();run(`desk.followActive=false;ingest(base,{...orch,crisis_id:'r:c2',plan_id:'r:c2:p1'},[])`);
 assert.equal(run('selection().id'),'r:c1');assert.equal(run('canReview()'),false);
});
test('retry clears old actions and does not reuse earlier validator pass',()=>{
 const {run,node}=runtime();run(`ingest(base,{...orch,plan_id:'r:c1:p2',proposed_plan:null,validation_status:'PENDING',validation_score:null,validation_issues:[],active_node:'generate_plan'},[ev('LLM_REQUEST',6,{plan_id:'r:c1:p2'})]);renderIncident()`);
 assert.doesNotMatch(node('plan-detail').innerHTML,/HOLD/);assert.match(node('validation-detail').innerHTML,/NOT YET VALIDATED/);
 assert.equal(run('pipelineStages(selection())[2].tone'),'quiet');
});
test('JSON/schema failure is not depicted as an observed safety-validation node',()=>{
 const {run,node}=runtime();run(`ingest(base,{...orch,plan_id:'r:c1:p2',proposed_plan:null,validation_status:'INVALID',validation_score:null,validation_issues:[]},[ev('LLM_FAILURE',6,{plan_id:'r:c1:p2',error_code:'LLM_SCHEMA_ERROR'}),ev('INVALID_PLAN',7,{plan_id:'r:c1:p2',codes:['LLM_SCHEMA_ERROR']})]);renderIncident()`);
 assert.match(node('validation-detail').innerHTML,/SCHEMA REJECTED/);assert.equal(run('pipelineStages(selection())[2].tone'),'quiet');
});
test('completion is distinct from first-movement recovery and fallback remains explicit',()=>{
 const {run}=runtime();run(`ingest(base,{...orch,active:false,active_node:'complete',fallback_used:true,fallback_reason:'LLM_TIMEOUT'},[ev('ORCH_COMPLETE',8,{fallback:true,duration_ms:60000,executed_actions:0})])`);
 assert.equal(run('selection().status'),'FALLBACK');assert.equal(run('Boolean(selection().recovered)'),false);
});
test('queued entries have no invented details and stale drops are retained',()=>{
 const {run}=runtime();run(`ingest(base,{...orch,queued_crises:1,queued_crisis_ids:['r:c2']},[]);selectCrisis('r:c2')`);
 assert.equal(run('selection().status'),'QUEUED');assert.equal(run('selection().kind'),'TYPE NOT RETAINED');assert.equal(run('selection().s.proposed_plan'),undefined);
 run(`ingest(base,{...orch,queued_crises:0,queued_crisis_ids:[]},[ev('STALE_DROPPED',10,{crisis_id:'r:c2',reason:'DEADLOCK_ALREADY_RESOLVED'})])`);
 assert.equal(run('selection().status'),'STALE DROPPED');
});
test('reset clears previous run, selection and observations',()=>{
 const {run}=runtime();run(`ingest({...base,run_id:'new'},{run_id:'new',active:false,queued_crises:0},[])`);
 assert.equal(run('desk.records.size'),0);assert.equal(run('desk.events.length'),0);assert.equal(run('desk.selected'),null);
});
test('event history, incident list and trace are bounded; pause-follow freezes trace',()=>{
 const {run,node}=runtime();run(`ingest(base,orch,Array.from({length:2500},(_,i)=>ev('ACTION_OK',i+10)));renderTrace(selection())`);
 assert.equal(run('desk.events.length'),2000);assert.equal((node('trace').innerHTML.match(/class="trace-row"/g)||[]).length,200);
 const original=node('trace').innerHTML;run(`desk.followTrace=false;desk.records.get('r:c1').events=[];renderTrace(selection())`);assert.equal(node('trace').innerHTML,original);
 run(`ingest(base,orch,Array.from({length:100},(_,i)=>ev('CRISIS_CREATED',i+3000,{crisis_id:'r:many'+i})))`);assert.ok(run('desk.records.size')<=40);
});
test('malformed endpoint payloads are rejected safely',()=>{
 const {run}=runtime();for(const code of ["validatePayload('/simulation/status',{})","validatePayload('/robots',[{id:1,position:null}])","validatePayload('/warehouse/grid',{width:2,height:2,grid:[[]]})","validatePayload('/orchestrator/state',{run_id:'r',active:true,queued_crises:0,proposed_plan:{actions:{}}})"])assert.throws(()=>run(code),/Malformed response/);
});
test('a changed plan at click-time sends no override request',async()=>{
 const {run,node}=runtime();
 await run(`(async()=>{let posts=0;api=async(path,body)=>{if(body)posts++;return {...orch,plan_id:'r:c1:new'};};poll=async()=>{};await override(true);if(posts)throw Error('stale plan submitted');})()`);
 assert.match(node('notice').textContent,/Plan changed/);
});
test('late approval response cannot overwrite a reset session',async()=>{
 const {run,node}=runtime();
 await run(`(async()=>{api=async(path,body)=>{if(!body)return structuredClone(orch);desk.epoch++;desk.orchestrator={run_id:'new',active:false};return {success:true};};poll=async()=>{};await override(true);})()`);
 assert.equal(run('desk.orchestrator.run_id'),'new');assert.notEqual(node('notice').textContent,'Approval accepted. Execution revalidates live safety.');
});
test('unchanged rendering preserves native expanded detail state',()=>{
 const {run,node}=runtime();run(`html('validation-detail','<details>report</details>')`);
 node('validation-detail').innerHTML='<details open>report</details>';
 run(`html('validation-detail','<details>report</details>')`);
 assert.match(node('validation-detail').innerHTML,/open/);
});
