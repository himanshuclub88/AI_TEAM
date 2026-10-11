// Keep the backend URL in exactly one place.
const API_BASE = 'http://127.0.0.1:8081';

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = {
  chats: [],
  activeChatId: null,
  messages: [],
  projects: [],
  activeProjectId: null,
  projectFiles: [],
  activeFilePath: null,
  currentView: 'chat',
  activityMode: 'events',
  sending: false,
  pollingTimer: null,
  activityTimer: null,
  lastActivitySignature: '',
  loadingMessages: false,
  loadingActivity: false,
  tasks: [],
  workflowChats: [],
  activeChatIsWorkflow: false,
  workflowSenderFilter: 'all',
  autoFollowWorkflow: false,
  userManuallySelectedChat: false,
  activeRequestChatId: null,
  activeRequestStartedAt: 0,
  lastSeenWorkflowMessageIds: new Set(),
  userHasScrolledUp: false,
  newMessagesWaiting: false,
  knownMessageIds: new Set(),
  theme: 'dark'
};

const roleNames = {
  user: 'You', manager: 'Manager', researcher: 'Researcher', architect: 'Architect',
  frontend_developer: 'Frontend Developer', backend_developer: 'Backend Developer', tester: 'Tester'
};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
}
function timeLabel(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
function dateLabel(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function shortText(value, max = 65) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
  });
  const raw = await response.text();
  let data = null;
  try { data = raw ? JSON.parse(raw) : null; } catch { data = raw; }
  if (!response.ok) {
    const detail = data && typeof data === 'object' ? (data.detail || data.message) : data;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return data;
}
function toast(message, type = '') {
  const item = document.createElement('div');
  item.className = `toast ${type}`;
  item.textContent = message;
  $('#toastRegion').append(item);
  setTimeout(() => item.remove(), 4300);
}
function setConnection(online, label) {
  ['#connectionDot', '#topStatusDot'].forEach(selector => {
    $(selector).classList.toggle('offline', !online);
  });
  $('#connectionText').textContent = label || (online ? 'Backend connected' : 'Backend unavailable');
  $('#backendLabel').textContent = online ? 'API · 8081 · Connected' : 'API · 8081 · Offline';
}
function setNotice(message) {
  $('#noticeText').textContent = message;
  $('#noticeBar').classList.toggle('hidden', !message);
}
function showView(view) {
  state.currentView = view;
  $$('.view').forEach(item => item.classList.remove('active-view'));
  $(`#${view}View`).classList.add('active-view');
  $$('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.view === view));
  $('#pageTitle').textContent = ({ chat: 'Team chat', playground: 'Playground', activity: 'Activity log' })[view];
  if (view === 'playground') loadProjects();
  if (view === 'activity') loadActivity();
}
function currentChat() {
  return state.chats.find(chat => chat.id === state.activeChatId);
}
function isNearBottom(element, threshold = 100) {
  return element.scrollHeight - element.scrollTop - element.clientHeight < threshold;
}
function scrollToBottom(force = false) {
  const scroller = $('#messageScroll');
  if (!scroller) return;
  if (force || isNearBottom(scroller)) {
    scroller.scrollTop = scroller.scrollHeight;
    state.newMessagesWaiting = false;
    $('#readingIndicator').classList.add('hidden');
  }
}
function avatarFor(sender) {
  if (sender === 'user') return '<div class="message-avatar user">HS</div>';
  if (sender === 'manager') return '<div class="message-avatar manager">✦</div>';
  const initials = (roleNames[sender] || sender || 'AI').replace(/[^A-Za-z]/g, '').slice(0, 2).toUpperCase();
  return `<div class="message-avatar agent">${escapeHtml(initials || 'AI')}</div>`;
}
function tagsFor(message) {
  const metadata = message.metadata || {};
  const tags = [];
  if (metadata.project_id) tags.push(`<span class="message-tag">PROJECT · ${escapeHtml(metadata.project_id)}</span>`);
  if (metadata.test_status) tags.push(`<span class="message-tag ${metadata.test_status === 'passed' ? 'success' : 'warning'}">TESTS · ${escapeHtml(metadata.test_status)}</span>`);
  if (metadata.error || metadata.blocked) tags.push('<span class="message-tag warning">NEEDS ATTENTION</span>');
  if (Array.isArray(metadata.files_written) && metadata.files_written.length) tags.push(`<span class="message-tag success">${metadata.files_written.length} FILES WRITTEN</span>`);
  return tags.length ? `<div class="message-tags">${tags.join('')}</div>` : '';
}
function messageMarkup(message) {
  const sender = message.sender_id || 'manager';
  const user = sender === 'user';
  const label = roleNames[sender] || sender.replaceAll('_', ' ');
  const type = message.message_type || 'chat';
  const error = (message.metadata || {}).error || /couldn't finish|failed:/i.test(message.content || '');
  return `<article class="message-row ${user ? 'user-row' : ''}" data-message-id="${escapeHtml(message.id)}">
    ${avatarFor(sender)}
    <div class="message-main">
      <div class="message-meta"><strong>${escapeHtml(label)}</strong>${type !== 'chat' ? `<span class="message-tag">${escapeHtml(type.replaceAll('_', ' ').toUpperCase())}</span>` : ''}<span class="message-time">${escapeHtml(timeLabel(message.created_at || message.timestamp))}</span></div>
      <div class="message-bubble ${error ? 'error' : ''}">${escapeHtml(message.content || '')}</div>
      ${tagsFor(message)}
      <details class="message-json"><summary>Inspect saved JSON</summary><pre>${escapeHtml(JSON.stringify({id: message.id, chat_id: message.chat_id, sender_id: sender, message_type: type, task_id: message.task_id ?? null, created_at: message.created_at ?? null, content: message.content ?? '', metadata: message.metadata ?? {}}, null, 2))}</pre></details>
    </div>
  </article>`;
}
function renderMessages(messages, options = {}) {
  // Update only changed/new messages. Never replace the whole conversation on polling:
  // replacing it resets the reader's scroll position and makes the page jump to the end.
  const scroller = $('#messageScroll');
  const wasNearBottom = isNearBottom(scroller);
  const oldTop = scroller.scrollTop;
  const container = $('#messages');
  const welcome = $('#welcomePanel');
  const ids = new Set(messages.map(m => String(m.id)));
  const visibleMessages = state.activeChatIsWorkflow && state.workflowSenderFilter !== 'all'
    ? messages.filter(message => String(message.sender_id || '') === state.workflowSenderFilter)
    : messages;
  const visibleIds = new Set(visibleMessages.map(m => String(m.id)));
  welcome.classList.toggle('hidden', visibleMessages.length > 0);
  if (state.activeChatIsWorkflow && state.workflowSenderFilter !== 'all') {
    welcome.querySelector('h2').innerHTML = `Waiting for <span>${escapeHtml(roleNames[state.workflowSenderFilter] || state.workflowSenderFilter)}</span>`;
    welcome.querySelector('p').textContent = 'This agent has not posted to the selected room yet. New saved messages will appear here automatically.';
  } else if (state.activeChatIsWorkflow) {
    welcome.querySelector('h2').innerHTML = 'Team is <span>working.</span>';
    welcome.querySelector('p').textContent = 'This room updates from saved backend messages. Expand “Inspect saved JSON” on a message to see its persisted metadata.';
  }

  // Update only the currently selected transcript filter, without replacing the whole conversation.
  [...container.children].forEach(node => {
    if (!visibleIds.has(node.dataset.messageId)) node.remove();
  });
  for (const message of visibleMessages) {
    const id = String(message.id);
    let node = container.querySelector(`[data-message-id="${CSS.escape(id)}"]`);
    const markup = messageMarkup(message);
    if (!node) {
      const wrapper = document.createElement('div');
      wrapper.innerHTML = markup;
      node = wrapper.firstElementChild;
      container.append(node);
    } else {
      const temp = document.createElement('div');
      temp.innerHTML = markup;
      const fresh = temp.firstElementChild;
      if (node.innerHTML !== fresh.innerHTML || node.className !== fresh.className) {
        node.replaceWith(fresh);
      }
    }
  }
  state.messages = messages;
  state.knownMessageIds = ids;
  renderWorkflowFilters();
  if (options.forceBottom || wasNearBottom) {
    scroller.scrollTop = scroller.scrollHeight;
    state.newMessagesWaiting = false;
    $('#readingIndicator').classList.add('hidden');
  } else {
    scroller.scrollTop = oldTop;
    const hasNew = messages.some(m => !options.previousIds?.has(String(m.id)) && m.sender_id !== 'user');
    if (hasNew) {
      state.newMessagesWaiting = true;
      $('#readingIndicator').classList.remove('hidden');
    }
  }
  const chat = currentChat();
  if (chat) {
    $('#conversationTitle').textContent = chat.title || 'Your AI team';
    $('#conversationSubtitle').textContent = chat.chat_type === 'individual' && chat.participant_ids?.includes('manager')
      ? 'One message to the Manager. The team handles the rest.'
      : 'Conversation history is saved in your workspace.';
  }
}
function renderWorkflowFilters() {
  const bar = $('#workflowFilterBar');
  if (!bar) return;
  const chat = currentChat();
  if (!chat || !state.activeChatIsWorkflow) {
    bar.classList.add('hidden');
    bar.innerHTML = '';
    return;
  }
  const ids = ['all', ...(chat.participant_ids || [])];
  // Development rooms include Tester and both developer roles in the saved transcript.
  if ((chat.title || '').toLowerCase().startsWith('development')) {
    ['researcher', 'frontend_developer', 'backend_developer', 'tester'].forEach(id => { if (!ids.includes(id)) ids.push(id); });
  }
  bar.classList.remove('hidden');
  bar.innerHTML = ids.map(id => {
    const label = id === 'all' ? 'Everyone' : (roleNames[id] || id.replaceAll('_', ' '));
    return `<button type="button" class="workflow-filter ${state.workflowSenderFilter === id ? 'active' : ''}" data-sender-filter="${escapeHtml(id)}">${escapeHtml(label)}</button>`;
  }).join('');
}
function setWorkflowFilter(senderId) {
  state.workflowSenderFilter = senderId || 'all';
  renderWorkflowFilters();
  renderMessages(state.messages, { forceBottom: true, previousIds: state.knownMessageIds });
  updateComposerForChat();
}

function renderChats() {
  const list = $('#chatList');
  const personal = state.chats.filter(chat =>
    !chat.workflow_chat && (chat.chat_type !== 'group' || chat.participant_ids?.length === 1)
  );
  const workflows = state.chats.filter(chat => chat.workflow_chat || (chat.chat_type === 'group' && chat.participant_ids?.length > 1));
  const chatMarkup = chat => {
    const workflow = Boolean(chat.workflow_chat || chat.chat_type === 'group');
    const subtitle = workflow
      ? `${(chat.participant_ids || []).length} team members · transcript`
      : (chat.chat_type || 'chat');
    return `<div class="chat-item ${chat.id === state.activeChatId ? 'selected' : ''} ${workflow ? 'workflow-chat-item' : ''}"
        data-chat-id="${escapeHtml(chat.id)}" data-workflow-chat="${workflow ? 'true' : 'false'}" role="button" tabindex="0">
      <div class="chat-item-icon">${workflow ? '⇄' : '◈'}</div>
      <div class="chat-item-copy"><strong>${escapeHtml(chat.title || 'Untitled chat')}</strong><small>${escapeHtml(subtitle)}</small></div>
      <span class="chat-arrow">${workflow ? '↗' : '›'}</span>
    </div>`;
  };
  list.innerHTML = `
    <div class="chat-group-label">MANAGER CHATS</div>
    ${personal.length ? personal.map(chatMarkup).join('') : '<div class="chat-list-empty">No Manager chats yet.</div>'}
    <div class="chat-group-label workflow-group-label">TEAM WORKFLOWS <span>${workflows.length}</span></div>
    ${workflows.length ? workflows.map(chatMarkup).join('') : '<div class="chat-list-empty">Workflow conversations appear when a build starts.</div>'}
  `;
}
async function loadChats(preferredId = null) {
  const chats = await api('/chats');
  state.chats = Array.isArray(chats) ? chats : [];
  renderChats();
  const available = state.chats.filter(chat => !chat.workflow_chat && (chat.chat_type !== 'group' || chat.participant_ids?.length === 1));
  const chosen = preferredId || state.activeChatId;
  if (chosen && available.some(chat => chat.id === chosen)) {
    if (chosen !== state.activeChatId) await selectChat(chosen);
  } else if (available.length) {
    await selectChat(available[0].id);
  } else {
    state.activeChatId = null;
    state.messages = [];
    $('#messages').innerHTML = '';
    $('#welcomePanel').classList.remove('hidden');
    $('#conversationTitle').textContent = 'Your AI team';
    $('#conversationSubtitle').textContent = 'One message to the Manager. The team handles the rest.';
  }
}
async function createNewChat() {
  const title = 'New conversation';
  const chat = await api('/chats', {
    method: 'POST',
    body: JSON.stringify({ title, chat_type: 'individual', participant_ids: ['manager'] })
  });
  state.chats.unshift(chat);
  state.activeChatId = chat.id;
  state.activeChatIsWorkflow = false;
  state.messages = [];
  state.knownMessageIds = new Set();
  $('#messages').innerHTML = '';
  $('#welcomePanel').classList.remove('hidden');
  renderChats();
  renderMessages([], { forceBottom: true });
  updateComposerForChat();
  showView('chat');
  $('#messageInput').focus();
  return chat;
}
async function selectChat(chatId, options = {}) {
  if (!options.automatic) {
    state.userManuallySelectedChat = true;
    state.autoFollowWorkflow = false;
  }
  if (state.activeChatId === chatId) {
    showView('chat');
    return;
  }
  state.activeChatId = chatId;
  state.activeChatIsWorkflow = Boolean(state.chats.find(chat => chat.id === chatId)?.workflow_chat ||
    state.chats.find(chat => chat.id === chatId)?.chat_type === 'group');
  state.workflowSenderFilter = 'all';
  state.messages = [];
  state.knownMessageIds = new Set();
  $('#messages').innerHTML = '';
  $('#welcomePanel').classList.remove('hidden');
  $('#messageScroll').scrollTop = 0;
  renderChats();
  showView('chat');
  updateComposerForChat();
  await loadMessages({ forceBottom: true });
}
function updateComposerForChat() {
  const input = $('#messageInput');
  const button = $('#sendButton');
  if (state.activeChatIsWorkflow) {
    input.placeholder = 'This is a read-only team transcript. Return to a Manager chat to send a request.';
    input.disabled = true;
    button.disabled = true;
    $('#conversationSubtitle').textContent = state.workflowSenderFilter === 'all' ? 'Live team room · inspect handoffs, results and saved JSON.' : `Filtered to ${roleNames[state.workflowSenderFilter] || state.workflowSenderFilter} messages.`;
  } else {
    input.placeholder = 'Message the Manager…  (Enter to send, Shift + Enter for a new line)';
    input.disabled = state.sending;
    button.disabled = state.sending;
    $('#conversationSubtitle').textContent = 'One message to the Manager. The team handles the rest.';
  }
}
async function loadMessages(options = {}) {
  if (!state.activeChatId || state.loadingMessages) return;
  state.loadingMessages = true;
  const requestedChatId = state.activeChatId;
  const previousIds = new Set(state.knownMessageIds);
  try {
    const messages = await api(`/chats/${encodeURIComponent(requestedChatId)}/messages`);
    // Ignore late responses from a chat the user has already switched away from.
    if (requestedChatId !== state.activeChatId) return;
    renderMessages(Array.isArray(messages) ? messages : [], { ...options, previousIds });
  } catch (error) {
    if (!options.silent) toast(`Couldn't load messages: ${error.message}`, 'error');
  } finally {
    state.loadingMessages = false;
  }
}
async function sendMessage(text) {
  const content = text.trim();
  if (!content || state.sending) return;
  if (state.activeChatIsWorkflow) {
    toast('Team workflow chats are read-only. Select a Manager chat to send a request.');
    return;
  }
  if (!state.activeChatId) await createNewChat();
  state.sending = true;
  state.autoFollowWorkflow = true;
  state.userManuallySelectedChat = false;
  state.activeRequestChatId = state.activeChatId;
  state.activeRequestStartedAt = Date.now();
  $('#sendButton').disabled = true;
  $('#messageInput').disabled = true;
  $('#messageInput').value = '';
  resizeComposer();
  setNotice('');
  try {
    const activeId = state.activeChatId;
    const result = await api(`/chats/${encodeURIComponent(activeId)}/messages`, {
      method: 'POST',
      body: JSON.stringify({ sender_id: 'user', content, target_agent_ids: ['manager'] })
    });
    if (activeId === state.activeChatId && Array.isArray(result)) {
      const byId = new Map(state.messages.map(message => [String(message.id), message]));
      result.forEach(message => byId.set(String(message.id), message));
      renderMessages([...byId.values()], { forceBottom: true, previousIds: state.knownMessageIds });
    }
    await loadChats(activeId);
    await loadMessages({ forceBottom: true, silent: true });
    setConnection(true, 'Backend connected');
    // If this was a build request, the API responds after the synchronous workflow completes.
    toast('Manager response received.');
  } catch (error) {
    $('#messageInput').value = content;
    setNotice(`Message could not be sent. ${error.message}`);
    toast(`Send failed: ${error.message}`, 'error');
  } finally {
    state.sending = false;
    state.autoFollowWorkflow = false;
    state.activeRequestChatId = null;
    updateComposerForChat();
    $('#messageInput').focus();
  }
}
function resizeComposer() {
  const input = $('#messageInput');
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
}
async function checkHealth() {
  try {
    await api('/health');
    setConnection(true);
  } catch {
    setConnection(false, 'Backend unavailable');
  }
}
async function loadProjects() {
  $('#projectList').innerHTML = '<div class="empty-small">Loading projects…</div>';
  try {
    state.projects = await api('/projects') || [];
    $('#projectCount').textContent = `${state.projects.length} project${state.projects.length === 1 ? '' : 's'}`;
    if (!state.projects.length) {
      $('#projectList').innerHTML = '<div class="empty-small">No projects yet.<br>Ask the Manager to build something.</div>';
      $('#fileList').innerHTML = '<div class="empty-small">No project selected.</div>';
      return;
    }
    $('#projectList').innerHTML = state.projects.map(project => {
      const id = project.id || project.project_id;
      return `<div class="project-item ${id === state.activeProjectId ? 'selected' : ''}" data-project-id="${escapeHtml(id)}" role="button" tabindex="0">
        <div class="project-icon">▤</div><div><strong>${escapeHtml(project.title || id)}</strong><small>${escapeHtml(id)}</small></div>
      </div>`;
    }).join('');
    const nextId = state.projects.some(project => (project.id || project.project_id) === state.activeProjectId)
      ? state.activeProjectId : (state.projects[0].id || state.projects[0].project_id);
    if (nextId) await selectProject(nextId);
  } catch (error) {
    $('#projectList').innerHTML = `<div class="empty-small">Couldn't load projects.<br>${escapeHtml(error.message)}</div>`;
    toast(`Project load failed: ${error.message}`, 'error');
  }
}
async function selectProject(projectId) {
  state.activeProjectId = projectId;
  state.activeFilePath = null;
  $$('.project-item').forEach(item => item.classList.toggle('selected', item.dataset.projectId === projectId));
  const project = state.projects.find(item => (item.id || item.project_id) === projectId);
  $('#filesHeading').textContent = project?.title || 'Project files';
  $('#filesSubheading').textContent = projectId;
  $('#fileList').innerHTML = '<div class="empty-small">Loading files…</div>';
  $('#fileContent').textContent = 'Select a file to read its contents.';
  $('#currentFileName').textContent = 'No file selected';
  try {
    state.projectFiles = await api(`/projects/${encodeURIComponent(projectId)}/files`) || [];
    $('#fileCount').textContent = `${state.projectFiles.length} files`;
    if (!state.projectFiles.length) {
      $('#fileList').innerHTML = '<div class="empty-small">This project has no visible files.</div>';
      return;
    }
    $('#fileList').innerHTML = state.projectFiles.map(file => {
      const path = typeof file === 'string' ? file : (file.path || file.name);
      return `<div class="file-item" data-file-path="${escapeHtml(path)}" role="button" tabindex="0"><span class="file-item-icon">⌑</span><div><strong>${escapeHtml(path.split('/').pop())}</strong><small>${escapeHtml(path)}</small></div></div>`;
    }).join('');
    const firstPath = typeof state.projectFiles[0] === 'string' ? state.projectFiles[0] : (state.projectFiles[0].path || state.projectFiles[0].name);
    await readProjectFile(firstPath);
  } catch (error) {
    $('#fileList').innerHTML = `<div class="empty-small">Couldn't load files.<br>${escapeHtml(error.message)}</div>`;
  }
}
async function readProjectFile(path) {
  if (!state.activeProjectId || !path) return;
  state.activeFilePath = path;
  $$('.file-item').forEach(item => item.classList.toggle('selected', item.dataset.filePath === path));
  $('#currentFileName').textContent = path;
  $('#fileContent').textContent = 'Reading file…';
  $('#copyFileButton').disabled = true;
  try {
    const result = await api(`/projects/${encodeURIComponent(state.activeProjectId)}/file?path=${encodeURIComponent(path)}`);
    // Ignore stale file response if user clicked another file while this request was in flight.
    if (state.activeFilePath !== path) return;
    $('#fileContent').textContent = result.content ?? '';
    $('#copyFileButton').disabled = false;
  } catch (error) {
    $('#fileContent').textContent = `Could not read this file.\n${error.message}`;
  }
}
function taskStage(task) {
  const id = task.assigned_to || '';
  if (id === 'manager') return 'manager';
  if (id === 'researcher') return 'researcher';
  if (id === 'architect') return 'architect';
  if (id.includes('developer')) return 'frontend_developer';
  if (id === 'tester') return 'tester';
  return null;
}
function stageStatus(stage, tasks) {
  const relevant = tasks.filter(task => taskStage(task) === stage);
  if (!relevant.length) return { label: 'WAITING', className: '' };
  if (relevant.some(task => ['blocked', 'failed'].includes(String(task.status).toLowerCase()))) return { label: 'BLOCKED', className: 'blocked' };
  if (relevant.some(task => ['assigned', 'pending', 'in_progress', 'accepted', 'running'].includes(String(task.status).toLowerCase()))) return { label: 'WORKING', className: 'working' };
  if (relevant.every(task => ['completed', 'done'].includes(String(task.status).toLowerCase()))) return { label: 'DONE', className: 'done' };
  return { label: String(relevant[relevant.length - 1].status || 'WAITING').toUpperCase(), className: '' };
}
function renderPipeline(tasks) {
  const stages = ['manager', 'researcher', 'architect', 'frontend_developer', 'tester'];
  stages.forEach(stage => {
    const row = $(`#pipelineSteps [data-stage="${stage}"]`);
    if (!row) return;
    const status = stageStatus(stage, tasks);
    row.classList.remove('stage-working', 'stage-done', 'stage-blocked');
    if (status.className) row.classList.add(`stage-${status.className}`);
    const badge = row.querySelector('.stage-state');
    if (badge) {
      badge.textContent = status.label;
      badge.className = `stage-state ${status.className}`;
    }
  });
}
async function refreshWorkflowActivity() {
  if (state.loadingActivity) return;
  state.loadingActivity = true;
  try {
    // Refresh the persisted workflow chat list and task states while the build request is still running.
    const [chats, tasks] = await Promise.all([api('/chats'), api('/tasks')]);
    state.chats = Array.isArray(chats) ? chats : state.chats;
    state.tasks = Array.isArray(tasks) ? tasks : [];
    state.workflowChats = state.chats.filter(chat => chat.workflow_chat || (chat.chat_type === 'group' && chat.participant_ids?.length > 1));
    renderChats();
    renderPipeline(state.tasks);

    // While a Manager build request is waiting, follow the newest persisted task's room.
    // A manual chat selection disables this so polling never fights the user.
    if (state.sending && state.autoFollowWorkflow && !state.userManuallySelectedChat && state.tasks.length) {
      const requestTasks = state.tasks.filter(task => new Date(task.created_at || 0).getTime() >= state.activeRequestStartedAt - 1500);
      const newestTask = [...requestTasks].sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))[0];
      const targetChat = newestTask && state.workflowChats.find(chat => chat.id === newestTask.chat_id);
      if (targetChat && targetChat.id !== state.activeChatId) {
        await selectChat(targetChat.id, { automatic: true });
        if (newestTask.assigned_to && state.activeChatIsWorkflow) setWorkflowFilter(newestTask.assigned_to);
      } else if (targetChat && state.activeChatIsWorkflow && newestTask.assigned_to && state.workflowSenderFilter !== newestTask.assigned_to) {
        setWorkflowFilter(newestTask.assigned_to);
      }
    }

    const transcripts = [];
    for (const chat of state.workflowChats.slice(0, 12)) {
      try {
        const messages = await api(`/chats/${encodeURIComponent(chat.id)}/messages`);
        for (const message of messages || []) {
          if (message.message_type === 'system') continue;
          transcripts.push({ ...message, workflowTitle: chat.title || chat.id, workflowId: chat.id });
        }
      } catch { /* one transcript may not be readable yet */ }
    }
    transcripts.sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0));
    const latest = transcripts.slice(-24);
    const pendingTasks = state.tasks.filter(task => ['assigned', 'pending', 'in_progress', 'accepted', 'running'].includes(String(task.status).toLowerCase()));
    const signature = latest.map(item => `${item.id}:${item.content}`).join('|') + '|' + state.tasks.map(t => `${t.id}:${t.status}`).join('|');
    $('#liveActivityStatus').textContent = pendingTasks.length ? 'Working now' : 'Live';
    if (signature !== state.lastActivitySignature) {
      state.lastActivitySignature = signature;
      const activity = $('#liveActivityList');
      const pendingMarkup = pendingTasks.map(task => {
        const sender = roleNames[task.assigned_to] || task.assigned_to || 'Agent';
        return `<div class="live-event live-working">
          <span class="live-event-marker"><span class="mini-spinner"></span></span>
          <div class="live-event-copy"><div><strong>${escapeHtml(sender)} · Working</strong><small>Live task</small></div>
            <p>${escapeHtml(shortText(task.title || task.description || 'Working on assigned task', 180))}</p><time>Started ${escapeHtml(timeLabel(task.created_at))}</time></div>
        </div>`;
      });
      const historyMarkup = latest.slice().reverse().map(item => {
        const sender = roleNames[item.sender_id] || item.sender_id || 'Agent';
        const status = item.metadata?.error ? 'blocked' : (item.message_type === 'task_result' ? 'done' : '');
        return `<div class="live-event ${status ? `live-${status}` : ''}">
          <span class="live-event-marker">${item.metadata?.error ? '!' : (item.message_type === 'task_result' ? '✓' : '·')}</span>
          <div class="live-event-copy"><div><strong>${escapeHtml(sender)}</strong><small>${escapeHtml(item.workflowTitle)}</small></div>
            <p>${escapeHtml(shortText(item.content, 180))}</p><time>${escapeHtml(timeLabel(item.created_at))}</time></div>
        </div>`;
      });
      activity.innerHTML = pendingMarkup.concat(historyMarkup).join('') || '<div class="live-empty">No workflow events yet. Start a build to watch the team.</div>';
    }
    // If a workflow transcript is currently open, refresh it too without stealing the user's scroll.
    if (state.activeChatIsWorkflow && state.activeChatId) await loadMessages({ silent: true });
  } catch (error) {
    $('#liveActivityStatus').textContent = 'Reconnecting';
  } finally {
    state.loadingActivity = false;
  }
}
async function loadActivity(mode = state.activityMode) {
  state.activityMode = mode;
  $('#activityEventsButton')?.classList.toggle('active', mode === 'events');
  $('#activityCallsButton')?.classList.toggle('active', mode === 'calls');
  const heading = $('#activityList');
  heading.innerHTML = `<div class="empty-small">Loading ${mode === 'calls' ? 'model calls' : 'activity'}…</div>`;
  try {
    if (mode === 'calls') {
      const calls = await api('/llm-calls?limit=50');
      const items = Array.isArray(calls) ? calls : [];
      $('#activityCount').textContent = `${items.length} model calls`;
      heading.innerHTML = items.length ? items.map(call => {
        const agent = roleNames[call.agent_id] || call.agent_name || call.agent_id || 'Agent';
        const response = call.validated_response ?? call.adapter_response ?? call.error ?? null;
        const json = {call_id: call.call_id, agent_id: call.agent_id, agent_name: call.agent_name, configured_agent_model: call.configured_agent_model, runtime_model: call.runtime_model, chat_id: call.chat_id, started_at: call.started_at, finished_at: call.finished_at, duration_ms: call.duration_ms, status: call.status, request: call.request, response, error: call.error ?? null};
        return `<article class="model-call-item ${call.status === 'error' ? 'model-call-error' : ''}">
          <div class="model-call-head"><div><strong>${escapeHtml(agent)}</strong><small>${escapeHtml(call.runtime_model || call.configured_agent_model || 'Configured model unavailable')}</small></div><span class="model-call-status ${call.status === 'error' ? 'error' : 'success'}">${escapeHtml((call.status || 'unknown').toUpperCase())}</span></div>
          <p>${escapeHtml(shortText(call.request?.messages?.at(-1)?.content || call.request?.system_prompt || 'Model request', 240))}</p>
          <div class="model-call-meta"><span>${escapeHtml(dateLabel(call.started_at))}</span><span>${Number.isFinite(Number(call.duration_ms)) ? `${Math.round(Number(call.duration_ms))} ms` : 'Duration unavailable'}</span><span>${escapeHtml(call.call_id || '')}</span></div>
          <details class="message-json"><summary>Inspect full request and response JSON</summary><pre>${escapeHtml(JSON.stringify(json, null, 2))}</pre></details>
        </article>`;
      }).join('') : '<div class="empty-small">No model-call records yet. New calls will appear after the backend logging patch is installed.</div>';
      return;
    }

    const chats = await api('/chats');
    const all = [];
    for (const chat of (chats || []).slice(0, 35)) {
      try {
        const messages = await api(`/chats/${encodeURIComponent(chat.id)}/messages`);
        messages.forEach(message => all.push({ ...message, chatTitle: chat.title || chat.id }));
      } catch { /* skip a chat that cannot be loaded */ }
    }
    all.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
    const events = all.slice(0, 80);
    $('#activityCount').textContent = `${events.length} events`;
    $('#activityList').innerHTML = events.length ? events.map(message => {
      const sender = roleNames[message.sender_id] || message.sender_id || 'Agent';
      return `<div class="activity-item"><div class="activity-symbol">${message.sender_id === 'user' ? '↗' : '✦'}</div><div class="activity-copy"><strong>${escapeHtml(sender)} · ${escapeHtml(message.chatTitle)}</strong><p>${escapeHtml(shortText(message.content, 360))}</p><small>${escapeHtml(dateLabel(message.created_at))} · ${escapeHtml((message.message_type || 'chat').replaceAll('_', ' '))}</small><details class="message-json"><summary>Inspect saved JSON</summary><pre>${escapeHtml(JSON.stringify(message, null, 2))}</pre></details></div></div>`;
    }).join('') : '<div class="empty-small">No activity yet.</div>';
  } catch (error) {
    $('#activityList').innerHTML = `<div class="empty-small">Couldn't load ${mode === 'calls' ? 'model calls' : 'activity'}.<br>${escapeHtml(error.message)}</div>`;
  }
}

function initEvents() {
  $('#messageForm').addEventListener('submit', event => {
    event.preventDefault();
    sendMessage($('#messageInput').value);
  });
  $('#messageInput').addEventListener('input', resizeComposer);
  $('#messageInput').addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendMessage($('#messageInput').value);
    }
  });
  $('#newChatButton').addEventListener('click', async () => {
    try { await createNewChat(); } catch (error) { toast(`Couldn't create chat: ${error.message}`, 'error'); }
  });
  $('#refreshChats').addEventListener('click', () => loadChats().catch(error => toast(error.message, 'error')));
  $('#chatList').addEventListener('click', event => {
    const item = event.target.closest('[data-chat-id]');
    if (item) selectChat(item.dataset.chatId).catch(error => toast(error.message, 'error'));
  });
  $('#workflowFilterBar').addEventListener('click', event => {
    const button = event.target.closest('[data-sender-filter]');
    if (button) {
      state.userManuallySelectedChat = true;
      state.autoFollowWorkflow = false;
      setWorkflowFilter(button.dataset.senderFilter);
    }
  });
  $('#chatList').addEventListener('keydown', event => {
    if ((event.key === 'Enter' || event.key === ' ') && event.target.matches('[data-chat-id]')) {
      event.preventDefault();
      selectChat(event.target.dataset.chatId).catch(error => toast(error.message, 'error'));
    }
  });
  $$('.nav-item').forEach(item => item.addEventListener('click', () => showView(item.dataset.view)));
  $$('.suggestion-card').forEach(item => item.addEventListener('click', () => {
    $('#messageInput').value = item.dataset.prompt || '';
    resizeComposer();
    $('#messageInput').focus();
  }));
  $('#messageScroll').addEventListener('scroll', () => {
    const nearBottom = isNearBottom($('#messageScroll'));
    state.userHasScrolledUp = !nearBottom;
    if (nearBottom) {
      state.newMessagesWaiting = false;
      $('#readingIndicator').classList.add('hidden');
    }
  }, { passive: true });
  $('#scrollLatestButton').addEventListener('click', () => scrollToBottom(true));
  $('#showNewMessages').addEventListener('click', () => scrollToBottom(true));
  $('#dismissNotice').addEventListener('click', () => setNotice(''));
  $('#clearNoticeButton').addEventListener('click', () => setNotice(''));
  $('#refreshProjects').addEventListener('click', loadProjects);
  $('#projectList').addEventListener('click', event => {
    const item = event.target.closest('[data-project-id]');
    if (item) selectProject(item.dataset.projectId);
  });
  $('#fileList').addEventListener('click', event => {
    const item = event.target.closest('[data-file-path]');
    if (item) readProjectFile(item.dataset.filePath);
  });
  $('#copyFileButton').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($('#fileContent').textContent); toast('File contents copied.'); }
    catch { toast('Clipboard access is unavailable in this browser.', 'error'); }
  });
  $('#refreshActivity').addEventListener('click', () => loadActivity());
  $('#activityEventsButton').addEventListener('click', () => loadActivity('events'));
  $('#activityCallsButton').addEventListener('click', () => loadActivity('calls'));
  $('#themeToggle').addEventListener('click', () => {
    document.body.classList.toggle('light-theme');
    state.theme = document.body.classList.contains('light-theme') ? 'light' : 'dark';
    $('#themeToggle').textContent = state.theme === 'light' ? '☾' : '☼';
  });
  $('#sidebarToggle').addEventListener('click', () => $('.sidebar').classList.toggle('collapsed'));
  document.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      createNewChat().catch(error => toast(error.message, 'error'));
    }
    if (event.key === 'Escape') $('#messageInput').blur();
  });
}
async function boot() {
  initEvents();
  checkHealth();
  try {
    await loadChats();
    setConnection(true);
  } catch (error) {
    setConnection(false);
    setNotice(`Cannot reach the backend at ${API_BASE}. Start your FastAPI server on port 8081, then refresh this page. Details: ${error.message}`);
    $('#chatList').innerHTML = '<div class="empty-small">Backend is offline.<br>Start the API and refresh.</div>';
  }
  // Live refresh: workflow chats/tasks are persisted during the synchronous build request.
  // Polling these endpoints lets the UI show agent handoffs before the final Manager reply arrives.
  state.pollingTimer = setInterval(async () => {
    await checkHealth();
    if (state.currentView === 'chat' && state.activeChatId) await loadMessages({ silent: true });
  }, 2200);
  state.activityTimer = setInterval(refreshWorkflowActivity, 1800);
  refreshWorkflowActivity();
}
boot();
