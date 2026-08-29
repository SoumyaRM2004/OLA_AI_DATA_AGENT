/**
 * OLA AI Data Agent — Frontend Application Logic
 */

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initChat();
    initDashboard();
    initDbExplorer();
    initEtlStudio();
});

// Global state
let activeChartInstances = {};

/* ==========================================================================
   1. NAVIGATION & TAB SWITCHING
   ========================================================================== */
function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    const tabPanes = document.querySelectorAll('.tab-pane');
    const pageTitle = document.getElementById('page-title');
    const pageDesc = document.getElementById('page-description');

    const tabDescriptions = {
        'chat-view': {
            title: 'AI Chat Studio',
            desc: 'Ask natural language questions to query the PostgreSQL database or trigger ETL pipelines.'
        },
        'overview-view': {
            title: 'Analytics KPI Dashboard',
            desc: 'High-level business metrics, revenue summaries, and ride distributions.'
        },
        'db-view': {
            title: 'Database Explorer',
            desc: 'Inspect tables, columns, schemas, and live record previews from PostgreSQL.'
        },
        'etl-view': {
            title: 'ETL Studio',
            desc: 'Extract data from external APIs and transform datasets using natural language.'
        },
        'architecture-view': {
            title: 'Agent Architecture',
            desc: 'Explore the LangGraph multi-agent orchestration and security judge pipeline.'
        }
    };

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetTab = item.getAttribute('data-tab');

            navItems.forEach(n => n.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));

            item.classList.add('active');
            const activePane = document.getElementById(targetTab);
            if (activePane) activePane.classList.add('active');

            if (tabDescriptions[targetTab]) {
                pageTitle.textContent = tabDescriptions[targetTab].title;
                pageDesc.textContent = tabDescriptions[targetTab].desc;
            }

            // Trigger data load when switching tabs
            if (targetTab === 'overview-view') {
                loadDashboardStats();
            } else if (targetTab === 'db-view') {
                loadDbSchema();
            } else if (targetTab === 'etl-view') {
                loadDataFiles();
            }

            // Re-render icons if needed
            if (window.lucide) lucide.createIcons();
        });
    });
}

/* ==========================================================================
   2. AI CHAT STUDIO
   ========================================================================== */
function initChat() {
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const messagesArea = document.getElementById('messages-area');
    const chips = document.querySelectorAll('.chip');

    // Query chips click
    chips.forEach(chip => {
        chip.addEventListener('click', () => {
            const prompt = chip.getAttribute('data-prompt');
            chatInput.value = prompt;
            chatForm.dispatchEvent(new Event('submit'));
        });
    });

    // Form submission
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const message = chatInput.value.trim();
        if (!message) return;

        // Render user message
        appendUserMessage(message);
        chatInput.value = '';

        // Render loading agent message
        const loadingId = 'loading-' + Date.now();
        appendLoadingMessage(loadingId);

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message })
            });

            const data = await response.json();
            removeMessage(loadingId);

            renderAgentResponse(data);
        } catch (err) {
            removeMessage(loadingId);
            appendErrorMessage(`Failed to communicate with agent server: ${err.message}`);
        }
    });
}

function appendUserMessage(text) {
    const messagesArea = document.getElementById('messages-area');
    const card = document.createElement('div');
    card.className = 'message-card user-message';
    card.innerHTML = `
        <div class="message-header">
            <div class="avatar user-avatar"><i data-lucide="user"></i></div>
            <div class="message-meta">
                <span class="sender-name">You</span>
                <span class="message-time">${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            </div>
        </div>
        <div class="message-body">
            <p>${escapeHtml(text)}</p>
        </div>
    `;
    messagesArea.appendChild(card);
    messagesArea.scrollTop = messagesArea.scrollHeight;
    if (window.lucide) lucide.createIcons();
}

function appendLoadingMessage(id) {
    const messagesArea = document.getElementById('messages-area');
    const card = document.createElement('div');
    card.id = id;
    card.className = 'message-card agent-message';
    card.innerHTML = `
        <div class="message-header">
            <div class="avatar agent-avatar"><i data-lucide="bot"></i></div>
            <div class="message-meta">
                <span class="sender-name">OLA AI Data Agent</span>
                <span class="message-time">Thinking...</span>
            </div>
        </div>
        <div class="message-body">
            <div style="display: flex; align-items: center; gap: 10px; color: var(--accent-cyan);">
                <div class="loading-spinner"></div>
                <span>Orchestrating agents, generating SQL & validating security policies...</span>
            </div>
        </div>
    `;
    messagesArea.appendChild(card);
    messagesArea.scrollTop = messagesArea.scrollHeight;
    if (window.lucide) lucide.createIcons();
}

function removeMessage(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function appendErrorMessage(errorText) {
    const messagesArea = document.getElementById('messages-area');
    const card = document.createElement('div');
    card.className = 'message-card agent-message';
    card.innerHTML = `
        <div class="message-header">
            <div class="avatar agent-avatar" style="background: var(--accent-red);"><i data-lucide="alert-triangle"></i></div>
            <div class="message-meta">
                <span class="sender-name">Agent Error</span>
            </div>
        </div>
        <div class="message-body" style="color: #FCA5A5;">
            <p>${escapeHtml(errorText)}</p>
        </div>
    `;
    messagesArea.appendChild(card);
    messagesArea.scrollTop = messagesArea.scrollHeight;
    if (window.lucide) lucide.createIcons();
}

function renderAgentResponse(data) {
    const messagesArea = document.getElementById('messages-area');
    const card = document.createElement('div');
    card.className = 'message-card agent-message';

    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const isSql = data.route === 'sql';
    const isSafe = data.is_safe === 'Yes';
    const routeBadgeClass = isSql ? 'sql' : 'etl';

    let html = `
        <div class="message-header">
            <div class="avatar agent-avatar"><i data-lucide="bot"></i></div>
            <div class="message-meta">
                <span class="sender-name">OLA AI Data Agent</span>
                <span class="p-badge ${routeBadgeClass}">${data.route.toUpperCase()} ANALYST</span>
                <span class="message-time">${timeStr}</span>
            </div>
        </div>
        <div class="message-body">
    `;

    // 1. Pipeline Accordion
    if (isSql && data.sql_query) {
        html += `
            <div class="agent-pipeline-box">
                <div class="pipeline-header" onclick="this.parentElement.querySelector('.pipeline-steps').classList.toggle('hidden')">
                    <span><i data-lucide="terminal"></i> Agent Reasoning & Security Verification</span>
                    <span class="p-badge ${isSafe ? 'safe' : 'p-badge-red'}">${isSafe ? '🛡️ Safe Query' : '⚠️ Blocked'}</span>
                </div>
                <div class="pipeline-steps">
                    <div class="p-step">
                        <strong>Curated:</strong> <span>${escapeHtml(data.curated_question || data.question)}</span>
                    </div>
                    <div class="p-step" style="flex-direction: column; width: 100%;">
                        <strong>Generated SQL:</strong>
                        <pre class="sql-code-block"><code class="language-sql">${escapeHtml(data.sql_query)}</code></pre>
                    </div>
                    <div class="p-step">
                        <strong>Judge Verdict:</strong> <span style="color: ${isSafe ? 'var(--primary-emerald)' : 'var(--accent-red)'}">${escapeHtml(data.judge_comments || 'Passed')}</span>
                    </div>
                </div>
            </div>
        `;
    }

    // 2. Main Answer Text
    html += `<div class="formatted-answer">${formatMarkdownText(data.answer)}</div>`;

    // 3. Visualization Container (Chart + Interactive Table)
    const uniqueVisId = 'vis-' + Date.now();
    const hasData = data.rows && data.rows.length > 0;
    const canChart = data.chart && data.chart.can_chart;

    if (hasData || canChart) {
        html += `
            <div class="data-vis-container" id="${uniqueVisId}">
                <div class="vis-header">
                    <span class="vis-title"><i data-lucide="bar-chart-2"></i> Result Visualization & Data</span>
                    <button class="btn-refresh" onclick="downloadCsv('${uniqueVisId}')"><i data-lucide="download"></i> Export CSV</button>
                </div>
        `;

        if (canChart) {
            html += `
                <div class="vis-chart-box">
                    <canvas id="chart-${uniqueVisId}"></canvas>
                </div>
            `;
        }

        if (hasData) {
            html += `
                <div class="table-responsive">
                    <table class="data-table" id="table-${uniqueVisId}">
                        <thead>
                            <tr>
                                ${data.columns.map(c => `<th>${escapeHtml(c)}</th>`).join('')}
                            </tr>
                        </thead>
                        <tbody>
                            ${data.rows.map(row => `
                                <tr>
                                    ${row.map(cell => `<td>${escapeHtml(String(cell))}</td>`).join('')}
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            `;
        }

        html += `</div>`;
    }

    html += `</div>`;
    card.innerHTML = html;
    messagesArea.appendChild(card);
    messagesArea.scrollTop = messagesArea.scrollHeight;

    // Highlight code blocks
    if (window.hljs) {
        card.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
    }

    // Render Chart if applicable
    if (canChart) {
        renderDynamicChart(`chart-${uniqueVisId}`, data.chart);
    }

    // Store data on table element for CSV download
    if (hasData) {
        const tableEl = document.getElementById(`table-${uniqueVisId}`);
        if (tableEl) {
            tableEl._dataColumns = data.columns;
            tableEl._dataRows = data.rows;
        }
    }

    if (window.lucide) lucide.createIcons();
}

function renderDynamicChart(canvasId, chartConfig) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const colors = [
        'rgba(16, 185, 129, 0.85)',
        'rgba(6, 182, 212, 0.85)',
        'rgba(139, 92, 246, 0.85)',
        'rgba(245, 158, 11, 0.85)',
        'rgba(239, 68, 68, 0.85)',
        'rgba(59, 130, 246, 0.85)'
    ];

    const isDoughnut = chartConfig.type === 'doughnut';

    new Chart(ctx, {
        type: chartConfig.type,
        data: {
            labels: chartConfig.labels,
            datasets: [{
                label: chartConfig.title || 'Value',
                data: chartConfig.values,
                backgroundColor: isDoughnut ? colors : 'rgba(16, 185, 129, 0.65)',
                borderColor: isDoughnut ? 'rgba(0,0,0,0.5)' : '#10B981',
                borderWidth: 1.5,
                borderRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: isDoughnut,
                    labels: { color: '#D1D5DB', font: { family: 'Inter', size: 11 } }
                },
                title: {
                    display: true,
                    text: chartConfig.title,
                    color: '#F9FAFB',
                    font: { family: 'Outfit', size: 13, weight: '600' }
                }
            },
            scales: isDoughnut ? {} : {
                x: {
                    ticks: { color: '#9CA3AF', font: { family: 'Inter', size: 11 } },
                    grid: { color: 'rgba(255, 255, 255, 0.05)' }
                },
                y: {
                    ticks: { color: '#9CA3AF', font: { family: 'Inter', size: 11 } },
                    grid: { color: 'rgba(255, 255, 255, 0.05)' }
                }
            }
        }
    });
}

function downloadCsv(visId) {
    const tableEl = document.getElementById(`table-${visId}`);
    if (!tableEl || !tableEl._dataColumns || !tableEl._dataRows) return;

    let csvContent = "data:text/csv;charset=utf-8,";
    csvContent += tableEl._dataColumns.map(c => `"${c}"`).join(",") + "\r\n";

    tableEl._dataRows.forEach(row => {
        csvContent += row.map(val => `"${String(val).replace(/"/g, '""')}"`).join(",") + "\r\n";
    });

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `ola_agent_export_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    link.remove();
}

/* ==========================================================================
   3. OVERVIEW / KPI DASHBOARD
   ========================================================================== */
async function initDashboard() {
    const refreshBtn = document.getElementById('refresh-stats-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadDashboardStats);
    }
    loadDashboardStats();
}

async function loadDashboardStats() {
    try {
        const res = await fetch('/api/stats');
        const stats = await res.json();

        // Update KPI cards
        document.getElementById('kpi-total-rides').textContent = Number(stats.total_rides || 0).toLocaleString();
        document.getElementById('kpi-completed-rides').textContent = `${Number(stats.completed_rides || 0).toLocaleString()} completed`;
        document.getElementById('kpi-revenue').textContent = '₹' + Number(stats.total_revenue || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        document.getElementById('kpi-users').textContent = Number(stats.total_users || 0).toLocaleString();
        document.getElementById('kpi-rating').textContent = `${stats.avg_rating || 0} ★`;

        // Render Payment Methods Chart
        renderPaymentMethodsChart(stats.payment_breakdown || []);

        // Render Ride Status Chart
        renderRideStatusChart(stats.rides_by_status || []);

        // Render Top Drivers Table
        renderTopDriversTable(stats.top_drivers || []);

    } catch (err) {
        console.error('Error loading dashboard stats:', err);
    }
}

function renderPaymentMethodsChart(data) {
    const ctx = document.getElementById('chart-payment-methods');
    if (!ctx) return;

    if (activeChartInstances.paymentChart) {
        activeChartInstances.paymentChart.destroy();
    }

    const labels = data.map(d => (d.payment_method || 'Unknown').toUpperCase());
    const counts = data.map(d => d.count);

    activeChartInstances.paymentChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: counts,
                backgroundColor: ['#10B981', '#06B6D4', '#8B5CF6', '#F59E0B', '#EF4444'],
                borderWidth: 2,
                borderColor: '#111827'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { color: '#9CA3AF', font: { family: 'Inter', size: 11 } } }
            }
        }
    });
}

function renderRideStatusChart(data) {
    const ctx = document.getElementById('chart-ride-status');
    if (!ctx) return;

    if (activeChartInstances.statusChart) {
        activeChartInstances.statusChart.destroy();
    }

    const labels = data.map(d => (d.status || 'Other').toUpperCase());
    const counts = data.map(d => d.count);

    activeChartInstances.statusChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Ride Count',
                data: counts,
                backgroundColor: 'rgba(6, 182, 212, 0.6)',
                borderColor: '#06B6D4',
                borderWidth: 1,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: { ticks: { color: '#9CA3AF', font: { family: 'Inter' } }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { ticks: { color: '#9CA3AF', font: { family: 'Inter' } }, grid: { color: 'rgba(255,255,255,0.05)' } }
            }
        }
    });
}

function renderTopDriversTable(drivers) {
    const wrapper = document.getElementById('top-drivers-table-wrapper');
    if (!wrapper) return;

    if (!drivers || drivers.length === 0) {
        wrapper.innerHTML = '<p class="placeholder-text">No driver data available yet.</p>';
        return;
    }

    let html = `
        <table class="data-table">
            <thead>
                <tr>
                    <th>Driver Name</th>
                    <th>Average Rating</th>
                    <th>Total Reviews</th>
                </tr>
            </thead>
            <tbody>
    `;

    drivers.forEach(d => {
        html += `
            <tr>
                <td><strong>${escapeHtml(d.driver_name || 'Driver')}</strong></td>
                <td><span style="color: var(--accent-amber); font-weight: 600;">★ ${d.avg_rating}</span></td>
                <td>${d.total_reviews} reviews</td>
            </tr>
        `;
    });

    html += `</tbody></table>`;
    wrapper.innerHTML = html;
}

/* ==========================================================================
   4. DATABASE EXPLORER
   ========================================================================== */
let dbSchemaCache = {};

async function initDbExplorer() {
    const searchInput = document.getElementById('db-search-input');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();
            filterActiveTableRows(query);
        });
    }
}

async function loadDbSchema() {
    const listContainer = document.getElementById('db-table-list');
    listContainer.innerHTML = '<p class="loading-text">Fetching schema...</p>';

    try {
        const res = await fetch('/api/schema');
        const data = await res.json();
        dbSchemaCache = data.tables || {};

        const tableNames = Object.keys(dbSchemaCache);
        if (tableNames.length === 0) {
            listContainer.innerHTML = '<p class="placeholder-text">No tables found. Run feed_db.py to populate.</p>';
            return;
        }

        listContainer.innerHTML = '';
        tableNames.forEach((tName, idx) => {
            const tInfo = dbSchemaCache[tName];
            const btn = document.createElement('button');
            btn.className = `table-btn ${idx === 0 ? 'active' : ''}`;
            btn.innerHTML = `
                <span>${tName}</span>
                <span class="table-badge">${Number(tInfo.row_count || 0).toLocaleString()} rows</span>
            `;
            btn.addEventListener('click', () => {
                document.querySelectorAll('.table-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                displayTableData(tName);
            });
            listContainer.appendChild(btn);
        });

        // Load first table by default
        if (tableNames.length > 0) {
            displayTableData(tableNames[0]);
        }

    } catch (err) {
        listContainer.innerHTML = `<p class="placeholder-text" style="color: var(--accent-red);">Error: ${err.message}</p>`;
    }
}

async function displayTableData(tableName) {
    const title = document.getElementById('active-table-title');
    const meta = document.getElementById('active-table-meta');
    const schemaInner = document.getElementById('schema-columns-table');
    const dataWrapper = document.getElementById('active-table-data-wrapper');

    title.textContent = `public.${tableName}`;
    const tInfo = dbSchemaCache[tableName] || {};
    meta.textContent = `${tInfo.row_count || 0} total records`;

    // Render columns schema table
    const columns = tInfo.columns || [];
    let schemaHtml = `
        <table class="data-table">
            <thead>
                <tr>
                    <th>Column Name</th>
                    <th>Data Type</th>
                    <th>Nullable</th>
                </tr>
            </thead>
            <tbody>
    `;
    columns.forEach(c => {
        schemaHtml += `
            <tr>
                <td><code>${c.column_name}</code></td>
                <td><span style="color: var(--accent-cyan);">${c.data_type}</span></td>
                <td>${c.is_nullable}</td>
            </tr>
        `;
    });
    schemaHtml += `</tbody></table>`;
    schemaInner.innerHTML = schemaHtml;

    // Fetch live 50 rows
    dataWrapper.innerHTML = '<p class="loading-text">Loading rows...</p>';
    try {
        const res = await fetch(`/api/tables/${tableName}?limit=50`);
        const tableData = await res.json();

        if (tableData.rows && tableData.rows.length > 0) {
            let dataHtml = `
                <table class="data-table" id="db-live-table">
                    <thead>
                        <tr>
                            ${tableData.columns.map(c => `<th>${escapeHtml(c)}</th>`).join('')}
                        </tr>
                    </thead>
                    <tbody>
                        ${tableData.rows.map(row => `
                            <tr>
                                ${row.map(cell => `<td>${escapeHtml(String(cell))}</td>`).join('')}
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
            dataWrapper.innerHTML = dataHtml;
        } else {
            dataWrapper.innerHTML = '<p class="placeholder-text">Table is empty.</p>';
        }
    } catch (err) {
        dataWrapper.innerHTML = `<p class="placeholder-text" style="color: var(--accent-red);">Error: ${err.message}</p>`;
    }
}

function filterActiveTableRows(query) {
    const table = document.getElementById('db-live-table');
    if (!table) return;

    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(query) ? '' : 'none';
    });
}

/* ==========================================================================
   5. ETL STUDIO
   ========================================================================== */
function initEtlStudio() {
    const extractForm = document.getElementById('etl-extract-form');
    const transformForm = document.getElementById('etl-transform-form');
    const refreshFilesBtn = document.getElementById('refresh-files-btn');

    if (extractForm) {
        extractForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const url = document.getElementById('extract-url').value.trim();
            const format = document.getElementById('extract-format').value;
            const folder = document.getElementById('extract-folder').value.trim();
            const outputBox = document.getElementById('extract-output');
            const btn = document.getElementById('btn-run-extract');

            btn.disabled = true;
            btn.innerHTML = '<div class="loading-spinner"></div> Extracting...';
            outputBox.innerHTML = '<p class="loading-text">Downloading from API and writing dataset...</p>';

            try {
                const res = await fetch('/api/etl/extract', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url, output_format: format, output_folder: folder })
                });
                const data = await res.json();
                outputBox.innerHTML = `
                    <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid var(--primary-emerald); padding: 12px; border-radius: 8px; color: #D1D5DB; margin-top: 10px;">
                        <strong style="color: var(--primary-emerald);">Result:</strong>
                        <pre style="white-space: pre-wrap; font-family: var(--font-mono); font-size: 0.8rem; margin-top: 6px;">${escapeHtml(data.message)}</pre>
                    </div>
                `;
                loadDataFiles();
            } catch (err) {
                outputBox.innerHTML = `<p style="color: var(--accent-red);">Extraction failed: ${err.message}</p>`;
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i data-lucide="play"></i> Run Extraction';
                if (window.lucide) lucide.createIcons();
            }
        });
    }

    if (transformForm) {
        transformForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const inputFile = document.getElementById('transform-file').value.trim();
            const prompt = document.getElementById('transform-prompt').value.trim();
            const format = document.getElementById('transform-format').value;
            const folder = document.getElementById('transform-folder').value.trim();
            const outputBox = document.getElementById('transform-output');
            const btn = document.getElementById('btn-run-transform');

            btn.disabled = true;
            btn.innerHTML = '<div class="loading-spinner"></div> Generating & Executing Code...';
            outputBox.innerHTML = '<p class="loading-text">Consulting Gemini to write and execute Pandas transformation...</p>';

            try {
                const res = await fetch('/api/etl/transform', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        input_file: inputFile,
                        user_question: prompt,
                        output_format: format,
                        output_folder: folder
                    })
                });
                const data = await res.json();
                outputBox.innerHTML = `
                    <div style="background: rgba(6, 182, 212, 0.1); border: 1px solid var(--accent-cyan); padding: 12px; border-radius: 8px; color: #D1D5DB; margin-top: 10px;">
                        <strong style="color: var(--accent-cyan);">Transformation Result:</strong>
                        <div style="margin-top: 8px;">${formatMarkdownText(data.message)}</div>
                    </div>
                `;
                if (window.hljs) {
                    outputBox.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
                }
                loadDataFiles();
            } catch (err) {
                outputBox.innerHTML = `<p style="color: var(--accent-red);">Transform failed: ${err.message}</p>`;
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i data-lucide="code"></i> Generate & Execute Transform';
                if (window.lucide) lucide.createIcons();
            }
        });
    }

    if (refreshFilesBtn) {
        refreshFilesBtn.addEventListener('click', loadDataFiles);
    }
}

async function loadDataFiles() {
    const listWrapper = document.getElementById('files-list-wrapper');
    if (!listWrapper) return;

    try {
        const res = await fetch('/api/files');
        const data = await res.json();
        const files = data.files || [];

        if (files.length === 0) {
            listWrapper.innerHTML = '<p class="placeholder-text">No extracted or transformed files found yet.</p>';
            return;
        }

        listWrapper.innerHTML = '';
        files.forEach((f, idx) => {
            const btn = document.createElement('button');
            btn.className = 'file-chip-btn';
            btn.innerHTML = `<i data-lucide="file-text"></i> ${f.relative_path} <span style="color: var(--text-dim);">(${f.size_kb} KB)</span>`;
            btn.addEventListener('click', () => previewFileContent(f.relative_path));
            listWrapper.appendChild(btn);
        });

        if (window.lucide) lucide.createIcons();

        // Preview the first file
        if (files.length > 0) {
            previewFileContent(files[0].relative_path);
        }
    } catch (err) {
        console.error('Error loading files:', err);
    }
}

async function previewFileContent(filePath) {
    const tableWrapper = document.getElementById('file-preview-table-wrapper');
    if (!tableWrapper) return;

    tableWrapper.innerHTML = `<p class="loading-text">Loading preview for ${filePath}...</p>`;

    try {
        const res = await fetch(`/api/files/preview?path=${encodeURIComponent(filePath)}`);
        const data = await res.json();

        if (data.error) {
            tableWrapper.innerHTML = `<p style="color: var(--accent-red);">Error: ${data.error}</p>`;
            return;
        }

        let html = `
            <div style="margin-bottom: 8px; font-size: 0.82rem; color: var(--accent-cyan);">
                Previewing <strong>${filePath}</strong> (${data.total_rows || data.rows.length} total rows)
            </div>
            <table class="data-table">
                <thead>
                    <tr>${data.columns.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr>
                </thead>
                <tbody>
                    ${data.rows.map(r => `<tr>${r.map(cell => `<td>${escapeHtml(String(cell))}</td>`).join('')}</tr>`).join('')}
                </tbody>
            </table>
        `;
        tableWrapper.innerHTML = html;
    } catch (err) {
        tableWrapper.innerHTML = `<p style="color: var(--accent-red);">Error previewing file: ${err.message}</p>`;
    }
}

/* ==========================================================================
   6. HELPERS
   ========================================================================== */
function escapeHtml(str) {
    if (typeof str !== 'string') return str;
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function formatMarkdownText(text) {
    if (!text) return '';
    
    // Basic Markdown transformations
    let html = escapeHtml(text);
    
    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    
    // Italic
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    
    // Inline code
    html = html.replace(/`(.*?)`/g, '<code style="background: rgba(255,255,255,0.08); padding: 2px 6px; border-radius: 4px; color: #38bdf8;">$1</code>');
    
    // Markdown code blocks
    html = html.replace(/```python([\s\S]*?)```/g, '<pre class="sql-code-block"><code class="language-python">$1</code></pre>');
    html = html.replace(/```sql([\s\S]*?)```/g, '<pre class="sql-code-block"><code class="language-sql">$1</code></pre>');
    html = html.replace(/```([\s\S]*?)```/g, '<pre class="sql-code-block"><code>$1</code></pre>');

    // Line breaks
    html = html.replace(/\n/g, '<br>');
    
    return html;
}
