/* 只记录用户的编辑选择；推荐配置不会写进继承槽。 */
(function (root) {
  "use strict";
  class BodyEditor {
    constructor(count) {
      this.bodies = Array.from({ length: count }, () => ({
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
      throw new Error("四项已选满。点击下方策略槽，选择要替换的位置。");
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
  if (typeof module !== "undefined" && module.exports)
    module.exports = { BodyEditor };
  else root.DataBodyModel = { BodyEditor };
})(globalThis);
