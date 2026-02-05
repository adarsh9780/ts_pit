<script setup>
import { ref, onMounted, watch, nextTick } from 'vue';

const props = defineProps({
  alertId: String
});

const emit = defineEmits(['close']);

// State
const messages = ref([
    { role: 'agent', content: 'Hello! I am your Trade Surveillance Assistant. How can I help you investigate this alert?' }
]);
const inputMessage = ref('');
const isLoading = ref(false);
const showTools = ref(false); // Toggle to show tool usage details
const sessionId = ref('');
const messagesContainer = ref(null);

// Generate Session ID
onMounted(() => {
    let stored = localStorage.getItem('agent_session_id');
    if (!stored) {
        stored = crypto.randomUUID();
        localStorage.setItem('agent_session_id', stored);
    }
    sessionId.value = stored;
});

// Scroll to bottom
const scrollToBottom = async () => {
    await nextTick();
    if (messagesContainer.value) {
        messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight;
    }
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

    try {
        const response = await fetch('http://localhost:8000/agent/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: userMsg,
                session_id: sessionId.value,
                alert_id: props.alertId
            })
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
        messages.value[agentMsgIndex].content += `\n[Error: ${e.message}]`;
    } finally {
        isLoading.value = false;
        scrollToBottom();
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
          <button @click="$emit('close')" class="close-btn">×</button>
      </div>
      
      <div class="messages-area" ref="messagesContainer">
          <div v-for="(msg, index) in messages" :key="index" :class="['message', msg.role]">
              
              <div class="message-content">
                  <div v-if="msg.content" class="text" v-html="msg.content.replace(/\n/g, '<br>')"></div>
                  
                  <!-- Tool Usage Indicators -->
                  <div v-if="msg.tools && msg.tools.length > 0" class="tools-container">
                      <div v-for="tool in msg.tools" :key="tool.name" class="tool-badge">
                          <span class="status-dot" :class="tool.status"></span>
                          {{ tool.name }}
                      </div>
                  </div>
              </div>
          </div>
          
          <div v-if="isLoading && !messages[messages.length-1].content" class="typing-indicator">
              Thinking...
          </div>
      </div>
      
      <div class="input-area">
          <input 
              v-model="inputMessage" 
              @keyup.enter="sendMessage"
              placeholder="Ask about this alert..." 
              :disabled="isLoading"
          />
          <button @click="sendMessage" :disabled="isLoading || !inputMessage">Send</button>
      </div>
  </div>
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
    align-self: flex-start;
    background-color: var(--color-background);
    color: var(--color-text-main);
    border: 1px solid var(--color-border);
    border-bottom-left-radius: 2px;
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
}

.input-area button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.typing-indicator {
    font-size: 0.8rem;
    color: var(--color-text-subtle);
    font-style: italic;
    margin-left: var(--spacing-2);
}
</style>
