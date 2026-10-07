'use strict';
// Architecture is documentation; the small telemetry strip is an observed snapshot.
let lastGood = 0;
const $ = id => document.getElementById(id);
async function refresh() {
    try {
        const results = await Promise.all(['/simulation/status','/orchestrator/state'].map(async path => {
            const response = await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(8000)});
            if(!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        }));
        const [s,o] = results;
        if(typeof s.run_id !== 'string' || !Number.isFinite(s.total_robots) || typeof o.active !== 'boolean') throw new Error('Malformed snapshot');
        if(s.run_id !== o.run_id) throw new Error('Run reset during read');
        lastGood = Date.now();
        $('run-id').textContent = s.run_id;
        $('step').textContent = s.current_step;
        $('sim-state').textContent = s.simulation_complete?'COMPLETE':s.running?'RUNNING':'PAUSED';
        $('fleet-size').textContent = s.total_robots;
        $('task-total').textContent = s.total_tasks;
        $('type-total').textContent = Array.isArray(s.crisis_types)?s.crisis_types.length:'—';
        $('budget-total').textContent = s.crisis_budget ?? '—';
        $('budget-state').textContent = `${s.crises_submitted ?? '—'} submitted / ${s.crisis_budget ?? '—'} budget · ${s.crises_remaining ?? '—'} remaining`;
        $('model-name').textContent = o.model || 'Not reported';
        $('provider-state').textContent = `${o.llm_provider || 'Not reported'} · ${o.llm_status || 'No request observed'}`;
        $('provider-error').textContent = o.provider_error || (o.error_code?`${o.error_code}: ${o.error || ''}`:'');
        const marks = $('agent-marks');
        if(marks.childElementCount !== Math.min(100,s.total_robots)) {
            marks.replaceChildren(...Array.from({length:Math.min(100,s.total_robots)},()=>document.createElement('i')));
        }
        $('connection').textContent = 'API CONNECTED';$('connection').className = 'connected';
        $('freshness').textContent = 'Live facts · refreshed every 5s';
    } catch(error) {
        $('connection').textContent = lastGood?'API STALE':'API UNAVAILABLE';$('connection').className = 'error';
        $('freshness').textContent = lastGood?`Last snapshot ${((Date.now()-lastGood)/1000).toFixed(0)}s ago`:'Architecture guide available; telemetry unavailable';
    } finally {
        setTimeout(refresh,5000); // No overlapping poll loops or unbounded history.
    }
}
document.addEventListener('DOMContentLoaded',refresh);
