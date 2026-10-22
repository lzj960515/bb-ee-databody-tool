"""创建继承用数据体，并维护游戏数据体包的编号和累计分数。"""
from __future__ import annotations

import struct

from .save_codec import Field, Message, SaveDocument, SaveFormatError

MODEL_NAME = "ModelPlayerNewFesActorPack"


def nested(field: Field) -> Message:
    if field.wire_type != 2:
        raise SaveFormatError("数据体字段格式不符合预期")
    return Message.parse(field.value)


def double_value(message: Message, number: int) -> float:
    fields = message.fields(number)
    if not fields:
        return 0.0
    if len(fields) != 1 or fields[0].wire_type != 1:
        raise SaveFormatError("数据体分数字段格式不符合预期")
    return struct.unpack("<d", fields[0].value)[0]


def double_field(number: int, value: float) -> Field:
    return Field.fixed64(number, struct.pack("<d", value))


def pack_from_save(document: SaveDocument) -> tuple[Message, Message]:
    try:
        model_data = document.get_model(MODEL_NAME)
    except SaveFormatError as error:
        raise SaveFormatError("存档缺少新版数据体记录。旧版存档请先在当前游戏中载入并保存，再用本工具打开。") from error
    model = Message.parse(model_data)
    return model, Message.parse(model.get_bytes(1))


def body_entries(pack: Message) -> list[tuple[int, Message]]:
    entries = []
    identifiers = set()
    for field in pack.fields(1):
        entry = nested(field)
        uid = entry.get_varint(1)
        body = Message.parse(entry.get_bytes(2))
        if not uid or uid in identifiers or body.get_varint(1) != uid:
            raise SaveFormatError("数据体编号重复或记录不一致，已停止修改")
        identifiers.add(uid)
        entries.append((uid, body))
    return entries


def capacity(pack: Message, rules: dict) -> int:
    total = pack.get_varint(5)
    pages = sum(total >= score for score in rules["page_unlock_scores"])
    return pages * rules["page_size"]


def create_body(uid: int, character: dict, strategy_ids: list[int], qualities: list[int], score: int) -> Message:
    fields = [Field.varint(1, uid), Field.varint(2, character["id"])]
    for attr in character["base_attrs"]:
        payload = Message([Field.varint(1, attr["type"]), double_field(3, attr["value"])])
        fields.append(Field.bytes(6, payload.to_bytes()))
    blessings = []
    for strategy_id, quality in zip(strategy_ids, qualities):
        blessing = Message([Field.varint(1, strategy_id), Field.varint(2, quality), Field.varint(3, 1)])
        blessings.append(blessing.to_bytes())
    fields.extend(Field.bytes(8, payload) for payload in blessings)
    for potential in character.get("potentials", []):
        fields.append(Field.bytes(15, Message([Field.varint(1, potential["id"])]).to_bytes()))
    # 600 分是本构建中保存两项继承策略的门槛，基础属性仍按角色初始配置。
    fields.append(double_field(16, score))
    for talent in character["talents"]:
        talent_fields = [Field.varint(1, talent["id"]), Field.varint(2, talent["quality"])]
        if talent.get("inheritNum"):
            talent_fields.append(Field.varint(3, talent["inheritNum"]))
        fields.append(Field.bytes(17, Message(talent_fields).to_bytes()))
    fields.extend(Field.bytes(30, payload) for payload in blessings)
    # 沿用游戏 GenerateByTemplate 的生成标记；继承技能索引/等级零值由游戏解释为第一项、一级。
    fields.append(Field.varint(35, 1))
    return Message(fields)


def append_body(document: SaveDocument, character: dict, strategy_ids: list[int], qualities: list[int], rules: dict) -> int:
    model, pack = pack_from_save(document)
    entries = body_entries(pack)
    if len(entries) >= capacity(pack, rules):
        raise ValueError("当前已解锁的数据体仓库已满，请先在游戏中删除不需要的数据体")
    uid = max([pack.get_varint(2), *(uid for uid, _ in entries)]) + 1
    if uid >= 1 << 32:
        raise ValueError("数据体编号已达到游戏格式上限")
    score = rules["inherit_score"]
    body = create_body(uid, character, strategy_ids, qualities, score)
    entry = Message([Field.varint(1, uid), Field.bytes(2, body.to_bytes())])
    pack = pack.replace(1, [*pack.fields(1), Field.bytes(1, entry.to_bytes())])
    pack = pack.replace(2, [Field.varint(2, uid)])
    scores = list(pack.fields(4))
    found = False
    for index, field in enumerate(scores):
        score_entry = nested(field)
        if score_entry.get_varint(1) == character["id"]:
            if found:
                raise SaveFormatError("角色最高分记录重复")
            found = True
            if double_value(score_entry, 2) < score:
                scores[index] = Field.bytes(4, score_entry.replace(2, [double_field(2, score)]).to_bytes())
    if not found:
        scores.append(Field.bytes(4, Message([Field.varint(1, character["id"]), double_field(2, score)]).to_bytes()))
    pack = pack.replace(4, scores)
    pack = pack.replace(5, [Field.varint(5, pack.get_varint(5) + score)])
    document.replace_model(MODEL_NAME, model.replace(1, [Field.bytes(1, pack.to_bytes())]).to_bytes())
    return uid
