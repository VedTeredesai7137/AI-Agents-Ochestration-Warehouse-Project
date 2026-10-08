'use strict';

const app = {
    rows: [], cursor: 0, oldestId: null, hasOlder: false, selectedId: null,
    level: 'ALL', category: 'ALL', search: '', follow: true,
    lastGood: 0, statusGood: 0, nextModelPoll: 0, runId: null,
    logBusy: false, statusBusy: false, modelBusy: false
};
const MAX_RUN_LOGS = 100000;
const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function getJson(path) {
    const response = await fetch(path, {cache:'no-store', signal:AbortSignal.timeout(8000)});
    if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
    return response.json();
}

function setStatus(status) {
    const nextRunId = status.run_id || '';
    if (app.runId && nextRunId && app.runId !== nextRunId) {
        app.rows = []; app.cursor = 0; app.oldestId = null; app.hasOlder = false; app.selectedId = null;
        $('buffer-note').textContent = 'New run started. Logs are retained from boot through completion.';
        render();
    }
    if (nextRunId) app.runId = nextRunId;
    $('run-id').textContent = nextRunId || '—';
    $('seed').textContent = Number.isInteger(status.seed) ? status.seed : '—';
    $('step').textContent = Number.isInteger(status.current_step) ? status.current_step.toLocaleString() : '—';
    let sim = status.simulation_complete ? 'COMPLETE' : status.running ? 'RUNNING' : 'PAUSED';
    $('simulation-state').textContent = sim;
    $('simulation-state').dataset.state = sim;
    app.statusGood = Date.now();
    updateConnection();
}

async function pollStatus() {
    if (app.statusBusy) return;
    app.statusBusy = true;
    try { setStatus(await getJson('/simulation/status')); }
    catch (_) { updateConnection(); }
    finally { app.statusBusy = false; }
}

async function pollModel() {
    if (app.modelBusy) return;
    app.modelBusy = true;
    try {
        const state = await getJson('/orchestrator/state');
        const provider = state.llm_provider || '';
        const model = state.model || '';
        $('model-name').textContent = model || provider || 'No model reported';
        $('model-name').title = [provider, model].filter(Boolean).join(' · ');
    } catch (_) {
        if (!$('model-name').textContent || $('model-name').textContent === 'Loading') $('model-name').textContent = 'Unavailable';
    } finally { app.modelBusy = false; }
}

function categoryOf(message) {
    if (/FALLBACK/i.test(message)) return 'FALLBACK';
    if (/LLM/i.test(message)) return 'LLM';
    if (/ORCH|VALIDATOR|EXECUTOR|HITL|PLAN/i.test(message)) return 'ORCH';
    if (/PATHFINDER|OBSTACLE BYPASS|DELIVERY PATH/i.test(message)) return 'PATHFINDER';
    if (/CHARGE|CHARGING/i.test(message)) return 'CHARGING';
    if (/\[ROBOT\]/i.test(message)) return 'ROBOT';
    if (/\bCNP\b|AUCTION|CFP|PROPOSAL/i.test(message)) return 'CNP';
    if (/CRISIS|DEADLOCK|CRISIS_QUEUE/i.test(message)) return 'CRISIS';
    if (/\[API\]|API request failed/i.test(message)) return 'API';
    return 'SIM';
}

function timeOf(timestamp) {
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString([], {hour12:false}) + '.' + String(date.getMilliseconds()).padStart(3, '0');
}

function filteredRows() {
    const query = app.search.trim().toLowerCase();
    return app.rows.filter(row => {
        if (app.level !== 'ALL' && row.level !== app.level) return false;
        if (app.category !== 'ALL' && categoryOf(row.message) !== app.category) return false;
        if (query && !`${row.level} ${row.logger} ${row.source} ${row.message}`.toLowerCase().includes(query)) return false;
        return true;
    });
}

function renderDetail(row) {
    $('selected-level').textContent = row?.level || '—';
    $('selected-level').dataset.level = row?.level || '';
    const host = $('record-detail');
    host.replaceChildren();
    if (!row) {
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        const title = document.createElement('strong'); title.textContent = 'NO RECORD SELECTED';
        const body = document.createElement('p'); body.textContent = 'Select a console line to inspect its timestamp, source location, and full message.';
        empty.append(title, body); host.append(empty); return;
    }
    const dl = document.createElement('dl'); dl.className = 'detail-list';
    for (const [label, value] of [['ID', row.id], ['TIME', new Date(row.timestamp * 1000).toISOString()], ['LOGGER', row.logger], ['SOURCE', row.source]]) {
        const dt = document.createElement('dt'); dt.textContent = label;
        const dd = document.createElement('dd'); dd.textContent = value ?? '—';
        dl.append(dt, dd);
    }
    const messageLabel = document.createElement('dt'); messageLabel.textContent = 'MESSAGE';
    const message = document.createElement('dd'); message.className = 'detail-message'; message.textContent = row.message;
    dl.append(messageLabel, message); host.append(dl);
}

function render() {
    const visible = filteredRows();
    $('count-loaded').textContent = app.rows.length.toLocaleString();
    $('count-errors').textContent = app.rows.filter(row => row.level === 'ERROR' || row.level === 'CRITICAL').length.toLocaleString();
    $('count-warnings').textContent = app.rows.filter(row => row.level === 'WARNING').length.toLocaleString();
    $('count-visible').textContent = visible.length.toLocaleString();
    $('load-earlier').hidden = !app.hasOlder;

    const list = $('log-list');
    const oldScrollTop = list.scrollTop;
    const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 36;
    const fragment = document.createDocumentFragment();
    if (!visible.length) {
        const empty = document.createElement('div'); empty.className = 'empty-state';
        const title = document.createElement('strong');
        title.textContent = app.rows.length ? 'NO MATCHING MESSAGES' : 'AWAITING BACKEND MESSAGES';
        const body = document.createElement('p');
        body.textContent = app.rows.length ? 'Change the level, source, or search filters.' : 'Start or step the simulation to produce operational output.';
        empty.append(title, body); fragment.append(empty);
    } else {
        for (const row of visible) {
            const button = document.createElement('button');
            button.type = 'button'; button.className = 'log-row';
            button.dataset.level = row.level; button.dataset.category = categoryOf(row.message);
            button.setAttribute('aria-selected', String(row.id === app.selectedId));
            button.setAttribute('aria-label', `${row.level} ${row.source}: ${row.message}`);
            const cells = [timeOf(row.timestamp), row.level, row.source, row.message];
            for (const [index, value] of cells.entries()) {
                const cell = document.createElement('span');
                cell.className = ['log-time','log-level','log-source','log-message'][index];
                cell.textContent = value;
                button.append(cell);
            }
            button.addEventListener('click', () => {
                app.selectedId = row.id;
                renderDetail(row);
                list.querySelectorAll('.log-row[aria-selected="true"]').forEach(node => node.setAttribute('aria-selected','false'));
                button.setAttribute('aria-selected','true');
            });
            fragment.append(button);
        }
    }
    list.replaceChildren(fragment);
    const selected = app.rows.find(row => row.id === app.selectedId);
    renderDetail(selected || null);
    if (app.follow && atBottom) list.scrollTop = list.scrollHeight;
    else list.scrollTop = Math.min(oldScrollTop, list.scrollHeight);
}

function updateConnection() {
    const age = app.lastGood ? (Date.now() - app.lastGood) / 1000 : Infinity;
    const connected = age < 4;
    const value = connected ? 'CONNECTED' : app.lastGood ? 'STALE' : 'CONNECTING';
    $('api-state').textContent = `API ${value}`;
    $('api-state').dataset.state = value;
    $('freshness').textContent = connected ? `LIVE · ${age.toFixed(1)}s` : app.lastGood ? `STALE · ${age.toFixed(1)}s` : 'WAITING FOR LOGS';
    $('freshness').dataset.state = connected ? 'LIVE' : app.lastGood ? 'STALE' : '';
    $('footer-freshness').textContent = connected ? `Last log response ${age.toFixed(1)}s ago` : app.lastGood ? `Log stream stale ${age.toFixed(1)}s` : 'Awaiting backend connection';
}

function acceptPage(data, mode) {
    const entries = Array.isArray(data.entries) ? data.entries : [];
    if (mode === 'older') app.rows = [...entries, ...app.rows];
    else if (mode === 'new') app.rows = [...app.rows, ...entries];
    else app.rows = entries;
    app.cursor = Math.max(app.cursor, Number(data.latest_id) || 0, ...app.rows.map(row => row.id));
    app.hasOlder = Boolean(data.has_older || data.truncated);
    if (data.truncated) {
        $('buffer-note').textContent = 'RUN LOG LIMIT REACHED · earliest available records were evicted from the 100,000-record buffer.';
        if (mode === 'new') app.rows = entries;
    }
    app.oldestId = app.rows[0]?.id ?? null;
    app.lastGood = Date.now();
    $('stream-error').hidden = true;
    render(); updateConnection();
}

async function pollLogs(initial=false) {
    if (app.logBusy) return;
    app.logBusy = true;
    try {
        let path = '/developer/logs?limit=500';
        if (!initial && app.cursor) path += `&after_id=${encodeURIComponent(app.cursor)}`;
        const data = await getJson(path);
        acceptPage(data, initial ? 'initial' : 'new');
    } catch (error) {
        $('stream-error').hidden = false;
        $('stream-error').textContent = `LOG API ERROR · ${error.message}`;
        updateConnection();
    } finally { app.logBusy = false; }
}

async function loadEarlier() {
    if (!app.hasOlder || !app.oldestId) return;
    const button = $('load-earlier'); button.disabled = true;
    try {
        const data = await getJson(`/developer/logs?limit=500&before_id=${encodeURIComponent(app.oldestId)}`);
        acceptPage(data, 'older');
        if (!data.entries?.length) app.hasOlder = false;
        render();
    } catch (error) {
        $('stream-error').hidden = false;
        $('stream-error').textContent = `COULD NOT LOAD EARLIER RECORDS · ${error.message}`;
    } finally { button.disabled = false; }
}

function exportVisible() {
    const payload = filteredRows().map(row => ({...row, time_iso:new Date(row.timestamp * 1000).toISOString()}));
    const blob = new Blob([JSON.stringify(payload, null, 2)], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = `warehouse-console-${new Date().toISOString().replaceAll(':','-')}.json`;
    link.click(); URL.revokeObjectURL(url);
}

async function copyAllLogs() {
    const button = $('copy-all');
    const original = button.textContent;
    button.disabled = true;
    button.textContent = 'LOADING RUN LOGS…';
    try {
        const data = await getJson(`/developer/logs?limit=${MAX_RUN_LOGS}`);
        const lines = (Array.isArray(data.entries) ? data.entries : []).map(row => {
            const time = new Date(row.timestamp * 1000).toISOString();
            return `${time} [${row.level}] [${row.logger}] [${row.source}] [run=${row.run_id || 'unknown'}] ${row.message}`;
        });
        const text = lines.join('\n');
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(text);
        } else {
            const area = document.createElement('textarea');
            area.value = text; area.setAttribute('readonly', '');
            area.style.position = 'fixed'; area.style.opacity = '0';
            document.body.append(area); area.select();
            const copied = document.execCommand('copy'); area.remove();
            if (!copied) throw new Error('Clipboard access is unavailable');
        }
        button.textContent = `COPIED ${lines.length.toLocaleString()} LOGS`;
        $('buffer-note').textContent = data.truncated
            ? 'COPY COMPLETE FOR RETAINED RECORDS · earlier records exceeded the run-history limit.'
            : `Copied all ${lines.length.toLocaleString()} retained records for run ${data.entries[0]?.run_id || 'current run'}.`;
    } catch (error) {
        button.textContent = 'COPY FAILED';
        $('buffer-note').textContent = `Could not copy logs · ${error.message}`;
    } finally {
        window.setTimeout(() => { button.textContent = original; button.disabled = false; }, 2600);
    }
}

function bindControls() {
    $('search').addEventListener('input', event => { app.search = event.target.value; render(); });
    $('category-filter').addEventListener('change', event => { app.category = event.target.value; render(); });
    document.querySelectorAll('[data-level]').forEach(button => button.addEventListener('click', () => {
        app.level = button.dataset.level;
        document.querySelectorAll('[data-level]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
        render();
    }));
    $('follow').addEventListener('click', () => {
        app.follow = !app.follow;
        $('follow').setAttribute('aria-pressed', String(app.follow));
        $('follow').textContent = app.follow ? 'LIVE FOLLOW' : 'FOLLOW PAUSED';
        if (app.follow) $('log-list').scrollTop = $('log-list').scrollHeight;
    });
    $('load-earlier').addEventListener('click', loadEarlier);
    $('copy-all').addEventListener('click', copyAllLogs);
    $('export').addEventListener('click', exportVisible);
}

async function boot() {
    bindControls();
    await Promise.allSettled([pollStatus(), pollModel(), pollLogs(true)]);
    app.nextModelPoll = Date.now() + 5000;
    window.setInterval(() => {
        void pollStatus(); void pollLogs(false);
        if (Date.now() >= app.nextModelPoll) { app.nextModelPoll = Date.now() + 5000; void pollModel(); }
        updateConnection();
    }, 1000);
    window.setInterval(updateConnection, 500);
}

boot();
