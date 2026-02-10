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

  const showDeleteDialog = ref(false);
  const deleteDialogMessage = ref('This will permanently delete your conversation history from the server.');
  const deleteDialogTitle = ref('Delete Conversation History');
  const deleteDialogShowButtons = ref(true);
  const isDeleting = ref(false);

  let abortController = null;
  let toolSeq = 0;

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

  const fetchChatHistory = async (sid) => {
    messages.value = [];
    try {
      const data = await getChatHistory(sid);
      if (data.messages?.length) {
        messages.value = data.messages;
      }
    } catch (e) {
      console.error('Failed to fetch chat history:', e);
    }
    await scrollToBottom();
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
              toolSeq += 1;
              messages.value[agentMsgIndex].tools.push({
                id: `${data.tool}-${toolSeq}`,
                name: data.tool,
                status: 'running',
                input: data.input || null,
                output: null,
                durationMs: null,
                startedAt: Date.now(),
              });
            } else if (data.type === 'tool_end') {
              const tool = messages.value[agentMsgIndex].tools.find(
                (t) => t.name === data.tool && t.status === 'running'
              );
              if (tool) {
                tool.status = 'done';
                tool.output = data.output || null;
                tool.durationMs = data.duration_ms ?? (Date.now() - (tool.startedAt || Date.now()));
              }
            } else if (data.type === 'artifact_created') {
              const relativePath = data.relative_path || data.artifact_name;
              const reportUrl = relativePath && sessionId.value
                ? buildArtifactDownloadUrl(sessionId.value, relativePath)
                : null;
              const reportLine = reportUrl
                ? `\n\nReport generated. [Download report](${reportUrl}) or use the Artifact button below the chat box.`
                : '\n\nReport generated. Use the Artifact button below the chat box to download it.';
              messages.value[agentMsgIndex].content += reportLine;
              showArtifactsMenu.value = true;
              await fetchArtifacts();
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
      messages.value[agentMsgIndex].content = absolutizeBackendLinks(
        messages.value[agentMsgIndex].content
      );
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
      void scrollToBottom();
    },
    { deep: true, flush: 'post' }
  );

  return {
    messages,
    inputMessage,
    isLoading,
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
    renderError: null,
    clearChat,
    showDeleteConfirmation,
    cancelDelete,
    confirmDelete,
    toggleArtifactsMenu,
    downloadArtifact,
    handleComposerKeydown,
    sendMessage,
    stopGeneration,
    startResize,
  };
}
