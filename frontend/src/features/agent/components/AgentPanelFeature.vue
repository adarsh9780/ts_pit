<script setup>
import { toRef } from 'vue';
import { marked } from 'marked';
import markedKatex from 'marked-katex-extension';
import 'katex/dist/katex.min.css';
import ConfirmDialog from '../../../components/ConfirmDialog.vue';
import { useAgentChat } from '../composables/useAgentChat.js';
import { useToast } from '../../../composables/useToast.js';

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

const escapeHtml = (value) => String(value || '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;');

const MAX_MARKDOWN_CACHE_ENTRIES = 200;
const markdownCache = new Map();
const renderMarkdown = (content) => {
  const raw = String(content || '');
  if (!raw) return '';

  const cached = markdownCache.get(raw);
  if (cached) return cached;

  const html = marked.parse(normalizeLatexDelimiters(raw));
  markdownCache.set(raw, html);
  if (markdownCache.size > MAX_MARKDOWN_CACHE_ENTRIES) {
    const oldestKey = markdownCache.keys().next().value;
    if (oldestKey) markdownCache.delete(oldestKey);
  }
  return html;
};
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
  const normalizeInputObject = (value) => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return value;
    if (value.kwargs && typeof value.kwargs === 'object' && !Array.isArray(value.kwargs)) {
      return value.kwargs;
    }
    if (value.input && typeof value.input === 'object' && !Array.isArray(value.input)) {
      return value.input;
    }
    if (value.payload && typeof value.payload === 'object' && !Array.isArray(value.payload)) {
      return value.payload;
    }
    if (value.args && typeof value.args === 'object' && !Array.isArray(value.args)) {
      return value.args;
    }
    return value;
  };
  try {
    const parsed = JSON.parse(tool.input);
    if (parsed && typeof parsed === 'object') return normalizeInputObject(parsed);
    if (typeof parsed === 'string') {
      try {
        const parsedAgain = JSON.parse(parsed);
        if (parsedAgain && typeof parsedAgain === 'object') return normalizeInputObject(parsedAgain);
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
  if (!input || typeof input !== 'object') return '';
  if (tool?.name === 'execute_sql') {
    return String(input.query || input.sql || input.statement || '');
  }
  if (tool?.name === 'execute_python') {
    return String(
      input.code
      || input.python_code
      || input.script
      || input.program
      || input.source
      || ''
    );
  }
  return '';
};
const codeLabel = (tool) => (tool?.name === 'execute_sql' ? 'SQL Code' : 'Python Code');
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
    notify('Code copied to clipboard.', { level: 'success' });
  } catch {
    notify('Unable to copy code. Please try again.', { level: 'error' });
  }
};
const copyMessageText = async (msg) => {
  const text = String(msg?.content || '').trim();
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    notify('Message copied to clipboard.', { level: 'success' });
  } catch {
    notify('Unable to copy message. Please try again.', { level: 'error' });
  }
};
const onPlaceholderFeedback = (kind) => {
  console.log('Feedback placeholder clicked:', kind);
  if (kind === 'thumbs_up') {
    notify('Feedback recorded: thumbs up (placeholder).');
    return;
  }
  if (kind === 'thumbs_down') {
    notify('Feedback recorded: thumbs down (placeholder).');
    return;
  }
  if (kind === 'save_feedback') {
    notify('Save feedback action is a placeholder for now.');
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
const parsePlannerContent = (rawContent) => {
  const raw = String(rawContent || '').trim();
  if (!raw) return { planAction: null, requiresExecution: null, markdown: '' };
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return { planAction: null, requiresExecution: null, markdown: raw };
    const lines = [];
    const steps = Array.isArray(parsed.steps) ? parsed.steps : [];
    if (steps.length) {
      steps.forEach((step, idx) => {
        if (typeof step === 'string') {
          lines.push(`${idx + 1}. ${step}`);
          return;
        }
        if (!step || typeof step !== 'object') return;
        const instruction = String(step.instruction || step.name || `Step ${idx + 1}`);
        const goal = String(step.goal || '').trim();
        const success = String(step.success_criteria || '').trim();
        const constraints = Array.isArray(step.constraints)
          ? step.constraints.filter((c) => String(c || '').trim()).map((c) => String(c).trim())
          : [];
        lines.push(`${idx + 1}. ${instruction}`);
        if (goal) lines.push(`   - Goal: ${goal}`);
        if (success) lines.push(`   - Success: ${success}`);
        if (constraints.length) lines.push(`   - Constraints: ${constraints.join('; ')}`);
      });
    } else {
      lines.push('No plan steps available.');
    }
    return {
      planAction: parsed.plan_action ? String(parsed.plan_action) : null,
      requiresExecution:
        typeof parsed.requires_execution === 'undefined'
          ? null
          : String(parsed.requires_execution),
      markdown: lines.join('\n'),
    };
  } catch {
    const actionMatch = raw.match(/^\s*Plan action:\s*(.+)$/im);
    const requiresMatch = raw.match(/^\s*Requires execution:\s*(.+)$/im);
    let markdown = raw
      .replace(/^\s*Plan action:\s*.+$/im, '')
      .replace(/^\s*Requires execution:\s*.+$/im, '')
      .replace(/^\s*Execution reason:\s*.+$/im, '')
      .replace(/^\s*\*\*Plan:\*\*\s*$/im, '')
      .trim();
    if (!markdown) markdown = raw;
    return {
      planAction: actionMatch ? actionMatch[1].trim() : null,
      requiresExecution: requiresMatch ? requiresMatch[1].trim() : null,
      markdown,
    };
  }
};
const plannerPlanAction = (msg) => parsePlannerContent(messagePlannerSegment(msg)?.content || '').planAction;
const plannerRequiresExecution = (msg) => parsePlannerContent(messagePlannerSegment(msg)?.content || '').requiresExecution;
const plannerMarkdown = (msg) => parsePlannerContent(messagePlannerSegment(msg)?.content || '').markdown;
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
const { notify } = useToast();

const {
  messages,
  inputMessage,
  isLoading,
  historyLoading,
  hasMoreHistory,
  showLoadMoreHistoryControl,
  sessionId,
  canSend,
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
        <button @click="clearChat" class="header-icon-btn" title="Clear chat (new session)" aria-label="Clear chat">
          <svg class="header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 20H7L3 16l9-13 8 8-5 9"/>
            <path d="M6.5 13.5l5 5"/>
          </svg>
        </button>
        <button @click="showDeleteConfirmation" class="header-icon-btn delete-btn" title="Delete history from server" aria-label="Delete history">
          <svg class="header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14M10 11v6M14 11v6"/>
          </svg>
        </button>
        <button @click="$emit('close')" class="header-icon-btn close-btn" title="Close assistant" aria-label="Close assistant">
          <svg class="header-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        </button>
      </div>
    </div>
    <div class="messages-area" ref="messagesContainer">
      <div v-if="historyLoading || (hasMoreHistory && showLoadMoreHistoryControl)" class="history-more-wrap">
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

        <template v-else-if="msg.role === 'user'">
        <div class="user-inline-row">
          <div class="message-actions inline-user">
            <button
              class="message-action-btn icon-btn"
              :disabled="!String(msg.content || '').trim()"
              @click="copyMessageText(msg)"
              title="Copy message"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
              </svg>
            </button>
          </div>
          <div class="user-bubble">
            <div
              class="text markdown-content"
              v-html="renderMarkdown(msg.content)"
            ></div>
          </div>
        </div>
        </template>

        <template v-else>
        <div class="message-content">
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
                <div class="plan-tags">
                  <span v-if="plannerPlanAction(msg)" class="plan-tag">
                    Plan action: {{ plannerPlanAction(msg) }}
                  </span>
                  <span v-if="plannerRequiresExecution(msg)" class="plan-tag">
                    Requires execution: {{ plannerRequiresExecution(msg) }}
                  </span>
                </div>
                <div
                  class="text markdown-content"
                  v-html="renderMarkdown(plannerMarkdown(msg))"
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

          <div
            v-if="messageVisibleSegments(msg).length && (messagePlannerSegment(msg)?.content || messageToolSegments(msg).length)"
            class="answer-divider"
          >
            <span>Final answer</span>
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
        <div
          v-if="msg.role === 'agent'"
          :class="[
            'message-actions-outside',
            msg.role,
            {
              'has-aux-sections':
                Boolean(messagePlannerSegment(msg)?.content) ||
                messageToolSegments(msg).length > 0 ||
                msg.isFormattingFinal,
            },
          ]"
        >
          <div class="message-actions">
            <button
              class="message-action-btn icon-btn"
              :disabled="!String(msg.content || '').trim()"
              @click="copyMessageText(msg)"
              title="Copy message"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
              </svg>
            </button>
            <template v-if="msg.role === 'agent'">
              <button
                class="message-action-btn icon-btn"
                @click="onPlaceholderFeedback('thumbs_up')"
                title="Thumbs up (coming soon)"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.3a2 2 0 0 0 2-1.7l1.4-9A2 2 0 0 0 19.7 9H14z"/>
                  <path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
                </svg>
              </button>
              <button
                class="message-action-btn icon-btn"
                @click="onPlaceholderFeedback('thumbs_down')"
                title="Thumbs down (coming soon)"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.7a2 2 0 0 0-2 1.7l-1.4 9A2 2 0 0 0 4.3 15H10z"/>
                  <path d="M17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
                </svg>
              </button>
              <button
                class="message-action-btn"
                @click="onPlaceholderFeedback('save_feedback')"
                title="Save feedback (coming soon)"
              >
                Save feedback
              </button>
            </template>
          </div>
        </div>
        </template>
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
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
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
          <button v-if="!isLoading" @click="sendMessage" class="send-circle-btn" :disabled="!canSend || !inputMessage.trim()" :title="canSend ? 'Send' : 'Sending disabled'">
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
  left: -6px;
  top: 0;
  bottom: 0;
  width: 14px;
  cursor: ew-resize;
  z-index: 40;
  display: flex;
  align-items: center;
  justify-content: center;
  touch-action: none;
}

.handle-line {
  width: 2px;
  height: 72px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.22);
  transition: background-color 0.15s ease, opacity 0.15s ease;
  opacity: 0.7;
}

.resize-handle:hover,
.resize-handle:active {
  background: rgba(59, 130, 246, 0.08);
}

.resize-handle:hover .handle-line,
.resize-handle:active .handle-line {
  background: rgba(59, 130, 246, 0.9);
  opacity: 1;
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
  gap: 8px;
}

.header-icon-btn {
  border: none;
  background: none;
  cursor: pointer;
  width: 34px;
  height: 34px;
  padding: 0;
  border-radius: 8px;
  color: #94a3b8;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.2s ease, color 0.2s ease;
}

.header-icon-btn:hover {
  background: var(--color-surface-hover);
  color: #7b8ca3;
}

.header-icon {
  width: 20px;
  height: 20px;
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
  align-self: stretch;
  max-width: 100%;
  background: transparent;
  border: none;
  padding: 0;
  margin: 4px 8px;
}

.message.agent {
  align-self: stretch;
  max-width: 100%;
  background: #ffffff;
  color: var(--color-text-main);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  margin: 4px 8px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.user-inline-row {
  width: 100%;
  display: flex;
  justify-content: flex-end;
  align-items: flex-end;
  gap: 6px;
}

.user-bubble {
  background: #eaf1fb;
  color: var(--color-text-main);
  border: 1px solid #d6e2f3;
  border-radius: 10px;
  border-bottom-right-radius: 2px;
  padding: var(--spacing-3);
  max-width: 82%;
}

.message-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.message-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 6px;
  background: transparent;
}

.message-actions-outside {
  display: flex;
  width: 100%;
  margin-top: 8px;
}

.message-actions-outside.user {
  justify-content: flex-end;
  padding-right: 6px;
}

.message-actions-outside.agent {
  justify-content: flex-end;
  padding-right: 10px;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s ease;
}

.message-actions-outside.agent.has-aux-sections {
  margin-top: 12px;
}

.message-actions.inline-user {
  justify-content: flex-start;
  margin-bottom: 2px;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.message.user:hover .message-actions.inline-user,
.message.user:focus-within .message-actions.inline-user {
  opacity: 1;
}

.message.agent:hover .message-actions-outside.agent,
.message.agent:focus-within .message-actions-outside.agent {
  opacity: 1;
  pointer-events: auto;
}

.message-action-btn {
  border: 1px solid #cfd8e6;
  background: transparent;
  color: #64748b;
  border-radius: 6px;
  font-size: 11px;
  line-height: 1;
  padding: 4px 8px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.message-action-btn:hover:enabled {
  background: rgba(15, 23, 42, 0.05);
  color: var(--color-text-main);
}

.message-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.message-action-btn.icon-btn {
  width: 26px;
  height: 22px;
  padding: 0;
  border: none;
  background: transparent;
}

.message-action-btn.icon-btn:hover:enabled {
  background: rgba(15, 23, 42, 0.06);
  border-radius: 6px;
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
  font-family: var(--font-family-ui);
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
  border-color: #c7d3e3;
  background: #f7fafc;
}

.plan-body {
  background: #f3f6fb;
  border-radius: 6px;
  padding: 12px 12px 10px;
  border-left: 3px solid #b8c9e0;
}

.plan-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.plan-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid #c7d3e3;
  background: #ffffff;
  color: #475569;
  font-size: 11px;
  font-weight: 600;
}

.plan-body .markdown-content {
  font-size: 13px;
  color: #334155;
}

.plan-body .markdown-content :deep(p:first-child),
.plan-body .markdown-content :deep(ol:first-child),
.plan-body .markdown-content :deep(ul:first-child),
.plan-body .markdown-content :deep(h1:first-child),
.plan-body .markdown-content :deep(h2:first-child),
.plan-body .markdown-content :deep(h3:first-child) {
  margin-top: 0;
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
  width: 34px;
  height: 34px;
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

.answer-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
  margin-bottom: 2px;
  color: #64748b;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.answer-divider::before,
.answer-divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: #d3dde9;
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
  font-family: var(--font-family-ui);
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
  font-family: var(--font-family-ui);
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
  width: 34px;
  height: 34px;
  padding: 0;
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
