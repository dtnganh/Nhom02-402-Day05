/**
 * VinFast AI Chatbot — Frontend Logic
 * Handles: chat UI, chain-of-thought streaming, tool status,
 *          real FastAPI SSE backend, sidebar, theme toggle
 */

"use strict";

/* ============================================================
   1. CONFIGURATION & CONSTANTS
   ============================================================ */
const CONFIG = {
  API_BASE: "http://127.0.0.1:8000", // Đổi khi deploy
  MAX_CHARS: 2000,
  THREAD_ID: `thread_${Date.now()}`,
  STREAM_SPEED: 18, // ms per char for streaming effect (local mock only)
  COT_STEP_DELAY: 600, // ms between chain-of-thought steps (mock mode)
  USE_REAL_API: true, // false = dùng mock offline, true = gọi FastAPI BE
};

const STORAGE_KEYS = {
  CONVERSATIONS: "vinfast_chat_conversations_v1",
  ACTIVE_ID: "vinfast_chat_active_id_v1",
};

const CONVERSATION_STATUS = {
  EMPTY: "empty",
  ACTIVE: "active",
  COMPLETED: "completed",
};

const SYNC_CHANNEL_NAME = "vinfast_chat_sync_v1";

/* ============================================================
   2. DOM REFERENCES
   ============================================================ */
const DOM = {
  // Layout
  sidebar: document.getElementById("sidebar"),
  mainLayout: document.getElementById("mainLayout"),
  sidebarToggle: document.getElementById("sidebarToggle"),
  menuBtn: document.getElementById("menuBtn"),
  newChatBtn: document.getElementById("newChatBtn"),

  // Chat
  chatHistory: document.getElementById("chatHistory"),
  welcomeScreen: document.getElementById("welcomeScreen"),
  messageList: document.getElementById("messageList"),
  chatInput: document.getElementById("chatInput"),
  sendBtn: document.getElementById("sendBtn"),
  charCount: document.getElementById("charCount"),

  // Tools strip
  toolStatusStrip: document.getElementById("toolStatusStrip"),
  toolStatusInner: document.getElementById("toolStatusInner"),

  // COT Panel
  cotPanel: document.getElementById("cotPanel"),
  cotStream: document.getElementById("cotStream"),
  cotClose: document.getElementById("cotClose"),
  cotExpand: document.getElementById("cotExpand"),
  cotTokenCount: document.getElementById("cotTokenCount"),
  cotToggleBtn: document.getElementById("cotToggleBtn"),

  // COT Modal
  cotModal: document.getElementById("cotModal"),
  cotModalBody: document.getElementById("cotModalBody"),
  cotModalClose: document.getElementById("cotModalClose"),
  cotModalBackdrop: document.getElementById("cotModalBackdrop"),

  // Nav
  themeToggle: document.getElementById("themeToggle"),
  clearBtn: document.getElementById("clearBtn"),
};

/* ============================================================
   3. STATE
   ============================================================ */
const STATE = {
  isProcessing: false,
  messages: [],
  isCotVisible: false,
  isSidebarOpen: true,
  theme: "dark",
  fullCotLog: [], // complete chain-of-thought for modal
  tokenCount: 0,
  conversations: [],
  activeConversationId: null,
  activeThreadId: CONFIG.THREAD_ID,
  syncChannel: null,
  undoDelete: null,
};

/* ============================================================
   4. COT STEP RENDERER (used by both real SSE + offline mock)
   ============================================================ */

/* ============================================================
   5. UTILITY HELPERS
   ============================================================ */

/** Format current time HH:MM */
function nowTime() {
  return new Date().toLocaleTimeString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Sleep helper */
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Auto-resize textarea */
function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 200) + "px";
}

/** Scroll chat to bottom */
function scrollToBottom(smooth = true) {
  const ml = DOM.messageList;
  ml.scrollTo({
    top: ml.scrollHeight,
    behavior: smooth ? "smooth" : "instant",
  });
}

/** Escape HTML */
function escHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function getConfidenceLevel(score, fallback = "mid") {
  if (typeof score !== "number") return fallback;
  if (score < 0.4) return "low";
  if (score < 0.7) return "mid";
  return "high";
}

function confidenceLabel(level, score = null) {
  const map = {
    high: "DO TIN CAY CAO",
    mid: "CAN XAC MINH",
    low: "CHUYEN TU VAN VIEN",
  };
  if (typeof score === "number") {
    return `${map[level] || level.toUpperCase()} (${score.toFixed(2)})`;
  }
  return map[level] || level.toUpperCase();
}

function normalizeConversation(conv) {
  const now = new Date().toISOString();
  const messages = Array.isArray(conv.messages) ? conv.messages : [];
  let status = conv.status;
  if (!status) {
    if (!messages.length) status = CONVERSATION_STATUS.EMPTY;
    else if (messages[messages.length - 1]?.role === "assistant")
      status = CONVERSATION_STATUS.COMPLETED;
    else status = CONVERSATION_STATUS.ACTIVE;
  }
  return {
    id:
      conv.id || `conv_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    thread_id:
      conv.thread_id ||
      `thread_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    title: conv.title || "Hoi thoai moi",
    created_at: conv.created_at || now,
    updated_at: conv.updated_at || now,
    messages,
    status,
  };
}

function enforceSingleEmptyConversation(conversations) {
  let emptyFound = false;
  return conversations.map((conv) => {
    const c = { ...conv };
    if (c.status !== CONVERSATION_STATUS.EMPTY) return c;
    if (!emptyFound) {
      emptyFound = true;
      return c;
    }
    c.status = c.messages.length
      ? CONVERSATION_STATUS.COMPLETED
      : CONVERSATION_STATUS.ACTIVE;
    if (!c.title || c.title === "Hoi thoai moi") c.title = "Hoi thoai";
    return c;
  });
}

function publishSync(action) {
  if (STATE.syncChannel) {
    STATE.syncChannel.postMessage({ action, ts: Date.now() });
  }
}

function loadConversations() {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.CONVERSATIONS);
    const parsed = raw ? JSON.parse(raw) : [];
    const normalized = parsed.map(normalizeConversation);
    return enforceSingleEmptyConversation(normalized);
  } catch {
    return [];
  }
}

function saveConversations(syncAction = "conversations_updated") {
  STATE.conversations = enforceSingleEmptyConversation(
    STATE.conversations,
  ).sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
  localStorage.setItem(
    STORAGE_KEYS.CONVERSATIONS,
    JSON.stringify(STATE.conversations),
  );
  publishSync(syncAction);
}

function saveActiveConversationId() {
  if (!STATE.activeConversationId) return;
  localStorage.setItem(STORAGE_KEYS.ACTIVE_ID, STATE.activeConversationId);
  publishSync("active_changed");
}

function findConversation(id) {
  return STATE.conversations.find((c) => c.id === id);
}

function createConversation(
  title = "Hoi thoai moi",
  status = CONVERSATION_STATUS.EMPTY,
) {
  const now = new Date().toISOString();
  const conversation = {
    id: `conv_${Date.now()}`,
    thread_id: `thread_${Date.now()}`,
    title,
    created_at: now,
    updated_at: now,
    messages: [],
    status,
  };
  STATE.conversations.unshift(conversation);
  STATE.activeConversationId = conversation.id;
  STATE.activeThreadId = conversation.thread_id;
  saveConversations("conversation_created");
  saveActiveConversationId();
  renderConversationHistory();
  return conversation;
}

function getOrCreateEmptyConversation() {
  const existingEmpty = STATE.conversations.find(
    (c) => c.status === CONVERSATION_STATUS.EMPTY,
  );
  if (existingEmpty) {
    STATE.activeConversationId = existingEmpty.id;
    STATE.activeThreadId = existingEmpty.thread_id;
    saveActiveConversationId();
    renderConversationHistory();
    return existingEmpty;
  }
  return createConversation("Hoi thoai moi", CONVERSATION_STATUS.EMPTY);
}

function updateConversationTimestamp(conversation) {
  conversation.updated_at = new Date().toISOString();
  STATE.conversations = STATE.conversations
    .filter((c) => c.id !== conversation.id)
    .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
  STATE.conversations.unshift(conversation);
}

function appendConversationMessage(message) {
  if (!STATE.activeConversationId) {
    getOrCreateEmptyConversation();
  }
  const conversation = findConversation(STATE.activeConversationId);
  if (!conversation) return;

  conversation.messages.push(message);
  if (conversation.messages.length === 1 && message.role === "user") {
    conversation.title =
      message.content.slice(0, 42) + (message.content.length > 42 ? "..." : "");
  }

  if (message.role === "user") {
    conversation.status = CONVERSATION_STATUS.ACTIVE;
  } else if (message.role === "assistant") {
    conversation.status = CONVERSATION_STATUS.COMPLETED;
  }

  updateConversationTimestamp(conversation);
  saveConversations("conversation_message_appended");
  renderConversationHistory();
}

function showUndoToast(text, onUndo) {
  const existing = document.getElementById("undoToast");
  if (existing) existing.remove();

  const toast = document.createElement("div");
  toast.id = "undoToast";
  toast.className = "undo-toast";
  toast.innerHTML = `<span>${escHtml(text)}</span><button type="button" class="undo-btn">Undo</button>`;
  document.body.appendChild(toast);

  const btn = toast.querySelector(".undo-btn");
  btn.addEventListener("click", () => {
    onUndo();
    toast.remove();
  });

  const timer = setTimeout(() => toast.remove(), 8000);
  STATE.undoDelete = { timer };
}

function deleteConversation(conversationId) {
  const target = findConversation(conversationId);
  if (!target) return;
  if (!window.confirm("Delete this conversation?")) return;

  const deletedCopy = JSON.parse(JSON.stringify(target));
  STATE.conversations = STATE.conversations.filter(
    (c) => c.id !== conversationId,
  );

  if (!STATE.conversations.length) {
    const empty = createConversation(
      "Hoi thoai moi",
      CONVERSATION_STATUS.EMPTY,
    );
    switchConversation(empty.id);
  } else if (STATE.activeConversationId === conversationId) {
    const fallback =
      STATE.conversations.find(
        (c) => c.status !== CONVERSATION_STATUS.COMPLETED,
      ) || STATE.conversations[0];
    switchConversation(fallback.id);
  } else {
    saveConversations("conversation_deleted");
    renderConversationHistory();
  }

  showUndoToast("Conversation deleted", () => {
    STATE.conversations.unshift(normalizeConversation(deletedCopy));
    saveConversations("conversation_delete_undone");
    switchConversation(deletedCopy.id);
  });
}

function citationHtml(citations) {
  const citeItems = citations.length
    ? citations
    : [
        {
          label: "vinfast.vn - Trang chinh thuc",
          url: "https://vinfast.vn",
          score: 0.8,
        },
      ];

  const topItems = citeItems.slice(0, 2);
  const extraItems = citeItems.slice(2);

  const topHtml = topItems
    .map(
      (c) =>
        `<a href="${c.url}" class="cite-link" target="_blank" rel="noopener noreferrer" title="${escHtml(`score ${Number(c.score || 0).toFixed(2)} | ${c.domain || "source"}`)}">${escHtml(c.label || c.url || "Nguon")}</a>`,
    )
    .join("");

  const extraHtml = extraItems
    .map(
      (c) =>
        `<li><a href="${c.url}" class="cite-link" target="_blank" rel="noopener noreferrer" title="${escHtml(`score ${Number(c.score || 0).toFixed(2)} | ${c.domain || "source"}`)}">${escHtml(c.label || c.url || "Nguon")}</a></li>`,
    )
    .join("");

  return `
      <div class="citations" role="complementary">
        <div class="citations-label">NGUON XAC MINH</div>
        ${topHtml}
        ${
          extraItems.length
            ? `<details class="citation-details"><summary>Show ${extraItems.length} more source(s)</summary><ul>${extraHtml}</ul></details>`
            : ""
        }
      </div>
    `;
}

function renderConversationHistory() {
  if (!DOM.chatHistory) return;
  DOM.chatHistory.innerHTML = "";

  if (!STATE.conversations.length) {
    const empty = document.createElement("p");
    empty.className = "history-label";
    empty.textContent = "CHƯA CÓ HỘI THOẠI";
    DOM.chatHistory.appendChild(empty);
    return;
  }

  const label = document.createElement("p");
  label.className = "history-label";
  label.textContent = "GẦN ĐÂY";
  DOM.chatHistory.appendChild(label);

  for (const conv of STATE.conversations.slice(0, 20)) {
    const row = document.createElement("div");
    row.className = "history-row";

    const btn = document.createElement("button");
    btn.className = `history-item ${conv.id === STATE.activeConversationId ? "active" : ""}`;
    btn.type = "button";
    btn.setAttribute("role", "listitem");
    if (conv.id === STATE.activeConversationId) {
      btn.setAttribute("aria-current", "true");
    }
    const statusTag = `<span class="history-status ${conv.status || "completed"}">${(conv.status || "completed").toUpperCase()}</span>`;
    btn.dataset.conversationId = conv.id;
    btn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
      <span class="history-title">${escHtml(conv.title || "Hoi thoai")}</span>
      ${statusTag}
    `;
    btn.addEventListener("click", () => switchConversation(conv.id));

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "history-delete-btn";
    deleteBtn.setAttribute("aria-label", "Delete conversation");
    deleteBtn.innerHTML = "&#128465;";
    deleteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteConversation(conv.id);
    });

    row.appendChild(btn);
    row.appendChild(deleteBtn);
    DOM.chatHistory.appendChild(row);
  }
}

function renderAssistantMessageStatic(message, msgId) {
  const confidenceScore =
    typeof message.confidence_score === "number"
      ? message.confidence_score
      : null;
  const confidence = getConfidenceLevel(
    confidenceScore,
    message.confidence || "mid",
  );
  const status = message.status || "ok";
  const citations = Array.isArray(message.citations) ? message.citations : [];

  const msgEl = document.createElement("div");
  msgEl.className = "message";
  msgEl.id = msgId;
  msgEl.dataset.requestId = message.request_id || "";
  msgEl.dataset.intentTag = message.intent_tag || "unknown";
  msgEl.dataset.status = status;
  if (status === "low_confidence") msgEl.classList.add("msg-low-confidence");
  if (status === "error") msgEl.classList.add("msg-error");

  const citeItems = citations.length
    ? citations
    : [{ label: "vinfast.vn - Trang chính thức", url: "https://vinfast.vn" }];

  msgEl.innerHTML = `
    <div class="message-avatar" aria-label="VinFast AI">AI</div>
    <div class="message-body">
      <div class="confidence-badge ${confidence}" role="status">
        <svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="12" r="10"/></svg>
        ${confidenceLabel(confidence, confidenceScore)}
      </div>
      <div class="message-bubble prose-content" id="${msgId}_bubble">${_markdownToHtml(message.content || "")}</div>
      ${citationHtml(citeItems)}
      <div class="message-meta">
        <span class="message-time">${nowTime()}</span>
      </div>
    </div>
  `;

  DOM.messageList.appendChild(msgEl);
}

function switchConversation(conversationId, silent = false) {
  const conversation = findConversation(conversationId);
  if (!conversation) return;

  STATE.activeConversationId = conversation.id;
  STATE.activeThreadId = conversation.thread_id;
  if (!silent) saveActiveConversationId();
  renderConversationHistory();

  DOM.messageList.innerHTML = "";
  DOM.welcomeScreen.classList.toggle(
    "hidden",
    conversation.messages.length > 0,
  );

  for (const message of conversation.messages) {
    if (message.role === "user") {
      renderUserMessage(message.content || "");
    } else {
      renderAssistantMessageStatic(
        message,
        `msg_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      );
    }
  }
  scrollToBottom(false);
}

function resetComposerArea() {
  DOM.chatInput.focus();
  DOM.chatInput.value = "";
  DOM.sendBtn.disabled = true;
  DOM.charCount.textContent = `0 / ${CONFIG.MAX_CHARS}`;
  autoResize(DOM.chatInput);
}

function setupCrossTabSync() {
  if (typeof BroadcastChannel !== "undefined") {
    STATE.syncChannel = new BroadcastChannel(SYNC_CHANNEL_NAME);
    STATE.syncChannel.onmessage = () => {
      STATE.conversations = loadConversations();
      const savedActiveId = localStorage.getItem(STORAGE_KEYS.ACTIVE_ID);
      const target = findConversation(savedActiveId) || STATE.conversations[0];
      if (target) switchConversation(target.id, true);
      renderConversationHistory();
    };
  }

  window.addEventListener("storage", (event) => {
    if (
      event.key !== STORAGE_KEYS.CONVERSATIONS &&
      event.key !== STORAGE_KEYS.ACTIVE_ID
    ) {
      return;
    }
    STATE.conversations = loadConversations();
    const savedActiveId = localStorage.getItem(STORAGE_KEYS.ACTIVE_ID);
    const target = findConversation(savedActiveId) || STATE.conversations[0];
    if (target) switchConversation(target.id, true);
    renderConversationHistory();
  });
}

/* ============================================================
   6. SIDEBAR CONTROL
   ============================================================ */
function openSidebar() {
  STATE.isSidebarOpen = true;
  DOM.sidebar.classList.remove("collapsed");
  DOM.sidebar.classList.add("mobile-open");
  DOM.menuBtn.setAttribute("aria-expanded", "true");
  DOM.sidebarToggle.setAttribute("aria-expanded", "true");
}

function closeSidebar() {
  STATE.isSidebarOpen = false;
  DOM.sidebar.classList.add("collapsed");
  DOM.sidebar.classList.remove("mobile-open");
  DOM.menuBtn.setAttribute("aria-expanded", "false");
  DOM.sidebarToggle.setAttribute("aria-expanded", "false");
}

DOM.sidebarToggle.addEventListener("click", closeSidebar);
DOM.menuBtn.addEventListener("click", () => {
  STATE.isSidebarOpen ? closeSidebar() : openSidebar();
});

/* ============================================================
   7. THEME TOGGLE
   ============================================================ */
DOM.themeToggle.addEventListener("click", () => {
  STATE.theme = STATE.theme === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", STATE.theme);
});

/* ============================================================
   8. COT PANEL
   ============================================================ */
function showCotPanel() {
  STATE.isCotVisible = true;
  DOM.cotPanel.classList.add("visible");
  DOM.cotPanel.removeAttribute("aria-hidden");
  DOM.cotToggleBtn.setAttribute("aria-pressed", "true");
}

function hideCotPanel() {
  STATE.isCotVisible = false;
  DOM.cotPanel.classList.remove("visible");
  DOM.cotPanel.setAttribute("aria-hidden", "true");
  DOM.cotToggleBtn.setAttribute("aria-pressed", "false");
}

DOM.cotToggleBtn.addEventListener("click", () => {
  STATE.isCotVisible ? hideCotPanel() : showCotPanel();
});

DOM.cotClose.addEventListener("click", hideCotPanel);

/* COT Expand Modal */
DOM.cotExpand.addEventListener("click", openCotModal);
DOM.cotModalClose.addEventListener("click", closeCotModal);
DOM.cotModalBackdrop.addEventListener("click", closeCotModal);

function openCotModal() {
  DOM.cotModalBody.innerHTML = DOM.cotStream.innerHTML;
  DOM.cotModal.removeAttribute("hidden");
  document.body.style.overflow = "hidden";
}

function closeCotModal() {
  DOM.cotModal.setAttribute("hidden", "");
  document.body.style.overflow = "";
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !DOM.cotModal.hasAttribute("hidden")) {
    closeCotModal();
  }
});

/* ============================================================
   9. CHAIN OF THOUGHT STREAMING
   ============================================================ */
let cotStepCount = 0;

async function streamCotSteps(steps) {
  DOM.cotStream.innerHTML = "";
  cotStepCount = 0;
  STATE.tokenCount = 0;
  STATE.fullCotLog = [];

  showCotPanel();

  for (const step of steps) {
    await sleep(CONFIG.COT_STEP_DELAY);

    const stepEl = document.createElement("div");
    stepEl.className = `cot-step ${step.type}`;

    const labelMap = {
      thinking: "SUY LUẬN",
      tool: "CÔNG CỤ",
      retrieval: "RAG RETRIEVAL",
      guard: "GUARDRAILS",
      result: "KẾT QUẢ",
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
  DOM.toolStatusStrip.removeAttribute("hidden");
  DOM.toolStatusInner.innerHTML = "";

  // Create all pill elements first as pending
  const pills = tools.map((toolName) => {
    const el = document.createElement("div");
    el.className = "tool-step pending";
    el.innerHTML = `<div class="tool-step-icon"></div>${toolName}`;
    DOM.toolStatusInner.appendChild(el);
    return { el, name: toolName };
  });

  // Animate each to running → complete
  for (const { el, name } of pills) {
    el.className = "tool-step running";
    el.innerHTML = `<div class="tool-step-icon"></div>${name}`;
    await sleep(CONFIG.COT_STEP_DELAY + 200);
    el.className = "tool-step complete";
    el.innerHTML = `<div class="tool-step-icon"></div>${name}`;
  }
}

function clearToolStrip() {
  DOM.toolStatusStrip.setAttribute("hidden", "");
  DOM.toolStatusInner.innerHTML = "";
}

/* ============================================================
   11. MESSAGE RENDERING
   ============================================================ */
function renderUserMessage(text) {
  const el = document.createElement("div");
  el.className = "message user-msg";
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
  const el = document.createElement("div");
  el.className = "typing-indicator";
  el.id = "typingIndicator";
  el.setAttribute("aria-label", "AI đang xử lý");
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
  const el = document.getElementById("typingIndicator");
  if (el) el.remove();
}

/** Render AI message with streaming text effect */
async function renderAIMessage(responseData) {
  const { answer, confidence, citations, ctas, tools } = responseData;
  const msgId = `msg_${Date.now()}`;

  const el = document.createElement("div");
  el.className = "message";
  el.id = msgId;

  // Confidence badge HTML
  const confBadge = confidence
    ? `<div class="confidence-badge ${confidence}" role="status" aria-label="Độ tin cậy ${confidence}">
        <svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="12" r="10"/></svg>
        ${{ high: "ĐỘ TIN CẬY CAO", mid: "CÓ THỂ CẦN XÁCMINH", low: "CHUYỂN TƯ VẤN VIÊN" }[confidence]}
       </div>`
    : "";

  // Tool pills HTML (initially all running style)
  const toolPillsHtml = tools
    ? `<div class="tool-pills" aria-label="Công cụ đã sử dụng">${tools
        .map(
          (t) =>
            `<div class="tool-pill done" role="listitem"><div class="tool-pill-dot"></div>${t}</div>`,
        )
        .join("")}</div>`
    : "";

  // Citations HTML
  const citationHtml =
    citations && citations.length
      ? `<div class="citations" role="complementary" aria-label="Nguồn trích dẫn">
        <div class="citations-label">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
          </svg>
          NGUỒN TRÍCH DẪN
        </div>
        ${citations
          .map(
            (c) =>
              `<a href="${c.url}" class="cite-link" target="_blank" rel="noopener noreferrer" aria-label="Xem nguồn: ${escHtml(c.label)}">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
              <polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
            </svg>
            ${escHtml(c.label)}
          </a>`,
          )
          .join("")}
       </div>`
      : "";

  // CTA buttons
  const ctaHtml =
    ctas && ctas.length
      ? `<div class="message-ctas" role="group" aria-label="Hành động tiếp theo">${ctas
          .map(
            (c) =>
              `<button class="cta-btn ${c.style === "secondary" ? "secondary" : ""}" aria-label="${escHtml(c.label)}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <polyline points="9 18 15 12 9 6"/>
          </svg>
          ${escHtml(c.label)}
        </button>`,
          )
          .join("")}</div>`
      : "";

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
  const cursor = bubble.querySelector(".stream-cursor");
  await streamText(bubble, cursor, answer);
}

/** Stream text character by character into element */
async function streamText(container, cursor, htmlContent) {
  // Parse to plain text for streaming, then set full HTML at end
  // For visual effect: stream a plain version, then swap to rich HTML
  const tempDiv = document.createElement("div");
  tempDiv.innerHTML = htmlContent;
  const plainText = tempDiv.textContent || "";

  let streamed = "";
  for (let i = 0; i < plainText.length; i++) {
    streamed += plainText[i];
    // Update text node before cursor
    const textNode = document.createTextNode(streamed);
    container.innerHTML = "";
    container.appendChild(textNode);
    container.appendChild(cursor);
    container.parentElement.scrollIntoView({
      block: "end",
      behavior: "nearest",
    });

    // Vary speed for natural feel
    const delay =
      plainText[i] === " "
        ? CONFIG.STREAM_SPEED * 0.5
        : plainText[i] === "\n"
          ? CONFIG.STREAM_SPEED * 3
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
  const message = btn.closest(".message");
  const parent = btn.closest(".message-actions");
  parent.querySelectorAll(".msg-action-btn").forEach((b) => {
    b.classList.remove("liked", "disliked");
  });
  btn.classList.toggle(type);

  const action = type === "liked" ? "liked" : "disliked";
  const reasonPrompt =
    action === "liked"
      ? "Điểm bạn hài lòng nhất là gì?"
      : "Nội dung nào cần sửa?";

  const reason = window.prompt(reasonPrompt, "");
  if (reason === null) return;

  const payload = {
    request_id: message?.dataset.requestId || `local_${Date.now()}`,
    thread_id: STATE.activeThreadId || CONFIG.THREAD_ID,
    action,
    reason: (reason || "").trim(),
    intent_tag: message?.dataset.intentTag || "unknown",
    status: message?.dataset.status || "ok",
  };

  submitFeedback(payload);
};

async function submitFeedback(payload) {
  try {
    await fetch(`${CONFIG.API_BASE}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    console.warn("Feedback submit failed:", err);
  }
}

window.copyMessage = (id) => {
  const el = document.getElementById(id);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent || "");
  // Brief flash
  el.style.outline = "2px solid #22C55E";
  setTimeout(() => {
    el.style.outline = "";
  }, 800);
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
  DOM.welcomeScreen.classList.add("hidden");

  // Render user message
  renderUserMessage(text);
  appendConversationMessage({
    id: `m_${Date.now()}`,
    role: "user",
    content: text,
    timestamp: new Date().toISOString(),
  });

  // Clear input
  DOM.chatInput.value = "";
  DOM.charCount.textContent = `0 / ${CONFIG.MAX_CHARS}`;
  autoResize(DOM.chatInput);

  // Prepare COT panel
  DOM.cotStream.innerHTML = "";
  STATE.fullCotLog = [];
  STATE.tokenCount = 0;
  DOM.cotTokenCount.textContent = "0 tokens";
  showCotPanel();

  // Show typing indicator
  renderTypingIndicator();

  // Prepare streaming state
  let finalAnswer = "";
  let toolsUsed = [];
  const toolConfidenceMap = {};
  let confidence = "mid";
  let status = "ok";
  let confidenceScore = null;
  let requestId = "";
  let intentTag = "unknown";
  let citations = [];
  let fallbackReason = "";

  // Create AI message container with empty bubble (will fill via SSE tokens)
  const msgId = `msg_${Date.now()}`;
  let msgEl = null; // created after typing indicator removed
  let bubble = null;
  let cursor = null;

  try {
    const response = await fetch(`${CONFIG.API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, thread_id: STATE.activeThreadId }),
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    // ── SSE parsing loop ────────────────────────────────────────
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop(); // keep incomplete line

      let eventType = null;
      let eventData = null;

      for (const line of lines) {
        if (line.startsWith("event:")) {
          eventType = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          try {
            eventData = JSON.parse(line.slice(5).trim());
          } catch {
            eventData = null;
          }
        } else if (line.trim() === "") {
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
    console.error("SSE error:", err);
    // Fallback: show error message
    removeTypingIndicator();
    clearToolStrip();
    const errEl = document.createElement("div");
    errEl.className = "message";
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
      case "start":
        requestId = data.request_id || "";
        // Restore COT Panel Title
        const cTitle = document.querySelector(".cot-title");
        if (cTitle)
          cTitle.innerHTML = `<div class="cot-indicator" aria-hidden="true"><span></span><span></span><span></span></div>ĐANG SUY LUẬN`;
        break;

      case "thinking": {
        // Update typing indicator text if present
        const typeText = document.querySelector(
          "#typingIndicator .typing-text",
        );
        if (typeText) typeText.textContent = data.text || "Đang xử lý...";

        // Add COT step to panel
        const stepEl = document.createElement("div");
        stepEl.className = `cot-step ${data.type || "thinking"}`;
        const labelMap = {
          thinking: "SUY LUẬN",
          tool: "CÔNG CỤ",
          retrieval: "RAG RETRIEVAL",
          guard: "GUARDRAILS",
          result: "KẾT QUẢ",
        };
        const stepType = data.type || "thinking";
        stepEl.innerHTML = `
          <div class="cot-step-label">${labelMap[stepType] || stepType.toUpperCase()}</div>
          <div class="cot-step-text">${data.text || ""}</div>`;
        DOM.cotStream.appendChild(stepEl);
        DOM.cotStream.scrollTop = DOM.cotStream.scrollHeight;
        STATE.fullCotLog.push(data);
        STATE.tokenCount += Math.floor(Math.random() * 60) + 30;
        DOM.cotTokenCount.textContent = `${STATE.tokenCount} tokens`;
        break;
      }

      case "tool_end": {
        // Show tool running in status strip
        const existing = DOM.toolStatusInner.querySelector(
          `[data-tool="${data.tool_name}"]`,
        );
        if (existing) {
          existing.className = `tool-step ${data.status === "ok" ? "complete" : "error"}`;
        } else {
          DOM.toolStatusStrip.removeAttribute("hidden");
          const pill = document.createElement("div");
          pill.className = `tool-step ${data.status === "ok" ? "complete" : "error"}`;
          pill.dataset.tool = data.tool_name;
          pill.innerHTML = `<div class="tool-step-icon"></div>${data.tool_name}`;
          DOM.toolStatusInner.appendChild(pill);
        }
        toolsUsed.push(data.tool_name);
        toolConfidenceMap[data.tool_name] = {
          score:
            typeof data.confidence_score === "number"
              ? data.confidence_score
              : null,
          level: data.confidence_level || "mid",
        };
        break;
      }

      case "token": {
        // First token: remove typing indicator and create AI message bubble
        if (!msgEl) {
          removeTypingIndicator();
          clearToolStrip();
          msgEl = document.createElement("div");
          msgEl.className = "message";
          msgEl.id = msgId;
          msgEl.dataset.requestId = requestId;
          msgEl.dataset.intentTag = intentTag;
          msgEl.dataset.status = status;
          msgEl.innerHTML = `
            <div class="message-avatar" aria-label="VinFast AI">AI</div>
            <div class="message-body">
              <div class="message-bubble prose-content" id="${msgId}_bubble"></div>
            </div>`;
          DOM.messageList.appendChild(msgEl);
          scrollToBottom();
        }

        // Append token text and morph DOM progressively
        const tokenText = data.text || "";
        finalAnswer += tokenText;

        _morphStream(msgId, finalAnswer);
        break;
      }

      case "done": {
        toolsUsed = data.tools_used || toolsUsed;
        confidenceScore =
          typeof data.confidence_score === "number"
            ? data.confidence_score
            : null;
        confidence = getConfidenceLevel(
          confidenceScore,
          data.confidence || "mid",
        );
        status = data.status || "ok";
        requestId = data.request_id || requestId;
        intentTag = data.intent_tag || "unknown";
        citations = Array.isArray(data.citations) ? data.citations : [];
        fallbackReason = data.fallback_reason || "";

        if (status === "low_confidence" && confidence !== "low") {
          confidence = "low";
        }

        // Update COT Panel Title to Completed
        const cTitleEnd = document.querySelector(".cot-title");
        if (cTitleEnd)
          cTitleEnd.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:8px; color: var(--primary)"><path d="M20 6L9 17l-5-5"/></svg>ĐÃ HOÀN TẤT`;

        // Render final rich HTML
        if (bubble) {
          const finalHtml = _markdownToHtml(finalAnswer);
          if (typeof morphdom !== "undefined") {
            morphdom(
              bubble,
              `<div class="message-bubble prose-content" id="${msgId}_bubble">${finalHtml}</div>`,
            );
          } else {
            bubble.innerHTML = finalHtml;
          }
        }

        // Append metadata to message body
        const body = msgEl ? msgEl.querySelector(".message-body") : null;
        if (body) {
          msgEl.dataset.requestId = requestId;
          msgEl.dataset.intentTag = intentTag;
          msgEl.dataset.status = status;
          if (status === "low_confidence")
            msgEl.classList.add("msg-low-confidence");
          if (status === "error") msgEl.classList.add("msg-error");

          // Confidence badge
          const badge = document.createElement("div");
          badge.className = `confidence-badge ${confidence}`;
          badge.setAttribute("role", "status");
          if (confidenceScore !== null) {
            badge.setAttribute("title", `Confidence score: ${confidenceScore}`);
          }
          badge.innerHTML = `<svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="12" r="10"/></svg> ${confidenceLabel(confidence, confidenceScore)}`;
          body.insertBefore(badge, body.firstChild);

          // Tool pills
          if (toolsUsed.length) {
            const pills = document.createElement("div");
            pills.className = "tool-pills";
            pills.setAttribute("aria-label", "Công cụ đã sử dụng");
            pills.innerHTML = toolsUsed
              .map((t) => {
                const toolMeta = toolConfidenceMap[t] || {};
                const toolLevel = getConfidenceLevel(
                  toolMeta.score,
                  toolMeta.level || "mid",
                );
                const toolLabel =
                  typeof toolMeta.score === "number"
                    ? `${t} (${toolMeta.score.toFixed(2)})`
                    : t;
                return `<div class="tool-pill ${toolLevel}" role="listitem" title="Tool confidence: ${typeof toolMeta.score === "number" ? toolMeta.score.toFixed(2) : "n/a"}"><div class="tool-pill-dot"></div>${escHtml(toolLabel)}</div>`;
              })
              .join("");
            body.appendChild(pills);
          }

          const citeWrap = document.createElement("div");
          citeWrap.innerHTML = citationHtml(citations);
          body.appendChild(citeWrap.firstElementChild);

          if (status === "low_confidence" && fallbackReason) {
            const warn = document.createElement("div");
            warn.className = "confidence-note";
            warn.textContent = `Lưu ý: ${fallbackReason}. Bạn nên xác minh với tư vấn viên.`;
            body.appendChild(warn);
          }

          const ctaWrap = document.createElement("div");
          ctaWrap.className = "message-ctas";
          if (status === "ok") {
            ctaWrap.innerHTML = `
              <button class="cta-btn" aria-label="Đặt lịch lái thử">Đặt lịch lái thử</button>
              <button class="cta-btn secondary" aria-label="Gặp tư vấn viên">Gặp tư vấn viên</button>
            `;
          } else if (status === "low_confidence") {
            ctaWrap.innerHTML = `
              <button class="cta-btn" aria-label="Gặp tư vấn viên">Gặp tư vấn viên</button>
            `;
          } else {
            ctaWrap.innerHTML = `
              <button class="cta-btn" aria-label="Thử lại" onclick="location.reload()">Thử lại</button>
            `;
          }
          body.appendChild(ctaWrap);

          // Message meta (time + actions)
          const meta = document.createElement("div");
          meta.className = "message-meta";
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

          appendConversationMessage({
            id: `m_${Date.now()}_ai`,
            role: "assistant",
            content: finalAnswer,
            confidence,
            confidence_score: confidenceScore,
            status,
            citations,
            request_id: requestId,
            intent_tag: intentTag,
            timestamp: new Date().toISOString(),
          });
        }

        scrollToBottom();
        break;
      }

      case "error":
        removeTypingIndicator();
        clearToolStrip();
        console.error("Backend error:", data);
        break;
    }
  }
}

/* ── Streaming Morphdom Renderer ─────────────────────────── */
let _morphThrottle;
function _morphStream(msgId, rawText) {
  if (_morphThrottle) cancelAnimationFrame(_morphThrottle);
  _morphThrottle = requestAnimationFrame(() => {
    const bubbleEl = document.getElementById(`${msgId}_bubble`);
    if (!bubbleEl) return;

    // Attempt to close incomplete markdown structures for stable visual streaming
    let processedText = rawText;
    const backticksCount = (processedText.match(/```/g) || []).length;
    if (backticksCount % 2 !== 0) {
      // Missing closing fence for a code block
      processedText += "\n```";
    }

    const htmlContent = _markdownToHtml(processedText);

    if (typeof morphdom !== "undefined") {
      morphdom(
        bubbleEl,
        `<div class="message-bubble prose-content" id="${msgId}_bubble">${htmlContent}</div>`,
      );
    } else {
      bubbleEl.innerHTML = htmlContent;
    }

    const parentContainer = bubbleEl.parentElement;
    if (parentContainer) {
      parentContainer.scrollIntoView({ block: "end", behavior: "nearest" });
    }
  });
}

/* ── Lightweight markdown → HTML converter ─────────────────── */
function _markdownToHtml(md) {
  if (!md) return "";
  if (typeof marked !== "undefined") {
    return marked.parse(md);
  }
  // Fallback (extremely basic)
  return md
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/\n\n/g, "<br><br>");
}

/* ============================================================
   14. INPUT HANDLERS
   ============================================================ */
DOM.chatInput.addEventListener("input", () => {
  autoResize(DOM.chatInput);
  const len = DOM.chatInput.value.length;
  DOM.sendBtn.disabled = len === 0 || STATE.isProcessing;
  DOM.charCount.textContent = `${len} / ${CONFIG.MAX_CHARS}`;
  DOM.charCount.classList.toggle("over", len > CONFIG.MAX_CHARS);
});

DOM.chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    const text = DOM.chatInput.value.trim();
    if (text) sendMessage(text);
  }
});

DOM.sendBtn.addEventListener("click", () => {
  const text = DOM.chatInput.value.trim();
  if (text) sendMessage(text);
});

/* Quick prompt chips */
document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const prompt = chip.dataset.prompt;
    DOM.chatInput.value = prompt;
    autoResize(DOM.chatInput);
    DOM.sendBtn.disabled = false;
    DOM.charCount.textContent = `${prompt.length} / ${CONFIG.MAX_CHARS}`;
    sendMessage(prompt);
  });
});

/* New chat */
DOM.newChatBtn.addEventListener("click", () => {
  const target = getOrCreateEmptyConversation();
  switchConversation(target.id);
  DOM.messageList.innerHTML = "";
  DOM.welcomeScreen.classList.remove("hidden");
  STATE.messages = [];
  STATE.fullCotLog = [];
  DOM.cotStream.innerHTML = "";
  DOM.cotTokenCount.textContent = "0 tokens";
  hideCotPanel();
  clearToolStrip();
  resetComposerArea();
});

/* Clear button */
DOM.clearBtn.addEventListener("click", () => {
  if (STATE.isProcessing) return;
  const conversation = findConversation(STATE.activeConversationId);
  if (conversation) {
    conversation.messages = [];
    conversation.status = CONVERSATION_STATUS.EMPTY;
    conversation.title = "Hoi thoai moi";
    conversation.updated_at = new Date().toISOString();
    saveConversations("conversation_cleared");
    renderConversationHistory();
  }
  DOM.messageList.innerHTML = "";
  DOM.welcomeScreen.classList.remove("hidden");
  DOM.cotStream.innerHTML = "";
  DOM.cotTokenCount.textContent = "0 tokens";
  hideCotPanel();
  clearToolStrip();
  resetComposerArea();
});

/* ============================================================
   15. INIT
   ============================================================ */
window.addEventListener("DOMContentLoaded", () => {
  STATE.conversations = loadConversations();
  const savedActiveId = localStorage.getItem(STORAGE_KEYS.ACTIVE_ID);

  if (!STATE.conversations.length) {
    const empty = createConversation(
      "Hoi thoai moi",
      CONVERSATION_STATUS.EMPTY,
    );
    switchConversation(empty.id);
    DOM.welcomeScreen.classList.remove("hidden");
  } else {
    const target =
      STATE.conversations.find((c) => c.id === savedActiveId) ||
      STATE.conversations[0];
    switchConversation(target.id);
  }

  renderConversationHistory();
  resetComposerArea();
  setupCrossTabSync();
  // Detect mobile and close sidebar
  if (window.innerWidth < 768) {
    closeSidebar();
  }
});

window.addEventListener("resize", () => {
  if (window.innerWidth < 768 && STATE.isSidebarOpen) {
    closeSidebar();
  }
});
