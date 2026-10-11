const $ = (id) => document.getElementById(id);

const state = {
  apiBase: "http://127.0.0.1:8081",
  agents: [],
  chats: [],
  currentChat: null,
  messages: [],
  busy: false,
};

function apiUrl(path) {
  return `${state.apiBase.replace(/\/+$/, "")}${path}`;
}

async function api(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const raw = await response.text();
  let data = null;
  try { data = raw ? JSON.parse(raw) : null; } catch { data = raw; }
  if (!response.ok) {
    const detail = data && typeof data === "object" ? (data.detail || JSON.stringify(data)) : data;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return data;
}

function setConnection(connected, text) {
  const el = $("connectionState");
  el.innerHTML = `<span class="status-dot ${connected ? "ok" : ""}"></span>${escapeHtml(text)}`;
}

function showError(message) {
  const banner = $("errorBanner");
  banner.textContent = message;
  banner.classList.remove("hidden");
}

function clearError() {
  $("errorBanner").classList.add("hidden");
  $("errorBanner").textContent = "";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function agentName(id) {
  if (id === "user") return "You";
  return state.agents.find((agent) => agent.id === id)?.name || id || "Agent";
}

function selectedAgentIds() {
  return [...$("agentSelect").selectedOptions].map((option) => option.value);
}

async function connect() {
  state.apiBase = $("apiBase").value.trim() || "http://127.0.0.1:8000";
  localStorage.setItem("aiTeamApiBase", state.apiBase);
  clearError();
  try {
    const [, agents, chats] = await Promise.all([
      api("/health"),
      api("/agents"),
      api("/chats"),
    ]);
    state.agents = agents || [];
    state.chats = chats || [];
    renderAgentOptions();
    renderChatList();
    setConnection(true, "Connected");
    if (state.chats.length && !state.currentChat) {
      await openChat(state.chats[0].id);
    } else if (state.currentChat) {
      const exists = state.chats.find((chat) => chat.id === state.currentChat.id);
      if (exists) await openChat(exists.id);
    }
  } catch (error) {
    setConnection(false, "Not connected");
    showError(`Cannot connect to backend: ${error.message}. Start FastAPI and check the backend URL. If the browser reports a CORS error, enable CORS in FastAPI for this frontend origin.`);
  }
}

function renderAgentOptions() {
  const select = $("agentSelect");
  const previous = selectedAgentIds();
  select.innerHTML = state.agents
    .filter((agent) => agent.enabled !== false)
    .map((agent) => `<option value="${escapeHtml(agent.id)}">${escapeHtml(agent.name)}</option>`)
    .join("");
  if (previous.length) {
    [...select.options].forEach((option) => { option.selected = previous.includes(option.value); });
  } else {
    const manager = [...select.options].find((option) => option.value === "manager");
    if (manager) manager.selected = true;
    else if (select.options[0]) select.options[0].selected = true;
  }
  updateChatType();
}

function updateChatType() {
  const individual = $("chatType").value === "individual";
  $("agentSelect").multiple = !individual;
  if (individual) {
    const selected = selectedAgentIds();
    const keep = selected[0] || $("agentSelect").options[0]?.value;
    [...$("agentSelect").options].forEach((option) => { option.selected = option.value === keep; });
    $("participantHint").textContent = "Select one agent for an individual chat.";
  } else {
    $("participantHint").textContent = "Use Ctrl/Cmd to select multiple agents.";
  }
}

function renderChatList() {
  const list = $("chatList");
  if (!state.chats.length) {
    list.innerHTML = `<div style="padding:8px 10px;color:#777a83;font-size:11px;line-height:1.6">Your chats will appear here.</div>`;
    return;
  }
  list.innerHTML = state.chats
    .slice()
    .sort((a, b) => new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at))
    .map((chat) => `
      <button class="chat-item ${state.currentChat?.id === chat.id ? "active" : ""}" data-chat-id="${escapeHtml(chat.id)}">
        <span class="chat-icon">${chat.chat_type === "group" ? "◉" : "○"}</span>
        <span class="chat-name">${escapeHtml(chat.title)}</span>
      </button>`)
    .join("");
  list.querySelectorAll("[data-chat-id]").forEach((button) => {
    button.addEventListener("click", () => openChat(button.dataset.chatId));
  });
}

async function createChat() {
  clearError();
  const participantIds = selectedAgentIds();
  if (!participantIds.length) {
    showError("Choose at least one agent.");
    return;
  }
  try {
    const chat = await api("/chats", {
      method: "POST",
      body: JSON.stringify({
        title: $("chatType").value === "group"
          ? `Team chat · ${participantIds.map(agentName).join(", ")}`
          : `Chat with ${agentName(participantIds[0])}`,
        chat_type: $("chatType").value,
        participant_ids: participantIds,
      }),
    });
    state.chats.push(chat);
    await openChat(chat.id);
  } catch (error) {
    showError(error.message);
  }
}

async function openChat(chatId) {
  clearError();
  try {
    const [chat, messages] = await Promise.all([
      api(`/chats/${encodeURIComponent(chatId)}`),
      api(`/chats/${encodeURIComponent(chatId)}/messages`),
    ]);
    state.currentChat = chat;
    state.messages = messages || [];
    $("chatTitle").textContent = chat.title;
    $("chatSubtitle").textContent = `${chat.chat_type === "group" ? "Group chat" : "Individual chat"} · ${chat.participant_ids.map(agentName).join(", ")}`;
    $("welcome").classList.add("hidden");
    $("messages").classList.remove("hidden");
    renderMessages();
    renderChatList();
  } catch (error) {
    showError(error.message);
  }
}

function renderMessages() {
  const container = $("messages");
  if (!state.messages.length) {
    container.innerHTML = `<div class="typing">Start the conversation. Messages from you and your agents will appear here.</div>`;
    return;
  }
  container.innerHTML = state.messages.map((message) => {
    const isUser = message.sender_id === "user";
    const name = agentName(message.sender_id);
    const initial = isUser ? "Y" : name.slice(0, 1).toUpperCase();
    const time = message.created_at ? new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
    const type = message.message_type && message.message_type !== "chat" ? `<span class="message-type">${escapeHtml(message.message_type.replaceAll("_", " "))}</span>` : "";
    return `<article class="message ${isUser ? "user" : ""}">
      <div class="avatar">${escapeHtml(initial)}</div>
      <div class="message-body">
        <div class="message-meta"><strong>${escapeHtml(name)}</strong><time>${escapeHtml(time)}</time>${type}</div>
        <div class="message-content">${escapeHtml(message.content)}</div>
      </div>
    </article>`;
  }).join("");
  container.scrollTop = container.scrollHeight;
}

async function sendMessage(content) {
  if (!state.currentChat) {
    showError("Create a chat first.");
    return;
  }
  if (state.busy) return;
  state.busy = true;
  clearError();
  $("sendBtn").disabled = true;
  $("sendBtn").textContent = "…";
  const container = $("messages");
  const typing = document.createElement("div");
  typing.className = "typing";
  typing.textContent = "Your AI team is working…";
  container.appendChild(typing);
  container.scrollTop = container.scrollHeight;
  try {
    const result = await api(`/chats/${encodeURIComponent(state.currentChat.id)}/messages`, {
      method: "POST",
      body: JSON.stringify({ sender_id: "user", content }),
    });
    typing.remove();
    // The API returns messages generated by this request; reload to display the canonical persisted history.
    state.messages = await api(`/chats/${encodeURIComponent(state.currentChat.id)}/messages`);
    renderMessages();
    state.chats = await api("/chats");
    renderChatList();
  } catch (error) {
    typing.remove();
    showError(error.message);
    // Reload history because the backend may have persisted the user message before an LLM error.
    try {
      state.messages = await api(`/chats/${encodeURIComponent(state.currentChat.id)}/messages`);
      renderMessages();
    } catch {}
  } finally {
    state.busy = false;
    $("sendBtn").disabled = false;
    $("sendBtn").textContent = "↑";
    $("messageInput").focus();
  }
}

$("connectBtn").addEventListener("click", connect);
$("createChatBtn").addEventListener("click", createChat);
$("newChatBtn").addEventListener("click", () => {
  state.currentChat = null;
  state.messages = [];
  $("chatTitle").textContent = "New chat";
  $("chatSubtitle").textContent = "Choose an agent and start a conversation";
  $("messages").classList.add("hidden");
  $("welcome").classList.remove("hidden");
  renderChatList();
});
$("chatType").addEventListener("change", updateChatType);
$("messageForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("messageInput");
  const content = input.value.trim();
  if (!content) return;
  input.value = "";
  input.style.height = "auto";
  await sendMessage(content);
});
$("messageInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("messageForm").requestSubmit();
  }
});
$("messageInput").addEventListener("input", (event) => {
  event.target.style.height = "auto";
  event.target.style.height = `${Math.min(event.target.scrollHeight, 160)}px`;
});
document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    $("messageInput").value = button.dataset.prompt;
    $("messageInput").focus();
    $("messageInput").dispatchEvent(new Event("input"));
  });
});

$("apiBase").value = localStorage.getItem("aiTeamApiBase") || state.apiBase;
connect();
