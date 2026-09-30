"""Optional Edge/Playwright UI checks. Use a DEDICATED API; real checks reset it.

Lifecycle fixtures below intercept browser responses only. They do not claim live
Ollama execution. Real override integration is covered by test_crisis_page.py.
"""
import argparse
import copy
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect


def verify(url, output):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width':1440, 'height':900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())
        page.goto(url+'/OperationCenter')
        page.locator('nav a[href="/CrisisOrchestration"]').click()
        expect(page).to_have_url(url+'/CrisisOrchestration')
        expect(page.locator('#connection')).to_have_text('API CONNECTED')
        expect(page.locator('#robot-layer .robot')).to_have_count(40)
        page.locator('[data-control="reset"]').click()
        expect(page.locator('#header-step')).to_have_text('0')
        expect(page.locator('#incident-headline')).to_have_text('SYSTEM NOMINAL')
        for w,h in [(1366,768),(1440,900),(1920,1080)]:
            page.set_viewport_size({'width':w,'height':h})
            assert page.evaluate('document.documentElement.scrollHeight<=innerHeight && document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(output/f'idle-{w}x{h}.png'))
        page.locator('[data-control="step"]').click()
        expect(page.locator('#header-step')).to_have_text('1')
        page.locator('[data-control="start"]').click()
        expect(page.locator('#simulation-state')).to_have_text('RUNNING')
        page.wait_for_function("Number(document.querySelector('#header-step').textContent)>=5")
        page.locator('[data-control="pause"]').click()
        expect(page.locator('#simulation-state')).to_have_text('PAUSED')
        page.locator('#robot-layer [data-robot="1"]').click()
        expect(page.locator('#robot-detail')).to_contain_text('R1')
        page.locator('#inject-crisis').click()
        expect(page.locator('#timeline .incident-item').first).to_be_visible()
        expect(page.locator('#crisis-layer .crisis-cell')).to_have_count(3)
        page.screenshot(path=str(output/'real-injected-crisis.png'))
        page.locator('nav a[href="/OperationCenter"]').click()
        expect(page.locator('#connection-status')).to_have_text('API CONNECTED')
        expect(page.locator('#warehouse-map .robot')).to_have_count(40)
        # Capture actual payload shapes, then cancel any local request via existing reset.
        assert page.request.post(url+'/simulation/reset',data={}).ok
        grid=page.request.get(url+'/warehouse/grid').json()
        robots=page.request.get(url+'/robots').json()
        tasks=page.request.get(url+'/tasks').json()
        results.append('REAL: page routes, both navigation directions, 40 robots/grid, start/pause/step/reset, robot selection, manual crisis')

        state=page.request.get(url+'/simulation/status').json()
        run=state['run_id']; cid=run+':crisis_0001'; pid=cid+':plan_001'
        # Browser-only, explicitly labelled fixtures for deterministic rare-state coverage.
        world={'status':state,'grid':grid,'robots':robots,'tasks':tasks,'events':[], 'fail':False,'posts':[]}
        world['orch']={'run_id':run,'active':True,'crisis_id':cid,'crisis_kind':'STRUCTURAL_COLLAPSE',
            'plan_id':pid,'active_node':'generate_plan','affected_robots':[1,2],
            'crisis_location':[[15,14],[16,14],[17,14]],'queued_crises':1,'queued_crisis_ids':[run+':crisis_0002'],
            'max_pending_crisis':5,'validation_status':'PENDING','validation_score':None,'validation_issues':[],
            'regeneration_count':0,'waiting_for_human':False,'proposed_plan':None,'fallback_used':False}
        def emit(kind, **extra):
            n=len(world['events'])+1
            world['events'].append({'event_type':kind,'event_id':f'{run}:event_{n:06}', 'run_id':run,
                'crisis_id':cid,'plan_id':world['orch']['plan_id'],'timestamp':1750000000+n,'step':240,**extra})
        def review():
            o=world['orch'];o.update(active_node='waiting_for_human',validation_status='VALID',validation_score=.96,
                waiting_for_human=True,validation_issues=[{'level':'WARNING','code':'LONG_HOLD','message':'Long hold requires operator review.','robot_id':1}],
                proposed_plan={'actions':[{'robot_id':1,'action':'HOLD','hold_steps':8+o['regeneration_count'],'reason':'Allow the blocked corridor to clear.'},
                    {'robot_id':2,'action':'REROUTE','waypoint':{'x':18,'y':14},'reason':'Use the adjacent walkable aisle.'}],'rationale':'Separate the affected movement.'})
            emit('LLM_SUCCESS',model='gemma4:12b',latency_ms=13828,actions=2)
            emit('PLAN_PARSED',actions=2)
            emit('VALIDATOR_PASS',validation_score=.96,errors=0,warnings=1,graph_node='validate',codes=['LONG_HOLD'])
            emit('HITL_REQUESTED',validation_score=.96)
        def serve(route):
            path=urlparse(route.request.url).path
            if path.startswith('/static/') or path in ('/CrisisOrchestration','/OperationCenter'):
                return route.continue_()
            if world['fail'] and path=='/orchestrator/state':
                return route.fulfill(status=503,json={'detail':'UI test outage'})
            if path=='/orchestrator/override':
                body=route.request.post_data_json;world['posts'].append(body)
                assert body['plan_id']==world['orch']['plan_id']
                if body['approved']:
                    emit('HITL_APPROVED');emit('ACTION_OK',robot_id=1,action='HOLD');emit('ACTION_OK',robot_id=2,action='REROUTE')
                    emit('ORCH_COMPLETE',executed_actions=2,duration_ms=18000,fallback=False)
                    world['orch'].update(active=False,active_node='complete',waiting_for_human=False,human_approved=True,approval_source='human',executed_actions=2)
                else:
                    emit('HITL_REJECTED');emit('PLAN_REGENERATED',attempt=1)
                    world['orch'].update(plan_id=cid+':plan_002',regeneration_count=1)
                    emit('LLM_REQUEST',model='gemma4:12b');review()
                return route.fulfill(json={'success':True,'message':'Fixture decision recorded'})
            payload={'/simulation/status':world['status'],'/orchestrator/state':world['orch'],
                '/orchestrator/events':{'run_id':run,'events':world['events']},'/robots':world['robots'],
                '/tasks':world['tasks'],'/warehouse/grid':world['grid']}.get(path)
            if payload is not None:return route.fulfill(json=payload)
            return route.continue_()
        page.route(url+'/**',serve)
        emit('CRISIS_CREATED',crisis_location=world['orch']['crisis_location'],affected=[1,2])
        emit('ORCH_START',crisis_kind='STRUCTURAL_COLLAPSE',affected=[1,2]);emit('DIAGNOSE',graph_node='diagnose')
        emit('LLM_REQUEST',model='gemma4:12b',attempt=1)
        page.goto(url+'/CrisisOrchestration')
        expect(page.locator('#kpi-node')).to_have_text('generate_plan')
        expect(page.locator('#model-detail')).to_contain_text('IN FLIGHT')
        expect(page.locator('#timeline .incident-item')).to_have_count(2)
        page.locator('#timeline [data-crisis="'+run+':crisis_0002"]').click()
        expect(page.locator('#incident-status')).to_have_text('QUEUED')
        expect(page.locator('#plan-detail')).to_contain_text('No plan generated')
        page.locator('#follow-active').click()
        expect(page.locator('#incident-status')).to_have_text('ACTIVE')
        review()
        expect(page.locator('#hitl-review')).to_be_visible()
        expect(page.locator('#validation-detail')).to_contain_text('PASS')
        expect(page.locator('#model-detail')).to_contain_text('13.83s')
        page.locator('#map-robot').select_option('1')
        expect(page.locator('#robot-detail')).to_contain_text('R1')
        for w,h in [(1366,768),(1440,900),(1920,1080)]:
            page.set_viewport_size({'width':w,'height':h})
            assert page.evaluate('document.documentElement.scrollHeight<=innerHeight && document.documentElement.scrollWidth<=innerWidth')
            assert page.locator('#impact-map').bounding_box()['height']>140
            assert page.locator('.plan-scroll').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
            page.screenshot(path=str(output/f'fixture-review-{w}x{h}.png'))
        page.locator('#reject-plan').click()
        expect(page.locator('#plan-detail')).to_contain_text('plan_002')
        expect(page.locator('#branch-state')).to_contain_text('OPERATOR REVIEW')
        page.locator('#approve-plan').click()
        expect(page.locator('#incident-status')).to_have_text('COMPLETE')
        expect(page.locator('#plan-detail')).to_contain_text('ACTION_OK')
        expect(page.locator('#hitl-review')).not_to_be_visible()
        assert world['posts']==[{'approved':False,'plan_id':pid},{'approved':True,'plan_id':cid+':plan_002'}]
        page.screenshot(path=str(output/'fixture-complete.png'))
        results.append('FIXTURES: queued/active selection, model request/latency, parsed actions, validation warning, reject/regenerate and approve payloads, execution receipts/completion')
        # Failure modes and malformed values cannot break the desk or expose approval.
        for code in ['LLM_TIMEOUT','LLM_UNAVAILABLE','LLM_INVALID_JSON','LLM_SCHEMA_ERROR','PLAN_VALIDATION_FAILED','ACTION_EXECUTION_FAILED']:
            world['orch'].update(active=True,active_node='fallback',waiting_for_human=False,validation_status='INVALID',validation_score=.4,validation_issues=[
                {'level':'ERROR','code':code,'message':'Long failure detail '+('reachable route validation ' * 12),'robot_id':1}],
                fallback_used=True,fallback_reason=code,error_code=code,proposed_plan=None)
            emit('LLM_FAILURE' if code.startswith('LLM_') else 'ACTION_FAILED',error_code=code)
            emit('FALLBACK_ACTIVATED',reason=code,fallback=True)
            expect(page.locator('#branch-state')).to_contain_text(code)
            expect(page.locator('#hitl-review')).not_to_be_visible()
            assert page.locator('.plan-scroll').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
        page.set_viewport_size({'width':1366,'height':768})
        page.screenshot(path=str(output/'fixture-fallback-1366x768.png'))
        for _ in range(220):emit('ACTION_OK',robot_id=1,action='HOLD')
        expect(page.locator('#trace .trace-row')).to_have_count(200)
        page.locator('#trace').evaluate('(e)=>e.scrollTop=0')
        expect(page.locator('#trace-follow')).to_have_text('PAUSED-FOLLOW')
        retained=page.locator('#trace').inner_html()
        emit('ORCH_COMPLETE',duration_ms=10000,executed_actions=1,fallback=True)
        world['orch'].update(active=False,active_node='complete')
        expect(page.locator('#kpi-active')).to_have_text('NONE')
        assert page.locator('#trace').inner_html()==retained
        page.locator('#trace-follow').click()
        expect(page.locator('#trace')).to_contain_text('ORCH_COMPLETE')
        world['fail']=True
        expect(page.locator('#connection')).to_contain_text('RECONNECTING',timeout=12000)
        expect(page.locator('#approve-plan')).to_be_disabled()
        expect(page.locator('#robot-layer .robot')).to_have_count(40)
        world['fail']=False
        expect(page.locator('#connection')).to_have_text('API CONNECTED',timeout=12000)
        world['status']['simulation_complete']=True
        expect(page.locator('#simulation-state')).to_have_text('COMPLETE')
        expect(page.locator('#connection')).to_have_text('API CONNECTED')
        results.append('FIXTURES: all listed failure codes, fallback, long-issue wrap, 200-row trace cap, paused-follow, API outage/recovery, completed-run connectivity')
        assert not errors,errors
        browser.close()
    report={'results':results,'viewports':[[1366,768],[1440,900],[1920,1080]],'js_errors':errors}
    (output/'browser-checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:8011')
    parser.add_argument('--output',type=Path,default=Path('evaluation_results/crisis_desk'))
    args=parser.parse_args()
    verify(args.url.rstrip('/'),args.output)
