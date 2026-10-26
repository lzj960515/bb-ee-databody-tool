/* 界面编辑状态与搭配请求生命周期；推荐配置不会写进继承槽。 */
(function (root) {
  "use strict";
  const copy = (value) => JSON.parse(JSON.stringify(value));
  class GuideRequestQueue {
    constructor(calculate) {
      this.calculate = calculate;
      this.revision = 0;
      this.running = false;
      this.pending = null;
    }
    invalidate() {
      this.revision++;
      if (this.pending) this.pending.resolve(null);
      this.pending = null;
    }
    request(input) {
      this.invalidate();
      return new Promise((resolve, reject) => {
        this.pending = { input, resolve, reject, revision: this.revision };
        this.runNext();
      });
    }
    async runNext() {
      if (this.running || !this.pending) return;
      const request = this.pending;
      this.pending = null;
      this.running = true;
      try {
        const result = await this.calculate(request.input);
        request.resolve(request.revision === this.revision ? result : null);
      } catch (error) {
        if (request.revision === this.revision) request.reject(error);
        else request.resolve(null);
      } finally {
        // 慢计算期间只保留最新草稿，避免每次点击都启动一次过期计算。
        this.running = false;
        this.runNext();
      }
    }
  }
  class BodyEditor {
    constructor(count, bodies = null) {
      this.bodies = bodies
        ? copy(bodies)
        : Array.from({ length: count }, () => ({
            character_id: null,
            body_quality: 3,
            slots: [null, null],
          }));
    }
    strategyIds() {
      return this.bodies.flatMap((body) =>
        body.slots.filter(Boolean).map((slot) => slot.id),
      );
    }
    locate(id) {
      for (let body = 0; body < this.bodies.length; body++) {
        const slot = this.bodies[body].slots.findIndex(
          (value) => value?.id === id,
        );
        if (slot >= 0) return [body, slot];
      }
      return null;
    }
    add(id, quality) {
      if (this.locate(id)) throw new Error("这项策略已经选入继承。");
      for (let body = 0; body < this.bodies.length; body++) {
        const slot = this.bodies[body].slots.indexOf(null);
        if (slot >= 0) {
          this.set(body, slot, id, quality);
          return [body, slot];
        }
      }
      const capacity = this.bodies.length === 1 ? "两项" : "四项";
      throw new Error(`${capacity}已选满。点击下方策略槽，选择要替换的位置。`);
    }
    set(body, slot, id, quality) {
      const existing = this.locate(id);
      if (existing && (existing[0] !== body || existing[1] !== slot))
        throw new Error("这项策略已选在另一个位置。");
      this.bodies[body].slots[slot] = { id, quality };
    }
    remove(body, slot) {
      this.bodies[body].slots[slot] = null;
    }
    requests() {
      if (this.bodies.some((body) => !body.character_id))
        throw new Error("请选择数据体角色。");
      if (
        new Set(this.bodies.map((body) => body.character_id)).size !==
        this.bodies.length
      )
        throw new Error("两个数据体请选择不同角色。");
      if (this.bodies.some((body) => body.slots.some((slot) => !slot)))
        throw new Error("请为每个数据体选择两项策略。");
      return this.bodies.map((body) => ({
        character_id: body.character_id,
        body_quality: body.body_quality,
        strategy_ids: body.slots.map((slot) => slot.id),
        qualities: body.slots.map((slot) => slot.quality),
      }));
    }
  }
  class SingleBodyEditor extends BodyEditor {
    constructor() {
      super(1);
      this.owned = [];
      this.fullPotentials = false;
    }
    setOwned(id, quality) {
      const existing = this.owned.find((row) => row.id === id);
      if (existing) existing.quality = quality;
      else this.owned.push({ id, quality });
      const location = this.locate(id);
      if (location) super.set(...location, id, quality);
    }
    removeOwned(id) {
      this.owned = this.owned.filter((row) => row.id !== id);
      const location = this.locate(id);
      if (location) this.remove(...location);
    }
    set(body, slot, id, quality) {
      super.set(body, slot, id, quality);
      this.setOwned(id, quality);
    }
    ownedQuality(id) {
      return this.owned.find((row) => row.id === id)?.quality || 4;
    }
    resolvedOwned(guide) {
      if (!guide) throw new Error("请等待策略计算完成。");
      if (guide.selection.errors.length)
        throw new Error(guide.selection.errors.join("；"));
      if (this.owned.some((row) => !guide.strategy_ids.includes(row.id)))
        throw new Error("策略已变化，请等待重新计算。");
      return guide.strategy_ids.map((id) => ({id, quality: this.ownedQuality(id)}));
    }
    requests(guide) {
      const requests = super.requests();
      const owned = this.resolvedOwned(guide);
      return requests.map((request) => ({
        ...request,
        owned_strategies: copy(owned),
        full_potentials: this.fullPotentials,
      }));
    }
  }
  class StrategyPickerModel {
    constructor(strategies, recommendedIds = []) {
      this.strategies = strategies;
      this.recommended = new Set(recommendedIds);
      this.query = "";
      this.element = "全部";
      this.selected = null;
      this.quality = 4;
    }
    visible() {
      const query = this.query.trim().toLowerCase();
      return this.strategies
        .filter(
          (row) =>
            (this.element === "全部" || row.category.includes(this.element)) &&
            `${row.name} ${row.description} ${row.category}`
              .toLowerCase()
              .includes(query),
        )
        .sort(
          (left, right) =>
            Number(this.recommended.has(right.id)) -
            Number(this.recommended.has(left.id)),
        );
    }
  }
  class CustomBuildDraft {
    constructor(document = {}, saved = false) {
      this.id = document.id || null;
      this.title = document.title || "";
      this.targetIds = [...(document.target_ids || [])];
      this.preferredIds = [...(document.preferred_ids || [])];
      this.requiredInherited = [...(document.required_inherited || [])];
      this.editor = new BodyEditor(2, document.bodies);
      this.savedSnapshot = saved ? JSON.stringify(this.document()) : null;
    }
    static fromGuide(guide, editor) {
      return new CustomBuildDraft({
        ...guide.definition,
        title: `${guide.title}（自定义）`,
        bodies: editor.bodies,
      });
    }
    get dirty() {
      return JSON.stringify(this.document()) !== this.savedSnapshot;
    }
    addTarget(id) {
      if (!this.targetIds.includes(id)) this.targetIds.push(id);
    }
    removeTarget(id) {
      this.targetIds = this.targetIds.filter((value) => value !== id);
      this.preferredIds = this.preferredIds.filter((value) => value !== id);
      this.requiredInherited = this.requiredInherited.filter(
        (value) => value !== id,
      );
    }
    document() {
      return {
        id: this.id,
        title: this.title,
        target_ids: [...this.targetIds],
        preferred_ids: [...this.preferredIds],
        required_inherited: [...this.requiredInherited],
        bodies: copy(this.editor.bodies),
      };
    }
    forSave() {
      if (!this.title.trim()) throw new Error("请填写玩法名称。");
      return { ...this.document(), title: this.title.trim() };
    }
    acknowledgeSave(document) {
      // 保存响应只更新已保存快照，保留等待响应期间的编辑。
      this.id = document.id;
      this.savedSnapshot = JSON.stringify(
        new CustomBuildDraft(document).document(),
      );
    }
  }
  if (typeof module !== "undefined" && module.exports)
    module.exports = {
      BodyEditor,
      CustomBuildDraft,
      GuideRequestQueue,
      StrategyPickerModel,
      SingleBodyEditor,
    };
  else
    root.DataBodyModel = {
      BodyEditor,
      CustomBuildDraft,
      GuideRequestQueue,
      StrategyPickerModel,
      SingleBodyEditor,
    };
})(globalThis);
