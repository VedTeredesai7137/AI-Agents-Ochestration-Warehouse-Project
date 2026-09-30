"""Focused real-API checks against a dedicated development server (resets it)."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

URL = 'http://127.0.0.1:8012'
OUT = Path('evaluation_results/agent_analytics')
OUT.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    browser = pw.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    assert page.request.post(URL+'/simulation/reset', data={}).ok
    page.goto(URL+'/AgentAnalytics')
    expect(page.locator('#connection')).to_have_text('API CONNECTED')
    expect(page.locator('.fleet-row')).to_have_count(40)
    expect(page.locator('#task-rows tr')).to_have_count(120)
    expect(page.locator('#agent-summary')).to_contain_text('NO AGENT SELECTED')
    for target in ['/OperationCenter', '/CrisisOrchestration', '/AgentAnalytics']:
        page.locator(f'nav a[href="{target}"]').click()
        expect(page).to_have_url(URL+target)
    expect(page.locator('.fleet-row')).to_have_count(40)
    page.locator('.fleet-row').first.click()
    chosen = page.locator('#selected-label').inner_text()
    page.locator('#fleet-filter').select_option('idle')
    expect(page.locator('.fleet-row')).to_have_count(40)
    page.locator('#fleet-sort').select_option('battery-up')
    page.locator('#heat-mode').select_option('presence')
    expect(page.locator('#heat-caption')).to_contain_text('not proven congestion')
    for _ in range(30):
        assert page.request.post(URL+'/simulation/step').ok
    expect(page.locator('#step')).to_have_text('30', timeout=15000)
    expect(page.locator('#selected-label')).to_have_text(chosen)
    page.locator('#fleet-filter').select_option('all')
    page.wait_for_timeout(2500)
    assert page.evaluate('analytics.samples.length>=2')
    assert page.evaluate('fleetRows().every((r,i,a)=>!i || a[i-1].battery<=r.battery)')
    for w,h in [(1366,768),(1440,900),(1920,1080)]:
        page.set_viewport_size({'width':w,'height':h})
        assert page.evaluate('document.documentElement.scrollHeight<=innerHeight && document.documentElement.scrollWidth<=innerWidth')
        assert page.locator('#fleet-list').evaluate('(e)=>e.scrollHeight>e.clientHeight')
        assert page.locator('#task-rows').evaluate('(e)=>e.parentElement.parentElement.scrollHeight>e.parentElement.parentElement.clientHeight')
        page.screenshot(path=str(OUT/f'agents-{w}x{h}.png'))
    page.locator('#task-filter').select_option('complete')
    assert page.locator('#task-rows').inner_text()
    # A browser-only outage leaves the last valid fleet usable.
    page.route('**/simulation/status', lambda route: route.fulfill(status=503, json={'detail':'test outage'}))
    expect(page.locator('#freshness')).to_contain_text('API ERROR', timeout=15000)
    expect(page.locator('.fleet-row')).to_have_count(40)
    page.unroute('**/simulation/status')
    expect(page.locator('#connection')).to_have_text('API CONNECTED', timeout=15000)
    assert page.request.post(URL+'/simulation/reset',data={}).ok
    expect(page.locator('#step')).to_have_text('0',timeout=15000)
    expect(page.locator('#selected-label')).to_have_text('NONE')
    assert page.evaluate('analytics.samples.length===1 && analytics.observations.length===0')
    assert not errors, errors
    browser.close()
print('PASS: routes/navigation, 40 robots, 120 tasks, selection/filter/sort, polling, observations, reset, outage/recovery, three desktop viewports; zero page errors')
