// ==========================================
// STATE MANAGEMENT
// ==========================================
const state = {
    grid: null,
    robots: [],
    tasks: [],
    agentStatus: [],
    messages: [],
    auctions: [],
    negotiations: [],
    simStatus: null,
    selectedRobotId: null,
    metrics: {
        totalMessages: 0,
        completedTasks: 0
    },
    renderedMessageIds: new Set(),
    orchestrator: null
};

const UI = {
    headerStatus: document.getElementById('header-sim-status'),
    headerStep: document.getElementById('header-step'),
    headerRobots: document.getElementById('header-robots'),
    headerTasks: document.getElementById('header-tasks'),
    gridContainer: document.getElementById('grid-container'),
    inspectorContent: document.getElementById('agent-inspector-content'),
    messageBusContent: document.getElementById('message-bus-content'),
    auctionContent: document.getElementById('auction-content'),
    metricsContent: document.getElementById('metrics-content'),
    negotiationContent: document.getElementById('negotiation-content'),
    orchestratorPanel: document.getElementById('orchestrator-panel'),
    orchestratorContent: document.getElementById('orchestrator-content'),
    orchestratorStatusBadge: document.getElementById('orchestrator-status-badge'),
    hitlOverlay: document.getElementById('hitl-overlay'),
    hitlDetails: document.getElementById('hitl-details')
};

// ==========================================
// API FETCHING
// ==========================================
async function fetchInitial() {
    try {
        const res = await fetch('/warehouse/grid');
        state.grid = await res.json();
        createGrid();
    } catch (e) {
        console.error("Failed to fetch grid", e);
    }
}

async function pollData() {
    try {
        const [
            statusRes, 
            robotsRes, 
            tasksRes, 
            agentsRes, 
            messagesRes, 
            auctionsRes, 
            negotiationsRes,
            orchestratorRes
        ] = await Promise.all([
            fetch('/simulation/status').catch(e => { console.error("Error fetching status:", e); throw e; }),
            fetch('/robots').catch(e => { console.error("Error fetching robots:", e); throw e; }),
            fetch('/tasks').catch(e => { console.error("Error fetching tasks:", e); throw e; }),
            fetch('/agents/status').catch(e => { console.error("Error fetching agent status:", e); throw e; }),
            fetch('/agents/messages').catch(e => { console.error("Error fetching agent messages:", e); throw e; }),
            fetch('/auction/logs').catch(e => { console.error("Error fetching auction logs:", e); throw e; }),
            fetch('/negotiation/logs').catch(e => { console.error("Error fetching negotiation logs:", e); throw e; }),
            fetch('/orchestrator/state').catch(e => { console.error("Error fetching orchestrator state:", e); throw e; })
        ]);

        state.simStatus = await statusRes.json();
        state.robots = await robotsRes.json();
        state.tasks = await tasksRes.json();
        const agentData = await agentsRes.json();
        state.agentStatus = agentData.agents;
        
        const msgData = await messagesRes.json();
        // Flatten messages and accumulate them instead of overwriting to prevent flickering
        let incomingMessages = [];
        if (msgData && msgData.agents) {
            msgData.agents.forEach(a => {
                if (a.pending_messages) {
                    incomingMessages = incomingMessages.concat(a.pending_messages.map(m => ({...m, recipient: a.robot_id})));
                }
            });
        }
        
        incomingMessages.forEach(msg => {
            if (!state.renderedMessageIds.has(msg.id)) {
                state.messages.push(msg);
                state.renderedMessageIds.add(msg.id);
                try {
                    // Log displayed message to console as requested
                    console.log(`[Message Bus] ID: ${msg.id} | Type: ${msg.type} | From: ${msg.sender} | To: ${msg.recipient} | Payload:`, msg.payload);
                } catch (err) {
                    console.error("Error logging message bus content:", err);
                }
            }
        });
        
        // Sort messages by ID to maintain order
        state.messages.sort((a,b) => a.id - b.id);
        
        // Keep the history bounded to prevent memory leaks
        if (state.messages.length > 200) {
            state.messages = state.messages.slice(-200);
        }
        
        state.auctions = await auctionsRes.json();
        state.negotiations = await negotiationsRes.json();
        state.orchestrator = await orchestratorRes.json();

        updateUI();

    } catch (e) {
        console.error("Polling error: Unable to fetch data from backend. Ensure the server is running.", e);
    }
}

// ==========================================
// WAREHOUSE VISUALIZATION
// ==========================================
function createGrid() {
    if (!state.grid) return;
    const { width, height, grid } = state.grid;
    
    UI.gridContainer.style.gridTemplateColumns = `repeat(${width}, 24px)`;
    UI.gridContainer.style.gridTemplateRows = `repeat(${height}, 24px)`;
    UI.gridContainer.innerHTML = '';

    for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
            const cellType = grid[y][x];
            const cell = document.createElement('div');
            cell.className = 'cell';
            cell.id = `cell-${x}-${y}`;
            
            if (cellType === 'X') cell.classList.add('wall');
            else if (cellType === 'S') cell.classList.add('shelf');
            else if (cellType === 'C') cell.classList.add('charger');
            
            UI.gridContainer.appendChild(cell);
        }
    }
}

function updateGrid() {
    // Remove existing robots
    document.querySelectorAll('.robot').forEach(el => el.remove());

    state.robots.forEach(robot => {
        const cellId = `cell-${robot.position.x}-${robot.position.y}`;
        const cell = document.getElementById(cellId);
        
        if (cell) {
            const robotEl = document.createElement('div');
            robotEl.className = `robot ${robot.status.toLowerCase()}`;
            if (state.selectedRobotId === robot.id) {
                robotEl.classList.add('selected');
            }
            robotEl.innerText = robot.id;
            
            // Interaction
            robotEl.onclick = (e) => {
                e.stopPropagation();
                state.selectedRobotId = robot.id;
                renderInspector();
                updateGrid(); // re-render to show selection outline
            };

            // Tooltip
            const tooltip = document.createElement('div');
            tooltip.className = 'tooltip';
            tooltip.innerHTML = `
                <strong>Robot ${robot.id}</strong><br>
                Status: ${robot.status}<br>
                Battery: ${Math.round(robot.battery)}%<br>
                Task: ${robot.current_task || 'None'}
            `;
            robotEl.appendChild(tooltip);

            cell.appendChild(robotEl);
        }
    });
}

// ==========================================
// AGENT INSPECTOR
// ==========================================
function renderInspector() {
    if (!state.selectedRobotId) {
        UI.inspectorContent.innerHTML = '<div class="empty-state">No agent selected</div>';
        return;
    }

    const robot = state.robots.find(r => r.id === state.selectedRobotId);
    const agent = state.agentStatus.find(a => a.robot_id === state.selectedRobotId);

    if (!robot || !agent) return;

    let beliefsHtml = '';
    for (const [k, v] of Object.entries(agent.beliefs)) {
        beliefsHtml += `<div class="key-value"><span class="key">${k}</span><span class="value">${Array.isArray(v) ? v.join(', ') || 'None' : v}</span></div>`;
    }

    UI.inspectorContent.innerHTML = `
        <div class="inspector-grid">
            <div class="inspector-card">
                <h3>Core Identity</h3>
                <div class="key-value"><span class="key">Robot ID</span><span class="value">${robot.id}</span></div>
                <div class="key-value"><span class="key">Goal</span><span class="value">${agent.goal}</span></div>
                <div class="key-value"><span class="key">Status</span><span class="value"><span class="status-badge" style="background: var(--status-${robot.status.toLowerCase()})">${robot.status}</span></span></div>
                <div class="key-value"><span class="key">Battery</span><span class="value">${Math.round(robot.battery)}%</span></div>
                <div class="key-value"><span class="key">Task ID</span><span class="value">${robot.current_task || 'None'}</span></div>
            </div>

            <div class="inspector-card">
                <h3>Current Beliefs</h3>
                ${beliefsHtml}
            </div>
            
            <div class="inspector-card">
                <h3>Operations</h3>
                <div class="key-value"><span class="key">Pending Messages</span><span class="value">${agent.pending_messages}</span></div>
                <div class="key-value"><span class="key">Memory Events</span><span class="value">${agent.memory_size}</span></div>
            </div>
        </div>
    `;
}

// ==========================================
// MESSAGE BUS
// ==========================================
function updateMessages() {
    let html = '';
    // Show last 20 messages for performance
    const recentMessages = state.messages.slice(-20).reverse();
    
    recentMessages.forEach(msg => {
        state.metrics.totalMessages = Math.max(state.metrics.totalMessages, msg.id);
        
        let payloadStr = JSON.stringify(msg.payload);
        if (payloadStr.length > 50) payloadStr = payloadStr.substring(0, 50) + '...';

        html += `
            <div class="message-card msg-${msg.type}">
                <div class="msg-header">
                    <span class="msg-type">${msg.type}</span>
                    <span class="msg-time">ID: ${msg.id}</span>
                </div>
                <div class="msg-body">
                    From <strong>${msg.sender}</strong> to <strong>${msg.recipient}</strong><br>
                    <span style="color: var(--text-secondary); font-size: 0.75rem;">${payloadStr}</span>
                </div>
            </div>
        `;
    });
    
    if (html === '') {
        html = '<div class="empty-state">No pending messages</div>';
    }
    
    UI.messageBusContent.innerHTML = html;
}

// ==========================================
// AUCTION MONITOR
// ==========================================
function updateAuctions() {
    if (state.auctions.length === 0) {
        UI.auctionContent.innerHTML = '<div class="empty-state">No recent auctions</div>';
        return;
    }

    let html = '';
    // Display last 5 auctions
    const recent = [...state.auctions].reverse().slice(0, 5);
    
    recent.forEach(log => {
        html += `
            <div class="log-card">
                <div class="log-title">
                    <span>Task ${log.task_id}</span>
                    <span style="color: var(--status-delivering)">Winner: R${log.winner}</span>
                </div>
                <div class="log-detail"><span>Bids:</span> ${log.bids.map(b => `R${b.robot_id}(${b.bid.toFixed(1)})`).join(', ')}</div>
            </div>
        `;
    });
    UI.auctionContent.innerHTML = html;
}

// ==========================================
// NEGOTIATION LOGS
// ==========================================
function updateNegotiations() {
    if (state.negotiations.length === 0) {
        UI.negotiationContent.innerHTML = '<div class="empty-state">No negotiations logged</div>';
        return;
    }

    let html = '';
    const recent = [...state.negotiations].reverse();
    
    recent.forEach(log => {
        const isAuction = log.event.includes("Auction");
        html += `
            <div class="log-card" style="border-left: 3px solid ${isAuction ? 'var(--msg-award)' : 'var(--status-negotiating)'}">
                <div class="log-title">
                    <span>${log.event}</span>
                    <span style="color: var(--text-secondary); font-size: 0.75rem;">${new Date(log.timestamp * 1000).toLocaleTimeString()}</span>
                </div>
                <div class="log-detail"><span>Reasoning:</span> ${log.reasoning}</div>
                <div class="log-detail" style="margin-top: 8px;"><span>Decision:</span> <strong style="color: ${isAuction ? 'var(--status-delivering)' : 'var(--status-idle)'}">${log.decision}</strong></div>
            </div>
        `;
    });
    UI.negotiationContent.innerHTML = html;
}

// ==========================================
// METRICS
// ==========================================
function updateMetrics() {
    if (!state.simStatus) return;
    
    const completed = state.tasks.filter(t => t.completed).length;
    const moving = state.robots.filter(r => r.status === 'MOVING').length;
    const charging = state.robots.filter(r => r.status === 'CHARGING').length;
    const idle = state.robots.filter(r => r.status === 'IDLE').length;
    
    let totalBattery = 0;
    state.robots.forEach(r => totalBattery += r.battery);
    const avgBattery = state.robots.length > 0 ? (totalBattery / state.robots.length).toFixed(1) : 0;

    UI.metricsContent.innerHTML = `
        <div class="metric-box">
            <span class="metric-title">Completed Tasks</span>
            <span class="metric-value" style="color: var(--status-delivering)">${completed}</span>
        </div>
        <div class="metric-box">
            <span class="metric-title">Moving Robots</span>
            <span class="metric-value" style="color: var(--status-moving)">${moving}</span>
        </div>
        <div class="metric-box">
            <span class="metric-title">Charging</span>
            <span class="metric-value" style="color: var(--status-charging)">${charging}</span>
        </div>
        <div class="metric-box">
            <span class="metric-title">Idle</span>
            <span class="metric-value" style="color: var(--status-idle)">${idle}</span>
        </div>
        <div class="metric-box">
            <span class="metric-title">Avg Battery</span>
            <span class="metric-value">${avgBattery}%</span>
        </div>
        <div class="metric-box">
            <span class="metric-title">Total Messages Seen</span>
            <span class="metric-value" style="color: var(--msg-cfp)">${state.metrics.totalMessages}</span>
        </div>
    `;
}

// ==========================================
// CORE LOOP
// ==========================================
function updateHeader() {
    if (!state.simStatus) return;
    
    UI.headerStatus.innerText = state.simStatus.running ? "Running" : "Paused";
    UI.headerStatus.style.color = state.simStatus.running ? "var(--status-delivering)" : "var(--status-error)";
    
    UI.headerStep.innerText = state.simStatus.current_step;
    UI.headerRobots.innerText = state.simStatus.total_robots;
    UI.headerTasks.innerText = state.simStatus.total_tasks;
}

function updateUI() {
    updateHeader();
    updateGrid();
    renderInspector();
    updateMessages();
    updateAuctions();
    updateNegotiations();
    updateMetrics();
    updateOrchestrator();
}

// ==========================================
// ORCHESTRATOR HUD
// ==========================================
function updateOrchestrator() {
    const orch = state.orchestrator;
    if (!orch || !UI.orchestratorPanel) return;

    const panel = UI.orchestratorPanel;
    const content = UI.orchestratorContent;
    const badge = UI.orchestratorStatusBadge;

    // Panel state classes
    panel.classList.remove('orch-active', 'orch-waiting');

    if (!orch.active && !orch.waiting_for_human) {
        badge.textContent = 'INACTIVE';
        badge.style.color = 'var(--text-secondary)';
        content.innerHTML = '<div class="empty-state">No active crisis orchestration</div>';
        // Hide HITL overlay
        if (UI.hitlOverlay) UI.hitlOverlay.style.display = 'none';
        return;
    }

    if (orch.waiting_for_human) {
        panel.classList.add('orch-waiting');
        badge.textContent = '⚠ AWAITING HUMAN';
        badge.style.color = 'var(--status-error)';
    } else {
        panel.classList.add('orch-active');
        badge.textContent = 'ACTIVE';
        badge.style.color = 'var(--status-negotiating)';
    }

    // Determine node progress states
    const nodeOrder = ['diagnose', 'generate_plan', 'validate', 'execute'];
    const activeNode = orch.active_node || '';
    
    function getNodeClass(nodeName) {
        const activeIdx = nodeOrder.indexOf(activeNode);
        const nodeIdx = nodeOrder.indexOf(nodeName);
        
        // Regenerating state: graph looped back to generate_plan after rejection
        if ((activeNode === 'regenerating' || activeNode === 'rejected') && nodeName === 'generate_plan') return 'active';
        if ((activeNode === 'regenerating' || activeNode === 'rejected') && nodeName === 'diagnose') return 'completed';
        if ((activeNode === 'regenerating' || activeNode === 'rejected') && (nodeName === 'validate' || nodeName === 'execute')) return '';
        
        if (activeNode === 'waiting_for_human' && nodeName === 'validate') return 'waiting';
        if (activeNode === 'waiting_for_human' && nodeIdx < nodeOrder.indexOf('validate')) return 'completed';
        if (activeNode === 'execute' || activeNode === 'executing' || activeNode === 'human_approved') {
            if (nodeIdx < nodeOrder.indexOf('execute')) return 'completed';
            if (nodeName === 'execute') return 'active';
        }
        if (nodeName === activeNode) return 'active';
        if (activeIdx >= 0 && nodeIdx < activeIdx) return 'completed';
        return '';
    }

    // Confidence color
    const conf = orch.confidence_score;
    let confColor = 'var(--status-delivering)';
    if (conf !== null && conf < 0.85) confColor = 'var(--status-error)';
    else if (conf !== null && conf < 0.90) confColor = 'var(--status-charging)';

    const confPct = conf !== null ? Math.round(conf * 100) : 0;

    // Build affected robots display
    const affectedStr = (orch.affected_robots || []).map(id => `R${id}`).join(', ') || 'None';

    // Plan summary
    let planSummary = 'N/A';
    if (orch.proposed_plan && orch.proposed_plan.routes) {
        planSummary = orch.proposed_plan.routes.map(r => `R${r.robot_id}: ${r.action}`).join('<br>');
    } else if (orch.proposed_plan && orch.proposed_plan.fallback) {
        planSummary = 'Fallback plan (LLM unavailable)';
    }

    content.innerHTML = `
        <div class="orch-node-progress">
            <div class="orch-node ${getNodeClass('diagnose')}">Diagnose</div>
            <div class="orch-node ${getNodeClass('generate_plan')}">Plan</div>
            <div class="orch-node ${getNodeClass('validate')}">Validate</div>
            <div class="orch-node ${getNodeClass('execute')}">Execute</div>
        </div>
        <div class="orch-detail-grid">
            <div class="orch-detail-row">
                <span class="label">Crisis Location</span>
                <span class="val">${orch.crisis_location ? JSON.stringify(orch.crisis_location) : 'N/A'}</span>
            </div>
            <div class="orch-detail-row">
                <span class="label">Affected Robots</span>
                <span class="val">${affectedStr}</span>
            </div>
            <div class="orch-detail-row">
                <span class="label">Confidence</span>
                <span class="val" style="color: ${confColor}">${conf !== null ? (confPct + '%') : 'Pending'}</span>
            </div>
            <div class="orch-detail-row">
                <span class="label">Human Approved</span>
                <span class="val">${orch.human_approved === null ? 'Pending' : (orch.human_approved ? '✅ Yes' : '❌ No')}</span>
            </div>
        </div>
        ${conf !== null ? `
        <div class="confidence-bar">
            <div class="confidence-fill" style="width: ${confPct}%; background: ${confColor};"></div>
        </div>` : ''}
        ${orch.error ? `<div style="margin-top: 8px; color: var(--status-error); font-size: 0.75rem;">Error: ${orch.error}</div>` : ''}
    `;

    // Console log orchestrator state changes
    console.log(`[Orchestrator HUD] Node: ${activeNode} | Confidence: ${conf} | Waiting: ${orch.waiting_for_human} | Affected: ${affectedStr}`);

    // HITL Overlay
    if (orch.waiting_for_human && UI.hitlOverlay) {
        UI.hitlOverlay.style.display = 'flex';
        if (UI.hitlDetails) {
            UI.hitlDetails.innerHTML = `
                <div class="orch-detail-row"><span class="label">Crisis Location</span><span class="val">${JSON.stringify(orch.crisis_location)}</span></div>
                <div class="orch-detail-row"><span class="label">Affected Robots</span><span class="val">${affectedStr}</span></div>
                <div class="orch-detail-row"><span class="label">Confidence Score</span><span class="val" style="color: var(--status-error)">${confPct}%</span></div>
                <div style="margin-top: 10px; font-size: 0.8rem; color: var(--text-secondary);">Proposed Plan:</div>
                <div style="margin-top: 4px; font-size: 0.8rem; color: var(--text-primary);">${planSummary}</div>
            `;
        }
    } else if (UI.hitlOverlay) {
        UI.hitlOverlay.style.display = 'none';
    }
}

// ==========================================
// ORCHESTRATOR OVERRIDE (HITL)
// ==========================================
async function orchestratorOverride(approved) {
    const action = approved ? 'APPROVE' : 'REJECT';
    console.log(`[Orchestrator HITL] Operator decision: ${action}`);
    
    const approveBtn = document.getElementById('hitl-approve');
    const rejectBtn = document.getElementById('hitl-reject');
    
    // Disable both buttons immediately to prevent double-clicks
    if (approveBtn) approveBtn.disabled = true;
    if (rejectBtn) rejectBtn.disabled = true;
    
    if (!approved && rejectBtn) {
        // Show loading state on REJECT — system is looping back to generate_plan
        rejectBtn.textContent = '🔄 Recalculating...';
        rejectBtn.style.opacity = '0.7';
        rejectBtn.style.cursor = 'wait';
        console.log('[Orchestrator HITL] Reject clicked — sending to backend, graph will loop to GENERATE_PLAN...');
    }
    
    try {
        const res = await fetch('/orchestrator/override', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ approved: approved }),
        });
        const data = await res.json();
        console.log(`[Orchestrator HITL] Server response:`, data);
        
        if (approved) {
            // APPROVE: hide overlay immediately
            if (UI.hitlOverlay) UI.hitlOverlay.style.display = 'none';
        } else {
            // REJECT: hide overlay after a brief delay so user sees the "Recalculating" state
            // The overlay will reappear when the graph pauses again at the next HITL interrupt
            setTimeout(() => {
                if (UI.hitlOverlay) UI.hitlOverlay.style.display = 'none';
                // Reset button text for next appearance
                if (rejectBtn) {
                    rejectBtn.textContent = '❌ REJECT';
                    rejectBtn.style.opacity = '1';
                    rejectBtn.style.cursor = 'pointer';
                    rejectBtn.disabled = false;
                }
                if (approveBtn) approveBtn.disabled = false;
            }, 1500);
        }
    } catch (e) {
        console.error('[Orchestrator HITL] Override request failed:', e);
        // Re-enable buttons on error
        if (approveBtn) approveBtn.disabled = false;
        if (rejectBtn) {
            rejectBtn.textContent = '❌ REJECT';
            rejectBtn.style.opacity = '1';
            rejectBtn.style.cursor = 'pointer';
            rejectBtn.disabled = false;
        }
    }
}

async function run() {
    await fetchInitial();
    setInterval(pollData, 200);
}

// Start
document.addEventListener('DOMContentLoaded', run);
