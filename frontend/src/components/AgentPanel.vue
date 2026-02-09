<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue';
import { marked } from 'marked';
import ConfirmDialog from './ConfirmDialog.vue';

marked.setOptions({ breaks: true, gfm: true });
const renderer = new marked.Renderer();
renderer.link = ({ href, title, text }) => {
  const titleAttr = title ? ` title="${title}"` : '';
  return `<a href="${href}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`;
};
marked.use({ renderer });

const renderMarkdown = (content) => (content ? marked.parse(content) : '');

const props = defineProps({ alertId: String });
defineEmits(['close']);

const messages = ref([]);
const inputMessage = ref('');
const isLoading = ref(false);
const sessionId = ref('');
const messagesContainer = ref(null);
const inputRef = ref(null);
const alertInfo = ref(null);
const previousAlertId = ref(null);
const panelWidth = ref(400);
const isResizing = ref(false);
const composerRef = ref(null);

const artifacts = ref([]);
const artifactsLoading = ref(false);
const showArtifactsMenu = ref(false);

let abortController = null;

const showDeleteDialog = ref(false);
const deleteDialogMessage = ref('This will permanently delete your conversation history from the server.');
const deleteDialogTitle = ref('Delete Conversation History');
const deleteDialogShowButtons = ref(true);
const isDeleting = ref(false);

const generateGreeting = (info) => {
  if (!info) return 'Hello! I am your Trade Surveillance Assistant. How can I help you investigate this alert?';
  return `Hello! I'm your Trade Surveillance Assistant. I can see you're investigating:\n\n` +
    `**Alert ${info.id}** - ${info.ticker} (${info.instrument_name})\n` +
    `- **Type:** ${info.trade_type}\n` +
    `- **Period:** ${info.start_date} to ${info.end_date}\n\n` +
    `How can I help you analyze this alert?`;
};

const scrollToBottom = async () => {
  await nextTick();
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight;
  }
};

const fetchArtifacts = async () => {
  if (!sessionId.value) {
    artifacts.value = [];
    return;
  }
  artifactsLoading.value = true;
  try {
    const response = await fetch(`http://localhost:8000/artifacts/${sessionId.value}`);
    if (!response.ok) throw new Error('Failed to fetch artifacts');
    const data = await response.json();
    artifacts.value = data.artifacts || [];
  } catch (e) {
    console.error('Failed to fetch artifacts:', e);
    artifacts.value = [];
  } finally {
    artifactsLoading.value = false;
  }
};

const fetchChatHistory = async (sid) => {
  messages.value = [];
  try {
    const response = await fetch(`http://localhost:8000/agent/history/${sid}`);
    if (response.ok) {
      const data = await response.json();
      if (data.messages?.length) {
        messages.value = data.messages;
      }
    }
  } catch (e) {
    console.error('Failed to fetch chat history:', e);
  }
  await scrollToBottom();
};

const initializeSession = async (alertId) => {
  if (!alertId) return;

  try {
    const response = await fetch(`http://localhost:8000/alerts/${alertId}`);
    if (!response.ok) throw new Error('Failed to fetch alert info');
    const newAlertInfo = await response.json();

    const previousTicker = alertInfo.value ? alertInfo.value.ticker : null;
    const newTicker = newAlertInfo.ticker;
    alertInfo.value = newAlertInfo;

    if (sessionId.value && previousTicker === newTicker) {
      if (previousAlertId.value && previousAlertId.value !== alertId) {
        messages.value.push({
          role: 'context-switch',
          alertId,
          ticker: newTicker,
          startDate: newAlertInfo.start_date,
          endDate: newAlertInfo.end_date,
          instrumentName: newAlertInfo.instrument_name,
        });
      }
    } else {
      const sessionKey = `agent_session_${newTicker}`;
      let storedSession = localStorage.getItem(sessionKey);
      if (!storedSession) {
        storedSession = crypto.randomUUID();
        localStorage.setItem(sessionKey, storedSession);
      }
      sessionId.value = storedSession;
      await fetchChatHistory(sessionId.value);
      await fetchArtifacts();

      if (!messages.value.length) {
        messages.value = [{ role: 'agent', content: generateGreeting(newAlertInfo) }];
      }
    }

    previousAlertId.value = alertId;
    await scrollToBottom();
  } catch (e) {
    console.error('Failed to initialize session:', e);
    alertInfo.value = null;
  }
};

const clearChat = () => {
  if (!alertInfo.value) return;
  const ticker = alertInfo.value.ticker;
  const newSessionId = crypto.randomUUID();
  const sessionKey = `agent_session_${ticker}`;
  localStorage.setItem(sessionKey, newSessionId);
  sessionId.value = newSessionId;
  artifacts.value = [];
  messages.value = [{ role: 'agent', content: generateGreeting(alertInfo.value) }];
};

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
    const response = await fetch(`http://localhost:8000/agent/history/${sessionId.value}`, { method: 'DELETE' });
    const data = await response.json();
    if (!response.ok || data.status === 'error') throw new Error(data.message || 'Unknown error');

    deleteDialogTitle.value = 'Success';
    deleteDialogMessage.value = 'Conversation history deleted successfully.';
    deleteDialogShowButtons.value = false;

    setTimeout(() => {
      showDeleteDialog.value = false;
      clearChat();
    }, 1500);
  } catch (e) {
    deleteDialogTitle.value = 'Error';
    deleteDialogMessage.value = `Failed to delete: ${e.message}`;
    deleteDialogShowButtons.value = false;
    setTimeout(() => {
      showDeleteDialog.value = false;
    }, 2000);
  } finally {
    isDeleting.value = false;
  }
};

const toggleArtifactsMenu = async () => {
  showArtifactsMenu.value = !showArtifactsMenu.value;
  if (showArtifactsMenu.value) await fetchArtifacts();
};

const downloadArtifact = (artifact) => {
  if (!artifact?.relative_path || !sessionId.value) return;
  const url = new URL(`http://localhost:8000/artifacts/${sessionId.value}/download`);
  url.searchParams.set('path', artifact.relative_path);
  window.open(url.toString(), '_blank', 'noopener,noreferrer');
};

const handleComposerKeydown = (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
};

const handleClickOutsideComposer = (e) => {
  if (composerRef.value && !composerRef.value.contains(e.target)) {
    showArtifactsMenu.value = false;
  }
};

const captureAndUploadChartSnapshot = async () => {
  if (!props.alertId || !sessionId.value) return;
  const captureFn = window.__tsPitCaptureAlertChart;
  if (typeof captureFn !== 'function') return;

  let imageDataUrl = null;
  try {
    imageDataUrl = captureFn();
  } catch (e) {
    console.error('Chart capture function failed:', e);
    return;
  }
  if (!imageDataUrl || typeof imageDataUrl !== 'string') return;

  try {
    await fetch('http://localhost:8000/reports/chart-snapshot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId.value,
        alert_id: props.alertId,
        image_data_url: imageDataUrl,
      }),
    });
  } catch (e) {
    console.error('Failed to upload chart snapshot:', e);
  }
};

const stopGeneration = () => {
  if (abortController) {
    abortController.abort();
    abortController = null;
  }
  isLoading.value = false;
};

const sendMessage = async () => {
  if (!inputMessage.value.trim() || isLoading.value) return;

  const userMsg = inputMessage.value;
  messages.value.push({ role: 'user', content: userMsg });
  inputMessage.value = '';
  isLoading.value = true;
  await scrollToBottom();
  await captureAndUploadChartSnapshot();

  const agentMsgIndex = messages.value.length;
  messages.value.push({ role: 'agent', content: '', tools: [] });

  abortController = new AbortController();

  try {
    const alertContext = alertInfo.value
      ? {
          id: alertInfo.value.id,
          ticker: alertInfo.value.ticker,
          isin: alertInfo.value.isin,
          start_date: alertInfo.value.start_date,
          end_date: alertInfo.value.end_date,
          instrument_name: alertInfo.value.instrument_name,
          trade_type: alertInfo.value.trade_type,
          status: alertInfo.value.status,
        }
      : null;

    const response = await fetch('http://localhost:8000/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: userMsg,
        session_id: sessionId.value,
        alert_context: alertContext,
      }),
      signal: abortController.signal,
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
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));

          if (data.type === 'token') {
            messages.value[agentMsgIndex].content += data.content;
          } else if (data.type === 'tool_start') {
            messages.value[agentMsgIndex].tools.push({ name: data.tool, status: 'running' });
          } else if (data.type === 'tool_end') {
            const tool = messages.value[agentMsgIndex].tools.find(
              (t) => t.name === data.tool && t.status === 'running'
            );
            if (tool) tool.status = 'done';
          } else if (data.type === 'artifact_created') {
            messages.value[agentMsgIndex].content += '\n\nReport generated. Download it from the Artifact icon next to the chat box.';
            fetchArtifacts();
          }

          await scrollToBottom();
        } catch {
          // ignore partial chunk JSON parse failures
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
    await scrollToBottom();
    await nextTick();
    inputRef.value?.focus();
  }
};

const startResize = () => {
  isResizing.value = true;
  document.addEventListener('mousemove', handleResize);
  document.addEventListener('mouseup', stopResize);
  document.body.style.userSelect = 'none';
};

const handleResize = (e) => {
  if (!isResizing.value) return;
  const newWidth = window.innerWidth - e.clientX;
  if (newWidth >= 300 && newWidth <= 800) panelWidth.value = newWidth;
};

const stopResize = () => {
  isResizing.value = false;
  document.removeEventListener('mousemove', handleResize);
  document.removeEventListener('mouseup', stopResize);
  document.body.style.userSelect = '';
};

onMounted(async () => {
  await initializeSession(props.alertId);
  document.addEventListener('click', handleClickOutsideComposer);
});

onBeforeUnmount(() => {
  document.removeEventListener('click', handleClickOutsideComposer);
});

watch(
  () => props.alertId,
  async (newId) => {
    if (newId) await initializeSession(newId);
  }
);
</script>

<template>
  <div class="agent-panel" :style="{ width: panelWidth + 'px' }">
    <div class="resize-handle" @mousedown="startResize">
      <div class="handle-line"></div>
    </div>

    <div class="panel-header">
      <h3>AI Assistant</h3>
      <div class="header-actions">
        <button @click="clearChat" class="action-btn" title="Clear chat (new session)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 20H7L3 16l9-13 8 8-5 9"/>
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

        <div v-else class="message-content">
          <div
            v-if="msg.content"
            :key="`md-${index}-${msg.content.length}`"
            class="text markdown-content"
            v-html="renderMarkdown(msg.content)"
          ></div>

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

    <div class="composer-wrap" ref="composerRef">
      <textarea
        ref="inputRef"
        v-model="inputMessage"
        @keydown="handleComposerKeydown"
        class="composer-textarea"
        placeholder="Ask about this alert..."
        :disabled="isLoading"
        rows="2"
      ></textarea>

      <div class="composer-toolbar">
        <div class="input-left-tools">
          <button class="artifact-btn" @click.stop="toggleArtifactsMenu" :disabled="!sessionId" title="Artifacts">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="7 10 12 15 17 10"/>
              <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
          </button>

          <div v-if="showArtifactsMenu" class="artifacts-menu">
            <div v-if="artifactsLoading" class="artifacts-empty">Loading...</div>
            <template v-else>
              <button
                v-for="artifact in artifacts"
                :key="artifact.relative_path"
                class="artifact-item"
                @click="downloadArtifact(artifact)"
              >
                <span class="artifact-name">{{ artifact.name }}</span>
                <span class="artifact-meta">{{ artifact.created_at }}</span>
              </button>
              <div v-if="artifacts.length === 0" class="artifacts-empty">No artifacts yet</div>
            </template>
          </div>
        </div>

        <button v-if="!isLoading" @click="sendMessage" class="send-circle-btn" :disabled="!inputMessage.trim()" title="Send">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="19" x2="12" y2="5"/>
            <polyline points="5 12 12 5 19 12"/>
          </svg>
        </button>
        <button v-else @click="stopGeneration" class="send-circle-btn stop-btn" title="Stop">
          <span class="stop-icon">■</span>
        </button>
      </div>
    </div>
  </div>

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
  box-shadow: -2px 0 10px rgba(0, 0, 0, 0.1);
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
}

.resize-handle:hover,
.resize-handle:active {
  background: #3b82f6;
}

.panel-header {
  padding: var(--spacing-4);
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--color-surface-hover);
  padding-left: 12px;
}

.panel-header h3 {
  margin: 0;
  font-size: var(--font-size-md);
  color: var(--color-text-main);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.action-btn {
  border: none;
  background: none;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
}

.action-btn:hover {
  background: var(--color-surface-hover);
}

.action-btn.delete-btn:hover {
  background: rgba(239, 68, 68, 0.1);
}

.close-btn {
  border: none;
  background: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: var(--color-text-subtle);
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
  align-self: stretch;
  max-width: 100%;
  background-color: var(--color-background);
  color: var(--color-text-main);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  margin: 4px 8px;
}

.markdown-content {
  line-height: 1.6;
}

.markdown-content :deep(p) { margin: 0 0 0.5em 0; }
.markdown-content :deep(p:last-child) { margin-bottom: 0; }
.markdown-content :deep(ul),
.markdown-content :deep(ol) { margin: 0.5em 0; padding-left: 1.5em; }
.markdown-content :deep(li) { margin: 0.25em 0; }
.markdown-content :deep(strong) { font-weight: 600; color: var(--color-text-main); }
.markdown-content :deep(code) {
  background: rgba(0, 0, 0, 0.08);
  padding: 0.15em 0.4em;
  border-radius: 3px;
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  font-size: 0.9em;
}

.tools-container {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.tool-badge {
  font-size: 10px;
  background: rgba(0, 0, 0, 0.05);
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

@keyframes pulse {
  0% { opacity: 0.5; }
  50% { opacity: 1; }
  100% { opacity: 0.5; }
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

.composer-wrap {
  margin: 10px;
  border: 1px solid var(--color-border);
  border-radius: 20px;
  background: var(--color-surface);
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
  position: relative;
}

.composer-textarea {
  width: 100%;
  resize: none;
  border: none;
  outline: none;
  background: transparent;
  color: var(--color-text-main);
  font-family: inherit;
  font-size: 14px;
  font-weight: 400;
  line-height: 1.5;
  min-height: 48px;
}

.composer-textarea::placeholder {
  color: var(--color-text-subtle);
}

.composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.input-left-tools {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
}

.artifact-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 7px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-subtle);
  cursor: pointer;
}

.artifact-btn:hover {
  background: var(--color-surface-hover);
  color: var(--color-text-main);
}

.artifacts-menu {
  position: absolute;
  bottom: calc(100% + 10px);
  left: 0;
  width: 320px;
  max-height: 260px;
  overflow-y: auto;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.16);
  z-index: 30;
}

.artifact-item {
  width: 100%;
  border: none;
  background: transparent;
  text-align: left;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  cursor: pointer;
}

.artifact-item:hover {
  background: var(--color-surface-hover);
}

.artifact-name {
  color: var(--color-text-main);
  font-size: 12px;
  font-weight: 600;
}

.artifact-meta {
  color: var(--color-text-subtle);
  font-size: 11px;
}

.artifacts-empty {
  padding: 12px;
  color: var(--color-text-subtle);
  font-size: 12px;
}

.send-circle-btn {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  border: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #0f172a;
  color: #fff;
  cursor: pointer;
  flex-shrink: 0;
}

.send-circle-btn:hover {
  background: #020617;
}

.send-circle-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.send-circle-btn.stop-btn {
  background: #dc2626;
}

.send-circle-btn.stop-btn:hover {
  background: #b91c1c;
}

.stop-icon {
  font-size: 0.8em;
}
</style>
