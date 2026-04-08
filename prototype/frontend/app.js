/**
 * VinFast AI Chatbot — Frontend Logic
 * Handles: chat UI, chain-of-thought streaming, tool status,
 *          real FastAPI SSE backend, sidebar, theme toggle
 */

'use strict';

/* ============================================================
   1. CONFIGURATION & CONSTANTS
   ============================================================ */
const CONFIG = {
  API_BASE: 'http://localhost:8000',  // Đổi khi deploy
  MAX_CHARS: 2000,
  THREAD_ID: `thread_${Date.now()}`,
  STREAM_SPEED: 18,       // ms per char for streaming effect (local mock only)
  COT_STEP_DELAY: 600,    // ms between chain-of-thought steps (mock mode)
  USE_REAL_API: true,     // false = dùng mock offline, true = gọi FastAPI BE
};

/* ============================================================
   2. DOM REFERENCES
   ============================================================ */
const DOM = {
  // Layout
  sidebar:         document.getElementById('sidebar'),
  mainLayout:      document.getElementById('mainLayout'),
  sidebarToggle:   document.getElementById('sidebarToggle'),
  menuBtn:         document.getElementById('menuBtn'),
  newChatBtn:      document.getElementById('newChatBtn'),

  // Chat
  welcomeScreen:   document.getElementById('welcomeScreen'),
  messageList:     document.getElementById('messageList'),
  chatInput:       document.getElementById('chatInput'),
  sendBtn:         document.getElementById('sendBtn'),
  charCount:       document.getElementById('charCount'),

  // Tools strip
  toolStatusStrip: document.getElementById('toolStatusStrip'),
  toolStatusInner: document.getElementById('toolStatusInner'),

  // COT Panel
  cotPanel:        document.getElementById('cotPanel'),
  cotStream:       document.getElementById('cotStream'),
  cotClose:        document.getElementById('cotClose'),
  cotExpand:       document.getElementById('cotExpand'),
  cotTokenCount:   document.getElementById('cotTokenCount'),
  cotToggleBtn:    document.getElementById('cotToggleBtn'),

  // COT Modal
  cotModal:        document.getElementById('cotModal'),
  cotModalBody:    document.getElementById('cotModalBody'),
  cotModalClose:   document.getElementById('cotModalClose'),
  cotModalBackdrop:document.getElementById('cotModalBackdrop'),

  // Nav
  themeToggle:     document.getElementById('themeToggle'),
  clearBtn:        document.getElementById('clearBtn'),
};

/* ============================================================
   3. STATE
   ============================================================ */
const STATE = {
  isProcessing: false,
  messages: [],
  isCotVisible: false,
  isSidebarOpen: true,
  theme: 'dark',
  fullCotLog: [],         // complete chain-of-thought for modal
  tokenCount: 0,
};

/* ============================================================
   4. COT STEP RENDERER (used by both real SSE + offline mock)
   ============================================================ */



/* ============================================================
   5. UTILITY HELPERS
   ============================================================ */

/** Format current time HH:MM */
function nowTime() {
  return new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
}

/** Sleep helper */
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

/** Auto-resize textarea */
function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
}

/** Scroll chat to bottom */
function scrollToBottom(smooth = true) {
  const ml = DOM.messageList;
  ml.scrollTo({ top: ml.scrollHeight, behavior: smooth ? 'smooth' : 'instant' });
}

/** Escape HTML */
function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/* ============================================================
   6. SIDEBAR CONTROL
   ============================================================ */
function openSidebar() {
  STATE.isSidebarOpen = true;
  DOM.sidebar.classList.remove('collapsed');
  DOM.sidebar.classList.add('mobile-open');
  DOM.menuBtn.setAttribute('aria-expanded', 'true');
  DOM.sidebarToggle.setAttribute('aria-expanded', 'true');
}

function closeSidebar() {
  STATE.isSidebarOpen = false;
  DOM.sidebar.classList.add('collapsed');
  DOM.sidebar.classList.remove('mobile-open');
  DOM.menuBtn.setAttribute('aria-expanded', 'false');
  DOM.sidebarToggle.setAttribute('aria-expanded', 'false');
}

DOM.sidebarToggle.addEventListener('click', closeSidebar);
DOM.menuBtn.addEventListener('click', () => {
  STATE.isSidebarOpen ? closeSidebar() : openSidebar();
});

/* ============================================================
   7. THEME TOGGLE
   ============================================================ */
DOM.themeToggle.addEventListener('click', () => {
  STATE.theme = STATE.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', STATE.theme);
});

/* ============================================================
   8. COT PANEL
   ============================================================ */
function showCotPanel() {
  STATE.isCotVisible = true;
  DOM.cotPanel.classList.add('visible');
  DOM.cotPanel.removeAttribute('aria-hidden');
  DOM.cotToggleBtn.setAttribute('aria-pressed', 'true');
}

function hideCotPanel() {
  STATE.isCotVisible = false;
  DOM.cotPanel.classList.remove('visible');
  DOM.cotPanel.setAttribute('aria-hidden', 'true');
  DOM.cotToggleBtn.setAttribute('aria-pressed', 'false');
}

DOM.cotToggleBtn.addEventListener('click', () => {
  STATE.isCotVisible ? hideCotPanel() : showCotPanel();
});

DOM.cotClose.addEventListener('click', hideCotPanel);

/* COT Expand Modal */
DOM.cotExpand.addEventListener('click', openCotModal);
DOM.cotModalClose.addEventListener('click', closeCotModal);
DOM.cotModalBackdrop.addEventListener('click', closeCotModal);

function openCotModal() {
  DOM.cotModalBody.innerHTML = DOM.cotStream.innerHTML;
  DOM.cotModal.removeAttribute('hidden');
  document.body.style.overflow = 'hidden';
}

function closeCotModal() {
  DOM.cotModal.setAttribute('hidden', '');
  document.body.style.overflow = '';
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !DOM.cotModal.hasAttribute('hidden')) {
    closeCotModal();
  }
});

/* ============================================================
   9. CHAIN OF THOUGHT STREAMING
   ============================================================ */
let cotStepCount = 0;

async function streamCotSteps(steps) {
  DOM.cotStream.innerHTML = '';
  cotStepCount = 0;
  STATE.tokenCount = 0;
  STATE.fullCotLog = [];

  showCotPanel();

  for (const step of steps) {
    await sleep(CONFIG.COT_STEP_DELAY);

    const stepEl = document.createElement('div');
    stepEl.className = `cot-step ${step.type}`;

    const labelMap = {
      thinking:  'SUY LUẬN',
      tool:      'CÔNG CỤ',
      retrieval: 'RAG RETRIEVAL',
      guard:     'GUARDRAILS',
      result:    'KẾT QUẢ',
    };

    stepEl.innerHTML = `
      <div class="cot-step-label">${labelMap[step.type] || step.type.toUpperCase()}</div>
      <div class="cot-step-text">${step.text}</div>
    `;

    DOM.cotStream.appendChild(stepEl);
    DOM.cotStream.scrollTop = DOM.cotStream.scrollHeight;

    STATE.fullCotLog.push(step);
    cotStepCount++;

    // Update token count (mock)
    STATE.tokenCount += Math.floor(Math.random() * 80) + 40;
    DOM.cotTokenCount.textContent = `${STATE.tokenCount} tokens`;
  }
}

/* ============================================================
   10. TOOL STATUS STRIP
   ============================================================ */
async function runToolStatusStrip(tools) {
  DOM.toolStatusStrip.removeAttribute('hidden');
  DOM.toolStatusInner.innerHTML = '';

  // Create all pill elements first as pending
  const pills = tools.map(toolName => {
    const el = document.createElement('div');
    el.className = 'tool-step pending';
    el.innerHTML = `<div class="tool-step-icon"></div>${toolName}`;
    DOM.toolStatusInner.appendChild(el);
    return { el, name: toolName };
  });

  // Animate each to running → complete
  for (const { el, name } of pills) {
    el.className = 'tool-step running';
    el.innerHTML = `<div class="tool-step-icon"></div>${name}`;
    await sleep(CONFIG.COT_STEP_DELAY + 200);
    el.className = 'tool-step complete';
    el.innerHTML = `<div class="tool-step-icon"></div>${name}`;
  }
}

function clearToolStrip() {
  DOM.toolStatusStrip.setAttribute('hidden', '');
  DOM.toolStatusInner.innerHTML = '';
}

/* ============================================================
   11. MESSAGE RENDERING
   ============================================================ */
function renderUserMessage(text) {
  const el = document.createElement('div');
  el.className = 'message user-msg';
  el.innerHTML = `
    <div class="message-avatar" aria-label="Bạn">YOU</div>
    <div class="message-body">
      <div class="message-bubble">${escHtml(text)}</div>
      <div class="message-meta">
        <span class="message-time">${nowTime()}</span>
      </div>
    </div>
  `;
  DOM.messageList.appendChild(el);
  scrollToBottom();
  return el;
}

function renderTypingIndicator() {
  const el = document.createElement('div');
  el.className = 'typing-indicator';
  el.id = 'typingIndicator';
  el.setAttribute('aria-label', 'AI đang xử lý');
  el.innerHTML = `
    <div class="message-avatar" aria-hidden="true">AI</div>
    <div class="typing-bubble" aria-hidden="true" style="display:flex; align-items:center;">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <span class="typing-text" style="margin-left: 12px; font-size: 0.85rem; color: var(--text-muted); opacity: 0.8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px;">Đang suy nghĩ...</span>
    </div>
  `;
  DOM.messageList.appendChild(el);
  scrollToBottom();
  return el;
}

function removeTypingIndicator() {
  const el = document.getElementById('typingIndicator');
  if (el) el.remove();
}

/** Render AI message with streaming text effect */
async function renderAIMessage(responseData) {
  const { answer, confidence, citations, ctas, tools } = responseData;
  const msgId = `msg_${Date.now()}`;

  const el = document.createElement('div');
  el.className = 'message';
  el.id = msgId;

  // Confidence badge HTML
  const confBadge = confidence
    ? `<div class="confidence-badge ${confidence}" role="status" aria-label="Độ tin cậy ${confidence}">
        <svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="12" r="10"/></svg>
        ${{ high: 'ĐỘ TIN CẬY CAO', mid: 'CÓ THỂ CẦN XÁCMINH', low: 'CHUYỂN TƯ VẤN VIÊN' }[confidence]}
       </div>`
    : '';

  // Tool pills HTML (initially all running style)
  const toolPillsHtml = tools
    ? `<div class="tool-pills" aria-label="Công cụ đã sử dụng">${tools.map(t =>
        `<div class="tool-pill done" role="listitem"><div class="tool-pill-dot"></div>${t}</div>`
      ).join('')}</div>`
    : '';

  // Citations HTML
  const citationHtml = citations && citations.length
    ? `<div class="citations" role="complementary" aria-label="Nguồn trích dẫn">
        <div class="citations-label">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
          </svg>
          NGUỒN TRÍCH DẪN
        </div>
        ${citations.map(c =>
          `<a href="${c.url}" class="cite-link" target="_blank" rel="noopener noreferrer" aria-label="Xem nguồn: ${escHtml(c.label)}">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
              <polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
            </svg>
            ${escHtml(c.label)}
          </a>`
        ).join('')}
       </div>`
    : '';

  // CTA buttons
  const ctaHtml = ctas && ctas.length
    ? `<div class="message-ctas" role="group" aria-label="Hành động tiếp theo">${ctas.map(c =>
        `<button class="cta-btn ${c.style === 'secondary' ? 'secondary' : ''}" aria-label="${escHtml(c.label)}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <polyline points="9 18 15 12 9 6"/>
          </svg>
          ${escHtml(c.label)}
        </button>`
      ).join('')}</div>`
    : '';

  el.innerHTML = `
    <div class="message-avatar" aria-label="VinFast AI">AI</div>
    <div class="message-body">
      ${confBadge}
      <div class="message-bubble prose-content" id="${msgId}_bubble">
        <span class="stream-cursor" aria-hidden="true"></span>
      </div>
      ${toolPillsHtml}
      ${citationHtml}
      ${ctaHtml}
      <div class="message-meta">
        <span class="message-time">${nowTime()}</span>
        <div class="message-actions" role="group" aria-label="Hành động với tin nhắn này">
          <button class="msg-action-btn" aria-label="Thích câu trả lời này" title="Thumbs up" onclick="toggleFeedback(this,'liked')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14z"/><path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>
          </button>
          <button class="msg-action-btn" aria-label="Báo cáo sai sót" title="Thumbs down" onclick="toggleFeedback(this,'disliked')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3H10z"/><path d="M17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/></svg>
          </button>
          <button class="msg-action-btn" aria-label="Sao chép câu trả lời" title="Copy" onclick="copyMessage('${msgId}_bubble')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          </button>
          <button class="msg-action-btn" aria-label="Xem suy luận AI" title="View reasoning" onclick="viewCot()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          </button>
        </div>
      </div>
    </div>
  `;

  DOM.messageList.appendChild(el);
  scrollToBottom();

  // Stream text into bubble
  const bubble = document.getElementById(`${msgId}_bubble`);
  const cursor = bubble.querySelector('.stream-cursor');
  await streamText(bubble, cursor, answer);
}

/** Stream text character by character into element */
async function streamText(container, cursor, htmlContent) {
  // Parse to plain text for streaming, then set full HTML at end
  // For visual effect: stream a plain version, then swap to rich HTML
  const tempDiv = document.createElement('div');
  tempDiv.innerHTML = htmlContent;
  const plainText = tempDiv.textContent || '';

  let streamed = '';
  for (let i = 0; i < plainText.length; i++) {
    streamed += plainText[i];
    // Update text node before cursor
    const textNode = document.createTextNode(streamed);
    container.innerHTML = '';
    container.appendChild(textNode);
    container.appendChild(cursor);
    container.parentElement.scrollIntoView({ block: 'end', behavior: 'nearest' });

    // Vary speed for natural feel
    const delay = plainText[i] === ' ' ? CONFIG.STREAM_SPEED * 0.5
                : plainText[i] === '\n' ? CONFIG.STREAM_SPEED * 3
                : CONFIG.STREAM_SPEED;
    await sleep(delay);
  }

  // Swap in rich HTML after streaming
  cursor.remove();
  container.innerHTML = htmlContent;
  scrollToBottom();
}

/* ============================================================
   12. FEEDBACK & ACTIONS
   ============================================================ */
window.toggleFeedback = (btn, type) => {
  const parent = btn.closest('.message-actions');
  parent.querySelectorAll('.msg-action-btn').forEach(b => {
    b.classList.remove('liked', 'disliked');
  });
  btn.classList.toggle(type);
};

window.copyMessage = (id) => {
  const el = document.getElementById(id);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent || '');
  // Brief flash
  el.style.outline = '2px solid #22C55E';
  setTimeout(() => { el.style.outline = ''; }, 800);
};

window.viewCot = () => {
  if (STATE.fullCotLog.length > 0) openCotModal();
  else showCotPanel();
};

/* ============================================================
   13. MAIN SEND LOGIC — Real SSE Backend
   ============================================================ */
async function sendMessage(text) {
  if (!text.trim() || STATE.isProcessing) return;
  if (text.length > CONFIG.MAX_CHARS) return;

  STATE.isProcessing = true;
  DOM.sendBtn.disabled = true;
  DOM.chatInput.disabled = true;

  // Hide welcome screen
  DOM.welcomeScreen.classList.add('hidden');

  // Render user message
  renderUserMessage(text);

  // Clear input
  DOM.chatInput.value = '';
  DOM.charCount.textContent = `0 / ${CONFIG.MAX_CHARS}`;
  autoResize(DOM.chatInput);

  // Prepare COT panel
  DOM.cotStream.innerHTML = '';
  STATE.fullCotLog = [];
  STATE.tokenCount = 0;
  DOM.cotTokenCount.textContent = '0 tokens';
  showCotPanel();

  // Show typing indicator
  renderTypingIndicator();

  // Prepare streaming state
  let finalAnswer = '';
  let toolsUsed    = [];
  let confidence   = 'mid';

  // Create AI message container with empty bubble (will fill via SSE tokens)
  const msgId = `msg_${Date.now()}`;
  let msgEl = null;         // created after typing indicator removed
  let bubble = null;
  let cursor = null;

  try {
    const response = await fetch(`${CONFIG.API_BASE}/chat`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ message: text, thread_id: CONFIG.THREAD_ID }),
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    // ── SSE parsing loop ────────────────────────────────────────
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();            // keep incomplete line

      let eventType = null;
      let eventData = null;

      for (const line of lines) {
        if (line.startsWith('event:')) {
          eventType = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          try { eventData = JSON.parse(line.slice(5).trim()); } catch { eventData = null; }
        } else if (line.trim() === '') {
          // Dispatch event
          if (eventType && eventData) {
            await _handleSSEEvent(eventType, eventData);
            eventType = null;
            eventData = null;
          }
        }
      }
    }

  } catch (err) {
    console.error('SSE error:', err);
    // Fallback: show error message
    removeTypingIndicator();
    clearToolStrip();
    const errEl = document.createElement('div');
    errEl.className = 'message';
    errEl.innerHTML = `
      <div class="message-avatar" aria-label="Lỗi">!</div>
      <div class="message-body">
        <div class="confidence-badge low">LỖI KẾT NỐI</div>
        <div class="message-bubble">
          Không thể kết nối đến server VinFast AI.<br/>
          Vui lòng đảm bảo backend đang chạy trên <strong>localhost:8000</strong><br/>
          hoặc chạy: <code>python backend/main.py</code>
        </div>
      </div>`;
    DOM.messageList.appendChild(errEl);
    scrollToBottom();
  } finally {
    STATE.isProcessing = false;
    DOM.sendBtn.disabled = false;
    DOM.chatInput.disabled = false;
    DOM.chatInput.focus();
  }

  // ── Internal SSE event handler ───────────────────────────────
  async function _handleSSEEvent(type, data) {
    switch (type) {

      case 'start':
        // Restore COT Panel Title
        const cTitle = document.querySelector('.cot-title');
        if (cTitle) cTitle.innerHTML = `<div class="cot-indicator" aria-hidden="true"><span></span><span></span><span></span></div>ĐANG SUY LUẬN`;
        break;

      case 'thinking': {
        // Update typing indicator text if present
        const typeText = document.querySelector('#typingIndicator .typing-text');
        if (typeText) typeText.textContent = data.text || 'Đang xử lý...';

        // Add COT step to panel
        const stepEl = document.createElement('div');
        stepEl.className = `cot-step ${data.type || 'thinking'}`;
        const labelMap = {
          thinking:  'SUY LUẬN',
          tool:      'CÔNG CỤ',
          retrieval: 'RAG RETRIEVAL',
          guard:     'GUARDRAILS',
          result:    'KẾT QUẢ',
        };
        const stepType = data.type || 'thinking';
        stepEl.innerHTML = `
          <div class="cot-step-label">${labelMap[stepType] || stepType.toUpperCase()}</div>
          <div class="cot-step-text">${data.text || ''}</div>`;
        DOM.cotStream.appendChild(stepEl);
        DOM.cotStream.scrollTop = DOM.cotStream.scrollHeight;
        STATE.fullCotLog.push(data);
        STATE.tokenCount += Math.floor(Math.random() * 60) + 30;
        DOM.cotTokenCount.textContent = `${STATE.tokenCount} tokens`;
        break;
      }

      case 'tool_end': {
        // Show tool running in status strip
        const existing = DOM.toolStatusInner.querySelector(`[data-tool="${data.tool_name}"]`);
        if (existing) {
          existing.className = `tool-step ${data.status === 'ok' ? 'complete' : 'error'}`;
        } else {
          DOM.toolStatusStrip.removeAttribute('hidden');
          const pill = document.createElement('div');
          pill.className = `tool-step ${data.status === 'ok' ? 'complete' : 'error'}`;
          pill.dataset.tool = data.tool_name;
          pill.innerHTML = `<div class="tool-step-icon"></div>${data.tool_name}`;
          DOM.toolStatusInner.appendChild(pill);
        }
        toolsUsed.push(data.tool_name);
        break;
      }

      case 'token': {
        // First token: remove typing indicator and create AI message bubble
        if (!msgEl) {
          removeTypingIndicator();
          clearToolStrip();
          msgEl = document.createElement('div');
          msgEl.className = 'message';
          msgEl.id = msgId;
          msgEl.innerHTML = `
            <div class="message-avatar" aria-label="VinFast AI">AI</div>
            <div class="message-body">
              <div class="message-bubble prose-content" id="${msgId}_bubble"><span class="stream-cursor" aria-hidden="true"></span></div>
            </div>`;
          DOM.messageList.appendChild(msgEl);
          bubble = document.getElementById(`${msgId}_bubble`);
          cursor = bubble.querySelector('.stream-cursor');
          scrollToBottom();
        }
        // Append token text before cursor
        finalAnswer += data.text || '';
        const textNode = document.createTextNode(finalAnswer);
        bubble.innerHTML = '';
        bubble.appendChild(textNode);
        bubble.appendChild(cursor);
        bubble.parentElement.scrollIntoView({ block: 'end', behavior: 'nearest' });
        break;
      }

      case 'done': {
        toolsUsed  = data.tools_used  || toolsUsed;
        confidence = data.confidence  || 'mid';

        // Update COT Panel Title to Completed
        const cTitleEnd = document.querySelector('.cot-title');
        if (cTitleEnd) cTitleEnd.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px; color: var(--primary)"><path d="M20 6L9 17l-5-5"/></svg>ĐÃ HOÀN TẤT`;

        // Remove streaming cursor
        if (cursor) cursor.remove();

        // Render final rich HTML (markdown-ish processing)
        if (bubble) {
          bubble.innerHTML = _markdownToHtml(finalAnswer);
        }

        // Append metadata to message body
        const body = msgEl ? msgEl.querySelector('.message-body') : null;
        if (body) {
          // Confidence badge
          const confMap = { high: 'ĐỘ TIN CẬY CAO', mid: 'CÓ THỂ CẦN XÁC MINH', low: 'CHUYỂN TƯ VẤN VIÊN' };
          const badge = document.createElement('div');
          badge.className = `confidence-badge ${confidence}`;
          badge.setAttribute('role', 'status');
          badge.innerHTML = `<svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="12" r="10"/></svg> ${confMap[confidence] || confidence.toUpperCase()}`;
          body.insertBefore(badge, body.firstChild);

          // Tool pills
          if (toolsUsed.length) {
            const pills = document.createElement('div');
            pills.className = 'tool-pills';
            pills.setAttribute('aria-label', 'Công cụ đã sử dụng');
            pills.innerHTML = toolsUsed.map(t =>
              `<div class="tool-pill done" role="listitem"><div class="tool-pill-dot"></div>${t}</div>`
            ).join('');
            body.appendChild(pills);
          }

          // Default citations for vinfast.vn
          const citeBlock = document.createElement('div');
          citeBlock.className = 'citations';
          citeBlock.setAttribute('role', 'complementary');
          citeBlock.innerHTML = `
            <div class="citations-label">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
              NGUỒN XÁC MINH
            </div>
            <a href="https://vinfast.vn" class="cite-link" target="_blank" rel="noopener noreferrer">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
              vinfast.vn — Trang chính thức
            </a>
          `;
          body.appendChild(citeBlock);

          // Message meta (time + actions)
          const meta = document.createElement('div');
          meta.className = 'message-meta';
          meta.innerHTML = `
            <span class="message-time">${nowTime()}</span>
            <div class="message-actions" role="group" aria-label="Hành động với tin nhắn này">
              <button class="msg-action-btn" aria-label="Thích" title="Thumbs up" onclick="toggleFeedback(this,'liked')">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14z"/><path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>
              </button>
              <button class="msg-action-btn" aria-label="Báo lỗi" title="Thumbs down" onclick="toggleFeedback(this,'disliked')">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3H10z"/><path d="M17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/></svg>
              </button>
              <button class="msg-action-btn" aria-label="Copy" title="Copy" onclick="copyMessage('${msgId}_bubble')">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              </button>
              <button class="msg-action-btn" aria-label="Xem suy luận" title="Reasoning" onclick="viewCot()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              </button>
            </div>`;
          body.appendChild(meta);
        }

        scrollToBottom();
        break;
      }

      case 'error':
        removeTypingIndicator();
        clearToolStrip();
        console.error('Backend error:', data);
        break;
    }
  }
}

/* ── Lightweight markdown → HTML converter ─────────────────── */
function _markdownToHtml(md) {
  if (!md) return '';
  if (typeof marked !== 'undefined') {
    return marked.parse(md);
  }
  // Fallback (extremely basic)
  return md
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/\n\n/g, '<br><br>');
}

/* ============================================================
   14. INPUT HANDLERS
   ============================================================ */
DOM.chatInput.addEventListener('input', () => {
  autoResize(DOM.chatInput);
  const len = DOM.chatInput.value.length;
  DOM.sendBtn.disabled = len === 0 || STATE.isProcessing;
  DOM.charCount.textContent = `${len} / ${CONFIG.MAX_CHARS}`;
  DOM.charCount.classList.toggle('over', len > CONFIG.MAX_CHARS);
});

DOM.chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    const text = DOM.chatInput.value.trim();
    if (text) sendMessage(text);
  }
});

DOM.sendBtn.addEventListener('click', () => {
  const text = DOM.chatInput.value.trim();
  if (text) sendMessage(text);
});

/* Quick prompt chips */
document.querySelectorAll('.chip').forEach(chip => {
  chip.addEventListener('click', () => {
    const prompt = chip.dataset.prompt;
    DOM.chatInput.value = prompt;
    autoResize(DOM.chatInput);
    DOM.sendBtn.disabled = false;
    DOM.charCount.textContent = `${prompt.length} / ${CONFIG.MAX_CHARS}`;
    sendMessage(prompt);
  });
});

/* New chat */
DOM.newChatBtn.addEventListener('click', () => {
  DOM.messageList.innerHTML = '';
  DOM.welcomeScreen.classList.remove('hidden');
  STATE.messages = [];
  STATE.fullCotLog = [];
  DOM.cotStream.innerHTML = '';
  DOM.cotTokenCount.textContent = '0 tokens';
  hideCotPanel();
  clearToolStrip();
  DOM.chatInput.focus();
  DOM.chatInput.value = '';
});

/* Clear button */
DOM.clearBtn.addEventListener('click', () => {
  if (STATE.isProcessing) return;
  DOM.messageList.innerHTML = '';
  DOM.welcomeScreen.classList.remove('hidden');
  DOM.cotStream.innerHTML = '';
  DOM.cotTokenCount.textContent = '0 tokens';
  hideCotPanel();
  clearToolStrip();
});

/* ============================================================
   15. INIT
   ============================================================ */
window.addEventListener('DOMContentLoaded', () => {
  DOM.chatInput.focus();
  // Detect mobile and close sidebar
  if (window.innerWidth < 768) {
    closeSidebar();
  }
});

window.addEventListener('resize', () => {
  if (window.innerWidth < 768 && STATE.isSidebarOpen) {
    closeSidebar();
  }
});
