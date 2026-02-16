<script setup>
import { toRef } from 'vue';
import { marked } from 'marked';
import markedKatex from 'marked-katex-extension';
import 'katex/dist/katex.min.css';
import ConfirmDialog from '../../../components/ConfirmDialog.vue';
import { useAgentChat } from '../composables/useAgentChat.js';

marked.setOptions({ breaks: true, gfm: true });
const renderer = new marked.Renderer();
renderer.link = ({ href, title, text }) => {
  const titleAttr = title ? ` title="${title}"` : '';
  return `<a href="${href}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`;
};
marked.use({ renderer });
marked.use(
  markedKatex({
    throwOnError: false,
    output: 'html',
    nonStandard: true,
  })
);

const normalizeLatexDelimiters = (content) => {
  if (!content || typeof content !== 'string') return content;
  return content
    // Convert block math from \[...\] to $$...$$.
    .replace(/\\\[([\s\S]*?)\\\]/g, (_, expr) => `$$${expr.trim()}$$`)
    // Convert inline math from \(...\) to $...$.
    .replace(/\\\(([\s\S]*?)\\\)/g, (_, expr) => `$${expr.trim()}$`)
    // Recover math accidentally wrapped as [ ... ] (non-link), only when TeX commands are present.
    .replace(/\[(\s*[^]\n]*\\[a-zA-Z][^]\n]*)\](?!\()/g, (_, expr) => `$$${expr.trim()}$$`);
};

const renderMarkdown = (content) => (content ? marked.parse(normalizeLatexDelimiters(content)) : '');
const formatToolLabel = (name) => name?.replaceAll('_', ' ') || 'tool';
const formatDuration = (ms) => {
  if (typeof ms !== 'number' || Number.isNaN(ms)) return '';
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
};
const prettyToolData = (value) => {
  if (!value) return '';
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return String(value);
  }
};
const isCodeTool = (name) => ['execute_sql', 'execute_python'].includes(name);
const parseToolInput = (tool) => {
  if (!tool?.input) return null;
  try {
    const parsed = JSON.parse(tool.input);
    if (parsed && typeof parsed === 'object') return parsed;
    if (typeof parsed === 'string') {
      try {
        const parsedAgain = JSON.parse(parsed);
        if (parsedAgain && typeof parsedAgain === 'object') return parsedAgain;
      } catch {
        return null;
      }
    }
    return null;
  } catch {
    return null;
  }
};
const toolCode = (tool) => {
  const input = parseToolInput(tool);
  if (!input) return '';
  if (tool?.name === 'execute_sql') return String(input.query || '');
  if (tool?.name === 'execute_python') {
    return String(input.code || input.python_code || input.script || '');
  }
  return '';
};
const codeLabel = (tool) => (tool?.name === 'execute_sql' ? 'SQL Code' : 'Python Code');
const escapeHtml = (value) => String(value || '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;');
const highlightCode = (tool) => {
  const raw = toolCode(tool);
  if (!raw) return '';
  let html = escapeHtml(raw);

  if (tool?.name === 'execute_sql') {
    const sqlKeywords = [
      'SELECT', 'FROM', 'WHERE', 'GROUP BY', 'ORDER BY', 'HAVING', 'JOIN', 'LEFT JOIN', 'RIGHT JOIN',
      'INNER JOIN', 'OUTER JOIN', 'ON', 'AS', 'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'DISTINCT',
      'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'AND', 'OR', 'NOT', 'IN', 'BETWEEN', 'LIKE', 'LIMIT',
    ];
    const pattern = new RegExp(`\\b(${sqlKeywords.join('|').replace(/ /g, '\\\\s+')})\\b`, 'gi');
    html = html.replace(pattern, '<span class="tok kw">$1</span>');
    html = html.replace(/'([^']*)'/g, '<span class="tok str">\'$1\'</span>');
    html = html.replace(/\b\d+(\.\d+)?\b/g, '<span class="tok num">$&</span>');
  } else if (tool?.name === 'execute_python') {
    const pyKeywords = [
      'def', 'class', 'return', 'if', 'elif', 'else', 'for', 'while', 'in', 'import', 'from', 'as',
      'try', 'except', 'finally', 'with', 'lambda', 'True', 'False', 'None', 'and', 'or', 'not',
    ];
    const pattern = new RegExp(`\\b(${pyKeywords.join('|')})\\b`, 'g');
    html = html.replace(pattern, '<span class="tok kw">$1</span>');
    html = html.replace(/'([^']*)'/g, '<span class="tok str">\'$1\'</span>');
    html = html.replace(/"([^"]*)"/g, '<span class="tok str">"$1"</span>');
    html = html.replace(/\b\d+(\.\d+)?\b/g, '<span class="tok num">$&</span>');
    html = html.replace(/(#.*)$/gm, '<span class="tok cmt">$1</span>');
  }
  return html;
};
const copyToolCode = async (tool) => {
  const code = toolCode(tool);
  if (!code) return;
  try {
    await navigator.clipboard.writeText(code);
  } catch {
    // no-op
  }
};
const messageSegments = (msg) => {
  if (msg?.segments?.length) return msg.segments;
  const segments = [];
  if (msg?.content) segments.push({ type: 'text', content: msg.content });
  if (msg?.tools?.length) {
    for (const tool of msg.tools) segments.push({ type: 'tool', tool });
  }
  return segments;
};
const messageVisibleSegments = (msg) => messageSegments(msg).filter((segment) => !['draft', 'tool', 'planner'].includes(segment?.type));
const messagePlannerSegment = (msg) => messageSegments(msg).find((segment) => segment.type === 'planner');
const messageToolSegments = (msg) => messageSegments(msg).filter((segment) => segment.type === 'tool');
const setPlanCollapsed = (msg, value) => {
  if (!msg || msg.role !== 'agent') return;
  msg.planCollapsed = Boolean(value);
};
const renderPlanMarkdown = (rawContent) => {
  const raw = String(rawContent || '').trim();
  if (!raw) return '';
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return raw;
    const lines = [];
    if (parsed.plan_action) lines.push(`**Plan action:** ${parsed.plan_action}`);
    if (typeof parsed.requires_execution !== 'undefined') {
      lines.push(`**Requires execution:** ${String(parsed.requires_execution)}`);
    }
    if (parsed.execution_reason) lines.push(`**Execution reason:** ${parsed.execution_reason}`);
    const steps = Array.isArray(parsed.steps) ? parsed.steps : [];
    if (steps.length) {
      lines.push('');
      lines.push('### Plan');
      steps.forEach((step, idx) => {
        if (typeof step === 'string') {
          lines.push(`${idx + 1}. ${step}`);
          return;
        }
        if (!step || typeof step !== 'object') return;
        const instruction = String(step.instruction || step.name || `Step ${idx + 1}`);
        const goal = String(step.goal || '').trim();
        lines.push(`${idx + 1}. ${instruction}`);
        if (goal) lines.push(`   - Goal: ${goal}`);
      });
    }
    return lines.join('\n');
  } catch {
    return raw;
  }
};
const contextTokenMax = (ctx) => {
  const raw = Number(ctx?.tokenBudget ?? 50000);
  if (!Number.isFinite(raw) || raw <= 0) return 50000;
  return raw;
};
const contextProgressPercent = (ctx) => {
  const raw = Number(ctx?.tokenEstimate ?? 0);
  if (!Number.isFinite(raw) || raw <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((raw / contextTokenMax(ctx)) * 100)));
};
const contextRingStyle = (ctx) => {
  const pct = contextProgressPercent(ctx);
  const color = ctx?.summarizationTriggered ? '#ef4444' : '#0f172a';
  return {
    background: `conic-gradient(${color} ${pct}%, #dbe3ef ${pct}% 100%)`,
  };
};

const props = defineProps({ alertId: String });
defineEmits(['close']);

const {
  messages,
  inputMessage,
  isLoading,
  historyLoading,
  hasMoreHistory,
  sessionId,
  messagesContainer,
  inputRef,
  panelWidth,
  composerRef,
  artifacts,
  artifactsLoading,
  showArtifactsMenu,
  showDeleteDialog,
  deleteDialogMessage,
  deleteDialogTitle,
  deleteDialogShowButtons,
  isDeleting,
  contextDebug,
  clearChat,
  showDeleteConfirmation,
  cancelDelete,
  confirmDelete,
  toggleArtifactsMenu,
  downloadArtifact,
  handleComposerKeydown,
  loadMoreHistory,
  sendMessage,
  stopGeneration,
  startResize,
} = useAgentChat(toRef(props, 'alertId'));
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
      <div v-if="hasMoreHistory || historyLoading" class="history-more-wrap">
        <button class="history-more-btn" @click="loadMoreHistory" :disabled="historyLoading">
          {{ historyLoading ? 'Loading...' : 'Load older messages' }}
        </button>
      </div>

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
          <div v-if="messagePlannerSegment(msg)?.content" class="ephemeral-wrap">
            <details
              class="ephemeral-group plan-group"
              :open="!msg.planCollapsed"
              @toggle="setPlanCollapsed(msg, !$event.target.open)"
            >
              <summary class="ephemeral-summary">
                Plan
              </summary>
              <div class="ephemeral-body plan-body">
                <div
                  class="text markdown-content"
                  v-html="renderMarkdown(renderPlanMarkdown(messagePlannerSegment(msg)?.content || ''))"
                ></div>
              </div>
            </details>
          </div>

          <div v-if="messageToolSegments(msg).length" class="tools-container">
            <div
              v-for="(segment, segIndex) in messageToolSegments(msg)"
              :key="`tool-${index}-${segIndex}`"
            >
              <details class="tool-trace" :open="segment.tool.status === 'error'">
                <summary class="tool-summary">
                  <span class="tool-main">
                    <span class="status-dot" :class="segment.tool.status"></span>
                    <span class="tool-name">{{ formatToolLabel(segment.tool.name) }}</span>
                  </span>
                  <span class="tool-meta">
                    <span class="tool-status">{{ segment.tool.status }}</span>
                    <span v-if="formatDuration(segment.tool.durationMs)" class="tool-duration">
                      {{ formatDuration(segment.tool.durationMs) }}
                    </span>
                  </span>
                </summary>
                <div class="tool-body">
                  <div v-if="segment.tool.commentary" class="tool-section">
                    <div class="tool-section-title">Action</div>
                    <div class="tool-commentary">{{ segment.tool.commentary }}</div>
                  </div>

                  <div v-if="isCodeTool(segment.tool.name) && toolCode(segment.tool)" class="tool-section">
                    <div class="tool-code-header">
                      <div class="tool-section-title">{{ codeLabel(segment.tool) }}</div>
                      <button class="copy-code-btn" @click="copyToolCode(segment.tool)">Copy</button>
                    </div>
                    <pre class="tool-code" v-html="highlightCode(segment.tool)"></pre>
                  </div>

                  <div v-if="segment.tool.errorCode || segment.tool.errorMessage" class="tool-section tool-error">
                    <div class="tool-section-title">Error</div>
                    <div v-if="segment.tool.errorCode" class="tool-error-line">Code: {{ segment.tool.errorCode }}</div>
                    <div v-if="segment.tool.errorMessage" class="tool-error-line">Message: {{ segment.tool.errorMessage }}</div>
                  </div>
                </div>
              </details>
            </div>
          </div>

          <div
            v-if="msg.isFormattingFinal && !messageVisibleSegments(msg).length"
            class="formatting-hint"
          >
            Formatting final output...
          </div>

          <div v-for="(segment, segIndex) in messageVisibleSegments(msg)" :key="`seg-${index}-${segIndex}`">
            <div
              v-if="segment.type === 'text' && segment.content"
              :key="`md-${index}-${segIndex}-${segment.content.length}`"
              class="text markdown-content"
              v-html="renderMarkdown(segment.content)"
            ></div>
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

        <div class="composer-right-tools">
          <div class="context-ring-wrap" :title="`Context memory: ${contextDebug.active ? 'active' : 'inactive'}\nTokens: ${(contextDebug.tokenEstimate ?? 'null')} / ${(contextDebug.tokenBudget ?? 'null')}\nTriggered: ${contextDebug.summarizationTriggered ? 'yes' : 'no'}`">
            <div class="context-ring" :style="contextRingStyle(contextDebug)">
              <div class="context-ring-inner">{{ contextProgressPercent(contextDebug) }}%</div>
            </div>
          </div>
          <button v-if="!isLoading" @click="sendMessage" class="send-circle-btn" :disabled="!inputMessage.trim()" title="Send">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
              <line x1="12" y1="19" x2="12" y2="5"/>
              <polyline points="5 12 12 5 19 12"/>
            </svg>
          </button>
          <button v-else @click="stopGeneration" class="send-circle-btn stop-btn" title="Stop">
            <span class="stop-icon"></span>
          </button>
        </div>
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

.history-more-wrap {
  display: flex;
  justify-content: center;
}

.history-more-btn {
  border: 1px solid var(--color-border);
  background: var(--color-surface-hover);
  color: var(--color-text-muted);
  border-radius: 9999px;
  padding: 6px 12px;
  font-size: 12px;
  cursor: pointer;
}

.history-more-btn:hover:enabled {
  background: #e7f0ff;
}

.history-more-btn:disabled {
  cursor: not-allowed;
  opacity: 0.75;
}

.message {
  max-width: 85%;
  padding: var(--spacing-3);
  border-radius: 8px;
  font-size: var(--font-size-sm);
  line-height: 1.4;
  overflow-wrap: anywhere;
  word-break: break-word;
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
.markdown-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0.75em 0;
  font-size: 0.92em;
}
.markdown-content :deep(th),
.markdown-content :deep(td) {
  border: 1px solid var(--color-border);
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
}
.markdown-content :deep(thead th) {
  background: var(--color-surface-hover);
  font-weight: 700;
}
.markdown-content :deep(tbody tr:nth-child(even)) {
  background: rgba(2, 6, 23, 0.02);
}

.tools-container {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ephemeral-wrap {
  margin-top: 8px;
}

.ephemeral-group {
  border: 1px dashed rgba(15, 23, 42, 0.25);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.03);
}

.ephemeral-summary {
  cursor: pointer;
  list-style: none;
  font-size: 11px;
  color: var(--color-text-subtle);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 7px 10px;
}

.ephemeral-summary::-webkit-details-marker {
  display: none;
}

.ephemeral-body {
  border-top: 1px dashed rgba(15, 23, 42, 0.2);
  padding: 8px;
  display: grid;
  gap: 8px;
}

.plan-group {
  border-color: rgba(15, 23, 42, 0.32);
}

.plan-body {
  background: rgba(15, 23, 42, 0.02);
  border-radius: 6px;
}

.tool-trace {
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.02);
  overflow: hidden;
  min-width: 0;
}

.tool-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  padding: 6px 8px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.tool-main {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tool-meta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.tool-name {
  font-weight: 600;
  color: var(--color-text-main);
  text-transform: capitalize;
}

.tool-status {
  text-transform: uppercase;
  font-size: 10px;
  letter-spacing: 0.03em;
}

.tool-duration {
  font-size: 10px;
  color: var(--color-text-subtle);
}

.tool-body {
  border-top: 1px solid var(--color-border);
  padding: 8px;
  display: grid;
  gap: 8px;
  min-width: 0;
}

.context-ring-wrap {
  margin-left: 8px;
  display: flex;
  align-items: center;
}

.context-ring {
  width: 32px;
  height: 32px;
  border-radius: 999px;
  padding: 2px;
  display: grid;
  place-items: center;
}

.context-ring-inner {
  width: 100%;
  height: 100%;
  border-radius: 999px;
  background: #fff;
  border: 1px solid var(--color-border);
  font-size: 9px;
  color: var(--color-text-subtle);
  display: grid;
  place-items: center;
  font-weight: 700;
}

.formatting-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-subtle);
  border: 1px dashed rgba(15, 23, 42, 0.2);
  border-radius: 8px;
  padding: 8px 10px;
  background: rgba(15, 23, 42, 0.03);
}

.tool-section-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-subtle);
  margin-bottom: 4px;
}

.tool-commentary {
  font-size: 12px;
  color: var(--color-text-main);
  line-height: 1.4;
}

.tool-pre {
  margin: 0;
  max-width: 100%;
  max-height: 180px;
  overflow-x: hidden;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
  padding: 8px;
  border-radius: 4px;
  border: 1px solid var(--color-border);
  background: #0f172a;
  color: #e2e8f0;
  font-size: 11px;
  line-height: 1.4;
  font-family: 'SF Mono', Monaco, Consolas, monospace;
}

.tool-code-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.copy-code-btn {
  border: 1px solid var(--color-border);
  background: #0b1220;
  color: #cbd5e1;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}

.copy-code-btn:hover {
  background: #111b30;
}

.tool-code {
  margin: 0;
  max-width: 100%;
  max-height: 220px;
  overflow-x: auto;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word; /* Ensure long identifiers wrap */
  padding: 10px;
  border-radius: 6px;
  border: 1px solid #1f2a44;
  background: linear-gradient(180deg, #0d1526 0%, #0b1220 100%);
  color: #e2e8f0;
  font-size: 11px;
  line-height: 1.45;
  font-family: 'SF Mono', Monaco, Consolas, monospace;
}

.tool-code :deep(.tok.kw) {
  color: #7dd3fc;
  font-weight: 600;
}

.tool-code :deep(.tok.str) {
  color: #86efac;
}

.tool-code :deep(.tok.num) {
  color: #fbbf24;
}

.tool-code :deep(.tok.cmt) {
  color: #94a3b8;
  font-style: italic;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #ccc;
}

.status-dot.running { background: #3498db; animation: pulse 1s infinite; }
.status-dot.done { background: #2ecc71; }
.status-dot.error { background: #ef4444; }

.tool-error {
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 4px;
  padding: 8px;
  background: rgba(239, 68, 68, 0.08);
}

.tool-error-line {
  font-size: 12px;
  color: #991b1b;
  overflow-wrap: anywhere;
  word-break: break-word;
}

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

.composer-right-tools {
  display: inline-flex;
  align-items: center;
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
  width: 10px;
  height: 10px;
  border-radius: 2px;
  background: currentColor;
  display: inline-block;
}
</style>
