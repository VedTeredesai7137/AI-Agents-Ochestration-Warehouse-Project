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
    renderedMessageIds: new Set()
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
    negotiationContent: document.getElementById('negotiation-content')
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
            negotiationsRes
        ] = await Promise.all([
            fetch('/simulation/status'),
            fetch('/robots'),
            fetch('/tasks'),
            fetch('/agents/status'),
            fetch('/agents/messages'),
            fetch('/auction/logs'),
            fetch('/negotiation/logs')
        ]);

        state.simStatus = await statusRes.json();
        state.robots = await robotsRes.json();
        state.tasks = await tasksRes.json();
        const agentData = await agentsRes.json();
        state.agentStatus = agentData.agents;
        
        const msgData = await messagesRes.json();
        // Flatten messages and sort by ID (assuming ID is sequential)
        let allMessages = [];
        msgData.agents.forEach(a => {
            allMessages = allMessages.concat(a.pending_messages.map(m => ({...m, recipient: a.robot_id})));
        });
        state.messages = allMessages.sort((a,b) => a.id - b.id);
        
        state.auctions = await auctionsRes.json();
        state.negotiations = await negotiationsRes.json();

        updateUI();

    } catch (e) {
        console.error("Polling error", e);
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
}

async function run() {
    await fetchInitial();
    setInterval(pollData, 200);
}

// Start
document.addEventListener('DOMContentLoaded', run);
