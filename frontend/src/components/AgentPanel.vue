<script setup>
import { ref, onMounted, watch, nextTick, computed } from 'vue';
import { marked } from 'marked';
import ConfirmDialog from './ConfirmDialog.vue';

// Configure marked for safe rendering
marked.setOptions({
    breaks: true,
    gfm: true  // GitHub Flavored Markdown (tables, strikethrough, etc.)
});

// Custom renderer to open links in new tab
const renderer = new marked.Renderer();
renderer.link = ({ href, title, text }) => {
    const titleAttr = title ? ` title="${title}"` : '';
    return `<a href="${href}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`;
};
marked.use({ renderer });

// Helper to render markdown content
const renderMarkdown = (content) => {
    if (!content) return '';
    return marked.parse(content);
};

const props = defineProps({
  alertId: String
});

const emit = defineEmits(['close']);

// State
const messages = ref([]);
const inputMessage = ref('');
const isLoading = ref(false);
const showTools = ref(false); // Toggle to show tool usage details
const sessionId = ref('');
const messagesContainer = ref(null);
const inputRef = ref(null);
const alertInfo = ref(null); // Store alert details for greeting
const previousAlertId = ref(null); // Track previous alert for context switch detection
let abortController = null; // Controller for stopping generation

// Dialog state
const showDeleteDialog = ref(false);
const deleteDialogMessage = ref('This will permanently delete your conversation history from the server.');
const deleteDialogTitle = ref('Delete Conversation History');
const deleteDialogShowButtons = ref(true);
const isDeleting = ref(false);

// Generate dynamic greeting based on alert info
const generateGreeting = (info) => {
    if (info) {
        const { id, ticker, instrument_name, trade_type, start_date, end_date } = info;
        // Check if we are resuming a session (history exists) - simpler greeting?
        // For now, consistent greeting at top is fine, or we can check messages.value.length
        return `Hello! I'm your Trade Surveillance Assistant. I can see you're investigating:\n\n` +
               `**Alert ${id}** - ${ticker} (${instrument_name})\n` +
               `- **Type:** ${trade_type}\n` +
               `- **Period:** ${start_date} to ${end_date}\n\n` +
               `How can I help you analyze this alert?`;
    }
    return 'Hello! I am your Trade Surveillance Assistant. How can I help you investigate this alert?';
};

// Fetch alert info and Initialize Session
const initializeSession = async (alertId) => {
    if (!alertId) return;
    
    // 1. Fetch Alert Info to get the Ticker
    try {
        const response = await fetch(`http://localhost:8000/alerts/${alertId}`);
        if (!response.ok) throw new Error('Failed to fetch alert info');
        
        const newAlertInfo = await response.json();
        
        // Check if we are switching tickers
        const previousTicker = alertInfo.value ? alertInfo.value.ticker : null;
        const newTicker = newAlertInfo.ticker;
        
        // Update current alert info
        alertInfo.value = newAlertInfo;
        
        // 2. Determine Session ID Logic
        if (sessionId.value && previousTicker === newTicker) {
            // SAME TICKER: Keep the same session!
            console.log(`[Agent] Keeping session ${sessionId.value} for same ticker ${newTicker}`);
            
            // Check if switching between different alerts of same ticker
            if (previousAlertId.value && previousAlertId.value !== alertId) {
                // Insert context switch indicator
                messages.value.push({
                    role: 'context-switch',
                    alertId: alertId,
                    ticker: newTicker,
                    startDate: newAlertInfo.start_date,
                    endDate: newAlertInfo.end_date,
                    instrumentName: newAlertInfo.instrument_name
                });
                scrollToBottom();
            }
        } else {
            // NEW TICKER (or first load): Switch Session
            const sessionKey = `agent_session_${newTicker}`;
            let storedSession = localStorage.getItem(sessionKey);
            
            if (!storedSession) {
                storedSession = crypto.randomUUID();
                localStorage.setItem(sessionKey, storedSession);
            }
            
            sessionId.value = storedSession;
            console.log(`[Agent] Switched to session ${sessionId.value} for ticker ${newTicker}`);
            
            // 3. Load History for this Ticker
            await fetchChatHistory(sessionId.value);
            
            // 4. If no history for this ticker, add greeting
            if (messages.value.length === 0) {
                messages.value = [{ role: 'agent', content: generateGreeting(newAlertInfo) }];
            }
        }
        
        // Update previous alert tracking
        previousAlertId.value = alertId;
        
    } catch (e) {
        console.error('Failed to initialize session:', e);
        // Fallback safety
        alertInfo.value = null;
    }
};

// Fetch chat history from backend
const fetchChatHistory = async (sid) => {
    messages.value = []; // Clear current view first
    try {
        const response = await fetch(`http://localhost:8000/agent/history/${sid}`);
        if (response.ok) {
            const data = await response.json();
            if (data.messages && data.messages.length > 0) {
                messages.value = data.messages;
                scrollToBottom();
                return;
            }
        }
    } catch (e) {
        console.error('Failed to fetch chat history:', e);
    }
};

// Clear chat (UI only, new session)
const clearChat = () => {
    if (!alertInfo.value) return;
    
    // Create new session for this Ticker
    const ticker = alertInfo.value.ticker;
    const newSessionId = crypto.randomUUID();
    const sessionKey = `agent_session_${ticker}`;
    
    localStorage.setItem(sessionKey, newSessionId);
    sessionId.value = newSessionId;
    
    // Reset to greeting
    messages.value = [
        { role: 'agent', content: generateGreeting(alertInfo.value) }
    ];
};

// Delete history from backend and clear UI
const showDeleteConfirmation = () => {
    deleteDialogShowButtons.value = true;
    deleteDialogTitle.value = 'Delete Conversation History';
    deleteDialogMessage.value = 'This will permanently delete your conversation history for this TICKER from the server. Continue?';
    showDeleteDialog.value = true;
};

const cancelDelete = () => {
    showDeleteDialog.value = false;
};

const confirmDelete = async () => {
    isDeleting.value = true;
    deleteDialogMessage.value = 'Deleting...';
    
    try {
        const response = await fetch(`http://localhost:8000/agent/history/${sessionId.value}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (!response.ok || data.status === 'error') {
            deleteDialogTitle.value = 'Error';
            deleteDialogMessage.value = `Failed to delete: ${data.message || 'Unknown error'}`;
            deleteDialogShowButtons.value = false; // Or provide just a close button, but here we hide misleading "delete"
            isDeleting.value = false;
            // Auto-close on error too or let user click out? 
            // For now, let's auto-close error too for consistency or maybe add a close button later.
            // Requirement was specifically about success. 
            // Let's keep buttons hidden for error to avoid "Delete" again.
            setTimeout(() => {
                 showDeleteDialog.value = false;
            }, 2000);
            return;
        }
        
        // Success
        deleteDialogTitle.value = 'Success';
        deleteDialogMessage.value = 'Conversation history deleted successfully.';
        deleteDialogShowButtons.value = false;
        isDeleting.value = false;
        
        // Auto-close and clear after 1.5s
        setTimeout(() => {
            showDeleteDialog.value = false;
            clearChat();
        }, 1500);
        
    } catch (e) {
        console.error('Failed to delete history:', e);
        deleteDialogTitle.value = 'Error';
        deleteDialogMessage.value = `Failed to delete: ${e.message}`;
        deleteDialogShowButtons.value = false;
        isDeleting.value = false;
        setTimeout(() => {
             showDeleteDialog.value = false;
        }, 2000);
    }
};

// Start logic
onMounted(async () => {
    await initializeSession(props.alertId);
});

// Watch for Alert ID changes to switch session if needed
watch(() => props.alertId, async (newId) => {
    if (newId) {
        await initializeSession(newId);
    }
});

// Scroll to bottom
const scrollToBottom = async () => {
    await nextTick();
    if (messagesContainer.value) {
        messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight;
    }
};

// Stop Generation
const stopGeneration = () => {
    if (abortController) {
        abortController.abort();
        abortController = null;
    }
    isLoading.value = false;
    // Add a marker that generation was stopped if needed, or just leave it
    // messages.value[messages.value.length - 1].content += ' [Stopped]';
};

// Send Message
const sendMessage = async () => {
    if (!inputMessage.value.trim() || isLoading.value) return;

    const userMsg = inputMessage.value;
    messages.value.push({ role: 'user', content: userMsg });
    inputMessage.value = '';
    isLoading.value = true;
    scrollToBottom();

    // Placeholder for agent response
    const agentMsgIndex = messages.value.length;
    messages.value.push({ 
        role: 'agent', 
        content: '', 
        tools: [] // To track tool usage
    });

    // Create new abort controller
    abortController = new AbortController();

    try {
        // Build alert context from current alert info
        const alertContext = alertInfo.value ? {
            id: alertInfo.value.id,
            ticker: alertInfo.value.ticker,
            isin: alertInfo.value.isin,
            start_date: alertInfo.value.start_date,
            end_date: alertInfo.value.end_date,
            instrument_name: alertInfo.value.instrument_name,
            trade_type: alertInfo.value.trade_type,
            status: alertInfo.value.status
        } : null;

        const response = await fetch('http://localhost:8000/agent/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: userMsg,
                session_id: sessionId.value,
                alert_context: alertContext
            }),
            signal: abortController.signal
        });

        if (!response.ok) throw new Error(response.statusText);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\n\n');
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        
                        if (data.type === 'token') {
                            messages.value[agentMsgIndex].content += data.content;
                        } else if (data.type === 'tool_start') {
                            messages.value[agentMsgIndex].tools.push({
                                name: data.tool,
                                status: 'running'
                            });
                        } else if (data.type === 'tool_end') {
                            // Find the running tool and mark complete
                            const tool = messages.value[agentMsgIndex].tools.find(t => t.name === data.tool && t.status === 'running');
                            if (tool) tool.status = 'done';
                        }
                        
                        scrollToBottom();
                    } catch (e) {
                         // Ignore parse errors for partial chunks
                    }
                }
            }
        }
    } catch (e) {
        if (e.name === 'AbortError') {
             messages.value[agentMsgIndex].content += '\n[Stopped by user]';
        } else {
             messages.value[agentMsgIndex].content += `\n[Error: ${e.message}]`;
        }
    } finally {
        isLoading.value = false;
        abortController = null;
        scrollToBottom();
        // Keep focus on input for continued typing
        await nextTick();
        inputRef.value?.focus();
    }
};

// Resize Logic
const panelWidth = ref(400); // Default width
const isResizing = ref(false);

const startResize = (e) => {
    isResizing.value = true;
    document.addEventListener('mousemove', handleResize);
    document.addEventListener('mouseup', stopResize);
    // Prevent text selection during resize
    document.body.style.userSelect = 'none';
};

const handleResize = (e) => {
    if (!isResizing.value) return;
    // Calculate new width: distance from right edge of window
    // Since panel is on the right, width = window.innerWidth - mouseX
    const newWidth = window.innerWidth - e.clientX;
    
    // Constraints
    if (newWidth >= 300 && newWidth <= 800) {
        panelWidth.value = newWidth;
    }
};

const stopResize = () => {
    isResizing.value = false;
    document.removeEventListener('mousemove', handleResize);
    document.removeEventListener('mouseup', stopResize);
    document.body.style.userSelect = '';
};
</script>

<template>
  <div class="agent-panel" :style="{ width: panelWidth + 'px' }">
      <!-- Resize Handle -->
      <div class="resize-handle" @mousedown="startResize">
          <div class="handle-line"></div>
      </div>

      <div class="panel-header">
          <h3>AI Assistant</h3>
          <div class="header-actions">
              <button @click="clearChat" class="action-btn" title="Clear chat (new session)">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M20 20H7L3 16l9-13 8 8-5 9z"/>
                      <path d="M6.5 13.5l5 5"/>
                  </svg>
              </button>
              <button @click="showDeleteConfirmation" class="action-btn delete-btn" title="Delete history from server">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14M10 11v6M14 11v6"/>
                  </svg>
              </button>
              <button @click="$emit('close')" class="close-btn">×</button>
          </div>
      </div>
      
      <div class="messages-area" ref="messagesContainer">
          <div v-for="(msg, index) in messages" :key="index" :class="['message', msg.role]">
              
              <!-- Context Switch Indicator -->
              <template v-if="msg.role === 'context-switch'">
                  <div class="context-switch-divider">
                      <div class="divider-line"></div>
                      <div class="divider-content">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                              <circle cx="12" cy="12" r="3"/>
                          </svg>
                          <span>Switched to <strong>{{ msg.alertId }}</strong></span>
                          <span class="date-range">{{ msg.startDate }} → {{ msg.endDate }}</span>
                      </div>
                      <div class="divider-line"></div>
                  </div>
              </template>
              
              <!-- Regular Messages -->
              <div v-else class="message-content">
                  <!-- Key forces re-render when content changes during streaming -->
                  <div v-if="msg.content" 
                       :key="`md-${index}-${msg.content.length}`"
                       class="text markdown-content" 
                       v-html="renderMarkdown(msg.content)"></div>
                  
                  <!-- Tool Usage Indicators -->
                  <div v-if="msg.tools && msg.tools.length > 0" class="tools-container">
                      <div v-for="tool in msg.tools" :key="tool.name" class="tool-badge">
                          <span class="status-dot" :class="tool.status"></span>
                          {{ tool.name }}
                      </div>
                  </div>
              </div>
          </div>
          
          <div v-if="isLoading" class="loading-container">
              <div class="spinner"></div>
          </div>
      </div>
      
      <div class="input-area">
          <input 
              ref="inputRef"
              v-model="inputMessage" 
              @keyup.enter="sendMessage"
              placeholder="Ask about this alert..." 
              :disabled="isLoading"
          />
          <button v-if="!isLoading" @click="sendMessage" :disabled="!inputMessage">Send</button>
          <button v-else @click="stopGeneration" class="stop-btn">
              <span class="stop-icon">■</span> Stop
          </button>
      </div>
  </div>
  
  <!-- Delete Confirmation Dialog -->
  <ConfirmDialog
      :isOpen="showDeleteDialog"
      :title="deleteDialogTitle"
      :message="deleteDialogMessage"
      :confirmText="isDeleting ? 'Deleting...' : 'Delete'"
      cancelText="Cancel"
      :showButtons="deleteDialogShowButtons"
      @confirm="confirmDelete"
      @cancel="cancelDelete"
  />
</template>

<style scoped>
.agent-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--color-surface);
    border-left: 1px solid var(--color-border);
    /* width removed here, set via style binding */
    box-shadow: -2px 0 10px rgba(0,0,0,0.1);
    position: relative;
    max-width: 90vw;
}

.resize-handle {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 4px;
    cursor: ew-resize;
    z-index: 10;
    display: flex;
    justify-content: center;
    align-items: center;
    transition: background 0.2s;
}

.resize-handle:hover, .resize-handle:active {
    background: #3b82f6;
}

.agent-panel:hover .resize-handle {
    background: rgba(59, 130, 246, 0.1);
}

.panel-header {
    padding: var(--spacing-4);
    border-bottom: 1px solid var(--color-border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: var(--color-surface-hover);
    padding-left: 12px; /* reduced padding to account for handle space if needed */
}

.panel-header h3 {
    margin: 0;
    font-size: var(--font-size-md);
    color: var(--color-text-main);
}

.close-btn {
    border: none;
    background: none;
    font-size: 1.5rem;
    cursor: pointer;
    color: var(--color-text-subtle);
}

.header-actions {
    display: flex;
    align-items: center;
    gap: 4px;
}

.action-btn {
    border: none;
    background: none;
    font-size: 1rem;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
    transition: background 0.2s;
}

.action-btn:hover {
    background: var(--color-surface-hover);
}

.action-btn.delete-btn:hover {
    background: rgba(239, 68, 68, 0.1);
}

.messages-area {
    flex: 1;
    overflow-y: auto;
    padding: var(--spacing-4);
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
}

.message {
    max-width: 85%;
    padding: var(--spacing-3);
    border-radius: 8px;
    font-size: var(--font-size-sm);
    line-height: 1.4;
}

.message.user {
    align-self: flex-end;
    background-color: var(--color-primary);
    color: white;
    border-bottom-right-radius: 2px;
}

.message.agent {
    align-self: stretch;  /* Full width instead of flex-start */
    max-width: 100%;      /* Remove max-width constraint */
    background-color: var(--color-background);
    color: var(--color-text-main);
    border: 1px solid var(--color-border);
    border-radius: 8px;
    margin: 4px 8px;      /* Aesthetic margins */
}

/* Markdown Content Styles */
.markdown-content {
    line-height: 1.6;
}

.markdown-content :deep(p) {
    margin: 0 0 0.5em 0;
}

.markdown-content :deep(p:last-child) {
    margin-bottom: 0;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
    margin: 0.5em 0;
    padding-left: 1.5em;
}

.markdown-content :deep(li) {
    margin: 0.25em 0;
}

.markdown-content :deep(strong) {
    font-weight: 600;
    color: var(--color-text-main);
}

.markdown-content :deep(em) {
    font-style: italic;
}

.markdown-content :deep(code) {
    background: rgba(0, 0, 0, 0.08);
    padding: 0.15em 0.4em;
    border-radius: 3px;
    font-family: 'SF Mono', Monaco, Consolas, monospace;
    font-size: 0.9em;
}

.markdown-content :deep(pre) {
    background: rgba(0, 0, 0, 0.06);
    padding: 0.75em;
    border-radius: 6px;
    overflow-x: auto;
    margin: 0.5em 0;
}

.markdown-content :deep(pre code) {
    background: none;
    padding: 0;
}

/* Table Styles */
.markdown-content :deep(table) {
    width: 100%;
    border-collapse: collapse;
    margin: 0.75em 0;
    font-size: 0.9em;
}

.markdown-content :deep(th),
.markdown-content :deep(td) {
    border: 1px solid var(--color-border);
    padding: 0.5em 0.75em;
    text-align: left;
}

.markdown-content :deep(th) {
    background: var(--color-surface-hover);
    font-weight: 600;
}

.markdown-content :deep(tr:nth-child(even)) {
    background: rgba(0, 0, 0, 0.02);
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4) {
    margin: 0.75em 0 0.5em 0;
    font-weight: 600;
}

.markdown-content :deep(h1) { font-size: 1.3em; }
.markdown-content :deep(h2) { font-size: 1.2em; }
.markdown-content :deep(h3) { font-size: 1.1em; }
.markdown-content :deep(h4) { font-size: 1em; }

.markdown-content :deep(blockquote) {
    border-left: 3px solid var(--color-primary);
    margin: 0.5em 0;
    padding-left: 1em;
    color: var(--color-text-subtle);
}

.tools-container {
    margin-top: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
}

.tool-badge {
    font-size: 10px;
    background: rgba(0,0,0,0.05);
    padding: 2px 6px;
    border-radius: 4px;
    color: var(--color-text-muted);
    display: flex;
    align-items: center;
    gap: 4px;
}

.status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #ccc;
}

.status-dot.running { background: #3498db; animation: pulse 1s infinite; }
.status-dot.done { background: #2ecc71; }

@keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }

.input-area {
    padding: var(--spacing-3);
    border-top: 1px solid var(--color-border);
    display: flex;
    gap: var(--spacing-2);
}

.input-area input {
    flex: 1;
    padding: 8px;
    border: 1px solid var(--color-border);
    border-radius: 4px;
    background: var(--color-background);
    color: var(--color-text-main);
}

.input-area button {
    padding: 8px 16px;
    background-color: var(--color-primary);
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 4px;
}

.stop-btn {
    background-color: #ef4444; /* Red color */
}

.stop-btn:hover {
    background-color: #dc2626;
}

.stop-icon {
    font-size: 0.8em;
}

.input-area button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.loading-container {
    padding: var(--spacing-3);
    padding-left: 0;
    display: flex;
    justify-content: flex-start;
}

.spinner {
    width: 20px;
    height: 20px;
    border: 2px solid var(--color-border);
    border-top: 2px solid var(--color-primary);
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}

/* Context Switch Indicator Styles */
.message.context-switch {
    max-width: 100%;
    padding: 0;
    background: none;
    border: none;
}

.context-switch-divider {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 0;
    width: 100%;
}

.divider-line {
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--color-border), transparent);
}

.divider-content {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11px;
    color: var(--color-text-muted);
    background: var(--color-surface);
    padding: 4px 12px;
    border-radius: 12px;
    border: 1px solid var(--color-border);
    white-space: nowrap;
}

.divider-content svg {
    color: var(--color-primary);
    flex-shrink: 0;
}

.divider-content strong {
    color: var(--color-text-main);
    font-weight: 600;
}

.divider-content .date-range {
    color: var(--color-text-subtle);
    font-size: 10px;
    padding-left: 8px;
    border-left: 1px solid var(--color-border);
}
</style>
