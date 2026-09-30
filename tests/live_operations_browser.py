"""Opt-in visual/interaction checks. Use a dedicated API: these checks reset its run.
Requires playwright and installed Edge, separate from the normal pytest suite.
Network fixtures test rare UI states only; they never alter backend behavior.
"""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def check_splitpanes(page, out):
    """Drive real Pointer Events with mouse drags, then keyboard and persistence."""
    key='warehouse-swarm-operation-layout'
    results=[]
    def bounds():
        return page.evaluate("""() => Object.fromEntries(['operations-workspace','main-workspace','context-panel','event-tape','map-viewport'].map(id=>[id,document.getElementById(id).getBoundingClientRect().toJSON()]))""")
    def drag(id, dx=0, dy=0):
        box=page.locator('#'+id).bounding_box()
        x,y=box['x']+box['width']/2,box['y']+box['height']/2
        page.mouse.move(x,y)
        page.mouse.down()
        page.mouse.move(x+dx,y+dy,steps=12)
        page.mouse.up()
        expect(page.locator('body')).not_to_have_class('resizing')
    def check(name):
        b=bounds()
        assert b['context-panel']['width']>=319, b
        assert b['context-panel']['width']<=b['operations-workspace']['width']*.5+1, b
        assert b['event-tape']['height']>=95, b
        assert b['main-workspace']['height']>=359, b
        assert b['map-viewport']['height']>150, b
        assert page.evaluate('document.documentElement.scrollHeight<=innerHeight && document.documentElement.scrollWidth<=innerWidth')
        results.append({'configuration':name,'bounds':b})
        page.screenshot(path=str(out/(name+'.png')))
    for w,h in [(1366,768),(1440,900),(1920,1080)]:
        page.set_viewport_size({'width':w,'height':h})
        page.locator('#context-divider').dblclick()
        page.locator('#events-divider').dblclick()
        check(f'default-{w}x{h}')
        drag('context-divider',dx=w)
        drag('events-divider',dy=h)
        check(f'A-map-large-{w}x{h}')
        drag('context-divider',dx=-w)
        check(f'B-inspector-wide-{w}x{h}')
        page.locator('#context-divider').dblclick()
        drag('events-divider',dy=-h)
        check(f'C-events-tall-{w}x{h}')
        page.locator('#map-plus').click()
        zoom=page.locator('#map-zoom').inner_text()
        drag('context-divider',dx=40)
        expect(page.locator('#map-zoom')).to_have_text(zoom)
        page.locator('[data-robot-id="1"]').click()
        expect(page.locator('#agent-inspector-content')).to_contain_text('ROBOT 1')
        # Paused real API snapshot: resize must preserve grid coordinates and route.
        robot=next(r for r in page.request.get(page.url.rsplit('/',1)[0]+'/robots').json() if r['id']==1)
        x,y=robot['position']['x'],robot['position']['y']
        expect(page.locator('[data-robot-id="1"]')).to_have_attribute('transform',f'translate({x*20},{y*20})')
        if robot['path']:
            points=[[x,y],*robot['path']]
            expect(page.locator('.selected-route')).to_have_attribute('points',' '.join(f'{px*20+10},{py*20+10}' for px,py in points))
        page.locator('#map-fit').click()
        assert page.evaluate("parseFloat(document.querySelector('#warehouse-map').style.getPropertyValue('--marker-font'))<=16")
    # Pointer-up saves once. Reload must recover the actual requested dimensions.
    saved=page.evaluate(f'JSON.parse(localStorage.getItem("{key}"))')
    page.reload()
    expect(page.locator('.robot')).to_have_count(40)
    b=bounds()
    assert abs(b['context-panel']['width']-saved['rightPanelWidth'])<2
    assert abs(b['event-tape']['height']-saved['eventTapeHeight'])<2
    # Browser shrink clamps the view without destroying the saved preference.
    page.set_viewport_size({'width':1366,'height':768})
    page.wait_for_function("document.querySelector('#context-panel').getBoundingClientRect().width <= innerWidth/2")
    check('D-restored-clamped')
    handle=page.locator('#context-divider')
    handle.dblclick()
    before=int(handle.get_attribute('aria-valuenow'))
    handle.focus()
    handle.press('ArrowLeft')
    assert int(handle.get_attribute('aria-valuenow'))==before+10
    handle.press('Shift+ArrowLeft')
    assert int(handle.get_attribute('aria-valuenow'))==before+50
    handle.press('Home')
    assert int(handle.get_attribute('aria-valuenow'))==before
    page.locator('#diagnostics-open').click()
    page.locator('#reset-layout').click()
    assert page.evaluate(f'localStorage.getItem("{key}")') is None
    page.locator('#diagnostics-close').click()
    check('E-reset-defaults')
    # Invalid saved state safely falls back. Narrow screens keep their stacked layout.
    page.evaluate(f'localStorage.setItem("{key}", "corrupt")')
    page.reload()
    expect(page.locator('.robot')).to_have_count(40)
    assert abs(bounds()['context-panel']['width']-before)<2
    page.set_viewport_size({'width':900,'height':768})
    expect(page.locator('#context-divider')).to_be_hidden()
    page.set_viewport_size({'width':1440,'height':900})
    expect(page.locator('#context-divider')).to_be_visible()
    page.locator('#context-divider').dblclick()
    page.locator('#events-divider').dblclick()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8010')
    parser.add_argument('--output', default='evaluation_results/ui')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    checks, errors, layouts = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width':1440, 'height':900})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())
        page.goto(args.url+'/OperationCenter')
        expect(page.locator('.robot')).to_have_count(40)
        expect(page.locator('#connection-status')).to_have_text('API CONNECTED')
        page.locator('#control-reset').click()
        expect(page.locator('#header-step')).to_have_text('0')
        expect(page.locator('#control-step')).to_be_enabled()
        page.locator('#control-step').click()
        expect(page.locator('#header-step')).to_have_text('1')
        page.locator('#control-start').click()
        expect(page.locator('#header-sim-status')).to_have_text('RUNNING')
        page.locator('#control-pause').click()
        expect(page.locator('#header-sim-status')).to_have_text('PAUSED')
        checks.append('real start/pause/step/reset')
        # Exercise the actual simulation, including CNP, energy and charging.
        for _ in range(110):
            assert page.request.post(args.url+'/simulation/step').ok
        page.wait_for_function("parseInt(document.querySelector('#kpi-charging').textContent)>0")
        expect(page.locator('.charger-cell')).to_have_count(8)
        page.locator('[data-robot-id="1"]').click()
        expect(page.locator('#context-robot')).to_be_visible()
        expect(page.locator('#agent-inspector-content')).to_contain_text('ROBOT 1')
        # Readable Fit, coordinate placement, no document overflow at all requested sizes.
        for width,height in [(1440,900),(1366,768),(1920,1080)]:
            page.set_viewport_size({'width':width,'height':height})
            page.locator('#map-fit').click()
            page.wait_for_function("document.querySelector('#warehouse-map').getBoundingClientRect().width > document.querySelector('#map-viewport').clientWidth * .9")
            bounds=page.evaluate("""() => ({width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,map:document.querySelector('#warehouse-map').getBoundingClientRect().toJSON()})""")
            assert bounds['scrollWidth']<=width and bounds['scrollHeight']<=height, bounds
            assert bounds['map']['width']>width*.60, bounds
            layouts.append(bounds)
            page.screenshot(path=str(out/f'live-{width}x{height}.png'))
        checks.append('real movement/charging/selection and three viewport bounds')
        page.set_viewport_size({'width':1440,'height':900})
        page.locator('#map-plus').click()
        expect(page.locator('#map-zoom')).to_have_text('125%')
        page.locator('#map-fit').click()
        page.locator('[data-layer="chargers"]').uncheck()
        expect(page.locator('#charger-layer')).to_be_hidden()
        page.locator('[data-layer="chargers"]').check()
        checks.append('fit/zoom/layers')
        split_checks=check_splitpanes(page,out)
        checks.append('pointer resize A/B/C, persistence, viewport clamp, reset, keyboard, corrupt storage and mobile fallback')
        page.locator('[data-filter="CNP"]').click()
        page.wait_for_function("document.querySelectorAll('#event-list .event-row').length > 0")
        assert page.locator('#event-list .event-row:not([data-category="CNP"])').count()==0
        page.locator('#tape-follow').click()
        expect(page.locator('#tape-follow')).to_have_text('PAUSED-FOLLOW')
        held=page.locator('#event-list').inner_html()
        page.request.post(args.url+'/simulation/step')
        # Wait for visible step change instead of a fixed sleep.
        current=page.request.get(args.url+'/simulation/status').json()['current_step']
        expect(page.locator('#header-step')).to_have_text(str(current))
        assert page.locator('#event-list').inner_html()==held
        page.locator('#tape-follow').click()
        page.locator('#diagnostics-open').click()
        expect(page.locator('#diagnostics')).to_be_visible()
        expect(page.locator('#auction-content')).to_contain_text('Winner')
        page.locator('#diagnostics-close').click()
        checks.append('event category/follow and preserved diagnostics')
        page.locator('#tab-crisis').click()
        expect(page.locator('#orchestrator-content')).to_contain_text('NO ACTIVE CRISIS')
        page.locator('#inject-crisis').click()
        expect(page.locator('#crisis-feedback')).to_contain_text('Injected',timeout=15000)
        page.wait_for_function("document.querySelectorAll('.crisis-cell').length>0")
        page.screenshot(path=str(out/'real-crisis.png'))
        checks.append('real manual collapse/grid refresh/crisis cells')
        # External reset: run id, grid and selection must all refresh.
        old_run=page.request.get(args.url+'/simulation/status').json()['run_id']
        page.request.post(args.url+'/simulation/reset',data={'seed':100})
        page.wait_for_function('(old) => document.querySelector("#run-id").title !== old',arg=old_run)
        expect(page.locator('#robot-select')).to_have_value('')
        expect(page.locator('#seed')).to_have_text('100')
        checks.append('external reset/grid/selection invalidation')
        # Honest UI-only fixtures: server simulation remains unchanged.
        status=page.request.get(args.url+'/simulation/status').json()
        completed={**status,'simulation_complete':True,'unfinished_tasks':0,'current_step':2043,'running':False}
        def complete(route): route.fulfill(json=completed)
        page.route('**/simulation/status',complete)
        expect(page.locator('#header-sim-status')).to_have_text('COMPLETE')
        expect(page.locator('#completion-banner')).to_be_visible()
        expect(page.locator('#connection-status')).to_have_text('API CONNECTED')
        page.screenshot(path=str(out/'fixture-complete.png'))
        page.unroute('**/simulation/status',complete)
        checks.append('fixture completion keeps API connected')
        def malformed(route): route.fulfill(json={'unexpected':True})
        page.route('**/simulation/status',malformed)
        expect(page.locator('#connection-status')).to_have_text('API RECONNECTING',timeout=15000)
        expect(page.locator('.robot')).to_have_count(40)
        page.screenshot(path=str(out/'fixture-api-error.png'))
        page.unroute('**/simulation/status',malformed)
        expect(page.locator('#connection-status')).to_have_text('API CONNECTED',timeout=15000)
        checks.append('fixture malformed response/recovery retains map')
        status=page.request.get(args.url+'/simulation/status').json()
        review={'run_id':status['run_id'],'active':True,'active_node':'waiting_for_human','crisis_id':'fixture-crisis','crisis_kind':'STRUCTURAL_COLLAPSE','crisis_location':[[3,2]],'plan_id':'fixture-plan','affected_robots':[1],'validation_status':'VALID','validation_score':.96,'validation_issues':[{'level':'WARNING','code':'LONG_HOLD','message':'Operator review required'}],'waiting_for_human':True,'queued_crises':2,'regeneration_count':1,'proposed_plan':{'actions':[{'robot_id':1,'action':'HOLD','hold_steps':8,'reason':'Allow traffic to clear <unsafe markup>'}]}}
        def orch(route): route.fulfill(json=review)
        posted=[]
        def override(route):
            posted.append(route.request.post_data_json)
            review['waiting_for_human']=False
            review['active_node']='regenerating' if not posted[-1]['approved'] else 'execute'
            route.fulfill(json={'success':True})
        page.route('**/orchestrator/state',orch)
        page.route('**/orchestrator/override',override)
        expect(page.locator('#hitl-overlay')).to_be_visible(timeout=15000)
        expect(page.locator('#hitl-reject')).to_be_enabled()
        page.screenshot(path=str(out/'fixture-hitl.png'))
        page.locator('#hitl-reject').click()
        expect(page.locator('#hitl-overlay')).to_be_hidden()
        assert posted[-1]=={'approved':False,'plan_id':'fixture-plan'}
        review.update(waiting_for_human=True,active_node='waiting_for_human',plan_id='fixture-plan-2')
        expect(page.locator('#hitl-overlay')).to_be_visible(timeout=15000)
        expect(page.locator('#hitl-approve')).to_be_enabled()
        page.locator('#hitl-approve').click()
        expect(page.locator('#hitl-overlay')).to_be_hidden()
        assert posted[-1]=={'approved':True,'plan_id':'fixture-plan-2'}
        checks.append('fixture HITL reject/new-plan/approve exact plan ids')
        page.unroute('**/orchestrator/state',orch)
        page.unroute('**/orchestrator/override',override)
        page.request.post(args.url+'/simulation/pause')
        page.request.post(args.url+'/simulation/reset',data={'seed':42})
        assert not errors, errors
        browser.close()
    report={'checks':checks,'javascript_errors':errors,'viewports':layouts,'split_panes':split_checks,'note':'Real API controls and movement; rare completion/error/HITL states use explicit browser-only response fixtures.'}
    (out/'browser-checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
