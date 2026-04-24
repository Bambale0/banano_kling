const tg = window.Telegram?.WebApp;

const quickActions = [
  {
    action: "create_image",
    icon: "🖼",
    title: "Открыть фото-флоу в чате",
    description: "Живой FSM-экран с клавиатурами бота.",
  },
  {
    action: "create_video",
    icon: "🎬",
    title: "Открыть видео-флоу в чате",
    description: "Если удобнее продолжать в Telegram.",
  },
  {
    action: "show_balance",
    icon: "🍌",
    title: "Баланс и пакеты",
    description: "Текущий баланс и пополнение.",
  },
  {
    action: "show_ai_assistant",
    icon: "🤖",
    title: "AI-помощник",
    description: "Вопросы по моделям, промптам и настройкам.",
  },
];

const serviceActions = [
  {
    action: "photo_prompt",
    icon: "📸",
    title: "Промпт по фото",
    description: "Разбор фото и генерация prompt в чате.",
  },
  {
    action: "open_edit_hub",
    icon: "✏️",
    title: "Изменить фото",
    description: "Edit-сценарии и работа с исходниками.",
  },
  {
    action: "open_animate_hub",
    icon: "🎞",
    title: "Оживить",
    description: "Переход в сценарии анимации.",
  },
  {
    action: "open_batch_edit",
    icon: "🧩",
    title: "Batch Edit",
    description: "Пакетное редактирование референсов.",
  },
  {
    action: "show_support",
    icon: "💬",
    title: "Поддержка",
    description: "Контакт и помощь по сложным кейсам.",
  },
  {
    action: "show_partner",
    icon: "🤝",
    title: "Партнёрам",
    description: "Рефералка, статистика и оферта.",
  },
  {
    action: "open_more_menu",
    icon: "⋯",
    title: "Ещё",
    description: "Дополнительные экраны бота.",
  },
];

const state = {
  bootstrap: null,
  imageAssets: [],
  videoStartAsset: null,
  videoImageRefs: [],
  videoAssets: [],
  selectedTaskId: null,
  taskPollTimer: null,
};

const basePath = window.location.pathname.replace(/\/$/, "");
const apiPath = (suffix) => `${basePath}/api/${suffix}`;

function $(id) {
  return document.getElementById(id);
}

function makeId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `id_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function nowLabel() {
  return new Date().toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function callApi(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

async function uploadAsset(fileKind, file) {
  const formData = new FormData();
  formData.append("init_data", tg?.initData || "");
  formData.append("file_kind", fileKind);
  formData.append("file", file);

  const response = await fetch(apiPath("upload"), {
    method: "POST",
    body: formData,
  });
  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data.error || "Upload failed");
  }
  return data;
}

function renderActions(target, actions) {
  const template = $("actionCardTemplate");
  target.innerHTML = "";

  for (const item of actions) {
    if (item.action === "show_admin" && !state.bootstrap?.is_admin) {
      continue;
    }
    const fragment = template.content.cloneNode(true);
    const button = fragment.querySelector(".action-card");
    fragment.querySelector(".action-icon").textContent = item.icon;
    fragment.querySelector(".action-title").textContent = item.title;
    fragment.querySelector(".action-description").textContent = item.description;
    button.addEventListener("click", () => runAction(item.action));
    target.appendChild(fragment);
  }

  if (state.bootstrap?.is_admin) {
    const fragment = template.content.cloneNode(true);
    const button = fragment.querySelector(".action-card");
    fragment.querySelector(".action-icon").textContent = "🛠";
    fragment.querySelector(".action-title").textContent = "Админка";
    fragment.querySelector(".action-description").textContent =
      "Откроет реальную админ-панель в чате.";
    button.addEventListener("click", () => runAction("show_admin"));
    target.appendChild(fragment);
  }
}

function activateTab(tabName) {
  for (const button of document.querySelectorAll(".tab")) {
    button.classList.toggle("is-active", button.dataset.tab === tabName);
  }
  for (const panel of document.querySelectorAll(".panel")) {
    panel.classList.toggle("is-active", panel.dataset.panel === tabName);
  }
}

function renderModelSelect(select, items, key = "id", label = "label") {
  select.innerHTML = items
    .map((item) => `<option value="${item[key]}">${item[label]}</option>`)
    .join("");
}

function findImageModel(modelId) {
  return state.bootstrap?.image_models?.find((item) => item.id === modelId);
}

function findVideoModel(modelId) {
  return state.bootstrap?.video_models?.find((item) => item.id === modelId);
}

function renderSelectOptions(select, items) {
  select.innerHTML = items
    .map((item) => `<option value="${item}">${item}</option>`)
    .join("");
}

function renderAssetList(targetId, items, removeHandler) {
  const target = $(targetId);
  const template = $("assetTagTemplate");
  target.innerHTML = "";
  for (const item of items) {
    const fragment = template.content.cloneNode(true);
    fragment.querySelector(".asset-tag__name").textContent = item.filename;
    fragment
      .querySelector(".asset-tag__remove")
      .addEventListener("click", () => removeHandler(item.id));
    target.appendChild(fragment);
  }
}

function renderTaskList(tasks) {
  const target = $("taskList");
  if (!tasks?.length) {
    target.innerHTML =
      '<div class="task-card empty">Пока нет задач. Запустите первую генерацию во вкладках Фото или Видео.</div>';
    $("taskDetailCard").innerHTML =
      '<div class="task-detail-empty">Выберите задачу в списке слева, чтобы увидеть детали и live-статус.</div>';
    return;
  }

  target.innerHTML = tasks
    .map((task) => {
      const badgeClass =
        task.status === "completed"
          ? "is-done"
          : task.status === "failed"
            ? "is-failed"
            : "is-pending";
      const media = task.result_url
        ? `<a class="task-link" href="${task.result_url}" target="_blank" rel="noreferrer">Открыть результат</a>`
        : '<span class="task-link muted">Результат ещё не готов</span>';
      return `
        <article class="task-card ${state.selectedTaskId === task.task_id ? "is-active" : ""}" data-task-id="${task.task_id}">
          <div class="task-head">
            <strong>${task.model_label}</strong>
            <span class="status-badge ${badgeClass}">${task.status}</span>
          </div>
          <p class="task-meta">${task.type === "image" ? "Фото" : "Видео"} • ${task.aspect_ratio || "—"} • ${task.cost}🍌</p>
          <p class="task-prompt">${task.prompt_preview || "Без prompt"}</p>
          <div class="task-foot">
            <span>${task.created_at}</span>
            ${media}
          </div>
        </article>
      `;
    })
    .join("");

  for (const card of target.querySelectorAll("[data-task-id]")) {
    card.addEventListener("click", () => openTaskDetail(card.dataset.taskId));
  }
}

function stopTaskPolling() {
  if (state.taskPollTimer) {
    window.clearInterval(state.taskPollTimer);
    state.taskPollTimer = null;
  }
}

function renderTaskDetail(task) {
  const badgeClass =
    task.status === "completed"
      ? "is-done"
      : task.status === "failed"
        ? "is-failed"
        : "is-pending";
  const media =
    task.result_url && task.type === "image"
      ? `<img class="result-media task-detail-media" src="${task.result_url}" alt="Task result" />`
      : task.result_url && task.type === "video"
        ? `<video class="result-media task-detail-media" controls playsinline src="${task.result_url}"></video>`
        : "";

  const refs =
    task.request_data?.reference_images?.length ||
    task.request_data?.v_reference_videos?.length ||
    0;

  $("taskDetailCard").innerHTML = `
    <div class="task-detail-head">
      <div>
        <p class="result-title">${task.model_label}</p>
        <p class="task-meta">${task.type === "image" ? "Фото" : "Видео"} • ${task.created_at}</p>
      </div>
      <span class="status-badge ${badgeClass}">${task.status}</span>
    </div>
    <div class="task-detail-meta">
      <div class="task-detail-row"><span>Task ID</span><code>${task.task_id}</code></div>
      <div class="task-detail-row"><span>Формат</span><strong>${task.aspect_ratio || "—"}</strong></div>
      <div class="task-detail-row"><span>Стоимость</span><strong>${task.cost}🍌</strong></div>
      <div class="task-detail-row"><span>Длительность</span><strong>${task.duration ? `${task.duration} сек` : "—"}</strong></div>
      <div class="task-detail-row"><span>Референсы</span><strong>${refs}</strong></div>
      ${
        task.result_url
          ? `<div class="task-detail-row"><span>Результат</span><a class="task-link" href="${task.result_url}" target="_blank" rel="noreferrer">Открыть оригинал</a></div>`
          : ""
      }
    </div>
    <div class="task-detail-prompt">${task.prompt || "Без prompt"}</div>
    ${media}
  `;
}

async function fetchTaskDetail(taskId) {
  const data = await callApi(apiPath("task-detail"), {
    init_data: tg?.initData || "",
    task_id: taskId,
  });
  return data.task;
}

async function openTaskDetail(taskId) {
  state.selectedTaskId = taskId;
  renderTaskList(state.bootstrap?.recent_tasks || []);
  $("taskDetailCard").innerHTML = '<div class="task-detail-empty">Загружаю детали задачи…</div>';
  stopTaskPolling();

  try {
    const task = await fetchTaskDetail(taskId);
    renderTaskDetail(task);
    if (task.status !== "completed" && task.status !== "failed") {
      state.taskPollTimer = window.setInterval(async () => {
        try {
          const refreshedTask = await fetchTaskDetail(taskId);
          renderTaskDetail(refreshedTask);
          await refreshDashboard({ preserveSelection: true, silentTaskRefresh: true });
          if (refreshedTask.status === "completed" || refreshedTask.status === "failed") {
            stopTaskPolling();
          }
        } catch (error) {
          console.error(error);
          stopTaskPolling();
        }
      }, 5000);
    }
  } catch (error) {
    $("taskDetailCard").innerHTML = `<div class="task-detail-empty">${error.message}</div>`;
  }
}

function renderImageSummary() {
  const modelId = $("imageModel").value;
  const model = findImageModel(modelId);
  const ratio = $("imageRatio").value;
  const prompt = $("imagePrompt").value.trim();
  const refs = state.imageAssets.length;

  $("imageSummary").innerHTML = `
    <div class="summary-row"><span>Модель</span><strong>${model?.label || "—"}</strong></div>
    <div class="summary-row"><span>Формат</span><strong>${ratio || "—"}</strong></div>
    <div class="summary-row"><span>Референсы</span><strong>${refs}</strong></div>
    <div class="summary-row"><span>Prompt</span><strong>${prompt ? `${prompt.slice(0, 90)}${prompt.length > 90 ? "…" : ""}` : "Не заполнен"}</strong></div>
  `;
}

function renderVideoSummary() {
  const modelId = $("videoModel").value;
  const model = findVideoModel(modelId);
  const mode = $("videoType").value;
  const duration = $("videoDuration").value;
  const ratio = $("videoRatio").value;
  const prompt = $("videoPrompt").value.trim();

  $("videoSummary").innerHTML = `
    <div class="summary-row"><span>Модель</span><strong>${model?.label || "—"}</strong></div>
    <div class="summary-row"><span>Режим</span><strong>${mode}</strong></div>
    <div class="summary-row"><span>Формат</span><strong>${ratio || "—"}</strong></div>
    <div class="summary-row"><span>Длительность</span><strong>${duration || "—"} сек</strong></div>
    <div class="summary-row"><span>Стартовое фото</span><strong>${state.videoStartAsset ? 1 : 0}</strong></div>
    <div class="summary-row"><span>Фото refs</span><strong>${state.videoImageRefs.length}</strong></div>
    <div class="summary-row"><span>Видео refs</span><strong>${state.videoAssets.length}</strong></div>
    <div class="summary-row"><span>Prompt</span><strong>${prompt ? `${prompt.slice(0, 90)}${prompt.length > 90 ? "…" : ""}` : "Не заполнен"}</strong></div>
  `;
}

function updateImageModelView() {
  const model = findImageModel($("imageModel").value);
  if (!model) {
    return;
  }
  renderSelectOptions($("imageRatio"), model.ratios);
  $("imageUploadHint").textContent = model.requires_reference
    ? `Этой модели нужен исходник. Можно загрузить до ${model.max_references} изображений.`
    : `Можно загрузить до ${model.max_references} изображений.`;
  $("imageCost").textContent = `Стоимость: ${model.cost}🍌`;
  renderImageSummary();
}

function updateVideoModelView() {
  const model = findVideoModel($("videoModel").value);
  if (!model) {
    return;
  }
  renderSelectOptions($("videoRatio"), model.ratios);
  renderSelectOptions($("videoDuration"), model.durations);

  const modeSelect = $("videoType");
  const currentMode = modeSelect.value;
  const allowed = new Set(model.supports);
  for (const option of modeSelect.options) {
    option.disabled = !allowed.has(option.value);
  }
  if (!allowed.has(currentMode)) {
    modeSelect.value = model.supports[0];
  }
  updateVideoModeView();
  const cost = model.costs?.[$("videoDuration").value] || model.costs?.[String(model.durations[0])] || "—";
  $("videoCost").textContent = `Стоимость: ${cost}🍌`;
  renderVideoSummary();
}

function updateVideoModeView() {
  const mode = $("videoType").value;
  $("videoImageUploader").classList.toggle("is-hidden", mode !== "imgtxt");
  $("videoReferenceUploader").classList.toggle("is-hidden", mode !== "video");
  renderVideoSummary();
}

function syncHeader(data) {
  $("userName").textContent = data.first_name || "Пользователь";
  $("creditsValue").textContent = data.credits;
  $("lastSync").textContent = nowLabel();
}

function setResultCard(targetId, html, tone = "") {
  const node = $(targetId);
  node.className = `result-card ${tone}`.trim();
  node.innerHTML = html;
}

async function bootstrap() {
  tg?.ready();
  tg?.expand();
  tg?.MainButton?.hide();

  const data = await callApi(apiPath("bootstrap"), {
    init_data: tg?.initData || "",
  });
  state.bootstrap = data;
  syncHeader(data);

  renderActions($("quickActions"), quickActions);
  renderActions($("secondaryActions"), serviceActions);
  renderTaskList(data.recent_tasks || []);

  renderModelSelect($("imageModel"), data.image_models || []);
  renderModelSelect($("videoModel"), data.video_models || []);
  updateImageModelView();
  updateVideoModelView();
}

async function refreshDashboard(options = {}) {
  const data = await callApi(apiPath("bootstrap"), {
    init_data: tg?.initData || "",
  });
  state.bootstrap = data;
  syncHeader(data);
  renderTaskList(data.recent_tasks || []);
  renderActions($("quickActions"), quickActions);
  renderActions($("secondaryActions"), serviceActions);
  updateImageModelView();
  updateVideoModelView();

  if (options.preserveSelection && state.selectedTaskId) {
    const exists = (data.recent_tasks || []).some((task) => task.task_id === state.selectedTaskId);
    if (exists && !options.silentTaskRefresh) {
      await openTaskDetail(state.selectedTaskId);
    }
  }
}

async function runAction(action) {
  try {
    tg?.HapticFeedback?.impactOccurred("light");
    await callApi(apiPath("action"), {
      init_data: tg?.initData || "",
      action,
    });
    tg?.showPopup?.({
      title: "Готово",
      message: "Экран отправлен в чат бота.",
      buttons: [{ type: "ok" }],
    });
  } catch (error) {
    console.error(error);
    tg?.showAlert?.(error.message || "Не удалось выполнить действие");
  }
}

async function handleImageUpload(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) {
    return;
  }
  const model = findImageModel($("imageModel").value);
  const remaining = Math.max((model?.max_references || 0) - state.imageAssets.length, 0);
  const queue = files.slice(0, remaining);
  $("imageStatusText").textContent = "Загружаю референсы…";

  try {
    for (const file of queue) {
      const uploaded = await uploadAsset("image_reference", file);
      state.imageAssets.push({
        id: makeId(),
        url: uploaded.url,
        filename: uploaded.filename,
      });
    }
    $("imageStatusText").textContent = "Референсы загружены.";
  } catch (error) {
    $("imageStatusText").textContent = error.message;
  } finally {
    event.target.value = "";
    renderAssetList("imageAssets", state.imageAssets, removeImageAsset);
    renderImageSummary();
  }
}

function removeImageAsset(id) {
  state.imageAssets = state.imageAssets.filter((item) => item.id !== id);
  renderAssetList("imageAssets", state.imageAssets, removeImageAsset);
  renderImageSummary();
}

function removeVideoImageAsset(id) {
  if (state.videoStartAsset?.id === id) {
    state.videoStartAsset = null;
  } else {
    state.videoImageRefs = state.videoImageRefs.filter((item) => item.id !== id);
  }
  renderAssetList(
    "videoImageAssets",
    [state.videoStartAsset, ...state.videoImageRefs].filter(Boolean),
    removeVideoImageAsset
  );
  renderVideoSummary();
}

function removeVideoAsset(id) {
  state.videoAssets = state.videoAssets.filter((item) => item.id !== id);
  renderAssetList("videoAssets", state.videoAssets, removeVideoAsset);
  renderVideoSummary();
}

async function handleVideoImageUpload(event) {
  const file = event.target.files?.[0];
  if (!file) {
    return;
  }
  $("videoStatusText").textContent = "Загружаю стартовое фото…";
  try {
    const uploaded = await uploadAsset("image_reference", file);
    state.videoStartAsset = {
      id: makeId(),
      url: uploaded.url,
      filename: `Старт: ${uploaded.filename}`,
    };
    $("videoStatusText").textContent = "Стартовое фото загружено.";
  } catch (error) {
    $("videoStatusText").textContent = error.message;
  } finally {
    event.target.value = "";
    renderAssetList(
      "videoImageAssets",
      [state.videoStartAsset, ...state.videoImageRefs].filter(Boolean),
      removeVideoImageAsset
    );
    renderVideoSummary();
  }
}

async function handleVideoRefsUpload(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) {
    return;
  }
  $("videoStatusText").textContent = "Загружаю фото-референсы…";
  try {
    for (const file of files.slice(0, Math.max(12 - state.videoImageRefs.length, 0))) {
      const uploaded = await uploadAsset("image_reference", file);
      state.videoImageRefs.push({
        id: makeId(),
        url: uploaded.url,
        filename: `Ref: ${uploaded.filename}`,
      });
    }
    $("videoStatusText").textContent = "Фото-референсы загружены.";
  } catch (error) {
    $("videoStatusText").textContent = error.message;
  } finally {
    event.target.value = "";
    renderAssetList(
      "videoImageAssets",
      [state.videoStartAsset, ...state.videoImageRefs].filter(Boolean),
      removeVideoImageAsset
    );
    renderVideoSummary();
  }
}

async function handleVideoUpload(event) {
  const files = Array.from(event.target.files || []);
  if (!files.length) {
    return;
  }
  $("videoStatusText").textContent = "Загружаю видео-референсы…";
  try {
    for (const file of files.slice(0, Math.max(5 - state.videoAssets.length, 0))) {
      const uploaded = await uploadAsset("video_reference", file);
      state.videoAssets.push({
        id: makeId(),
        url: uploaded.url,
        filename: uploaded.filename,
      });
    }
    $("videoStatusText").textContent = "Видео-референсы загружены.";
  } catch (error) {
    $("videoStatusText").textContent = error.message;
  } finally {
    event.target.value = "";
    renderAssetList("videoAssets", state.videoAssets, removeVideoAsset);
    renderVideoSummary();
  }
}

async function submitImage() {
  const payload = {
    init_data: tg?.initData || "",
    img_service: $("imageModel").value,
    img_ratio: $("imageRatio").value,
    img_quality: $("imageQuality").value,
    prompt: $("imagePrompt").value.trim(),
    reference_images: state.imageAssets.map((item) => item.url),
  };

  setResultCard("imageResult", "<p>Запускаю фото задачу…</p>");
  try {
    const result = await callApi(apiPath("generate-image"), payload);
    $("creditsValue").textContent = result.credits;
    const body =
      result.status === "done" && result.saved_url
        ? `
          <p class="result-title">Фото готово</p>
          <img class="result-media" src="${result.saved_url}" alt="Generated image" />
          <p>Модель: ${result.model_label}</p>
          <p>Стоимость: ${result.cost}🍌</p>
        `
        : `
          <p class="result-title">Задача принята</p>
          <p>Модель: ${result.model_label}</p>
          <p>Task ID: <code>${result.task_id}</code></p>
          <p>Результат придёт в чат и появится в истории после обновления.</p>
        `;
    setResultCard("imageResult", body, "is-success");
    $("imageStatusText").textContent = "Фото задача успешно запущена.";
    await refreshDashboard();
    if (result.task_id) {
      await openTaskDetail(result.task_id);
    }
  } catch (error) {
    setResultCard("imageResult", `<p class="result-title">Ошибка</p><p>${error.message}</p>`, "is-error");
    $("imageStatusText").textContent = error.message;
  }
}

async function submitVideo() {
  const payload = {
    init_data: tg?.initData || "",
    v_model: $("videoModel").value,
    v_type: $("videoType").value,
    v_ratio: $("videoRatio").value,
    v_duration: Number($("videoDuration").value),
    prompt: $("videoPrompt").value.trim(),
    v_image_url: state.videoStartAsset?.url || "",
    reference_images: state.videoImageRefs.map((item) => item.url),
    v_reference_videos: state.videoAssets.map((item) => item.url),
  };

  setResultCard("videoResult", "<p>Запускаю видео задачу…</p>");
  try {
    const result = await callApi(apiPath("generate-video"), payload);
    $("creditsValue").textContent = result.credits;
    const body =
      result.status === "done" && result.saved_url
        ? `
          <p class="result-title">Видео готово</p>
          <video class="result-media" controls playsinline src="${result.saved_url}"></video>
          <p>Модель: ${result.model_label}</p>
          <p>Стоимость: ${result.cost}🍌</p>
        `
        : `
          <p class="result-title">Видео задача запущена</p>
          <p>Модель: ${result.model_label}</p>
          <p>Task ID: <code>${result.task_id}</code></p>
          <p>Результат придёт в чат и подтянется в историю.</p>
        `;
    setResultCard("videoResult", body, "is-success");
    $("videoStatusText").textContent = "Видео задача успешно запущена.";
    await refreshDashboard();
    if (result.task_id) {
      await openTaskDetail(result.task_id);
    }
  } catch (error) {
    setResultCard("videoResult", `<p class="result-title">Ошибка</p><p>${error.message}</p>`, "is-error");
    $("videoStatusText").textContent = error.message;
  }
}

function bindEvents() {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => activateTab(tab.dataset.tab));
  }

  $("refreshButton").addEventListener("click", refreshDashboard);
  $("imageModel").addEventListener("change", updateImageModelView);
  $("imageRatio").addEventListener("change", renderImageSummary);
  $("imagePrompt").addEventListener("input", renderImageSummary);
  $("imageQuality").addEventListener("change", renderImageSummary);
  $("imageUploadInput").addEventListener("change", handleImageUpload);
  $("imageSubmit").addEventListener("click", submitImage);

  $("videoModel").addEventListener("change", updateVideoModelView);
  $("videoType").addEventListener("change", updateVideoModeView);
  $("videoRatio").addEventListener("change", renderVideoSummary);
  $("videoDuration").addEventListener("change", updateVideoModelView);
  $("videoPrompt").addEventListener("input", renderVideoSummary);
  $("videoImageInput").addEventListener("change", handleVideoImageUpload);
  $("videoRefsInput").addEventListener("change", handleVideoRefsUpload);
  $("videoUploadInput").addEventListener("change", handleVideoUpload);
  $("videoSubmit").addEventListener("click", submitVideo);
}

bindEvents();

bootstrap().catch((error) => {
  console.error(error);
  $("userName").textContent = "Ошибка авторизации";
  $("creditsValue").textContent = "—";
  $("lastSync").textContent = "—";
  setResultCard("imageResult", `<p class="result-title">Ошибка</p><p>${error.message}</p>`, "is-error");
  setResultCard("videoResult", `<p class="result-title">Ошибка</p><p>${error.message}</p>`, "is-error");
});

// Motion Control Mini App flow
state.motionImageAsset = state.motionImageAsset || null;
state.motionVideoAsset = state.motionVideoAsset || null;

function renderMotionAssets() {
  const items = [];
  if (state.motionImageAsset) {
    items.push({
      ...state.motionImageAsset,
      filename: `Фото: ${state.motionImageAsset.filename}`,
    });
  }
  if (state.motionVideoAsset) {
    items.push({
      ...state.motionVideoAsset,
      filename: `Видео: ${state.motionVideoAsset.filename}`,
    });
  }
  renderAssetList("motionAssets", items, removeMotionAsset);
  updateMotionSummary();
}

function removeMotionAsset(id) {
  if (state.motionImageAsset?.id === id) {
    state.motionImageAsset = null;
  }
  if (state.motionVideoAsset?.id === id) {
    state.motionVideoAsset = null;
  }
  renderMotionAssets();
}

function updateMotionSummary() {
  const summary = $("motionSummary");
  if (!summary) return;

  const mode = $("motionMode")?.value || "720p";
  const direction = $("motionDirection")?.value || "video";
  const prompt = $("motionPrompt")?.value.trim() || "—";

  summary.innerHTML = `
    <div class="summary-row"><span>Режим</span><strong>Kling 2.6 Motion Control</strong></div>
    <div class="summary-row"><span>Качество</span><strong>${mode}</strong></div>
    <div class="summary-row"><span>Ориентация</span><strong>${direction === "image" ? "как на фото" : "как в видео"}</strong></div>
    <div class="summary-row"><span>Фото персонажа</span><strong>${state.motionImageAsset ? "загружено" : "нет"}</strong></div>
    <div class="summary-row"><span>Видео движения</span><strong>${state.motionVideoAsset ? "загружено" : "нет"}</strong></div>
    <div class="summary-row"><span>Промпт</span><strong>${prompt}</strong></div>
  `;
}

async function handleMotionImageUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  $("motionStatusText").textContent = "Загружаю фото персонажа…";
  try {
    const uploaded = await uploadAsset("image_reference", file);
    state.motionImageAsset = {
      id: makeId(),
      url: uploaded.url,
      filename: uploaded.filename,
    };
    $("motionStatusText").textContent = "Фото персонажа загружено.";
  } catch (error) {
    $("motionStatusText").textContent = error.message;
  } finally {
    event.target.value = "";
    renderMotionAssets();
  }
}

async function handleMotionVideoUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  $("motionStatusText").textContent = "Загружаю видео движения…";
  try {
    const uploaded = await uploadAsset("video_reference", file);
    state.motionVideoAsset = {
      id: makeId(),
      url: uploaded.url,
      filename: uploaded.filename,
    };
    $("motionStatusText").textContent = "Видео движения загружено.";
  } catch (error) {
    $("motionStatusText").textContent = error.message;
  } finally {
    event.target.value = "";
    renderMotionAssets();
  }
}

async function submitMotion() {
  const resultCard = $("motionResult");
  const statusText = $("motionStatusText");

  if (!state.motionImageAsset) {
    statusText.textContent = "Загрузите фото персонажа.";
    return;
  }
  if (!state.motionVideoAsset) {
    statusText.textContent = "Загрузите видео движения.";
    return;
  }

  statusText.textContent = "Запускаю Motion Control…";
  resultCard.innerHTML = '<div class="result-placeholder">Создаю задачу Motion Control…</div>';

  try {
    const data = await callApi(apiPath("generate-motion"), {
      init_data: tg?.initData || "",
      motion_image_url: state.motionImageAsset.url,
      motion_video_url: state.motionVideoAsset.url,
      motion_mode: $("motionMode").value,
      motion_direction: $("motionDirection").value,
      prompt: $("motionPrompt").value.trim(),
    });

    $("creditsValue").textContent = data.credits ?? $("creditsValue").textContent;
    statusText.textContent = `Задача запущена. Списано ${data.cost}🍌`;

    resultCard.innerHTML = `
      <div class="result-success">
        <p class="result-title">Motion Control запущен</p>
        <p>ID: <code>${data.task_id}</code></p>
        <p>Статус: ${data.status}</p>
      </div>
    `;

    state.selectedTaskId = data.task_id;
    await refreshBootstrap();
    startTaskPolling(data.task_id);
  } catch (error) {
    statusText.textContent = error.message;
    resultCard.innerHTML = `<div class="result-error">${error.message}</div>`;
  }
}

function bindMotionControls() {
  $("motionImageInput")?.addEventListener("change", handleMotionImageUpload);
  $("motionVideoInput")?.addEventListener("change", handleMotionVideoUpload);
  $("motionSubmit")?.addEventListener("click", submitMotion);
  $("motionMode")?.addEventListener("change", updateMotionSummary);
  $("motionDirection")?.addEventListener("change", updateMotionSummary);
  $("motionPrompt")?.addEventListener("input", updateMotionSummary);
  updateMotionSummary();
}

bindMotionControls();
