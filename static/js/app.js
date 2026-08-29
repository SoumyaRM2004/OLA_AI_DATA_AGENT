/**
 * OLA AI Data Agent — Frontend Application Logic
 */

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initChat();
    initDashboard();
    initDbExplorer();
    initEtlStudio();
    initDataImport();
});

// Global state
let activeChartInstances = {};
const CHAT_STORAGE_KEY = 'ola_ai_data_agent_chat_v1';

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
            desc: 'Ask natural language questions to query OLA ride data, correlate with Open-Meteo weather, or trigger ETL pipelines.'
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
            title: 'Weather ETL Studio',
            desc: 'Extract data from external APIs and transform datasets using natural language.'
        },
        'import-view': {
            title: 'Mobility CSV Dataset Importer',
            desc: 'Validate and import custom CSV datasets for Users, Vehicles, Rides, Payments, and Ratings with duplicate and foreign-key checks.'
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
            } else if (targetTab === 'import-view') {
                refreshStagedTable();
            }

            // Re-render icons if needed
            if (window.lucide) lucide.createIcons();
        });
    });
}

/* ==========================================================================
   2. AI CHAT STUDIO & PERSISTENCE
   ========================================================================== */

function getChatHistory() {
    try {
        const raw = localStorage.getItem(CHAT_STORAGE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
        console.warn("Error reading chat history from localStorage:", e);
        return [];
    }
}

function saveChatHistory(history) {
    try {
        localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(history));
    } catch (e) {
        console.warn("Error saving chat history to localStorage:", e);
    }
}

function renderDefaultWelcomeMessage() {
    const messagesArea = document.getElementById('messages-area');
    messagesArea.innerHTML = `
        <div class="message-card agent-message">
            <div class="message-header">
                <div class="avatar agent-avatar"><i data-lucide="bot"></i></div>
                <div class="message-meta">
                    <span class="sender-name">OLA AI Data Agent</span>
                    <span class="message-time">Just now</span>
                </div>
            </div>
            <div class="message-body">
                <p>Welcome to the <strong>OLA Mobility Intelligence Platform</strong>! I am your AI Data Agent combining synthetic ride-hailing datasets with external <strong>Open-Meteo weather data across all 8 Canadian ride-hailing cities</strong>.</p>
                <ul>
                    <li>📊 <strong>SQL Analytics</strong>: Query rides, fares, driver ratings, and correlate ride metrics with weather conditions (rain vs. cancellations, surge pricing) across Calgary, Edmonton, Halifax, Montreal, Ottawa, Toronto, Vancouver, and Winnipeg.</li>
                    <li>🌦️ <strong>Weather & Mobility ETL</strong>: Extract historical hourly weather data for all 8 cities from Open-Meteo Archive API and transform datasets using Pandas.</li>
                    <li>📁 <strong>CSV Data Import</strong>: Upload and validate custom datasets for Users, Vehicles, Rides, Payments, and Ratings with strict schema and foreign-key checks.</li>
                </ul>
                <p>Every SQL query is evaluated by an automated <strong>Security Judge</strong> before execution for safe read-only analytics!</p>
            </div>
        </div>
    `;
    if (window.lucide) lucide.createIcons();
}

function restoreChatHistory() {
    const history = getChatHistory();
    const messagesArea = document.getElementById('messages-area');

    if (!history || history.length === 0) {
        renderDefaultWelcomeMessage();
        return;
    }

    messagesArea.innerHTML = '';
    history.forEach(item => {
        if (item.role === 'user') {
            appendUserMessage(item.text, item.time, false);
        } else if (item.role === 'assistant' && item.data) {
            renderAgentResponse(item.data, item.time, false);
        }
    });
}

function initChat() {
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const chips = document.querySelectorAll('.chip');

    // Restore saved chat history on load
    restoreChatHistory();

    // Query chips click
    chips.forEach(chip => {
        chip.addEventListener('click', () => {
            const prompt = chip.getAttribute('data-prompt');
            chatInput.value = prompt;
            chatForm.dispatchEvent(new Event('submit'));
        });
    });

    // Chat Actions: New Chat, Clear History, Export Chat
    const btnNewChat = document.getElementById('btn-new-chat');
    const btnClearChat = document.getElementById('btn-clear-chat');
    const btnExportChat = document.getElementById('btn-export-chat');

    if (btnNewChat) {
        btnNewChat.addEventListener('click', () => {
            localStorage.removeItem(CHAT_STORAGE_KEY);
            renderDefaultWelcomeMessage();
        });
    }

    if (btnClearChat) {
        btnClearChat.addEventListener('click', () => {
            if (confirm("Are you sure you want to clear your saved chat history? This cannot be undone.")) {
                localStorage.removeItem(CHAT_STORAGE_KEY);
                renderDefaultWelcomeMessage();
            }
        });
    }

    if (btnExportChat) {
        btnExportChat.addEventListener('click', () => {
            const history = getChatHistory();
            if (history.length === 0) {
                alert("No chat history to export yet.");
                return;
            }

            const exportData = {
                platform: "OLA AI Data Agent",
                exported_at: new Date().toISOString(),
                total_messages: history.length,
                conversation: history
            };

            const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(exportData, null, 2));
            const downloadAnchor = document.createElement('a');
            downloadAnchor.setAttribute("href", dataStr);
            downloadAnchor.setAttribute("download", `ola_chat_export_${new Date().toISOString().slice(0,10)}.json`);
            document.body.appendChild(downloadAnchor);
            downloadAnchor.click();
            downloadAnchor.remove();
        });
    }

    // Form submission
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const message = chatInput.value.trim();
        if (!message) return;

        const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        // 1. Render & persist user message
        appendUserMessage(message, timeStr, true);
        chatInput.value = '';

        // 2. Render loading agent message
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

            // 3. Render & persist agent response
            renderAgentResponse(data, timeStr, true);
        } catch (err) {
            removeMessage(loadingId);
            appendErrorMessage(`Failed to communicate with agent server: ${err.message}`);
        }
    });
}

function appendUserMessage(text, timeStr = null, shouldSave = true) {
    const messagesArea = document.getElementById('messages-area');
    const card = document.createElement('div');
    card.className = 'message-card user-message';
    const displayTime = timeStr || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    card.innerHTML = `
        <div class="message-header">
            <div class="avatar user-avatar"><i data-lucide="user"></i></div>
            <div class="message-meta">
                <span class="sender-name">You</span>
                <span class="message-time">${displayTime}</span>
            </div>
        </div>
        <div class="message-body">
            <p>${escapeHtml(text)}</p>
        </div>
    `;
    messagesArea.appendChild(card);
    messagesArea.scrollTop = messagesArea.scrollHeight;
    if (window.lucide) lucide.createIcons();

    if (shouldSave) {
        const history = getChatHistory();
        history.push({
            role: 'user',
            text: text,
            time: displayTime,
            timestamp: new Date().toISOString()
        });
        saveChatHistory(history);
    }
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

function renderAgentResponse(data, timeStr = null, shouldSave = true) {
    const messagesArea = document.getElementById('messages-area');
    const card = document.createElement('div');
    card.className = 'message-card agent-message';

    const displayTime = timeStr || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const isSql = data.route === 'sql';
    const isSafe = data.is_safe === 'Yes';
    const routeBadgeClass = isSql ? 'sql' : 'etl';

    let html = `
        <div class="message-header">
            <div class="avatar agent-avatar"><i data-lucide="bot"></i></div>
            <div class="message-meta">
                <span class="sender-name">OLA AI Data Agent</span>
                <span class="p-badge ${routeBadgeClass}">${(data.route || 'SQL').toUpperCase()} ANALYST</span>
                <span class="message-time">${displayTime}</span>
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
    const uniqueVisId = 'vis-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
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

    if (shouldSave) {
        const history = getChatHistory();
        history.push({
            role: 'assistant',
            data: data,
            time: displayTime,
            timestamp: new Date().toISOString()
        });
        saveChatHistory(history);
    }
}

function renderDynamicChart(canvasId, chartConfig) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    if (activeChartInstances[canvasId]) {
        activeChartInstances[canvasId].destroy();
    }

    const colors = [
        'rgba(16, 185, 129, 0.85)',
        'rgba(6, 182, 212, 0.85)',
        'rgba(139, 92, 246, 0.85)',
        'rgba(245, 158, 11, 0.85)',
        'rgba(239, 68, 68, 0.85)',
        'rgba(59, 130, 246, 0.85)',
        'rgba(236, 72, 153, 0.85)',
        'rgba(168, 85, 247, 0.85)'
    ];

    const isDoughnut = chartConfig.type === 'doughnut';

    // Format labels defensively on frontend
    const formattedLabels = (chartConfig.labels || []).map(lbl => {
        const s = String(lbl);
        if (s.toLowerCase() === 'true' || s.toLowerCase() === 'false') {
            const isT = s.toLowerCase() === 'true';
            const col = (chartConfig.label_column || '').toLowerCase();
            if (col.includes('rain') || col.includes('weather')) return isT ? 'Rainy' : 'Non-Rainy';
            if (col.includes('active')) return isT ? 'Active' : 'Inactive';
            return isT ? 'Yes' : 'No';
        }
        return s;
    });

    activeChartInstances[canvasId] = new Chart(ctx, {
        type: chartConfig.type || 'bar',
        data: {
            labels: formattedLabels,
            datasets: [{
                label: chartConfig.title || 'Metric',
                data: chartConfig.values || [],
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
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const val = context.parsed.y !== undefined ? context.parsed.y : context.parsed;
                            return ` ${context.label}: ${Number(val).toLocaleString()}`;
                        }
                    }
                }
            },
            scales: isDoughnut ? {} : {
                x: {
                    ticks: { color: '#9CA3AF', font: { family: 'Inter', size: 11 } },
                    grid: { color: 'rgba(255, 255, 255, 0.05)' }
                },
                y: {
                    ticks: { color: '#9CA3AF', font: { family: 'Inter', size: 11 } },
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    beginAtZero: true
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

        // Update Weather KPI card
        if (stats.weather_stats) {
            const wCities = stats.weather_stats.cities_count || 0;
            const wRecords = stats.weather_stats.total_records || 0;
            const wEl = document.getElementById('kpi-weather-cities');
            const wSubEl = document.getElementById('kpi-weather-records');
            if (wEl) wEl.textContent = `${wCities} Cities`;
            if (wSubEl) wSubEl.textContent = `${Number(wRecords).toLocaleString()} records (Jan 2025)`;

            // Render city rainfall chart
            renderCityRainfallChart(stats.weather_stats.city_breakdown || []);
        }

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

function renderCityRainfallChart(cityData) {
    const ctx = document.getElementById('chart-city-rainfall');
    if (!ctx) return;

    if (activeChartInstances.rainfallChart) {
        activeChartInstances.rainfallChart.destroy();
    }

    const labels = cityData.map(d => d.city);
    const rainVals = cityData.map(d => d.total_precip_mm || 0);

    activeChartInstances.rainfallChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Total Precip (mm)',
                data: rainVals,
                backgroundColor: 'rgba(59, 130, 246, 0.6)',
                borderColor: '#3B82F6',
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
                x: { ticks: { color: '#9CA3AF', font: { family: 'Inter', size: 10 } }, grid: { color: 'rgba(255,255,255,0.05)' } },
                y: { ticks: { color: '#9CA3AF', font: { family: 'Inter', size: 10 } }, grid: { color: 'rgba(255,255,255,0.05)' } }
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
        if (!res.ok) {
            let errorText = `Database schema request failed (HTTP ${res.status}). Check server logs.`;
            try {
                const errData = await res.json();
                if (errData && errData.error) errorText = errData.error;
            } catch (_) {}
            listContainer.innerHTML = `<p class="placeholder-text" style="color: var(--accent-red);">${escapeHtml(errorText)}</p>`;
            return;
        }

        const data = await res.json();
        if (data.error) {
            listContainer.innerHTML = `<p class="placeholder-text" style="color: var(--accent-red);">${escapeHtml(data.error)}</p>`;
            return;
        }

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
        listContainer.innerHTML = `<p class="placeholder-text" style="color: var(--accent-red);">Database schema request failed: ${escapeHtml(err.message || 'Check server logs.')}</p>`;
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
                <td><code>${escapeHtml(c.column_name)}</code></td>
                <td><span style="color: var(--accent-cyan);">${escapeHtml(c.data_type)}</span></td>
                <td>${escapeHtml(c.is_nullable)}</td>
            </tr>
        `;
    });
    schemaHtml += `</tbody></table>`;
    schemaInner.innerHTML = schemaHtml;

    // Fetch live 50 rows
    dataWrapper.innerHTML = '<p class="loading-text">Loading rows...</p>';
    try {
        const res = await fetch(`/api/tables/${tableName}?limit=50`);
        if (!res.ok) {
            let errorText = `Failed to fetch live rows for ${tableName} (HTTP ${res.status}). Check server logs.`;
            try {
                const errData = await res.json();
                if (errData && errData.error) errorText = errData.error;
            } catch (_) {}
            dataWrapper.innerHTML = `<p class="placeholder-text" style="color: var(--accent-red);">${escapeHtml(errorText)}</p>`;
            return;
        }

        const tableData = await res.json();

        if (tableData.error) {
            dataWrapper.innerHTML = `<p class="placeholder-text" style="color: var(--accent-red);">${escapeHtml(tableData.error)}</p>`;
            return;
        }

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
                                ${row.map(cell => `<td>${escapeHtml(String(cell !== null && cell !== undefined ? cell : ''))}</td>`).join('')}
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
        dataWrapper.innerHTML = `<p class="placeholder-text" style="color: var(--accent-red);">Failed to fetch live rows for ${tableName}: ${escapeHtml(err.message || 'Check server logs.')}</p>`;
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
            const citySelect = document.getElementById('extract-city-select') ? document.getElementById('extract-city-select').value : 'All 8 Cities';
            const startDate = document.getElementById('extract-start-date') ? document.getElementById('extract-start-date').value : '2025-01-01';
            const endDate = document.getElementById('extract-end-date') ? document.getElementById('extract-end-date').value : '2025-01-31';
            const format = document.getElementById('extract-format').value;
            const folder = document.getElementById('extract-folder').value.trim();
            const outputBox = document.getElementById('extract-output');
            const btn = document.getElementById('btn-run-extract');

            btn.disabled = true;
            btn.innerHTML = '<div class="loading-spinner"></div> Extracting Multi-City Weather...';
            outputBox.innerHTML = '<p class="loading-text">Downloading from Open-Meteo Archive API and writing dataset...</p>';

            try {
                const res = await fetch('/api/etl/extract', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        city_name: citySelect,
                        start_date: startDate,
                        end_date: endDate,
                        output_format: format,
                        output_folder: folder
                    })
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
                btn.innerHTML = '<i data-lucide="play"></i> Extract Weather Dataset';
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

    let activePreviewFile = "data/extract/weather_data.csv";

    const loadToDbBtn = document.getElementById('load-to-db-btn');
    if (loadToDbBtn) {
        loadToDbBtn.addEventListener('click', async () => {
            loadToDbBtn.disabled = true;
            loadToDbBtn.innerHTML = '<div class="loading-spinner"></div> Loading into PostgreSQL...';
            try {
                const targetFile = activePreviewFile || 'data/extract/weather_data.csv';
                const res = await fetch('/api/etl/load-db', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ file_path: targetFile, table_name: 'weather_data' })
                });
                const data = await res.json();
                alert(data.message || 'Dataset loaded into PostgreSQL!');
                loadDbSchema();
            } catch (err) {
                alert('Database Load Error: ' + err.message);
            } finally {
                loadToDbBtn.disabled = false;
                loadToDbBtn.innerHTML = '<i data-lucide="upload-cloud"></i> Load to PostgreSQL (weather_data)';
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
            btn.addEventListener('click', () => {
                activePreviewFile = f.relative_path;
                previewFileContent(f.relative_path);
            });
            listWrapper.appendChild(btn);
        });

        if (window.lucide) lucide.createIcons();

        // Preview the first file
        if (files.length > 0) {
            activePreviewFile = files[0].relative_path;
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
   5.5 DATA IMPORT STUDIO
   ========================================================================== */

let stagedDatasetsState = {};

function initDataImport() {
    const uploadForm = document.getElementById('import-upload-form');
    const fileInput = document.getElementById('import-file-input');
    const dropArea = document.getElementById('file-drop-area');
    const selectedBadge = document.getElementById('selected-file-name');
    const targetSelect = document.getElementById('import-target-table');
    const btnValidate = document.getElementById('btn-validate-csv');
    const validationOutput = document.getElementById('validation-output');
    const btnLoadDb = document.getElementById('btn-load-database');
    const btnClearStaged = document.getElementById('btn-clear-staged');
    const loadOutput = document.getElementById('load-db-output');

    if (!uploadForm) return;

    function updateValidateButtonState() {
        const hasDatasetType = targetSelect && targetSelect.value.trim() !== '';
        const hasFile = fileInput && fileInput.files && fileInput.files.length > 0;
        if (btnValidate) {
            btnValidate.disabled = !(hasDatasetType && hasFile);
        }
    }

    // Dataset type change listener
    if (targetSelect) {
        targetSelect.addEventListener('change', updateValidateButtonState);
    }

    // Drag and drop handlers
    ['dragenter', 'dragover'].forEach(eventName => {
        dropArea.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropArea.classList.add('dragover');
        });
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropArea.classList.remove('dragover');
        });
    });

    dropArea.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
            fileInput.files = files;
            updateSelectedFileUI(files[0]);
        }
        updateValidateButtonState();
    });

    dropArea.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            updateSelectedFileUI(fileInput.files[0]);
        } else {
            updateValidateButtonState();
        }
    });

    function updateSelectedFileUI(file) {
        selectedBadge.style.display = 'inline-flex';
        selectedBadge.innerHTML = `<span style="color: var(--primary-emerald); font-weight: 700; margin-right: 6px;">✓</span> <strong>${escapeHtml(file.name)}</strong> <span style="color: var(--text-dim); margin-left: 6px;">(${(file.size / 1024).toFixed(1)} KB)</span>`;
        if (window.lucide) lucide.createIcons();
        updateValidateButtonState();
    }

    // Initial state check
    updateValidateButtonState();
    if (btnLoadDb) {
        btnLoadDb.disabled = Object.keys(stagedDatasetsState).length === 0;
    }

    // Form Submission: Validate CSV
    uploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!fileInput.files || fileInput.files.length === 0) {
            alert('Please select a CSV file to validate.');
            return;
        }

        const file = fileInput.files[0];
        const datasetType = targetSelect.value;

        if (!datasetType) {
            alert('Please select a Dataset Type (Users, Vehicles, Rides, Payments, or Ratings).');
            return;
        }

        btnValidate.disabled = true;
        btnValidate.innerHTML = '<div class="loading-spinner"></div> Validating Dataset Schema & PKs...';
        validationOutput.style.display = 'block';
        validationOutput.innerHTML = '<p class="loading-text">Validating column mappings, primary key uniqueness, and non-empty fields against the selected schema...</p>';

        try {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('dataset_type', datasetType);

            const res = await fetch('/api/import/validate', {
                method: 'POST',
                body: formData
            });

            const data = await res.json();
            renderValidationResult(data);

            if (data.valid && data.table_name) {
                stagedDatasetsState[data.table_name] = {
                    filename: data.filename,
                    row_count: data.row_count,
                    columns: data.columns,
                    sample_records: data.sample_records,
                    staged_at: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                };
                refreshStagedTable();
                showImportPreview(data.table_name, data.sample_records, data.columns, data.row_count);
            }
        } catch (err) {
            validationOutput.innerHTML = `<div class="import-error-list"><strong>Network/Server Error:</strong> ${escapeHtml(err.message)}</div>`;
        } finally {
            btnValidate.innerHTML = '<i data-lucide="check-circle"></i> Validate CSV Dataset';
            updateValidateButtonState();
            if (window.lucide) lucide.createIcons();
        }
    });

    // Load staged datasets into PostgreSQL
    btnLoadDb.addEventListener('click', async () => {
        const stagedTables = Object.keys(stagedDatasetsState);
        if (stagedTables.length === 0) {
            alert('No validated datasets are staged for loading.');
            return;
        }

        btnLoadDb.disabled = true;
        btnLoadDb.innerHTML = '<div class="loading-spinner"></div> Executing Atomic Transaction...';
        loadOutput.innerHTML = '<p class="loading-text">Validating foreign keys and executing PostgreSQL batch insert...</p>';

        try {
            const res = await fetch('/api/import/load', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tables: stagedTables })
            });

            const result = await res.json();

            if (result.success) {
                let countSummary = '';
                if (result.loaded_counts) {
                    countSummary = Object.entries(result.loaded_counts)
                        .map(([t, c]) => `• <strong>${t}</strong>: ${c} rows`)
                        .join('<br>');
                }

                loadOutput.innerHTML = `
                    <div style="background: rgba(16, 185, 129, 0.15); border: 1px solid var(--primary-emerald); padding: 14px; border-radius: 8px; color: #D1D5DB;">
                        <div style="display: flex; align-items: center; gap: 8px; color: var(--primary-emerald); font-weight: 600; margin-bottom: 6px;">
                            <i data-lucide="check-circle-2"></i> Database Load Successful!
                        </div>
                        <p style="font-size: 0.88rem; margin-bottom: 8px;">All datasets committed atomically in dependency order:</p>
                        <div style="font-size: 0.84rem; line-height: 1.6;">${countSummary}</div>
                    </div>
                `;

                // Reset staged state
                stagedDatasetsState = {};
                refreshStagedTable();

                // Automatically refresh DB explorer & KPI dashboard
                loadDbSchema();
                loadDashboardStats();
            } else {
                let errHtml = `<strong style="color: var(--accent-red);">${escapeHtml(result.error || 'Database load failed.')}</strong>`;
                if (result.errors && result.errors.length > 0) {
                    errHtml += `<ul style="margin-top: 6px; margin-left: 18px;">${result.errors.map(e => `<li>${escapeHtml(e)}</li>`).join('')}</ul>`;
                }
                loadOutput.innerHTML = `
                    <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid var(--accent-red); padding: 14px; border-radius: 8px; color: #FECACA;">
                        <div style="display: flex; align-items: center; gap: 8px; color: var(--accent-red); font-weight: 600; margin-bottom: 6px;">
                            <i data-lucide="alert-octagon"></i> Transaction Rolled Back
                        </div>
                        <p style="font-size: 0.86rem;">No partial changes were saved. Please resolve the integrity errors and retry:</p>
                        <div style="font-size: 0.84rem; margin-top: 6px;">${errHtml}</div>
                    </div>
                `;
            }
        } catch (err) {
            loadOutput.innerHTML = `<div class="import-error-list"><strong>Failed to execute database load:</strong> ${escapeHtml(err.message)}</div>`;
        } finally {
            btnLoadDb.disabled = Object.keys(stagedDatasetsState).length === 0;
            btnLoadDb.innerHTML = '<i data-lucide="database"></i> Load into PostgreSQL (Atomic Transaction)';
            if (window.lucide) lucide.createIcons();
        }
    });

    // Clear Staged Datasets
    btnClearStaged.addEventListener('click', async () => {
        try {
            await fetch('/api/import/clear-staged', { method: 'POST' });
            stagedDatasetsState = {};
            refreshStagedTable();
            loadOutput.innerHTML = '';
            validationOutput.style.display = 'none';
            document.getElementById('import-preview-section').style.display = 'none';
        } catch (err) {
            console.error('Error clearing staged:', err);
        }
    });
}

function renderValidationResult(data) {
    const validationOutput = document.getElementById('validation-output');
    validationOutput.style.display = 'block';

    const isValid = data.valid;
    const errors = data.errors || [];
    const warnings = data.warnings || [];

    let checkpointsHtml = `
        <div class="checkpoint-list">
            <div class="checkpoint-item ${data.filename.endsWith('.csv') ? 'pass' : 'fail'}">
                <i data-lucide="${data.filename.endsWith('.csv') ? 'check-circle' : 'x-circle'}"></i>
                <span>File Format: CSV (.csv) Verified</span>
            </div>
            <div class="checkpoint-item ${errors.some(e => e.includes('missing required column')) ? 'fail' : 'pass'}">
                <i data-lucide="${errors.some(e => e.includes('missing required column')) ? 'x-circle' : 'check-circle'}"></i>
                <span>Required Schema Columns: ${errors.some(e => e.includes('missing required column')) ? 'Missing Columns' : 'All Present'}</span>
            </div>
            <div class="checkpoint-item ${errors.some(e => e.includes('duplicate primary key')) ? 'fail' : 'pass'}">
                <i data-lucide="${errors.some(e => e.includes('duplicate primary key')) ? 'x-circle' : 'check-circle'}"></i>
                <span>Primary Key Uniqueness: ${errors.some(e => e.includes('duplicate primary key')) ? 'Duplicate PKs Detected' : '0 Duplicates'}</span>
            </div>
            <div class="checkpoint-item ${errors.some(e => e.includes('completely empty')) ? 'fail' : 'pass'}">
                <i data-lucide="${errors.some(e => e.includes('completely empty')) ? 'x-circle' : 'check-circle'}"></i>
                <span>Field Completeness: ${errors.some(e => e.includes('completely empty')) ? 'Empty Required Fields' : 'Populated'}</span>
            </div>
        </div>
    `;

    let errorsHtml = '';
    if (errors.length > 0) {
        errorsHtml = `
            <div class="import-error-list">
                <strong>Validation Errors Detected:</strong>
                <ul>
                    ${errors.map(err => `<li>${escapeHtml(err)}</li>`).join('')}
                </ul>
            </div>
        `;
    }

    let warningsHtml = '';
    if (warnings.length > 0) {
        warningsHtml = `
            <div style="margin-top: 10px; padding: 8px 12px; background: rgba(245, 158, 11, 0.12); border-left: 3px solid var(--accent-amber); border-radius: 4px; color: #FCD34D; font-size: 0.82rem;">
                <strong>Warnings:</strong>
                <ul style="margin-left: 18px; margin-top: 4px;">
                    ${warnings.map(w => `<li>${escapeHtml(w)}</li>`).join('')}
                </ul>
            </div>
        `;
    }

    validationOutput.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div style="font-size: 0.92rem; font-weight: 600; color: ${isValid ? 'var(--primary-emerald)' : 'var(--accent-red)'}; display: flex; align-items: center; gap: 6px;">
                <i data-lucide="${isValid ? 'check-circle-2' : 'alert-octagon'}"></i>
                <span>${isValid ? 'Validation Passed & Staged' : 'Validation Failed'}</span>
            </div>
            <span class="p-badge ${isValid ? 'safe' : 'p-badge-red'}">${escapeHtml(data.label || data.table_name || 'Dataset')}</span>
        </div>
        <div style="font-size: 0.84rem; color: var(--text-muted); margin-bottom: 8px;">
            Target Table: <strong>public.${escapeHtml(data.table_name || 'unknown')}</strong> | Rows: <strong>${data.row_count || 0}</strong> | Columns: <strong>${(data.columns || []).length}</strong>
        </div>
        ${checkpointsHtml}
        ${errorsHtml}
        ${warningsHtml}
    `;

    if (window.lucide) lucide.createIcons();
}

function refreshStagedTable() {
    const tbody = document.getElementById('staged-datasets-body');
    const btnLoadDb = document.getElementById('btn-load-database');
    const tables = Object.keys(stagedDatasetsState);

    if (!tbody) return;

    if (tables.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="4" class="text-muted" style="text-align: center; padding: 20px;">
                    No datasets staged yet. Upload and validate a CSV file to begin.
                </td>
            </tr>
        `;
        if (btnLoadDb) btnLoadDb.disabled = true;
        return;
    }

    if (btnLoadDb) btnLoadDb.disabled = false;

    tbody.innerHTML = tables.map(tbl => {
        const item = stagedDatasetsState[tbl];
        return `
            <tr>
                <td><strong>public.${escapeHtml(tbl)}</strong><br><span style="font-size: 0.76rem; color: var(--text-dim);">${escapeHtml(item.filename)}</span></td>
                <td>${item.row_count.toLocaleString()}</td>
                <td><span class="p-badge safe">Ready</span></td>
                <td>
                    <button class="btn-refresh" style="padding: 4px 8px; font-size: 0.78rem;" onclick="previewStagedTable('${escapeHtml(tbl)}')">
                        <i data-lucide="eye"></i> Preview
                    </button>
                </td>
            </tr>
        `;
    }).join('');

    if (window.lucide) lucide.createIcons();
}

function previewStagedTable(tableName) {
    const item = stagedDatasetsState[tableName];
    if (!item) return;
    showImportPreview(tableName, item.sample_records, item.columns, item.row_count);
}

function showImportPreview(tableName, records, columns, totalRows) {
    const previewSection = document.getElementById('import-preview-section');
    const previewTitle = document.getElementById('import-preview-title');
    const tableWrapper = document.getElementById('import-preview-table-wrapper');

    if (!previewSection || !tableWrapper) return;

    previewSection.style.display = 'block';
    previewTitle.innerHTML = `<i data-lucide="table"></i> Staged Dataset Preview: public.${escapeHtml(tableName)} (${totalRows} total rows)`;

    if (!records || records.length === 0) {
        tableWrapper.innerHTML = `<p class="placeholder-text">No sample records available for preview.</p>`;
        return;
    }

    const cols = columns || Object.keys(records[0]);
    let html = `
        <table class="data-table">
            <thead>
                <tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr>
            </thead>
            <tbody>
                ${records.map(r => `
                    <tr>${cols.map(c => `<td>${escapeHtml(String(r[c] !== null && r[c] !== undefined ? r[c] : ''))}</td>`).join('')}</tr>
                `).join('')}
            </tbody>
        </table>
    `;
    tableWrapper.innerHTML = html;
    if (window.lucide) lucide.createIcons();
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
