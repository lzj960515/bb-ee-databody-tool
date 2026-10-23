/* 本地桌面界面；游戏规则与存档事务由 Python 负责。 */
(function () {
  "use strict";
  const { BodyEditor } = globalThis.DataBodyModel;
  const elements = [
    "全部",
    "火系",
    "冰系",
    "电系",
    "毒系",
    "暗系",
    "光系",
    "刃系",
  ];
  const colors = {
    火系: "var(--fire)",
    冰系: "var(--ice)",
    电系: "var(--thunder)",
    毒系: "var(--poison)",
    暗系: "var(--dark)",
    光系: "var(--light)",
    刃系: "var(--blade)",
  };
  const qualityNames = { 1: "白色", 2: "蓝色", 3: "紫色", 4: "金色" };
  const tiers = { 1: "基础", 2: "强化", 3: "进阶", 4: "双重" };
  const workspace = document.querySelector("#workspace");
  const modal = document.querySelector("#modal");
  const state = {
    mode: "build",
    buildId: null,
    guide: null,
    builds: [],
    catalog: null,
    strategies: new Map(),
    drafts: new Map(),
    single: new BodyEditor(1),
    element: "全部",
    query: "",
    saves: [],
    save: null,
    selectedPath: null,
    busy: false,
    guideRevision: 0,
    picker: null,
    confirm: null,
  };
  let toastTimer;
  const clean = (value) =>
    String(value ?? "").replace(/<\/?(?:color|size|b|i|u)(?:=[^>]*)?>/gi, "");
  const escape = (value) =>
    clean(value).replace(
      /[&<>"']/g,
      (char) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[char],
    );
  const elementColor = (category) =>
    colors[
      elements.find(
        (name) => name !== "全部" && String(category).includes(name),
      )
    ] || "var(--blue)";
  function strategy(id) {
    return state.strategies.get(Number(id));
  }
  function editor() {
    return state.mode === "single"
      ? state.single
      : state.drafts.get(state.buildId);
  }
  function name(id) {
    return strategy(id)?.name || "未选择";
  }
  function toast(message, error = false) {
    const element = document.querySelector("#toast");
    clearTimeout(toastTimer);
    element.textContent = message;
    element.className = error ? "error" : "";
    element.hidden = false;
    toastTimer = setTimeout(
      () => {
        element.hidden = true;
      },
      error ? 7000 : 4000,
    );
  }
  async function call(method, ...args) {
    const response = await window.pywebview.api[method](...args);
    if (!response?.ok)
      throw new Error(response?.error || "操作未完成，请重试。");
    return response.data;
  }
  function tags(items) {
    return items
      .map(
        (item) =>
          `<span class="element-tag" style="--element-color:${elementColor(item)}">${escape(item)}</span>`,
      )
      .join("");
  }
  function render() {
    document
      .querySelectorAll(".nav-button")
      .forEach((button) =>
        button.classList.toggle("active", button.dataset.mode === state.mode),
      );
    if (state.mode === "single") renderSingle();
    else if (state.buildId && state.guide) renderDetail();
    else renderLibrary();
  }
  function renderLibrary() {
    workspace.innerHTML = `<section class="library"><div class="library-heading"><h1>流派玩法</h1><input class="search" id="build-search" aria-label="搜索玩法" placeholder="搜索玩法或策略" value="${escape(state.query)}"></div><div class="element-filter" aria-label="元素筛选">${elements.map((item) => `<button class="element-button ${state.element === item ? "active" : ""}" data-action="element" data-value="${item}">${item}</button>`).join("")}<span class="result-count" id="result-count"></span></div><div class="build-grid" id="build-grid"></div></section>`;
    renderBuildList();
  }
  function renderBuildList() {
    const query = state.query.trim().toLowerCase();
    const visible = state.builds.filter(
      (build) =>
        (state.element === "全部" || build.elements.includes(state.element)) &&
        `${build.title} ${build.summary}`.toLowerCase().includes(query),
    );
    document.querySelector("#result-count").textContent =
      `${visible.length} 个玩法`;
    document.querySelector("#build-grid").innerHTML = visible.length
      ? visible
          .map(
            (build) =>
              `<button class="build-card" data-action="open-build" data-id="${escape(build.id)}" style="--element-color:${elementColor(build.elements[0])}"><h2>${escape(build.title)}</h2><p>${escape(build.summary)}</p><div class="build-tags">${tags(build.elements)}<span class="enter-mark" aria-hidden="true">›</span></div></button>`,
          )
          .join("")
      : '<div class="empty-result">没有找到这个玩法，换个名称试试。</div>';
  }
  async function openBuild(id) {
    if (!state.drafts.has(id)) state.drafts.set(id, new BodyEditor(2));
    state.buildId = id;
    const revision = ++state.guideRevision;
    const guide = await call(
      "describe_build",
      id,
      state.drafts.get(id).strategyIds(),
    );
    if (revision !== state.guideRevision || state.buildId !== id) return;
    state.guide = guide;
    render();
  }
  function strategyCard(id, suggested = false) {
    const row = strategy(id);
    if (!row) return "";
    const selected = Boolean(editor().locate(id));
    const required = state.guide.required_inherited?.includes(id);
    return `<article class="strategy-card ${selected ? "selected" : ""}" data-strategy="${id}" style="--element-color:${elementColor(row.category)}"><div class="strategy-title"><h3>${escape(row.name)}</h3><span class="tier ${row.is_combined ? "combined" : ""}">${tiers[row.gradation]}</span></div><div class="strategy-card-actions"><button data-action="inspect" data-id="${id}" aria-label="查看${escape(row.name)}效果">效果</button><span class="suggested">${required ? "需继承" : suggested ? "推荐" : ""}</span><button data-action="${selected ? "unpick" : "pick"}" data-id="${id}">${selected ? "移出" : "继承"}</button></div></article>`;
  }
  function renderDetail() {
    const guide = state.guide;
    const suggested = new Set(guide.suggested_ids);
    workspace.innerHTML = `<section class="detail"><div class="detail-scroll"><div class="detail-content"><div class="detail-heading"><button class="back-button" data-action="back">‹ 返回</button><div><h1>${escape(guide.title)}</h1><p>${escape(guide.summary)}</p></div></div>${guide.chain.length ? `<div class="effect-chain">${guide.chain.map((text) => `<span class="chain-link">${escape(text)}</span>`).join('<span class="chain-arrow" aria-hidden="true">→</span>')}</div>` : ""}<div class="section-heading"><h2>最终搭配</h2><span class="muted">从下方选择四项继承</span></div><div class="lanes">${guide.lanes.map((lane) => `<section class="lane"><div class="lane-header"><span>${escape(lane.label)}</span><span class="lane-index">${lane.strategies.length ? `${lane.strategies.length} 项` : ""}</span></div><div class="lane-cards">${lane.strategies.length ? lane.strategies.map((id) => strategyCard(id, suggested.has(id))).join("") : '<div class="lane-empty">不限定</div>'}</div></section>`).join("")}</div>${guide.other_strategy_ids.length ? `<div class="extra-strategies">${guide.other_strategy_ids.map((id) => strategyCard(id, suggested.has(id))).join("")}</div>` : ""}${guide.notes.length ? `<div class="guide-notes">${guide.notes.map((note) => `<p>${escape(note)}</p>`).join("")}</div>` : ""}<section class="route-section" id="route-section">${routeHtml()}</section></div></div><aside class="inheritance-dock"><div class="dock-inner"><div class="body-pair" id="body-editors">${bodyEditorHtml(0)}${bodyEditorHtml(1)}</div><div class="dock-footer"><div id="selection-feedback" class="feedback">${feedbackHtml()}</div><span class="selection-count" id="selection-count">已选 ${editor().strategyIds().length} / 4</span><button class="primary" data-action="save" ${state.busy ? "disabled" : ""}>添加两个数据体</button></div></div></aside></section>`;
    applyFeedbackStyle();
  }
  function routeHtml() {
    const guide = state.guide,
      selected = editor().strategyIds();
    if (guide.selection.errors.length)
      return `<h2>局内怎么拿</h2><p class="feedback error">${escape([...new Set(guide.selection.errors)].join("；"))}</p>`;
    const lines = guide.steps
      .map(
        (step) =>
          `<div class="route-item"><div><strong>${escape(name(step.strategy_id))}</strong><p>${escape(strategy(step.strategy_id)?.description)}</p></div></div>`,
      )
      .join("");
    const introduction = selected.length
      ? "已带出的策略从路线中省去，其余按下面顺序补齐。"
      : "下面是完整获取顺序。选入继承后，会自动省去可以跳过的步骤。";
    return `<h2>局内怎么拿</h2><p class="route-intro">${guide.steps.length ? introduction : selected.length ? "目标策略已齐，可以在局内提升品质。" : "此玩法没有额外的获取步骤。"}</p>${lines ? `<div class="route-list">${lines}</div>` : ""}`;
  }
  function bodyEditorHtml(index) {
    const body = editor().bodies[index];
    const characters = state.catalog.characters
      .map(
        (character) =>
          `<option value="${character.id}" ${body.character_id === character.id ? "selected" : ""}>${escape(character.name)}</option>`,
      )
      .join("");
    return `<section class="body-editor"><div class="body-heading"><h3>数据体${index === 0 ? "一" : "二"}</h3><select data-field="character" data-body="${index}" aria-label="数据体${index + 1}角色"><option value="">选择角色</option>${characters}</select><select class="color-select ${body.body_quality === 4 ? "gold" : ""}" data-field="color" data-body="${index}" aria-label="数据体${index + 1}颜色"><option value="3" ${body.body_quality === 3 ? "selected" : ""}>紫色 · 600分</option><option value="4" ${body.body_quality === 4 ? "selected" : ""}>金色 · 700分</option></select></div><div class="body-slots">${body.slots.map((slot, slotIndex) => slotHtml(index, slotIndex, slot)).join("")}</div></section>`;
  }
  function slotHtml(bodyIndex, slotIndex, slot) {
    const description =
      slot && state.mode === "single"
        ? strategy(slot.id).quality_details.find(
            (item) => item.quality === slot.quality,
          ).description
        : "";
    return `<div class="body-slot ${slot ? "filled" : ""}">${slot ? "" : '<span class="slot-add" aria-hidden="true">＋</span>'}<button class="slot-main" data-action="slot" data-body="${bodyIndex}" data-slot="${slotIndex}"><strong>${slot ? escape(name(slot.id)) : `选择策略${slotIndex === 0 ? "一" : "二"}`}</strong><span>${slot ? `${qualityNames[slot.quality]}策略` : "点击选择"}</span>${description ? `<p class="slot-description">${escape(description)}</p>` : ""}</button>${slot ? `<button class="slot-remove" data-action="remove" data-body="${bodyIndex}" data-slot="${slotIndex}" aria-label="移除${escape(name(slot.id))}">×</button>` : ""}</div>`;
  }
  function feedbackHtml() {
    const selection = state.guide.selection;
    const errors = [
      ...(selection.conflicts || []),
      ...(selection.errors || []),
    ];
    if (errors.length) return escape([...new Set(errors)].join("；"));
    if (selection.missing?.length)
      return `有 ${selection.missing.length} 项继承策略等待激活，按上方局内顺序补齐即可。`;
    const count = editor().strategyIds().length;
    return count
      ? `已选 ${count} 项，${selection.active_ids.length} 项开局生效。`
      : "选择想带出的四项策略。";
  }
  function applyFeedbackStyle() {
    const node = document.querySelector("#selection-feedback");
    if (!node) return;
    const selection = state.guide.selection;
    node.classList.toggle(
      "error",
      Boolean(selection.conflicts?.length || selection.errors?.length),
    );
    node.classList.toggle(
      "warning",
      !selection.conflicts?.length &&
        !selection.errors?.length &&
        Boolean(selection.missing?.length),
    );
  }
  async function selectionChanged() {
    refreshEditors();
    if (state.mode === "single") return;
    const buildId = state.buildId,
      revision = ++state.guideRevision;
    const guide = await call("describe_build", buildId, editor().strategyIds());
    if (revision !== state.guideRevision || state.buildId !== buildId) return;
    state.guide = guide;
    if (state.mode !== "build") return;
    document.querySelector("#route-section").innerHTML = routeHtml();
    document.querySelector("#selection-feedback").innerHTML = feedbackHtml();
    applyFeedbackStyle();
    document.querySelectorAll(".strategy-card").forEach((card) => {
      const picked = Boolean(editor().locate(Number(card.dataset.strategy)));
      card.classList.toggle("selected", picked);
      const button = card.querySelector(
        "[data-action=pick],[data-action=unpick]",
      );
      button.dataset.action = picked ? "unpick" : "pick";
      button.textContent = picked ? "移出" : "继承";
    });
  }
  function refreshEditors() {
    if (state.mode === "single") {
      renderSingle();
      return;
    }
    document.querySelector("#body-editors").innerHTML =
      bodyEditorHtml(0) + bodyEditorHtml(1);
    document.querySelector("#selection-count").textContent =
      `已选 ${editor().strategyIds().length} / 4`;
  }
  function renderSingle() {
    workspace.innerHTML = `<section class="single-page"><div class="single-layout"><h1>单个数据体</h1><div class="single-form">${bodyEditorHtml(0)}<div class="dock-footer"><span class="feedback"></span><button class="primary" data-action="save" ${state.busy ? "disabled" : ""}>添加数据体</button></div></div></div></section>`;
  }
  function showModal(title, body, actions = "") {
    modal.className = "";
    document.querySelector("#modal-content").innerHTML =
      `<div class="modal-header"><h2>${escape(title)}</h2><button class="modal-close" data-action="close-modal" aria-label="关闭">×</button></div><div class="modal-body">${body}</div>${actions ? `<div class="modal-actions">${actions}</div>` : ""}`;
    if (!modal.open) modal.showModal();
  }
  function closeModal() {
    modal.close();
    state.picker = null;
    state.confirm = null;
  }
  function openPicker(body, slot) {
    const existing = editor().bodies[body].slots[slot];
    const ids =
      state.mode === "single"
        ? state.catalog.strategies.map((row) => row.id)
        : state.guide.strategy_ids;
    state.picker = {
      body,
      slot,
      ids,
      selected: existing?.id || null,
      quality: existing?.quality || 4,
      query: "",
    };
    showModal(
      `选择策略${slot === 0 ? "一" : "二"}`,
      `<div class="picker-controls"><input id="strategy-search" placeholder="搜索策略" aria-label="搜索策略"><span class="muted small">${ids.length} 项</span></div><div class="picker-layout"><div class="picker-list" id="picker-list"></div><section class="picker-detail" id="picker-detail"></section></div>`,
      `<button class="secondary" data-action="close-modal">取消</button><button class="primary" id="picker-save" data-action="picker-save">保存选择</button>`,
    );
    renderPickerList();
    renderPickerDetail();
    document.querySelector("#strategy-search").focus();
  }
  function inspectStrategy(id) {
    const existing = editor().locate(id);
    const current = existing
      ? editor().bodies[existing[0]].slots[existing[1]]
      : null;
    state.picker = {
      body: existing?.[0],
      slot: existing?.[1],
      ids: [id],
      selected: id,
      quality: current?.quality || 4,
      query: "",
    };
    showModal(
      "策略效果",
      '<section class="picker-detail strategy-inspector" id="picker-detail"></section>',
      `<button class="secondary" data-action="close-modal">关闭</button><button class="primary" id="picker-save" data-action="picker-save">${existing ? "保存品质" : "选作继承"}</button>`,
    );
    modal.className = "strategy-modal";
    renderPickerDetail();
  }
  function renderPickerList() {
    const picker = state.picker,
      query = picker.query.trim().toLowerCase();
    const visible = picker.ids
      .map(strategy)
      .filter(
        (row) =>
          row &&
          `${row.name} ${row.description} ${row.category}`
            .toLowerCase()
            .includes(query),
      );
    document.querySelector("#picker-list").innerHTML =
      visible
        .map(
          (row) =>
            `<button class="picker-row ${row.id === picker.selected ? "active" : ""}" data-action="picker-row" data-id="${row.id}"><span>${escape(row.name)}</span><span>${escape(row.category)}</span></button>`,
        )
        .join("") || '<div class="empty-result">没有找到这个策略。</div>';
  }
  function renderPickerDetail() {
    const picker = state.picker;
    document.querySelector("#picker-save").disabled = !picker.selected;
    const row = strategy(picker.selected);
    if (!row) {
      document.querySelector("#picker-detail").innerHTML =
        '<p class="muted">选择策略后查看效果。</p>';
      return;
    }
    const detail =
      row.quality_details.find((item) => item.quality === picker.quality) ||
      row.quality_details.at(-1);
    picker.quality = detail.quality;
    const prerequisites = row.true_pre
      .map((label) =>
        state.catalog.strategies
          .filter((candidate) => candidate.labels.includes(label))
          .map((candidate) => candidate.name)
          .join(" / "),
      )
      .filter(Boolean);
    document.querySelector("#picker-detail").innerHTML =
      `<h3>${escape(row.name)}</h3>${tags([row.category])}<p>${escape(detail.description)}</p><div class="quality-row"><label for="picker-quality">策略品质</label><select id="picker-quality">${row.qualities.map((quality) => `<option value="${quality}" ${quality === picker.quality ? "selected" : ""}>${qualityNames[quality]}</option>`).join("")}</select></div>${prerequisites.length ? `<div class="strategy-prerequisites">生效需要：${escape(prerequisites.join(" ＋ "))}</div>` : ""}`;
  }
  async function chooseSave(path) {
    if (state.busy) return;
    setBusy(true);
    state.save = null;
    state.selectedPath = path;
    updateSaveLabel();
    try {
      state.save = await call("load_save", path);
    } finally {
      updateSaveLabel();
      setBusy(false);
    }
  }
  async function browseSave() {
    if (state.busy) return;
    setBusy(true);
    try {
      const result = await call("browse_save");
      if (result) {
        state.save = result;
        state.selectedPath = result.path;
        updateSaveLabel();
      }
    } catch (error) {
      state.save = null;
      state.selectedPath = null;
      updateSaveLabel();
      throw error;
    } finally {
      setBusy(false);
    }
  }
  function setBusy(value) {
    state.busy = value;
    document
      .querySelectorAll(".save-controls button,.save-controls select")
      .forEach((element) => (element.disabled = value));
  }
  function updateSaveLabel() {
    const select = document.querySelector("#save-select");
    select.innerHTML =
      '<option value="">选择存档</option>' +
      state.saves
        .map(
          (save) =>
            `<option value="${escape(save.path)}">${escape(save.label)}</option>`,
        )
        .join("");
    if (
      state.selectedPath &&
      !state.saves.some((save) => save.path === state.selectedPath)
    ) {
      const option = document.createElement("option");
      option.value = state.selectedPath;
      option.textContent = state.selectedPath;
      select.append(option);
    }
    select.value = state.selectedPath || "";
    select.title = state.selectedPath || "选择目标存档";
    document.querySelector("#body-count").textContent = state.save
      ? ` ${state.save.count}`
      : "";
  }
  function showBodies() {
    if (!state.save) throw new Error("请先选择存档。");
    showModal(
      "数据体仓库",
      `<div class="bodies-toolbar"><input id="body-search" aria-label="搜索角色或策略" placeholder="搜索角色或策略"><span class="muted small">${state.save.count} / ${state.save.capacity}</span></div><div class="body-table-wrap"><table class="body-table"><thead><tr><th>角色</th><th>策略一</th><th>策略二</th></tr></thead><tbody id="bodies-rows"></tbody></table></div>`,
    );
    renderBodies("");
    document.querySelector("#body-search").focus();
  }
  function renderBodies(query) {
    const savedText = (text) =>
      clean(text).replace(
        /（品质\s+([1-4])）/g,
        (_, quality) => `（${qualityNames[quality]}）`,
      );
    const rows = state.save.bodies.filter((body) =>
      `${body.character_name} ${body.strategies.join(" ")}`
        .toLowerCase()
        .includes(query.toLowerCase()),
    );
    document.querySelector("#bodies-rows").innerHTML =
      rows
        .map(
          (body) =>
            `<tr><td>${escape(body.character_name)}</td><td>${escape(savedText(body.strategies[0] || "—"))}</td><td>${escape(savedText(body.strategies[1] || "—"))}</td></tr>`,
        )
        .join("") || '<tr><td colspan="3">没有找到数据体。</td></tr>';
  }
  async function prepareSave() {
    if (state.busy) return;
    const requests = editor().requests();
    if (!state.save) throw new Error("请先在右上角选择存档。");
    if (state.mode === "build") {
      const guide = await call(
        "describe_build",
        state.buildId,
        editor().strategyIds(),
      );
      const errors = [...guide.selection.conflicts, ...guide.selection.errors];
      if (errors.length) throw new Error([...new Set(errors)].join("；"));
    }
    state.confirm = { requests, path: state.save.path };
    const rows = requests
      .map(
        (request, index) =>
          `<div class="confirm-body"><h3>${requests.length === 1 ? "数据体" : `数据体${index === 0 ? "一" : "二"}`}：${escape(state.catalog.characters.find((row) => row.id === request.character_id).name)}</h3><p class="muted">${request.body_quality === 4 ? "金色 700分" : "紫色 600分"}</p>${request.strategy_ids.map((id, i) => `<p>${escape(name(id))}（${qualityNames[request.qualities[i]]}）</p>`).join("")}</div>`,
      )
      .join("");
    showModal(
      "确认添加",
      `<div class="confirm-grid">${rows}</div><h3>目标存档</h3><p class="file-path">${escape(state.save.path)}</p><p class="confirmation-note">请先退出游戏。保存前会自动备份原存档。</p>`,
      `<button class="secondary" data-action="close-modal">取消</button><button class="primary" data-action="confirm-save">确认添加</button>`,
    );
  }
  async function confirmSave() {
    if (state.busy || !state.confirm) return;
    if (state.confirm.path !== state.save?.path)
      throw new Error("目标存档已变化，请重新确认。");
    setBusy(true);
    const requests = state.confirm.requests;
    modal
      .querySelectorAll("button")
      .forEach((button) => (button.disabled = true));
    try {
      const result = await call("save_bodies", requests);
      state.save = result.save;
      updateSaveLabel();
      closeModal();
      toast(
        result.warning || `已添加 ${requests.length} 个数据体，原存档已备份。`,
        Boolean(result.warning),
      );
    } finally {
      setBusy(false);
      modal
        .querySelectorAll("button")
        .forEach((button) => (button.disabled = false));
    }
  }
  async function restore() {
    if (state.busy) return;
    setBusy(true);
    try {
      const result = await call("restore_backup");
      if (result) {
        state.save = result.save;
        if (result.save) state.selectedPath = result.save.path;
        updateSaveLabel();
        toast(result.warning || "备份已恢复。", Boolean(result.warning));
      }
    } finally {
      setBusy(false);
    }
  }
  async function handleAction(button) {
    const action = button.dataset.action;
    if (state.busy && action !== "close-modal") return;
    if (action === "mode") {
      state.mode = button.dataset.mode;
      render();
    } else if (action === "element") {
      state.element = button.dataset.value;
      renderLibrary();
    } else if (action === "open-build") await openBuild(button.dataset.id);
    else if (action === "back") {
      state.buildId = null;
      state.guide = null;
      ++state.guideRevision;
      renderLibrary();
    } else if (action === "pick") {
      const row = strategy(button.dataset.id);
      editor().add(row.id, Math.max(...row.qualities));
      await selectionChanged();
    } else if (action === "unpick") {
      const location = editor().locate(Number(button.dataset.id));
      if (location) editor().remove(...location);
      await selectionChanged();
    } else if (action === "inspect") inspectStrategy(Number(button.dataset.id));
    else if (action === "slot")
      openPicker(Number(button.dataset.body), Number(button.dataset.slot));
    else if (action === "remove") {
      editor().remove(Number(button.dataset.body), Number(button.dataset.slot));
      await selectionChanged();
    } else if (action === "close-modal") {
      if (!state.busy) closeModal();
    } else if (action === "picker-row") {
      state.picker.selected = Number(button.dataset.id);
      renderPickerList();
      renderPickerDetail();
    } else if (action === "picker-save") {
      const picker = state.picker;
      if (picker.body === undefined)
        editor().add(picker.selected, picker.quality);
      else
        editor().set(picker.body, picker.slot, picker.selected, picker.quality);
      closeModal();
      await selectionChanged();
    } else if (action === "browse") await browseSave();
    else if (action === "bodies") showBodies();
    else if (action === "save") await prepareSave();
    else if (action === "confirm-save") await confirmSave();
    else if (action === "restore") await restore();
  }
  document.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (button && !button.disabled)
      handleAction(button).catch((error) => toast(error.message, true));
  });
  document.addEventListener("input", (event) => {
    if (event.target.id === "build-search") {
      state.query = event.target.value;
      renderBuildList();
    } else if (event.target.id === "strategy-search") {
      state.picker.query = event.target.value;
      renderPickerList();
    } else if (event.target.id === "body-search")
      renderBodies(event.target.value);
  });
  document.addEventListener("change", (event) => {
    const field = event.target.dataset.field;
    if (field === "character")
      editor().bodies[Number(event.target.dataset.body)].character_id =
        Number(event.target.value) || null;
    else if (field === "color") {
      editor().bodies[Number(event.target.dataset.body)].body_quality = Number(
        event.target.value,
      );
      event.target.classList.toggle("gold", Number(event.target.value) === 4);
    } else if (event.target.id === "picker-quality") {
      state.picker.quality = Number(event.target.value);
      renderPickerDetail();
    } else if (event.target.id === "save-select") {
      if (event.target.value)
        chooseSave(event.target.value).catch((error) =>
          toast(error.message, true),
        );
      else {
        state.save = null;
        state.selectedPath = null;
        updateSaveLabel();
      }
    }
  });
  modal.addEventListener("cancel", (event) => {
    if (state.busy) event.preventDefault();
    else {
      state.picker = null;
      state.confirm = null;
    }
  });
  let started = false;
  async function start() {
    if (started) return;
    started = true;
    try {
      const initial = await call("get_initial_data");
      state.catalog = initial.catalog;
      state.strategies = new Map(
        state.catalog.strategies.map((row) => [row.id, row]),
      );
      state.builds = await call("list_builds");
      state.saves = await call("discover_saves");
      updateSaveLabel();
      render();
      workspace.setAttribute("aria-busy", "false");
    } catch (error) {
      workspace.innerHTML = `<section class="fatal"><h1>载入失败</h1><p>${escape(error.message)}</p><p>请关闭工具后重新打开。</p></section>`;
    }
  }
  window.addEventListener("pywebviewready", start);
  if (window.pywebview?.api) start();
})();
