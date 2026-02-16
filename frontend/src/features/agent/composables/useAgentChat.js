import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue';
import {
  buildArtifactDownloadUrl,
  deleteChatHistory,
  getAgentChatUrl,
  getAlertDetail,
  getChatHistory,
  listArtifacts,
  uploadChartSnapshot,
} from '../../../api/service.js';
import { API_BASE_URL } from '../../../api/index.js';

export function useAgentChat(alertIdRef) {
  const HISTORY_PAGE_SIZE = 10;
  const messages = ref([]);
  const inputMessage = ref('');
  const isLoading = ref(false);
  const historyLoading = ref(false);
  const hasMoreHistory = ref(false);
  const historyOffset = ref(0);
  const isPrependingHistory = ref(false);
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

  const showDeleteDialog = ref(false);
  const deleteDialogMessage = ref('This will permanently delete your conversation history from the server.');
  const deleteDialogTitle = ref('Delete Conversation History');
  const deleteDialogShowButtons = ref(true);
  const isDeleting = ref(false);
  const contextDebug = ref({
    active: false,
    tokenEstimate: null,
    tokenBudget: 50000,
    summaryVersion: null,
    summarizationTriggered: false,
  });

  let abortController = null;
  let toolSeq = 0;

  const ensureTextSegment = (msg) => {
    if (!msg.segments) msg.segments = [];
    const last = msg.segments[msg.segments.length - 1];
    if (!last || last.type !== 'text') {
      msg.segments.push({ type: 'text', content: '' });
    }
    return msg.segments[msg.segments.length - 1];
  };

  const ensurePlannerSegment = (msg) => {
    if (!msg.segments) msg.segments = [];
    const existingIndex = msg.segments.findIndex((seg) => seg.type === 'planner');
    if (existingIndex >= 0) return msg.segments[existingIndex];
    const plannerSegment = { type: 'planner', content: '' };
    msg.segments.push(plannerSegment);
    return plannerSegment;
  };

  const hasEphemeralSegments = (msg) => (
    Boolean(msg?.segments?.some((seg) => ['planner', 'draft', 'tool'].includes(seg.type)))
  );

  const hasFinalText = (msg) => (
    Boolean(msg?.segments?.some((seg) => seg.type === 'text' && String(seg.content || '').trim()))
  );

  const autoCollapseEphemeralIfFinalReady = (msg) => {
    if (!msg) return;
    if (!hasEphemeralSegments(msg)) return;
    if (!hasFinalText(msg)) return;
    msg.planCollapsed = true;
  };

  const generateGreeting = (info) => {
    if (!info) return 'Hello! I am your Trade Surveillance Assistant. How can I help you investigate this alert?';
    return `Hello! I'm your Trade Surveillance Assistant. I can see you're investigating:\n\n` +
      `**Alert ${info.id}** - ${info.ticker} (${info.instrument_name})\n` +
      `- **Type:** ${info.trade_type}\n` +
      `- **Period:** ${info.start_date} to ${info.end_date}\n\n` +
      `How can I help you analyze this alert?`;
  };

  const absolutizeBackendLinks = (content) => {
    if (!content || typeof content !== 'string') return content;
    return content
      .replace(/\]\(\/reports\/([^)]+)\)/g, `](${API_BASE_URL}/reports/$1)`)
      .replace(/\]\(\/artifacts\/([^)]+)\)/g, `](${API_BASE_URL}/artifacts/$1)`);
  };

  const scrollToBottom = async () => {
    await nextTick();
    await new Promise((resolve) => requestAnimationFrame(() => resolve()));
    const el = messagesContainer.value;
    if (!el) return;
    el.scrollTop = el.scrollHeight + 1000;
  };

  const fetchArtifacts = async () => {
    if (!sessionId.value) {
      artifacts.value = [];
      return;
    }
    artifactsLoading.value = true;
    try {
      const data = await listArtifacts(sessionId.value);
      artifacts.value = data.artifacts || [];
    } catch (e) {
      console.error('Failed to fetch artifacts:', e);
      artifacts.value = [];
    } finally {
      artifactsLoading.value = false;
    }
  };

  const mapFrontendMessages = (rawMessages) => (
    rawMessages.map((msg) => {
      if (msg.role === 'agent') {
        return {
          ...msg,
          segments: msg.content ? [{ type: 'text', content: msg.content }] : [],
          tools: msg.tools || [],
        };
      }
      return msg;
    })
  );

  const fetchChatHistory = async (sid, { appendOlder = false } = {}) => {
    if (!sid || historyLoading.value) return;
    if (appendOlder && !hasMoreHistory.value) return;
    historyLoading.value = true;
    isPrependingHistory.value = appendOlder;
    try {
      const requestOffset = appendOlder ? historyOffset.value : 0;
      const data = await getChatHistory(sid, {
        limit: HISTORY_PAGE_SIZE,
        offset: requestOffset,
      });
      const pageMessages = mapFrontendMessages(data.messages || []);
      const pagination = data.pagination || {};
      hasMoreHistory.value = Boolean(pagination.has_more);
      historyOffset.value = typeof pagination.next_offset === 'number'
        ? pagination.next_offset
        : requestOffset + pageMessages.length;

      if (appendOlder) {
        messages.value = [...pageMessages, ...messages.value];
      } else {
        messages.value = pageMessages;
      }
    } catch (e) {
      console.error('Failed to fetch chat history:', e);
      if (!appendOlder) messages.value = [];
      hasMoreHistory.value = false;
    } finally {
      historyLoading.value = false;
      isPrependingHistory.value = false;
    }
    if (!appendOlder) await scrollToBottom();
  };

  const loadMoreHistory = async () => {
    await fetchChatHistory(sessionId.value, { appendOlder: true });
  };

  const initializeSession = async (alertId) => {
    if (!alertId) return;

    try {
      const newAlertInfo = await getAlertDetail(alertId);

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
        hasMoreHistory.value = false;
        historyOffset.value = 0;
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
    hasMoreHistory.value = false;
    historyOffset.value = 0;
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
      const data = await deleteChatHistory(sessionId.value);
      if (data.status === 'error') throw new Error(data.message || 'Unknown error');

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
    const url = buildArtifactDownloadUrl(sessionId.value, artifact.relative_path);
    const link = document.createElement('a');
    link.href = url;
    link.download = artifact.name || 'artifact';
    link.rel = 'noopener noreferrer';
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
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
    if (!alertIdRef.value || !sessionId.value) return;
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
      await uploadChartSnapshot({
        session_id: sessionId.value,
        alert_id: alertIdRef.value,
        image_data_url: imageDataUrl,
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
    messages.value.push({
      role: 'agent',
      content: '',
      tools: [],
      segments: [],
      planCollapsed: false,
      isFormattingFinal: false,
    });
    contextDebug.value = {
      active: false,
      tokenEstimate: null,
      tokenBudget: 50000,
      summaryVersion: null,
      summarizationTriggered: false,
    };

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
          buy_qt: alertInfo.value.buy_qt ?? alertInfo.value.buy_quantity ?? alertInfo.value.buyQty ?? 0,
          sell_qt: alertInfo.value.sell_qt ?? alertInfo.value.sell_quantity ?? alertInfo.value.sellQty ?? 0,
        }
        : null;

      const response = await fetch(getAgentChatUrl(), {
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

      console.log('Starting stream read loop');
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          console.log('Stream done');
          break;
        }

        const text = decoder.decode(value, { stream: true });
        console.log('Received chunk:', text.length, 'chars');
        buffer += text;
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        console.log('Processing lines:', lines.length, 'Buffer remainder:', buffer.length);

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));
            console.log('Parsed data type:', data.type);

            if (data.type === 'token') {
              const node = String(data.node || '').trim();
              const msg = messages.value[agentMsgIndex];
              const tokenContent = String(data.content || '');
              if (node === 'planner') {
                const segment = ensurePlannerSegment(msg);
                segment.content += tokenContent;
              } else if (node === 'respond' || node === 'answer_rewriter') {
                msg.isFormattingFinal = true;
                const segment = ensureTextSegment(msg);
                segment.content += tokenContent;
                msg.content += tokenContent;
              } else if (node === 'answer_validator') {
                // hidden unless debug stream enabled at backend
              } else {
                const segment = ensureTextSegment(msg);
                segment.content += tokenContent;
                msg.content += tokenContent;
              }
            } else if (data.type === 'tool_start') {
              toolSeq += 1;
              const toolRun = {
                id: `${data.tool}-${toolSeq}`,
                name: data.tool,
                status: 'running',
                commentary: data.commentary || null,
                input: data.input || null,
                output: null,
                durationMs: null,
                startedAt: Date.now(),
              };
              const msg = messages.value[agentMsgIndex];
              msg.tools.push(toolRun);
              if (!msg.segments) msg.segments = [];
              msg.segments.push({ type: 'tool', tool: toolRun });
            } else if (data.type === 'tool_end') {
              const tool = messages.value[agentMsgIndex].tools.find(
                (t) => t.name === data.tool && t.status === 'running'
              );
              if (tool) {
                tool.status = data.ok === false ? 'error' : 'done';
                tool.output = data.output || null;
                tool.durationMs = data.duration_ms ?? (Date.now() - (tool.startedAt || Date.now()));
                tool.errorCode = data.error_code || null;
                tool.errorMessage = data.error_message || null;
              }
            } else if (data.type === 'artifact_created') {
              const relativePath = data.relative_path || data.artifact_name;
              const reportUrl = relativePath && sessionId.value
                ? buildArtifactDownloadUrl(sessionId.value, relativePath)
                : null;
              const reportLine = reportUrl
                ? `\n\nReport generated. [Download report](${reportUrl}) or use the Artifact button below the chat box.`
                : '\n\nReport generated. Use the Artifact button below the chat box to download it.';
              const msg = messages.value[agentMsgIndex];
              const segment = ensureTextSegment(msg);
              segment.content += reportLine;
              msg.content += reportLine;
              showArtifactsMenu.value = true;
              await fetchArtifacts();
            } else if (data.type === 'context_debug') {
              contextDebug.value = {
                active: Boolean(data.active),
                tokenEstimate: Number.isInteger(data.token_estimate)
                  ? data.token_estimate
                  : null,
                tokenBudget: Number.isInteger(data.token_budget) && data.token_budget > 0
                  ? data.token_budget
                  : 50000,
                summaryVersion: Number.isInteger(data.summary_version)
                  ? data.summary_version
                  : null,
                summarizationTriggered: Boolean(data.summarization_triggered),
              };
            } else if (data.type === 'draft_update') {
              const msg = messages.value[agentMsgIndex];
              const node = String(data.node || '');
              if (node === 'respond' || node === 'answer_rewriter') {
                msg.isFormattingFinal = true;
              }
            } else if (data.type === 'done') {
              const msg = messages.value[agentMsgIndex];
              msg.isFormattingFinal = false;
              autoCollapseEphemeralIfFinalReady(msg);
            }

            await scrollToBottom();
            // Force UI update
            await nextTick();
          } catch (e) {
            console.error('JSON parse error:', e, 'Line:', line);
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
      messages.value[agentMsgIndex].content = absolutizeBackendLinks(
        messages.value[agentMsgIndex].content
      );
      autoCollapseEphemeralIfFinalReady(messages.value[agentMsgIndex]);
      messages.value[agentMsgIndex].isFormattingFinal = false;
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
    await initializeSession(alertIdRef.value);
    document.addEventListener('click', handleClickOutsideComposer);
  });

  onBeforeUnmount(() => {
    document.removeEventListener('click', handleClickOutsideComposer);
  });

  watch(alertIdRef, async (newId) => {
    if (newId) await initializeSession(newId);
  });

  watch(
    [messages, isLoading],
    () => {
      if (isPrependingHistory.value) return;
      void scrollToBottom();
    },
    { deep: true, flush: 'post' }
  );

  return {
    messages,
    inputMessage,
    isLoading,
    historyLoading,
    hasMoreHistory,
    sessionId,
    messagesContainer,
    inputRef,
    alertInfo,
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
    renderError: null,
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
    autoCollapseEphemeralIfFinalReady,
  };
}
