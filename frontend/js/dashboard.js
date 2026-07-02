// ---- State ----

let gridData = null;
let gridWidth = 50;
let gridHeight = 30;
let cells = [];
let selectedRobotId = null;
let previousPaths = {};
let displayedAuctionLogs = 0;
let displayedNegotiationLogs = 0;
let lastKnownStep = -1;

// ---- Init ----

async function init() {
    await fetchGrid();
    buildGrid();
    
    document.getElementById('grid').addEventListener('click', (e) => {
        const robotCell = e.target.closest('.cell-robot');
        if (robotCell) {
            const idText = robotCell.querySelector('.robot-id').textContent.replace('R', '');
            selectedRobotId = parseInt(idText);
            document.getElementById('agent-diagnostics').style.display = 'block';
            document.getElementById('diag-robot-id').textContent = 'R' + selectedRobotId;
        }
    });
    
    poll();
    setInterval(poll, 200);
}

// ---- Fetch warehouse grid ----

async function fetchGrid() {
    try {
        const res = await fetch('/warehouse/grid');
        const data = await res.json();
        gridData = data.grid;
        gridWidth = data.width;
        gridHeight = data.height;
    } catch (e) {
        console.error('Failed to fetch grid:', e);
    }
}

// ---- Refresh grid after reset ----

async function refreshGrid() {
    await fetchGrid();
    buildGrid();
    previousPaths = {};
    displayedAuctionLogs = 0;
    displayedNegotiationLogs = 0;
    lastKnownStep = 0;
    console.log('[GRID REFRESH] Warehouse grid re-fetched and rebuilt after reset.');
}

// ---- Build grid DOM ----

function buildGrid() {
    const container = document.getElementById('grid');
    container.style.gridTemplateColumns = `repeat(${gridWidth}, 34px)`;
    container.innerHTML = '';
    cells = [];
    
    const titleEl = document.getElementById('grid-title');
    if (titleEl) {
        titleEl.textContent = `Warehouse Grid (${gridWidth} × ${gridHeight})`;
    }

    for (let y = 0; y < gridHeight; y++) {
        const row = [];
        for (let x = 0; x < gridWidth; x++) {
            const cell = document.createElement('div');
            cell.className = 'cell';
            cell.dataset.x = x;
            cell.dataset.y = y;
            container.appendChild(cell);
            row.push(cell);
        }
        cells.push(row);
    }
}

// ---- Poll API ----

async function poll() {
    try {
        const [robotsRes, tasksRes, statusRes, agentsRes] = await Promise.all([
            fetch('/robots'),
            fetch('/tasks'),
            fetch('/simulation/status'),
            fetch('/agents/status')
        ]);

        const robots = await robotsRes.json();
        const tasks = await tasksRes.json();
        const status = await statusRes.json();
        const agents = await agentsRes.json();

        // Detect simulation reset: step went back to 0 or dropped below last known
        if (status.current_step < lastKnownStep && status.current_step <= 1) {
            console.log('[RESET DETECTED] Simulation step dropped — refreshing grid...');
            await refreshGrid();
        }
        lastKnownStep = status.current_step;

        updateGrid(robots, tasks);
        drawPaths(robots);
        updateStatus(status);
        updateRobotList(robots);
        updateDiagnostics(agents.agents);

        document.getElementById('connection-badge').textContent = '● Connected';
        document.getElementById('connection-badge').style.color = 'var(--accent-green)';
    } catch (e) {
        console.error('Error fetching main simulation data:', e);
        document.getElementById('connection-badge').textContent = '● Disconnected';
        document.getElementById('connection-badge').style.color = 'var(--accent-red)';
    }
    
    try {
        const auctionRes = await fetch('/auction/logs');
        if (!auctionRes.ok) {
            throw new Error(`HTTP error! status: ${auctionRes.status}`);
        }
        const auctionLogs = await auctionRes.json();
        
        if (!auctionLogs || auctionLogs.length === 0) {
            // console.log("Auction logs received: []"); // Disabled verbose polling to avoid spam, but can be enabled
        } else if (auctionLogs.length > displayedAuctionLogs) {
            console.log(`Auction logs received: ${auctionLogs.length} logs found`, auctionLogs);
        }
        
        updateAuctionLogs(auctionLogs);
    } catch (e) {
        console.error('Error fetching auction logs:', e);
    }

    try {
        const negotiationRes = await fetch('/negotiation/logs');
        if (!negotiationRes.ok) {
            throw new Error(`HTTP error! status: ${negotiationRes.status}`);
        }
        const negotiationLogs = await negotiationRes.json();
        
        if (negotiationLogs && negotiationLogs.length > 0) {
            // Log fetched successfully
        }
        
        updateNegotiationLogs(negotiationLogs);
    } catch (e) {
        console.error('Error fetching negotiation logs:', e);
    }
}

// ---- Update Grid ----

function updateGrid(robots, tasks) {
    if (!gridData) return;

    // Reset all cells to base
    for (let y = 0; y < gridHeight; y++) {
        for (let x = 0; x < gridWidth; x++) {
            const cell = cells[y][x];
            const tile = gridData[y][x];

            cell.className = 'cell';
            cell.innerHTML = '';

            if (tile === 'S') {
                cell.classList.add('cell-shelf');
            } else if (tile === 'C') {
                cell.classList.add('cell-charger');
                cell.innerHTML = '<span class="cell-charger-icon">⚡</span>';
            } else if (tile === 'R') {
                cell.classList.add('cell-spawn');
            } else {
                cell.classList.add('cell-aisle');
            }
        }
    }

    // Draw task pickups (incomplete only)
    for (const task of tasks) {
        if (task.completed) continue;

        // Delivery
        const dx = task.delivery_x;
        const dy = task.delivery_y;
        if (dy >= 0 && dy < gridHeight && dx >= 0 && dx < gridWidth) {
            const dc = cells[dy][dx];
            dc.className = 'cell cell-delivery';
            dc.innerHTML = `D${task.id}`;
        }

        // Pickup (drawn after delivery so it takes priority on overlap)
        const px = task.pickup_x;
        const py = task.pickup_y;
        if (py >= 0 && py < gridHeight && px >= 0 && px < gridWidth) {
            const pc = cells[py][px];
            pc.className = 'cell cell-pickup';
            pc.innerHTML = `T${task.id}`;
        }
    }

    // Draw robots (drawn last so they are always visible)
    for (const robot of robots) {
        const rx = robot.position.x;
        const ry = robot.position.y;
        if (ry >= 0 && ry < gridHeight && rx >= 0 && rx < gridWidth) {
            const rc = cells[ry][rx];
            let statusClass = '';
            if (robot.status === 'CHARGING') statusClass = ' charging';
            else if (robot.status === 'DELIVERING') statusClass = ' delivering';

            rc.className = 'cell cell-robot' + statusClass;
            rc.innerHTML = `<span class="robot-id">R${robot.id}</span><span class="robot-batt">${Math.round(robot.battery)}%</span>`;
        }
    }
}

// ---- Update Status Panel ----

function updateStatus(status) {
    document.getElementById('stat-step').textContent = status.current_step;
    document.getElementById('stat-active').textContent = status.active_robots;
    document.getElementById('stat-total-tasks').textContent = status.total_tasks;
    document.getElementById('stat-unfinished').textContent = status.unfinished_tasks;

    const runEl = document.getElementById('stat-running');

    if (status.simulation_complete) {
        runEl.textContent = 'COMPLETE';
        runEl.className = 'stat-value complete';
    } else if (status.running) {
        runEl.textContent = 'RUNNING';
        runEl.className = 'stat-value running';
    } else {
        runEl.textContent = 'PAUSED';
        runEl.className = 'stat-value paused';
    }
}

// ---- Update Robot List ----

function updateRobotList(robots) {
    const list = document.getElementById('robot-list');
    list.innerHTML = '';

    for (const robot of robots) {
        const batt = Math.round(robot.battery);
        let battColor = 'var(--accent-green)';
        if (batt <= 20) battColor = 'var(--accent-red)';
        else if (batt <= 50) battColor = 'var(--accent-orange)';

        const statusLower = robot.status.toLowerCase();
        let statusClass = 'status-idle';
        if (statusLower === 'moving') statusClass = 'status-moving';
        else if (statusLower === 'charging') statusClass = 'status-charging';
        else if (statusLower === 'delivering') statusClass = 'status-delivering';

        const entry = document.createElement('div');
        entry.className = 'robot-entry';
        entry.innerHTML = `
            <span class="robot-entry-id">R${robot.id}</span>
            <span class="robot-entry-status ${statusClass}">${robot.status}</span>
            <div class="battery-bar">
                <div class="battery-fill" style="width: ${batt}%; background: ${battColor};"></div>
            </div>
            <span class="battery-text">${batt}%</span>
        `;
        list.appendChild(entry);
    }
}

// ---- Render Paths ----

function drawPaths(robots) {
    const svg = document.getElementById('path-overlay');
    if (!svg) return;
    svg.innerHTML = '';
    
    // Explicitly define SVG scale via grid dimensions (34px cell + 2px gap + padding)
    const w = 6 + (gridWidth * 36);
    const h = 6 + (gridHeight * 36);
    svg.setAttribute('width', w);
    svg.setAttribute('height', h);
    svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    svg.style.width = w + 'px';
    svg.style.height = h + 'px';

    for (const robot of robots) {
        if (!robot.path || robot.path.length < 1) continue;
        
        const isSelected = (robot.id === selectedRobotId);
        const color = isSelected ? 'rgba(74, 144, 226, 0.9)' : 'rgba(74, 144, 226, 0.4)';
        const strokeWidth = isSelected ? 3 : 2;
        const strokeDasharray = isSelected ? "4,4" : "2,4";

        let pathStr = JSON.stringify(robot.path);
        let recalculated = false;
        if (previousPaths[robot.id] && previousPaths[robot.id] !== pathStr) {
            const prevArr = JSON.parse(previousPaths[robot.id]);
            if (prevArr.length > 0 && robot.path.length > 0) {
                const prevDest = prevArr[prevArr.length - 1];
                const currDest = robot.path[robot.path.length - 1];
                if (prevDest[0] === currDest[0] && prevDest[1] === currDest[1]) {
                    if (prevArr.length <= robot.path.length || (prevArr.length > 1 && prevArr[1][0] !== robot.path[0][0])) {
                        recalculated = true;
                    }
                }
            }
        }
        previousPaths[robot.id] = pathStr;

        let d = "";
        let startX = 21 + 36 * robot.position.x;
        let startY = 21 + 36 * robot.position.y;
        d += `M ${startX} ${startY} `;

        for (let i = 0; i < robot.path.length; i++) {
            const p = robot.path[i];
            let cx = 21 + 36 * p[0];
            let cy = 21 + 36 * p[1];
            d += `L ${cx} ${cy} `;
        }

        const pathEl = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        pathEl.setAttribute('d', d);
        pathEl.setAttribute('stroke', color);
        pathEl.setAttribute('stroke-width', strokeWidth);
        pathEl.setAttribute('fill', 'none');
        pathEl.setAttribute('stroke-dasharray', strokeDasharray);
        
        if (recalculated) {
            pathEl.style.animation = "pathFlash 0.5s ease-out";
        }
        
        svg.appendChild(pathEl);
    }
}

// ---- Render Diagnostics & Auction Logs ----

function updateDiagnostics(agents) {
    if (selectedRobotId === null) return;
    const agent = agents.find(a => a.robot_id === selectedRobotId);
    if (agent) {
        document.getElementById('diag-goal').textContent = agent.goal;
        document.getElementById('diag-memory').textContent = agent.memory_size;
        document.getElementById('diag-beliefs').textContent = JSON.stringify(agent.beliefs, null, 2);
    }
}

function updateAuctionLogs(logs) {
    if (!logs || logs.length === displayedAuctionLogs) return;
    
    const container = document.getElementById('auction-logs');
    for (let i = displayedAuctionLogs; i < logs.length; i++) {
        const log = logs[i];
        const div = document.createElement('div');
        div.style.padding = '8px';
        div.style.background = 'var(--bg-cell)';
        div.style.borderRadius = '6px';
        div.style.borderLeft = '3px solid var(--accent-orange)';
        
        let bidsHtml = log.bids.map(b => `R${b.robot_id}: ${b.bid.toFixed(1)}`).join(', ');
        div.innerHTML = `<strong>Task ${log.task_id} Bids:</strong><br><span style="color:var(--text-secondary)">${bidsHtml}</span><br><strong style="color:var(--accent-green)">Winner: R${log.winner}</strong>`;
        container.prepend(div);
    }
    displayedAuctionLogs = logs.length;
}

function updateNegotiationLogs(logs) {
    if (!logs) return;
    
    const container = document.getElementById('negotiation-logs');
    container.innerHTML = '';
    
    for (let i = 0; i < logs.length; i++) {
        const log = logs[i];
        const div = document.createElement('div');
        div.style.padding = '8px';
        div.style.background = 'var(--bg-cell)';
        div.style.borderRadius = '6px';
        div.style.borderLeft = '3px solid var(--accent-blue)';
        
        if (log.robot1 === "Auction") {
            div.innerHTML = `<strong>Auction Explain: ${log.robot2}</strong><br><span style="color:var(--text-secondary)">${log.reason}</span><br><strong style="color:var(--accent-green)">Winner: R${log.winner}</strong>`;
        } else if (log.robot1 === "System") {
            div.innerHTML = `<strong>System: ${log.robot2} Initialized</strong><br><span style="color:var(--text-secondary)">${log.reason}</span>`;
        } else {
            div.innerHTML = `<strong>R${log.robot1} vs R${log.robot2} @ (${log.cell[0]},${log.cell[1]})</strong><br><span style="color:var(--text-secondary)">${log.reason}</span><br><strong style="color:var(--accent-green)">Yield Winner: R${log.winner}</strong>`;
        }
        
        container.prepend(div);
    }
}

// ---- API Post Helper ----

async function apiPost(url) {
    try {
        await fetch(url, { method: 'POST' });
        // After reset, immediately refresh the grid so shelves match the new warehouse
        if (url.includes('/simulation/reset')) {
            await refreshGrid();
        }
    } catch (e) {
        console.error('API call failed:', e);
    }
}

// ---- Start ----

init();
