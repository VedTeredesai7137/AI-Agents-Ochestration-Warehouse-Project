"""Optional rendered checks on a dedicated local server; HTTP inference is mocked."""
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
import uvicorn
from playwright.sync_api import sync_playwright, expect
from backend import api
from backend.agents.plans import PlanError


class UnavailableFreeModel:
    provider = "openrouter"
    model = "openai/gpt-oss-120b:free"
    last_response = {"http_status":404, "failure_type":"LLM_PROVIDER_UNAVAILABLE",
                     "provider_error":"This model is unavailable for free."}

    def generate(self, prompt, schema):
        raise PlanError("LLM_UNAVAILABLE", "OpenRouter HTTP 404: This model is unavailable for free.", **self.last_response)


def main():
    output = Path("evaluation_results/system_overview")
    output.mkdir(parents=True, exist_ok=True)
    api.simulation.orchestrator_runner.client = UnavailableFreeModel()
    api.simulation.settings = api.simulation.settings.model_copy(update={"crisis_budget":6})
    server = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1",port=8779,log_level="warning"))
    worker = threading.Thread(target=server.run,daemon=True)
    worker.start()
    root = "http://127.0.0.1:8779"
    for _ in range(50):
        if server.started:
            break
        time.sleep(.1)
    checks, errors = [], []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge",headless=True)
            page = browser.new_page()
            page.on("pageerror",lambda error: errors.append(str(error)))
            page.on("dialog",lambda dialog: dialog.accept())
            page.goto(root+"/SystemOverview")
            expect(page.locator("#connection")).to_have_text("API CONNECTED")
            expect(page.locator("#fleet-size")).to_have_text("40")
            expect(page.locator("#type-total")).to_have_text("5")
            for width,height in ((1366,768),(1440,900),(1920,1080)):
                page.set_viewport_size({"width":width,"height":height})
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth && document.documentElement.scrollHeight<=innerHeight")
                assert page.locator(".recovery-flow").is_visible()
                page.screenshot(path=str(output/f"overview-{width}x{height}.png"))
                checks.append(f"Overview {width}x{height}: no document overflow")
            page.locator("#story-scroll").evaluate("el=>el.scrollTop=el.scrollHeight")
            page.screenshot(path=str(output/"overview-playbook.png"))
            page.locator('nav a[href="/CrisisOrchestration"]').click()
            expect(page.locator("#connection")).to_have_text("API CONNECTED")
            page.set_viewport_size({"width":1440,"height":900})
            page.locator("#crisis-kind").select_option("ROBOT_IMMOBILIZED")
            page.locator("#inject-crisis").click()
            expect(page.locator("#model-detail")).to_contain_text("404")
            expect(page.locator("#model-detail")).to_contain_text("unavailable for free")
            expect(page.locator("#budget-summary")).to_contain_text("1 / 6")
            assert requests.get(root+"/robots",timeout=5).json()[0]["fault_reason"] is None
            page.screenshot(path=str(output/"crisis-provider-error.png"))
            checks.append("Injected transport failure: provider/model/404/reason visible; fallback cleared immobilization; one budget slot")
            for route,indicator in (("/OperationCenter","#connection-status"),("/AgentAnalytics","#connection"),("/SystemOverview","#connection")):
                page.locator(f'nav a[href="{route}"]').click()
                expect(page.locator(indicator)).to_have_text("API CONNECTED")
            checks.append("Navigation across Operations, Crisis, Analytics and Overview")
            page.route("**/simulation/status",lambda route:route.fulfill(status=503,json={"detail":"Browser fixture outage"}))
            expect(page.locator("#connection")).to_have_text("API STALE",timeout=10000)
            assert page.locator(".architecture").is_visible()
            checks.append("API failure leaves the architecture guide readable")
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=5)
        api.simulation.close()
    result = {"checks":checks,"page_errors":errors,"inference":"mocked; no network model call"}
    (output/"checks.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
