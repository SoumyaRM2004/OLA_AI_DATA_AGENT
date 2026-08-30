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
   2. AI CHAT STUDIO — PERSISTENT MULTI-CHAT SYSTEM (CHATGPT-STYLE)
   ========================================================================== */

let activeChatId = null;
let chatSessionsCache = [];

function renderDefaultWelcomeMessage() {
    const messagesArea = document.getElementById('messages-area');
    if (!messagesArea) return;
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
                <p>Welcome to the <strong>OLA Mobility Intelligence Platform</strong>! I am your AI Data Agent querying PostgreSQL live and combining synthetic ride-hailing datasets with external <strong>Open-Meteo weather data across all 8 Canadian ride-hailing cities</strong>.</p>
                <ul>
                    <li>📊 <strong>SQL Analytics</strong>: Query rides, fares, driver ratings, and correlate ride metrics with weather conditions (rain vs. cancellations, surge pricing) across Calgary, Edmonton, Halifax, Montreal, Ottawa, Toronto, Vancouver, and Winnipeg.</li>
                    <li>🌦️ <strong>Weather & Mobility ETL</strong>: Extract historical hourly weather data for all 8 cities from Open-Meteo Archive API and transform datasets using Pandas.</li>
                    <li>📁 <strong>CSV Data Import</strong>: Upload and validate custom datasets for Users, Vehicles, Rides, Payments, and Ratings with strict schema and foreign-key checks.</li>
                </ul>
                <p>Every SQL query is evaluated by an automated <strong>Security Judge</strong> before execution against current PostgreSQL data!</p>
            </div>
        </div>
    `;
    if (window.lucide) lucide.createIcons();
}

async function initChat() {
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const chips = document.querySelectorAll('.chip');

    // Toolbar & action buttons
    const btnNewChat = document.getElementById('btn-new-chat');
    const btnClearChat = document.getElementById('btn-clear-chat');
    const btnExportChat = document.getElementById('btn-export-chat');
    const btnRenameActive = document.getElementById('btn-rename-active-chat');
    const btnSaveRename = document.getElementById('btn-save-rename');
    const btnCancelRename = document.getElementById('btn-cancel-rename');
    const renameInput = document.getElementById('chat-rename-input');

    if (btnNewChat) {
        btnNewChat.addEventListener('click', () => createNewChat());
    }

    if (btnClearChat) {
        btnClearChat.addEventListener('click', () => clearActiveChat());
    }

    if (btnExportChat) {
        btnExportChat.addEventListener('click', () => exportActiveChat());
    }

    if (btnRenameActive) {
        btnRenameActive.addEventListener('click', () => {
            const currentTitle = document.getElementById('current-chat-title').textContent.trim();
            showRenameForm(currentTitle);
        });
    }

    if (btnSaveRename) {
        btnSaveRename.addEventListener('click', () => saveActiveChatRename());
    }

    if (btnCancelRename) {
        btnCancelRename.addEventListener('click', () => hideRenameForm());
    }

    if (renameInput) {
        renameInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                saveActiveChatRename();
            } else if (e.key === 'Escape') {
                hideRenameForm();
            }
        });
    }

    // Query chips click
    chips.forEach(chip => {
        chip.addEventListener('click', () => {
            const prompt = chip.getAttribute('data-prompt');
            if (chatInput) {
                chatInput.value = prompt;
                chatForm.dispatchEvent(new Event('submit'));
            }
        });
    });

    // Form submission
    if (chatForm) {
        chatForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const message = chatInput.value.trim();
            if (!message) return;

            const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            // 1. Render & display user message locally
            appendUserMessage(message, timeStr);
            chatInput.value = '';

            // 2. Render loading agent message
            const loadingId = 'loading-' + Date.now();
            appendLoadingMessage(loadingId);

            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message, chat_id: activeChatId })
                });

                const data = await response.json();
                removeMessage(loadingId);

                if (data.chat_id) {
                    activeChatId = data.chat_id;
                    localStorage.setItem('ola_active_chat_id', data.chat_id);
                }

                if (data.chat_title) {
                    document.getElementById('current-chat-title').textContent = data.chat_title;
                }

                // 3. Render agent response
                renderAgentResponse(data, timeStr);

                // 4. Refresh chat sidebar list to show updated title / time
                loadChatSessions(activeChatId, false);

            } catch (err) {
                removeMessage(loadingId);
                appendErrorMessage(`Failed to communicate with agent server: ${err.message}`);
            }
        });
    }

    // Initial load of chat sessions
    await loadChatSessions();
}

async function loadChatSessions(targetId = null, switchSession = true) {
    try {
        const res = await fetch('/api/chats');
        const data = await res.json();
        chatSessionsCache = data.chats || [];

        renderChatSessionsList();

        if (chatSessionsCache.length === 0) {
            await createNewChat();
            return;
        }

        if (switchSession) {
            const savedId = targetId || localStorage.getItem('ola_active_chat_id');
            const validSession = chatSessionsCache.find(c => c.id === savedId);
            const activeId = validSession ? validSession.id : chatSessionsCache[0].id;
            await switchChat(activeId);
        } else {
            highlightActiveSessionInList();
        }
    } catch (err) {
        console.error('Error loading chat sessions:', err);
    }
}

function renderChatSessionsList() {
    const listEl = document.getElementById('chat-sessions-list');
    if (!listEl) return;

    listEl.innerHTML = '';
    chatSessionsCache.forEach(chat => {
        const isActive = chat.id === activeChatId;
        const item = document.createElement('div');
        item.className = `chat-session-item ${isActive ? 'active' : ''}`;
        item.setAttribute('data-chat-id', chat.id);

        let timeDisplay = '';
        if (chat.updated_at) {
            try {
                const d = new Date(chat.updated_at);
                timeDisplay = d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            } catch (_) {}
        }

        item.innerHTML = `
            <div class="chat-session-info" onclick="switchChat('${escapeHtml(chat.id)}')">
                <span class="chat-session-title" title="${escapeHtml(chat.title || 'Untitled')}">${escapeHtml(chat.title || 'New Chat')}</span>
                <span class="chat-session-time">${escapeHtml(timeDisplay)}</span>
            </div>
            <div class="chat-session-actions">
                <button class="btn-session-action" title="Rename" onclick="event.stopPropagation(); promptRenameChat('${escapeHtml(chat.id)}', '${escapeHtml(chat.title || '')}')">
                    <i data-lucide="edit-2"></i>
                </button>
                <button class="btn-session-action delete" title="Delete" onclick="event.stopPropagation(); deleteChatSession('${escapeHtml(chat.id)}')">
                    <i data-lucide="trash-2"></i>
                </button>
            </div>
        `;

        listEl.appendChild(item);
    });

    if (window.lucide) lucide.createIcons();
}

function highlightActiveSessionInList() {
    document.querySelectorAll('.chat-session-item').forEach(el => {
        const cId = el.getAttribute('data-chat-id');
        if (cId === activeChatId) {
            el.classList.add('active');
        } else {
            el.classList.remove('active');
        }
    });
}

async function switchChat(chatId) {
    if (!chatId) return;
    activeChatId = chatId;
    localStorage.setItem('ola_active_chat_id', chatId);
    highlightActiveSessionInList();

    const messagesArea = document.getElementById('messages-area');
    const titleEl = document.getElementById('current-chat-title');
    hideRenameForm();

    messagesArea.innerHTML = '<p class="loading-text">Loading conversation...</p>';

    try {
        const res = await fetch(`/api/chats/${chatId}`);
        if (!res.ok) {
            renderDefaultWelcomeMessage();
            return;
        }

        const chatData = await res.json();
        titleEl.textContent = chatData.title || 'New Chat';

        const messages = chatData.messages || [];
        if (messages.length === 0) {
            renderDefaultWelcomeMessage();
            return;
        }

        messagesArea.innerHTML = '';
        messages.forEach(msg => {
            const timeStr = msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
            if (msg.role === 'user') {
                appendUserMessage(msg.content, timeStr);
            } else if (msg.role === 'assistant') {
                const responseData = msg.extra && Object.keys(msg.extra).length > 0 ? msg.extra : {
                    route: 'sql',
                    answer: msg.content,
                    is_safe: 'Yes',
                    sql_query: msg.extra ? msg.extra.sql_query : '',
                    columns: msg.extra ? msg.extra.columns : [],
                    rows: msg.extra ? msg.extra.rows : [],
                    chart: msg.extra ? msg.extra.chart : { can_chart: false }
                };
                renderAgentResponse(responseData, timeStr);
            }
        });

    } catch (err) {
        messagesArea.innerHTML = `<p class="placeholder-text" style="color: var(--accent-red);">Error loading chat: ${escapeHtml(err.message)}</p>`;
    }
}

async function createNewChat() {
    try {
        const res = await fetch('/api/chats', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: 'New Chat' })
        });
        const newChat = await res.json();
        activeChatId = newChat.id;
        localStorage.setItem('ola_active_chat_id', newChat.id);

        await loadChatSessions(newChat.id, true);
        const chatInput = document.getElementById('chat-input');
        if (chatInput) chatInput.focus();
    } catch (err) {
        console.error('Failed to create new chat:', err);
    }
}

function showRenameForm(currentTitle) {
    const displayBox = document.getElementById('chat-title-display');
    const formBox = document.getElementById('chat-rename-form');
    const input = document.getElementById('chat-rename-input');

    if (displayBox) displayBox.classList.add('hidden');
    if (formBox) formBox.classList.remove('hidden');
    if (input) {
        input.value = currentTitle;
        input.focus();
        input.select();
    }
}

function hideRenameForm() {
    const displayBox = document.getElementById('chat-title-display');
    const formBox = document.getElementById('chat-rename-form');

    if (displayBox) displayBox.classList.remove('hidden');
    if (formBox) formBox.classList.add('hidden');
}

async function saveActiveChatRename() {
    const input = document.getElementById('chat-rename-input');
    if (!input || !activeChatId) return;

    const newTitle = input.value.trim();
    if (!newTitle) {
        hideRenameForm();
        return;
    }

    try {
        const res = await fetch(`/api/chats/${activeChatId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: newTitle })
        });
        const updated = await res.json();
        document.getElementById('current-chat-title').textContent = updated.title || newTitle;
        hideRenameForm();
        loadChatSessions(activeChatId, false);
    } catch (err) {
        alert(`Failed to rename chat: ${err.message}`);
    }
}

async function promptRenameChat(chatId, oldTitle) {
    const newTitle = prompt("Enter new title for conversation:", oldTitle || "New Chat");
    if (newTitle && newTitle.trim() && newTitle.trim() !== oldTitle) {
        try {
            const res = await fetch(`/api/chats/${chatId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: newTitle.trim() })
            });
            const updated = await res.json();
            if (activeChatId === chatId) {
                document.getElementById('current-chat-title').textContent = updated.title || newTitle.trim();
            }
            loadChatSessions(activeChatId, false);
        } catch (err) {
            alert(`Failed to rename chat: ${err.message}`);
        }
    }
}

async function deleteChatSession(chatId) {
    if (!confirm("Are you sure you want to delete this chat conversation?")) return;

    try {
        await fetch(`/api/chats/${chatId}`, { method: 'DELETE' });
        if (activeChatId === chatId) {
            activeChatId = null;
            localStorage.removeItem('ola_active_chat_id');
        }
        await loadChatSessions();
    } catch (err) {
        alert(`Failed to delete chat: ${err.message}`);
    }
}

async function clearActiveChat() {
    if (!activeChatId) return;
    if (!confirm("Are you sure you want to clear all messages in this conversation?")) return;

    try {
        await fetch(`/api/chats/${activeChatId}/clear`, { method: 'POST' });
        renderDefaultWelcomeMessage();
        loadChatSessions(activeChatId, false);
    } catch (err) {
        alert(`Failed to clear chat: ${err.message}`);
    }
}

async function exportActiveChat() {
    if (!activeChatId) return;
    try {
        const res = await fetch(`/api/chats/${activeChatId}`);
        const chatData = await res.json();

        const exportData = {
            platform: "OLA AI Data Agent",
            chat_id: chatData.id,
            title: chatData.title,
            exported_at: new Date().toISOString(),
            total_messages: (chatData.messages || []).length,
            conversation: chatData.messages || []
        };

        const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(exportData, null, 2));
        const downloadAnchor = document.createElement('a');
        downloadAnchor.setAttribute("href", dataStr);
        downloadAnchor.setAttribute("download", `ola_chat_${chatData.title.toLowerCase().replace(/[^a-z0-9]/g, '_')}_${new Date().toISOString().slice(0,10)}.json`);
        document.body.appendChild(downloadAnchor);
        downloadAnchor.click();
        downloadAnchor.remove();
    } catch (err) {
        alert(`Failed to export chat: ${err.message}`);
    }
}

function appendUserMessage(text, timeStr = null) {
    const messagesArea = document.getElementById('messages-area');
    if (!messagesArea) return;
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
}

function appendLoadingMessage(id) {
    const messagesArea = document.getElementById('messages-area');
    if (!messagesArea) return;
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
                <span>Querying live PostgreSQL, orchestrating agents & verifying security policies...</span>
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
    if (!messagesArea) return;
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

function renderAgentResponse(data, timeStr = null) {
    const messagesArea = document.getElementById('messages-area');
    if (!messagesArea) return;
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
   3. OVERVIEW / KPI DASHBOARD (LIVE POSTGRESQL AGGREGATIONS)
   ========================================================================== */
async function initDashboard() {
    const refreshBtn = document.getElementById('refresh-stats-btn');
    const refreshBtnTop = document.getElementById('refresh-stats-btn-top');

    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => loadDashboardStats());
    }
    if (refreshBtnTop) {
        refreshBtnTop.addEventListener('click', () => loadDashboardStats());
    }

    loadDashboardStats();
}

async function loadDashboardStats() {
    const refreshBtnTop = document.getElementById('refresh-stats-btn-top');
    if (refreshBtnTop) {
        refreshBtnTop.innerHTML = '<div class="loading-spinner"></div> <span>Fetching Live Data...</span>';
    }

    try {
        const res = await fetch('/api/stats');
        const stats = await res.json();

        // Update KPI cards
        const ridesEl = document.getElementById('kpi-total-rides');
        const completedEl = document.getElementById('kpi-completed-rides');
        const revEl = document.getElementById('kpi-revenue');
        const usersEl = document.getElementById('kpi-users');
        const ratingEl = document.getElementById('kpi-rating');

        if (ridesEl) ridesEl.textContent = Number(stats.total_rides || 0).toLocaleString();
        if (completedEl) completedEl.textContent = `${Number(stats.completed_rides || 0).toLocaleString()} completed`;
        if (revEl) revEl.textContent = '₹' + Number(stats.total_revenue || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        if (usersEl) usersEl.textContent = Number(stats.total_users || 0).toLocaleString();
        if (ratingEl) ratingEl.textContent = `${stats.avg_rating || 0} ★`;

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
    } finally {
        if (refreshBtnTop) {
            refreshBtnTop.innerHTML = '<i data-lucide="rotate-cw"></i> <span>Refresh Dashboard</span>';
            if (window.lucide) lucide.createIcons();
        }
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
        wrapper.innerHTML = '<p class="placeholder-text">No driver ratings recorded yet.</p>';
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
   4. DATABASE EXPLORER (LIVE POSTGRESQL QUERIES & REFRESH)
   ========================================================================== */
let dbSchemaCache = {};
let currentActiveDbTable = 'users';

async function initDbExplorer() {
    const searchInput = document.getElementById('db-search-input');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();
            filterActiveTableRows(query);
        });
    }

    const refreshDbBtn = document.getElementById('btn-refresh-db-explorer');
    if (refreshDbBtn) {
        refreshDbBtn.addEventListener('click', async () => {
            refreshDbBtn.innerHTML = '<div class="loading-spinner"></div> <span>Querying...</span>';
            await loadDbSchema(currentActiveDbTable);
            refreshDbBtn.innerHTML = '<i data-lucide="rotate-cw"></i> <span>Refresh Data</span>';
            if (window.lucide) lucide.createIcons();
        });
    }
}

async function loadDbSchema(preferredTable = null) {
    const listContainer = document.getElementById('db-table-list');
    listContainer.innerHTML = '<p class="loading-text">Fetching live schema from PostgreSQL...</p>';

    try {
        const res = await fetch('/api/schema');
        if (!res.ok) {
            let errorText = `Database schema request failed (HTTP ${res.status}). Check PostgreSQL connection.`;
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
            listContainer.innerHTML = '<p class="placeholder-text">No tables found in PostgreSQL schema.</p>';
            return;
        }

        const selectedTable = preferredTable && tableNames.includes(preferredTable) ? preferredTable : (tableNames.includes(currentActiveDbTable) ? currentActiveDbTable : tableNames[0]);
        currentActiveDbTable = selectedTable;

        listContainer.innerHTML = '';
        tableNames.forEach((tName) => {
            const tInfo = dbSchemaCache[tName];
            const btn = document.createElement('button');
            btn.className = `table-btn ${tName === selectedTable ? 'active' : ''}`;
            btn.innerHTML = `
                <span>${tName}</span>
                <span class="table-badge">${Number(tInfo.row_count || 0).toLocaleString()} rows</span>
            `;
            btn.addEventListener('click', () => {
                document.querySelectorAll('.table-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentActiveDbTable = tName;
                displayTableData(tName);
            });
            listContainer.appendChild(btn);
        });

        // Load active table data
        displayTableData(selectedTable);

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
    meta.textContent = `${Number(tInfo.row_count || 0).toLocaleString()} total records in PostgreSQL`;

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
    dataWrapper.innerHTML = '<p class="loading-text">Loading rows from PostgreSQL...</p>';
    try {
        const res = await fetch(`/api/tables/${tableName}?limit=50`);
        if (!res.ok) {
            let errorText = `Failed to fetch live rows for ${tableName} (HTTP ${res.status}).`;
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
            dataWrapper.innerHTML = '<p class="placeholder-text">Table is empty in PostgreSQL.</p>';
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

                const contentType = res.headers.get('content-type') || '';
                let data = {};
                if (contentType.includes('application/json')) {
                    data = await res.json();
                } else {
                    const rawText = await res.text();
                    data = { success: false, error: `Server returned non-JSON response (HTTP ${res.status}): ${rawText.slice(0, 250)}` };
                }

                if (!res.ok || data.success === false) {
                    const errorText = data.error || data.message || `Extraction failed with HTTP status ${res.status}`;
                    outputBox.innerHTML = `
                        <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid var(--accent-red); padding: 12px; border-radius: 8px; color: #FECACA; margin-top: 10px;">
                            <div style="display: flex; align-items: center; gap: 6px; color: var(--accent-red); font-weight: 600; margin-bottom: 6px;">
                                <i data-lucide="alert-octagon"></i> Extraction Failed
                            </div>
                            <pre style="white-space: pre-wrap; font-family: var(--font-mono); font-size: 0.8rem; margin: 0; color: #FECACA;">${escapeHtml(errorText)}</pre>
                        </div>
                    `;
                } else {
                    outputBox.innerHTML = `
                        <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid var(--primary-emerald); padding: 12px; border-radius: 8px; color: #D1D5DB; margin-top: 10px;">
                            <div style="display: flex; align-items: center; gap: 6px; color: var(--primary-emerald); font-weight: 600; margin-bottom: 6px;">
                                <i data-lucide="check-circle-2"></i> Extraction Result
                            </div>
                            <pre style="white-space: pre-wrap; font-family: var(--font-mono); font-size: 0.8rem; margin-top: 6px;">${escapeHtml(data.message)}</pre>
                        </div>
                    `;
                    loadDataFiles();
                }
            } catch (err) {
                outputBox.innerHTML = `
                    <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid var(--accent-red); padding: 12px; border-radius: 8px; color: #FECACA; margin-top: 10px;">
                        <div style="display: flex; align-items: center; gap: 6px; color: var(--accent-red); font-weight: 600; margin-bottom: 6px;">
                            <i data-lucide="alert-octagon"></i> Network Error
                        </div>
                        <pre style="white-space: pre-wrap; font-family: var(--font-mono); font-size: 0.8rem; margin: 0; color: #FECACA;">${escapeHtml(err.message)}</pre>
                    </div>
                `;
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
let lastValidationResult = null;
let currentInspectionData = null;

function setWorkflowStep(stepName) {
    const steps = ['upload', 'detect', 'map', 'validate', 'stage', 'load'];
    const targetIdx = steps.indexOf(stepName);
    if (targetIdx === -1) return;

    steps.forEach((s, idx) => {
        const el = document.getElementById(`step-${s}`);
        if (!el) return;
        el.classList.remove('active', 'completed');
        if (idx < targetIdx) {
            el.classList.add('completed');
        } else if (idx === targetIdx) {
            el.classList.add('active');
        }
    });
}

function initDataImport() {
    const uploadForm = document.getElementById('import-upload-form');
    const fileInput = document.getElementById('import-file-input');
    const dropArea = document.getElementById('file-drop-area');
    const selectedBadge = document.getElementById('selected-file-name');
    const targetSelect = document.getElementById('import-target-table');
    const modeSelect = document.getElementById('import-mode-select');
    const btnValidate = document.getElementById('btn-validate-csv');
    const validationOutput = document.getElementById('validation-output');
    const btnLoadDb = document.getElementById('btn-load-database');
    const btnClearStaged = document.getElementById('btn-clear-staged');
    const loadOutput = document.getElementById('load-db-output');
    const mappingCard = document.getElementById('column-mapping-card');
    const mappingTbody = document.getElementById('column-mapping-tbody');
    const missingFieldsCard = document.getElementById('missing-fields-card');
    const missingFieldsList = document.getElementById('missing-fields-list');
    const confidenceBadge = document.getElementById('detection-confidence-badge');
    const btnDownloadNorm = document.getElementById('btn-download-canonical-csv');

    if (!uploadForm) return;

    function updateValidateButtonState() {
        const hasFile = fileInput && fileInput.files && fileInput.files.length > 0;
        if (btnValidate) {
            btnValidate.disabled = !hasFile;
        }
    }

    // Fast Inspect when file is selected or dropped
    async function inspectSelectedFile(file) {
        if (!file) return;
        setWorkflowStep('detect');
        const datasetType = targetSelect ? targetSelect.value : 'auto';

        const formData = new FormData();
        formData.append('file', file);
        formData.append('dataset_type', datasetType);

        try {
            const res = await fetch('/api/import/inspect', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            currentInspectionData = data;

            if (data.detected_dataset && data.detected_dataset !== 'unknown') {
                if (targetSelect && (targetSelect.value === 'auto' || !targetSelect.value)) {
                    targetSelect.value = data.detected_dataset;
                }
                setWorkflowStep('map');
                renderColumnMappingCard(data);
                renderMissingFieldsCard(data);
            }
        } catch (err) {
            console.warn('Inspect error:', err);
        }
    }

    function renderMissingFieldsCard(data) {
        if (!missingFieldsCard || !missingFieldsList) return;
        
        const missing = data.missing_required || (data.metadata && data.metadata.missing_required) || [];
        const detectedTbl = data.detected_dataset || (data.metadata && data.metadata.dataset_type) || (targetSelect ? targetSelect.value : 'users');

        if (!missing || missing.length === 0) {
            missingFieldsCard.style.display = 'none';
            missingFieldsList.innerHTML = '';
            return;
        }

        missingFieldsCard.style.display = 'block';

        const columnPresets = {
            'users': {
                'user_type': {
                    label: 'User Type (Rider or Driver)',
                    type: 'VARCHAR(20) [Required]',
                    presets: [
                        { value: 'rider', label: 'Set Default: "rider" (Passenger)' },
                        { value: 'driver', label: 'Set Default: "driver" (Vehicle Driver)' }
                    ]
                },
                'user_id': { label: 'User ID', type: 'INT [Primary Key]', presets: [] },
                'first_name': { label: 'First Name', type: 'VARCHAR(50) [Required]', presets: [] },
                'last_name': { label: 'Last Name', type: 'VARCHAR(50) [Required]', presets: [] },
                'email': { label: 'Email Address', type: 'VARCHAR(100) [Required]', presets: [] }
            },
            'vehicles': {
                'driver_id': { label: 'Driver ID', type: 'INT [Foreign Key -> users.user_id]', presets: [] },
                'vehicle_id': { label: 'Vehicle ID', type: 'INT [Primary Key]', presets: [] }
            },
            'rides': {
                'rider_id': { label: 'Rider ID', type: 'INT [Foreign Key -> users.user_id]', presets: [] },
                'driver_id': { label: 'Driver ID', type: 'INT [Foreign Key -> users.user_id]', presets: [] },
                'ride_id': { label: 'Ride ID', type: 'INT [Primary Key]', presets: [] }
            },
            'payments': {
                'ride_id': { label: 'Ride ID', type: 'INT [Foreign Key -> rides.ride_id]', presets: [] },
                'user_id': { label: 'User ID', type: 'INT [Foreign Key -> users.user_id]', presets: [] },
                'payment_id': { label: 'Payment ID', type: 'INT [Primary Key]', presets: [] }
            },
            'ratings': {
                'ride_id': { label: 'Ride ID', type: 'INT [Foreign Key -> rides.ride_id]', presets: [] },
                'rider_id': { label: 'Rider ID', type: 'INT [Foreign Key -> users.user_id]', presets: [] },
                'driver_id': { label: 'Driver ID', type: 'INT [Foreign Key -> users.user_id]', presets: [] },
                'rating_id': { label: 'Rating ID', type: 'INT [Primary Key]', presets: [] }
            }
        }[detectedTbl] || {};

        missingFieldsList.innerHTML = missing.map(col => {
            const info = columnPresets[col] || { label: col, type: 'Required Column', presets: [] };
            const presetsHtml = (info.presets || []).map(p => `
                <option value="${p.value}">${p.label}</option>
            `).join('');

            return `
                <div class="missing-field-card" data-column="${escapeHtml(col)}">
                    <div class="missing-field-top">
                        <div>
                            <span class="missing-field-name"><i data-lucide="alert-circle" style="width: 14px; height: 14px; display: inline-block; vertical-align: middle; margin-right: 4px;"></i>${escapeHtml(col)}</span>
                            <span class="missing-field-type" style="margin-left: 8px;">(${escapeHtml(info.type)})</span>
                        </div>
                        <span class="p-badge p-badge-amber" style="font-size: 0.72rem;">Missing from CSV</span>
                    </div>
                    <div class="missing-field-controls">
                        <select class="missing-field-select" data-column="${escapeHtml(col)}">
                            <option value="">-- Choose Resolution Action --</option>
                            ${presetsHtml}
                            <option value="__custom__">Enter Explicit Default Value...</option>
                        </select>
                        <input type="text" class="missing-field-custom-input" data-column="${escapeHtml(col)}" placeholder="Enter value for all rows..." style="display: none; width: 180px;" />
                        <div class="missing-field-notice-container" id="notice-${escapeHtml(col)}" style="display: none;"></div>
                    </div>
                </div>
            `;
        }).join('');

        // Attach listeners for selects and custom inputs
        missingFieldsList.querySelectorAll('.missing-field-select').forEach(sel => {
            sel.addEventListener('change', (e) => {
                const col = e.target.getAttribute('data-column');
                const card = e.target.closest('.missing-field-card');
                const customInput = card.querySelector(`.missing-field-custom-input[data-column="${col}"]`);
                const noticeContainer = card.querySelector(`#notice-${col}`);
                const val = e.target.value;

                if (val === '__custom__') {
                    if (customInput) {
                        customInput.style.display = 'inline-block';
                        customInput.focus();
                    }
                    if (noticeContainer) noticeContainer.style.display = 'none';
                } else if (val) {
                    if (customInput) customInput.style.display = 'none';
                    if (noticeContainer) {
                        noticeContainer.style.display = 'inline-block';
                        noticeContainer.innerHTML = `<span class="missing-field-notice"><i data-lucide="check"></i> Will apply '<strong>${escapeHtml(val)}</strong>' to all rows in uploaded dataset</span>`;
                        if (window.lucide) lucide.createIcons();
                    }
                } else {
                    if (customInput) customInput.style.display = 'none';
                    if (noticeContainer) noticeContainer.style.display = 'none';
                }
            });
        });

        missingFieldsList.querySelectorAll('.missing-field-custom-input').forEach(inp => {
            inp.addEventListener('input', (e) => {
                const col = e.target.getAttribute('data-column');
                const card = e.target.closest('.missing-field-card');
                const noticeContainer = card.querySelector(`#notice-${col}`);
                const val = e.target.value.trim();

                if (val && noticeContainer) {
                    noticeContainer.style.display = 'inline-block';
                    noticeContainer.innerHTML = `<span class="missing-field-notice"><i data-lucide="check"></i> Will apply '<strong>${escapeHtml(val)}</strong>' to all rows in uploaded dataset</span>`;
                    if (window.lucide) lucide.createIcons();
                } else if (noticeContainer) {
                    noticeContainer.style.display = 'none';
                }
            });
        });

        if (window.lucide) lucide.createIcons();
    }

    function renderColumnMappingCard(data) {
        if (!mappingCard || !mappingTbody) return;
        mappingCard.style.display = 'block';

        if (confidenceBadge) {
            const conf = data.confidence || 'Medium';
            confidenceBadge.textContent = `${conf} Confidence (${data.confidence_score || 0}%)`;
            confidenceBadge.className = `confidence-badge ${conf.toLowerCase() === 'medium' ? 'medium' : ''}`;
        }

        const details = data.mapping_details || [];
        const detectedTbl = data.detected_dataset || 'users';

        // Canonical column options
        const schemaCols = {
            'users': ['user_id', 'first_name', 'last_name', 'email', 'phone', 'city', 'province', 'user_type', 'signup_date', 'is_active'],
            'vehicles': ['vehicle_id', 'driver_id', 'make', 'model', 'year', 'license_plate', 'color', 'is_active'],
            'rides': ['ride_id', 'rider_id', 'driver_id', 'requested_at', 'pickup_time', 'dropoff_time', 'pickup_latitude', 'pickup_longitude', 'dropoff_latitude', 'dropoff_longitude', 'distance_km', 'fare', 'surge_multiplier', 'status', 'cancellation_reason'],
            'payments': ['payment_id', 'ride_id', 'user_id', 'amount', 'payment_method', 'payment_status', 'transaction_id', 'payment_time'],
            'ratings': ['rating_id', 'ride_id', 'rider_id', 'driver_id', 'rating', 'comment', 'rated_at']
        }[detectedTbl] || [];

        mappingTbody.innerHTML = details.map((item, idx) => {
            const isMapped = item.canonical !== null && item.canonical !== undefined;
            let typeBadge = '<span class="p-badge p-badge-amber">Extra Column</span>';
            if (item.status === 'exact') {
                typeBadge = '<span class="p-badge safe">Exact Match</span>';
            } else if (item.status === 'alias') {
                typeBadge = '<span class="p-badge safe">Alias</span>';
            } else if (item.status === 'composite') {
                typeBadge = '<span class="p-badge p-badge-amber">Composite Mapping</span>';
            } else if (item.status === 'custom') {
                typeBadge = '<span class="p-badge safe">Custom</span>';
            }

            let confLabel = item.confidence ? `${item.confidence}%` : '--';
            if (item.status === 'composite') {
                confLabel = 'Review Required';
            }
            const reasonLabel = escapeHtml(item.reason || (item.status === 'exact' ? 'Exact normalized header match' : (item.status === 'alias' ? 'Known configured alias' : 'No safe mapping found (Extra column)')));

            // Build select options including composite options
            const compositeOptions = detectedTbl === 'users' ? `
                <option value="first_name+last_name" ${item.canonical === 'first_name + last_name' || item.status === 'composite' ? 'selected' : ''}>
                    first_name + last_name (Composite Split)
                </option>
            ` : '';

            const optionsHtml = `
                <option value="__ignore__" ${!isMapped ? 'selected' : ''}>-- Ignore / Extra Column --</option>
                ${compositeOptions}
                ${schemaCols.map(c => `
                    <option value="${c}" ${item.canonical === c ? 'selected' : ''}>${c}</option>
                `).join('')}
            `;

            return `
                <tr>
                    <td><code>${escapeHtml(item.uploaded)}</code></td>
                    <td>
                        <select class="mapping-col-select" data-uploaded="${escapeHtml(item.uploaded)}">
                            ${optionsHtml}
                        </select>
                    </td>
                    <td>${typeBadge}</td>
                    <td><strong>${confLabel}</strong></td>
                    <td style="font-size: 0.8rem; color: var(--text-muted);">${reasonLabel}</td>
                </tr>
            `;
        }).join('');

        if (window.lucide) lucide.createIcons();
    }

    // Dataset type change listener
    if (targetSelect) {
        targetSelect.addEventListener('change', () => {
            if (fileInput && fileInput.files && fileInput.files.length > 0) {
                inspectSelectedFile(fileInput.files[0]);
            }
            updateValidateButtonState();
        });
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
            inspectSelectedFile(files[0]);
        }
        updateValidateButtonState();
    });

    dropArea.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            updateSelectedFileUI(fileInput.files[0]);
            inspectSelectedFile(fileInput.files[0]);
        } else {
            updateValidateButtonState();
        }
    });

    function updateSelectedFileUI(file) {
        selectedBadge.style.display = 'inline-flex';
        selectedBadge.innerHTML = `<span style="color: var(--primary-emerald); font-weight: 700; margin-right: 6px;">✓</span> <strong>${escapeHtml(file.name)}</strong> <span style="color: var(--text-dim); margin-left: 6px;">(${(file.size / 1024).toFixed(1)} KB)</span>`;
        if (window.lucide) lucide.createIcons();
        updateValidateButtonState();
        setWorkflowStep('upload');
    }

    // Initial state check
    updateValidateButtonState();
    if (btnLoadDb) btnLoadDb.disabled = Object.keys(stagedDatasetsState).length === 0;
    if (btnClearStaged) btnClearStaged.disabled = Object.keys(stagedDatasetsState).length === 0;

    // Form Submission: Validate CSV
    uploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!fileInput.files || fileInput.files.length === 0) {
            alert('Please select a CSV file to validate.');
            return;
        }

        const file = fileInput.files[0];
        const datasetType = targetSelect.value;
        const importMode = modeSelect ? modeSelect.value : 'upsert';

        // Collect custom mapping overrides
        const customMappings = {};
        const mappingSelects = document.querySelectorAll('.mapping-col-select');
        mappingSelects.forEach(sel => {
            const upl = sel.getAttribute('data-uploaded');
            const can = sel.value;
            if (upl && can && can !== '__ignore__') {
                customMappings[upl] = can;
            }
        });

        // Collect explicit default values for missing required columns
        const defaultValues = {};
        const fieldCards = document.querySelectorAll('.missing-field-card');
        fieldCards.forEach(card => {
            const col = card.getAttribute('data-column');
            const sel = card.querySelector('.missing-field-select');
            const customInp = card.querySelector('.missing-field-custom-input');
            if (sel && sel.value) {
                if (sel.value === '__custom__' && customInp && customInp.value.trim()) {
                    defaultValues[col] = customInp.value.trim();
                } else if (sel.value !== '__custom__') {
                    defaultValues[col] = sel.value;
                }
            }
        });

        setWorkflowStep('validate');
        btnValidate.disabled = true;
        btnValidate.innerHTML = '<div class="loading-spinner"></div> Validating Schema, Types & PKs...';
        validationOutput.style.display = 'block';
        validationOutput.innerHTML = '<p class="loading-text">Executing deterministic normalization, timestamp parsing, duplicate PK check, and constraints...</p>';

        try {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('dataset_type', datasetType);
            formData.append('import_mode', importMode);
            if (Object.keys(customMappings).length > 0) {
                formData.append('custom_mappings', JSON.stringify(customMappings));
            }
            if (Object.keys(defaultValues).length > 0) {
                formData.append('default_values', JSON.stringify(defaultValues));
            }

            const res = await fetch('/api/import/validate', {
                method: 'POST',
                body: formData
            });

            const data = await res.json();
            lastValidationResult = data;
            renderValidationResult(data);

            if (data.valid && data.table_name) {
                setWorkflowStep('stage');
                stagedDatasetsState[data.table_name] = {
                    filename: data.filename,
                    row_count: data.row_count,
                    columns: data.columns,
                    sample_records: data.sample_records,
                    import_mode: importMode,
                    staged_at: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                };
                refreshStagedTable();
                showImportPreview(data.table_name, data.sample_records, data.columns, data.row_count);
                if (missingFieldsCard) missingFieldsCard.style.display = 'none';
            } else {
                renderMissingFieldsCard(data);
            }
        } catch (err) {
            validationOutput.innerHTML = `<div class="structured-error-card"><div class="error-card-title">❌ Network Error</div><p>${escapeHtml(err.message)}</p></div>`;
        } finally {
            btnValidate.innerHTML = '<i data-lucide="check-circle"></i> Validate & Stage Dataset';
            updateValidateButtonState();
            if (window.lucide) lucide.createIcons();
        }
    });

    // Load staged datasets into PostgreSQL (Atomic Transaction)
    btnLoadDb.addEventListener('click', async () => {
        const stagedTables = Object.keys(stagedDatasetsState);
        if (stagedTables.length === 0) {
            alert('No validated datasets are staged for loading.');
            return;
        }

        const importMode = modeSelect ? modeSelect.value : 'upsert';

        // Replace Mode Confirmation Prompt
        if (importMode === 'replace') {
            const confirmed = confirm(
                `⚠️ Destructive Replace Mode Confirmation:\n\n` +
                `This operation will CLEAR / TRUNCATE all existing rows in table(s): ${stagedTables.join(', ')} before inserting the staged data.\n\n` +
                `Are you sure you want to replace these tables?`
            );
            if (!confirmed) return;
        }

        setWorkflowStep('load');
        btnLoadDb.disabled = true;
        btnLoadDb.innerHTML = '<div class="loading-spinner"></div> Executing Atomic Transaction...';
        loadOutput.innerHTML = '<p class="loading-text">Validating batch foreign keys and executing PostgreSQL atomic transaction in dependency order...</p>';

        try {
            const res = await fetch('/api/import/load', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tables: stagedTables, import_mode: importMode })
            });

            const result = await res.json();

            if (result.success) {
                let countSummary = '';
                if (result.loaded_counts) {
                    countSummary = Object.entries(result.loaded_counts)
                        .map(([t, c]) => `• <strong>public.${t}</strong>: ${c.toLocaleString()} records`)
                        .join('<br>');
                }

                loadOutput.innerHTML = `
                    <div style="background: rgba(16, 185, 129, 0.15); border: 1px solid var(--primary-emerald); padding: 16px; border-radius: 8px; color: #D1D5DB;">
                        <div style="display: flex; align-items: center; gap: 8px; color: var(--primary-emerald); font-weight: 700; font-size: 1rem; margin-bottom: 6px;">
                            <i data-lucide="check-circle-2"></i> Atomic Database Load Successful!
                        </div>
                        <p style="font-size: 0.88rem; margin-bottom: 8px;">All datasets committed atomically in dependency order (${escapeHtml(importMode.toUpperCase())} mode):</p>
                        <div style="font-size: 0.84rem; line-height: 1.6; margin-bottom: 10px;">${countSummary}</div>
                        <span class="p-badge safe"><i data-lucide="shield-check"></i> Transaction Committed</span>
                    </div>
                `;
                // Reset staged state
                stagedDatasetsState = {};
                refreshStagedTable();

                // Automatically refresh DB explorer & KPI dashboard
                loadDbSchema();
                loadDashboardStats();
            } else {
                let structuredHtml = '';
                if (result.structured_error) {
                    const se = result.structured_error;
                    structuredHtml = renderSingleStructuredErrorCard(se);
                } else if (result.structured_errors && result.structured_errors.length > 0) {
                    structuredHtml = result.structured_errors.map(renderSingleStructuredErrorCard).join('');
                } else if (result.error) {
                    structuredHtml = `<div class="structured-error-card"><div class="error-card-title">❌ Transaction Rolled Back</div><div class="error-explanation-box">${escapeHtml(result.error)}</div></div>`;
                }

                let techHtml = '';
                if (result.technical_error) {
                    techHtml = `
                        <details class="error-tech-details">
                            <summary>Technical Details (PostgreSQL Log)</summary>
                            <pre>${escapeHtml(result.technical_error)}</pre>
                        </details>
                    `;
                }

                loadOutput.innerHTML = `
                    <div style="background: rgba(239, 68, 68, 0.12); border: 1px solid var(--accent-red); padding: 16px; border-radius: 8px; color: #FECACA;">
                        <div style="display: flex; align-items: center; gap: 8px; color: var(--accent-red); font-weight: 700; font-size: 1rem; margin-bottom: 6px;">
                            <i data-lucide="alert-octagon"></i> Transaction Rolled Back
                        </div>
                        <p style="font-size: 0.86rem; margin-bottom: 12px;"><strong>No partial changes were saved to PostgreSQL.</strong> All changes were rolled back atomically.</p>
                        ${structuredHtml}
                        ${techHtml}
                    </div>
                `;
            }
        } catch (err) {
            loadOutput.innerHTML = `<div class="structured-error-card"><div class="error-card-title">❌ Load Execution Failed</div><p>${escapeHtml(err.message)}</p></div>`;
        } finally {
            const hasStaged = Object.keys(stagedDatasetsState).length > 0;
            btnLoadDb.disabled = !hasStaged;
            if (btnClearStaged) btnClearStaged.disabled = !hasStaged;
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
            if (mappingCard) mappingCard.style.display = 'none';
            document.getElementById('import-preview-section').style.display = 'none';
            if (btnLoadDb) btnLoadDb.disabled = true;
            if (btnClearStaged) btnClearStaged.disabled = true;
            setWorkflowStep('upload');
        } catch (err) {
            console.error('Error clearing staged:', err);
        }
    });

    // Download Normalized CSV button
    if (btnDownloadNorm) {
        btnDownloadNorm.addEventListener('click', () => {
            const stagedTbl = Object.keys(stagedDatasetsState)[0];
            if (!stagedTbl || !stagedDatasetsState[stagedTbl]) {
                alert('No staged dataset available to download.');
                return;
            }
            const item = stagedDatasetsState[stagedTbl];
            const records = item.sample_records || [];
            if (records.length === 0) {
                alert('No records available to download.');
                return;
            }
            const headers = Object.keys(records[0]);
            const csvRows = [headers.join(',')];
            records.forEach(row => {
                const values = headers.map(h => {
                    const val = row[h] !== null && row[h] !== undefined ? String(row[h]) : '';
                    return `"${val.replace(/"/g, '""')}"`;
                });
                csvRows.push(values.join(','));
            });
            const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${stagedTbl}_normalized.csv`;
            a.click();
            URL.revokeObjectURL(url);
        });
    }
}

function renderSingleStructuredErrorCard(err) {
    if (!err) return '';
    const errType = (err.error_type || 'validation_error').replace(/_/g, ' ').toUpperCase();
    return `
        <div class="structured-error-card">
            <div class="error-card-title">
                <i data-lucide="alert-circle"></i> ${escapeHtml(errType)}
            </div>
            <div class="error-meta-grid">
                <div class="error-meta-item"><strong>File</strong><span>${escapeHtml(err.file || 'uploaded.csv')}</span></div>
                <div class="error-meta-item"><strong>Dataset</strong><span>${escapeHtml(err.dataset || 'Unknown')}</span></div>
                <div class="error-meta-item"><strong>Target Table</strong><span>${escapeHtml(err.target_table || 'public.unknown')}</span></div>
                ${err.row !== null && err.row !== undefined ? `<div class="error-meta-item"><strong>Row</strong><span>${escapeHtml(String(err.row))}</span></div>` : ''}
                ${err.column ? `<div class="error-meta-item"><strong>Column</strong><span>${escapeHtml(err.column)}</span></div>` : ''}
                ${err.value !== null && err.value !== undefined ? `<div class="error-meta-item"><strong>Value</strong><span>${escapeHtml(String(err.value))}</span></div>` : ''}
            </div>
            <div class="error-explanation-box">
                <strong>Problem:</strong> ${escapeHtml(err.problem || err.message || 'Validation failed.')}
            </div>
            ${err.expected ? `<div class="error-explanation-box" style="color: #93C5FD;"><strong>Expected:</strong> ${escapeHtml(err.expected)}</div>` : ''}
            ${err.suggested_action ? `
                <div class="error-suggested-box">
                    <strong>Suggested Action:</strong> ${escapeHtml(err.suggested_action)}
                </div>
            ` : ''}
            ${err.technical_details ? `
                <details class="error-tech-details">
                    <summary>Technical Stacktrace</summary>
                    <pre>${escapeHtml(err.technical_details)}</pre>
                </details>
            ` : ''}
        </div>
    `;
}

function downloadErrorReport(data) {
    if (!data) return;
    const report = {
        timestamp: new Date().toISOString(),
        filename: data.filename,
        dataset_type: data.table_name,
        validation_state: data.validation_state,
        errors: data.structured_errors || data.errors,
        warnings: data.warnings
    };
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `error_report_${data.filename || 'dataset'}.json`;
    a.click();
    URL.revokeObjectURL(url);
}

function renderValidationResult(data) {
    const validationOutput = document.getElementById('validation-output');
    if (!validationOutput) return;
    validationOutput.style.display = 'block';

    const isValid = data.valid;
    const state = data.validation_state || (isValid ? 'VALID' : 'INVALID');
    const structuredErrors = data.structured_errors || [];
    const textErrors = data.errors || [];
    const warnings = data.warnings || [];

    let statusTitle = 'Validation Passed & Staged';
    let statusClass = 'safe';
    let statusIcon = 'check-circle-2';

    if (state === 'VALID_WITH_WARNINGS') {
        statusTitle = 'Validation Passed with Warnings';
        statusClass = 'safe';
        statusIcon = 'alert-triangle';
    } else if (state === 'INVALID') {
        statusTitle = 'Validation Failed';
        statusClass = 'p-badge-red';
        statusIcon = 'alert-octagon';
    } else if (state === 'UNSUPPORTED_DATASET') {
        statusTitle = 'Unsupported Dataset Type';
        statusClass = 'p-badge-red';
        statusIcon = 'help-circle';
    }

    const isParseFailed = (state === 'CSV_PARSE_FAILED' || state === 'EMPTY_CSV');

    let checkpointsHtml = '';
    if (isParseFailed) {
        checkpointsHtml = `
            <div class="checkpoint-list">
                <div class="checkpoint-item fail">
                    <i data-lucide="x-circle"></i>
                    <span>File Format: CSV Parse Failed / Empty File</span>
                </div>
                <div class="checkpoint-item not-evaluated">
                    <i data-lucide="minus-circle"></i>
                    <span>Required Schema Columns: Not evaluated</span>
                </div>
                <div class="checkpoint-item not-evaluated">
                    <i data-lucide="minus-circle"></i>
                    <span>Primary Key Uniqueness: Not evaluated</span>
                </div>
                <div class="checkpoint-item not-evaluated">
                    <i data-lucide="minus-circle"></i>
                    <span>Timestamp & Data Types: Not evaluated</span>
                </div>
            </div>
        `;
    } else {
        const hasMissingReq = textErrors.some(e => e.toLowerCase().includes('missing required column') || e.toLowerCase().includes('null_required_value')) || structuredErrors.some(e => e.error_type === 'missing_required_column' || e.error_type === 'missing_column' || e.error_type === 'null_required_value');
        const hasPkDup = textErrors.some(e => e.toLowerCase().includes('duplicate primary key')) || structuredErrors.some(e => e.error_type === 'duplicate_primary_key' || e.error_type === 'existing_primary_key');
        const hasTypeErr = textErrors.some(e => e.toLowerCase().includes('invalid ') || e.toLowerCase().includes('type mismatch')) || structuredErrors.some(e => e.error_type && (e.error_type.startsWith('invalid_') || e.error_type === 'timestamp_parse_error'));

        checkpointsHtml = `
            <div class="checkpoint-list">
                <div class="checkpoint-item ${data.filename && data.filename.endsWith('.csv') ? 'pass' : 'fail'}">
                    <i data-lucide="${data.filename && data.filename.endsWith('.csv') ? 'check-circle' : 'x-circle'}"></i>
                    <span>File Format: CSV (.csv) Verified</span>
                </div>
                <div class="checkpoint-item ${hasMissingReq ? 'fail' : 'pass'}">
                    <i data-lucide="${hasMissingReq ? 'x-circle' : 'check-circle'}"></i>
                    <span>Required Schema Columns: ${hasMissingReq ? 'Missing Columns' : 'All Present'}</span>
                </div>
                <div class="checkpoint-item ${hasPkDup ? 'fail' : 'pass'}">
                    <i data-lucide="${hasPkDup ? 'x-circle' : 'check-circle'}"></i>
                    <span>Primary Key Uniqueness: ${hasPkDup ? 'Duplicate PKs Detected' : '0 Duplicates'}</span>
                </div>
                <div class="checkpoint-item ${hasTypeErr ? 'fail' : 'pass'}">
                    <i data-lucide="${hasTypeErr ? 'x-circle' : 'check-circle'}"></i>
                    <span>Timestamp & Data Types: ${hasTypeErr ? 'Type Errors Detected' : 'Strict Types Verified'}</span>
                </div>
            </div>
        `;
    }

    let errorsHtml = '';
    if (structuredErrors.length > 0) {
        errorsHtml = `
            <div style="margin-top: 14px;">
                <div style="font-weight: 700; color: var(--accent-red); margin-bottom: 8px; font-size: 0.9rem;">
                    Diagnostic Errors (${structuredErrors.length}):
                </div>
                ${structuredErrors.map(renderSingleStructuredErrorCard).join('')}
            </div>
        `;
    } else if (textErrors.length > 0) {
        errorsHtml = `
            <div class="import-error-list" style="margin-top: 12px;">
                <strong>Validation Errors Detected:</strong>
                <ul>${textErrors.map(err => `<li>${escapeHtml(err)}</li>`).join('')}</ul>
            </div>
        `;
    }

    let warningsHtml = '';
    if (warnings.length > 0) {
        warningsHtml = `
            <div style="margin-top: 10px; padding: 10px 14px; background: rgba(245, 158, 11, 0.12); border-left: 3px solid var(--accent-amber); border-radius: 4px; color: #FCD34D; font-size: 0.84rem;">
                <strong>Warnings / Notices:</strong>
                <ul style="margin-left: 18px; margin-top: 4px;">
                    ${warnings.map(w => `<li>${escapeHtml(w)}</li>`).join('')}
                </ul>
            </div>
        `;
    }

    let actionsHtml = '';
    if (!isValid) {
        actionsHtml = `
            <div class="report-actions">
                <button class="btn-refresh" onclick='downloadErrorReport(lastValidationResult)' style="font-size: 0.8rem;">
                    <i data-lucide="download"></i> Download Diagnostic Error Report (JSON)
                </button>
            </div>
        `;
    }

    validationOutput.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div style="font-size: 0.95rem; font-weight: 700; color: ${isValid ? 'var(--primary-emerald)' : 'var(--accent-red)'}; display: flex; align-items: center; gap: 6px;">
                <i data-lucide="${statusIcon}"></i>
                <span>${statusTitle}</span>
            </div>
            <span class="p-badge ${statusClass}">${escapeHtml(data.label || data.table_name || 'Dataset')}</span>
        </div>
        <div style="font-size: 0.84rem; color: var(--text-muted); margin-bottom: 8px;">
            Target Table: <strong>public.${escapeHtml(data.table_name || 'unknown')}</strong> | Total Rows: <strong>${(data.row_count || 0).toLocaleString()}</strong> | Mapped Columns: <strong>${(data.columns || []).length}</strong>
        </div>
        ${checkpointsHtml}
        ${errorsHtml}
        ${warningsHtml}
        ${actionsHtml}
    `;

    if (window.lucide) lucide.createIcons();
}

function refreshStagedTable() {
    const tbody = document.getElementById('staged-datasets-body');
    const btnLoadDb = document.getElementById('btn-load-database');
    const btnClearStaged = document.getElementById('btn-clear-staged');
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
        if (btnClearStaged) btnClearStaged.disabled = true;
        return;
    }

    if (btnLoadDb) btnLoadDb.disabled = false;
    if (btnClearStaged) btnClearStaged.disabled = false;

    tbody.innerHTML = tables.map(tbl => {
        const item = stagedDatasetsState[tbl];
        return `
            <tr>
                <td><strong>public.${escapeHtml(tbl)}</strong><br><span style="font-size: 0.76rem; color: var(--text-dim);">${escapeHtml(item.filename)}</span></td>
                <td>${item.row_count.toLocaleString()}</td>
                <td><span class="p-badge safe">Ready to Load</span></td>
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
    previewTitle.innerHTML = `<i data-lucide="table"></i> Staged Normalized Preview: public.${escapeHtml(tableName)} (${totalRows.toLocaleString()} total rows)`;

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
