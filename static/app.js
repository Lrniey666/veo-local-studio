const state = {
  conversations: [],
  activeConversationId: null,
  commands: [],
  sourceCommandId: null,
  theme: localStorage.getItem("theme") || "dark",
};

const $ = (id) => document.getElementById(id);
document.documentElement.setAttribute("data-theme", state.theme);

async function api(url, options = {}) {
  const res = await fetch(url, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || "API request failed");
  return body;
}

function setStatus(text, isError = false) {
  const el = $("generateStatus");
  el.textContent = text;
  el.className = isError ? "small status-error" : "small";
}

function renderConversations() {
  const list = $("conversationList");
  list.innerHTML = "";
  state.conversations.forEach((c) => {
    const el = document.createElement("button");
    el.className = `conversation-item ${c.id === state.activeConversationId ? "active" : ""}`;
    el.textContent = c.title;
    el.onclick = () => setActiveConversation(c.id);
    list.appendChild(el);
  });
}

function renderHistory() {
  const root = $("historyList");
  root.innerHTML = "";
  state.commands.forEach((cmd) => {
    const box = document.createElement("div");
    box.className = "history-item";
    const statusClass = cmd.status === "done" ? "status-done" : cmd.status === "error" ? "status-error" : "";
    const videoLink = cmd.output_video_path
      ? `<a class="video-link" href="${cmd.output_video_path}" target="_blank">${cmd.output_video_path}</a>`
      : "-";
    box.innerHTML = `
      <div><strong>#${cmd.id}</strong> <span class="${statusClass}">${cmd.status}</span></div>
      <div class="small">${new Date(cmd.created_at).toLocaleString()}</div>
      <div>${cmd.prompt}</div>
      <div class="small">圖片 ${cmd.image_paths.length} 張 | ${cmd.duration_seconds}s | ${cmd.aspect_ratio} | ${cmd.quality}</div>
      <div class="small">影片：${videoLink}</div>
      ${cmd.error_message ? `<div class="status-error">${cmd.error_message}</div>` : ""}
      <button class="btn">載入此命令並再生成</button>
    `;
    box.querySelector("button").onclick = () => {
      $("promptInput").value = cmd.prompt;
      $("durationSelect").value = String(cmd.duration_seconds);
      $("aspectSelect").value = cmd.aspect_ratio;
      $("qualitySelect").value = cmd.quality;
      state.sourceCommandId = cmd.id;
      setStatus(`已載入命令 #${cmd.id}，可修改後再次生成`);
    };
    root.appendChild(box);
  });
}

async function loadConversations() {
  state.conversations = await api("/api/conversations");
  if (!state.activeConversationId && state.conversations.length > 0) {
    state.activeConversationId = state.conversations[0].id;
  }
  renderConversations();
  if (state.activeConversationId) {
    await loadCommands(state.activeConversationId);
  }
}

async function setActiveConversation(id) {
  state.activeConversationId = id;
  const item = state.conversations.find((c) => c.id === id);
  $("currentConversationTitle").textContent = item?.title || "未命名對話";
  renderConversations();
  await loadCommands(id);
}

async function loadCommands(conversationId) {
  state.commands = await api(`/api/conversations/${conversationId}/commands`);
  renderHistory();
}

async function createConversation() {
  const title = `對話 ${new Date().toLocaleString()}`;
  await api("/api/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  await loadConversations();
}

async function saveConfig() {
  const payload = {
    veo_api_base: $("apiBase").value.trim(),
    veo_api_key: $("apiKey").value.trim(),
    veo_model: $("modelName").value.trim() || "veo-3.1",
    max_image_inputs: Number($("maxImageInputs").value || "8"),
    discord_enabled: $("discordEnabled").checked,
    discord_bot_token: $("discordToken").value.trim(),
  };
  await api("/api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  setStatus("設定已儲存");
  await loadConfig();
}

async function loadConfig() {
  const cfg = await api("/api/config");
  $("apiBase").value = cfg.veo_api_base || "";
  $("modelName").value = cfg.veo_model || "veo-3.1";
  $("maxImageInputs").value = cfg.max_image_inputs || 8;
  $("imageInput").setAttribute("data-max-images", String(cfg.max_image_inputs || 8));
  $("discordEnabled").checked = !!cfg.discord_enabled;
  $("maskedKeyText").textContent = cfg.veo_api_key_masked
    ? `目前已存 API Key: ${cfg.veo_api_key_masked}`
    : "目前尚未存 API Key";
}

async function generate() {
  if (!state.activeConversationId) {
    throw new Error("請先建立或選擇對話");
  }
  const form = new FormData();
  form.append("conversation_id", String(state.activeConversationId));
  form.append("prompt", $("promptInput").value.trim());
  form.append("duration_seconds", $("durationSelect").value);
  form.append("aspect_ratio", $("aspectSelect").value);
  form.append("quality", $("qualitySelect").value);
  if (state.sourceCommandId) {
    form.append("source_command_id", String(state.sourceCommandId));
  }
  const files = $("imageInput").files;
  const maxImages = Number($("imageInput").getAttribute("data-max-images") || "8");
  if (files.length > maxImages) {
    throw new Error(`圖片數量不可超過 ${maxImages} 張`);
  }
  for (const file of files) {
    form.append("images", file);
  }

  setStatus("生成中，請稍候...");
  const res = await api("/api/generate", { method: "POST", body: form });
  if (res.status === "done") {
    setStatus("生成完成");
  } else {
    setStatus(res.error_message || "生成失敗", true);
  }
  state.sourceCommandId = null;
  $("imageInput").value = "";
  await loadCommands(state.activeConversationId);
}

function toggleTheme() {
  state.theme = state.theme === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", state.theme);
  localStorage.setItem("theme", state.theme);
}

$("newConversationBtn").onclick = createConversation;
$("saveConfigBtn").onclick = () => saveConfig().catch((e) => setStatus(e.message, true));
$("generateBtn").onclick = () => generate().catch((e) => setStatus(e.message, true));
$("themeBtn").onclick = toggleTheme;

loadConfig()
  .then(loadConversations)
  .catch((e) => setStatus(e.message, true));
