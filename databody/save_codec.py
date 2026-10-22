"""无损编辑游戏的 LZ4 / Protobuf 存档容器，不承担磁盘写入。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import lz4.frame


class SaveFormatError(ValueError):
    """输入不符合当前游戏存档格式，调用方应停止保存。"""


def _encode_varint(value: int) -> bytes:
    if not isinstance(value, int) or not 0 <= value < (1 << 64):
        raise ValueError("整数必须处于 uint64 范围内")
    output = bytearray()
    while value >= 128:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)
    return bytes(output)


def _read_varint(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    for index in range(10):
        if position >= len(data):
            raise SaveFormatError("Protobuf 整数字段不完整")
        byte = data[position]
        position += 1
        if index == 9 and byte > 1:
            raise SaveFormatError("Protobuf 整数字段超过 uint64 范围")
        value |= (byte & 127) << (index * 7)
        if byte < 128:
            return value, position
    raise SaveFormatError("Protobuf 整数字段过长")


def _field_tag(number: int, wire_type: int) -> bytes:
    if not isinstance(number, int) or not 1 <= number < (1 << 29):
        raise ValueError("Protobuf 字段编号无效")
    return _encode_varint((number << 3) | wire_type)


@dataclass(frozen=True)
class Field:
    """保留原始编码；读取后未替换的字段保持逐字节一致。"""

    number: int
    wire_type: int
    value: int | bytes
    raw: bytes

    @classmethod
    def varint(cls, number: int, value: int) -> Field:
        raw = _field_tag(number, 0) + _encode_varint(value)
        return cls(number, 0, value, raw)

    @classmethod
    def bytes(cls, number: int, value: bytes) -> Field:
        payload = bytes(value)
        raw = _field_tag(number, 2) + _encode_varint(len(payload)) + payload
        return cls(number, 2, payload, raw)

    @classmethod
    def fixed64(cls, number: int, value: bytes) -> Field:
        return cls._fixed(number, value, 1, 8)

    @classmethod
    def fixed32(cls, number: int, value: bytes) -> Field:
        return cls._fixed(number, value, 5, 4)

    @classmethod
    def _fixed(cls, number: int, value: bytes, wire_type: int, length: int) -> Field:
        payload = bytes(value)
        if len(payload) != length:
            raise ValueError(f"定长字段需要 {length} 个字节")
        return cls(number, wire_type, payload, _field_tag(number, wire_type) + payload)


class Message:
    """当前存档使用的 Protobuf wire 类型 0、1、2、5。"""

    def __init__(self, fields: Iterable[Field] = ()):
        self._fields = tuple(fields)

    @classmethod
    def parse(cls, data: bytes) -> Message:
        data = bytes(data)
        fields = []
        position = 0
        while position < len(data):
            start = position
            tag, position = _read_varint(data, position)
            number, wire_type = tag >> 3, tag & 7
            if not 1 <= number < (1 << 29):
                raise SaveFormatError("Protobuf 字段编号无效")
            if wire_type == 0:
                value, position = _read_varint(data, position)
            elif wire_type in (1, 2, 5):
                if wire_type == 2:
                    length, position = _read_varint(data, position)
                else:
                    length = 8 if wire_type == 1 else 4
                end = position + length
                if end > len(data):
                    raise SaveFormatError("Protobuf 字段内容不完整")
                value = data[position:end]
                position = end
            else:
                raise SaveFormatError(f"当前存档不支持 Protobuf wire 类型 {wire_type}")
            fields.append(Field(number, wire_type, value, data[start:position]))
        return cls(fields)

    def fields(self, number: int | None = None) -> tuple[Field, ...]:
        if number is None:
            return self._fields
        return tuple(field for field in self._fields if field.number == number)

    def to_bytes(self) -> bytes:
        return b"".join(field.raw for field in self._fields)

    def _scalar(self, number: int, wire_type: int, default: int | bytes) -> int | bytes:
        matching = self.fields(number)
        if len(matching) > 1 or (matching and matching[0].wire_type != wire_type):
            raise SaveFormatError(f"字段 {number} 重复或类型不符合预期")
        return matching[0].value if matching else default

    def get_varint(self, number: int, default: int = 0) -> int:
        return self._scalar(number, 0, default)

    def get_bytes(self, number: int, default: bytes = b"") -> bytes:
        return self._scalar(number, 2, default)

    def replace(self, number: int, replacements: Iterable[Field]) -> Message:
        replacements = tuple(replacements)
        if any(field.number != number for field in replacements):
            raise ValueError("替换字段的编号必须一致")
        output = []
        inserted = False
        for field in self._fields:
            if field.number == number:
                if not inserted:
                    output.extend(replacements)
                    inserted = True
            else:
                output.append(field)
        if not inserted:
            output.extend(replacements)
        return Message(output)


class SaveDocument:
    """DataSave 包装与具名模型；修改仅影响选中模型的 Data 字段。"""

    def __init__(self, message: Message, original: bytes, payload: bytes, frame_info: dict):
        self.message = message
        self._original = original
        self._payload = payload
        self._frame_info = frame_info

    @classmethod
    def from_compressed(cls, data: bytes) -> SaveDocument:
        data = bytes(data)
        if not data.startswith(b"\x04\x22\x4d\x18"):
            raise SaveFormatError("文件不是受支持的 LZ4 游戏存档")
        try:
            frame_info = lz4.frame.get_frame_info(data)
            payload, consumed = lz4.frame.decompress(data, return_bytes_read=True)
        except (RuntimeError, ValueError, OverflowError) as error:
            raise SaveFormatError("LZ4 存档不完整或已损坏") from error
        if consumed != len(data):
            raise SaveFormatError("LZ4 存档末尾包含额外数据")
        message = Message.parse(payload)
        if message.get_bytes(1) != b"AutoSave":
            raise SaveFormatError("文件不是游戏的 AutoSave 存档")
        return cls(message, data, payload, frame_info)

    def to_compressed(self) -> bytes:
        payload = self.message.to_bytes()
        if payload == self._payload:
            return self._original
        return lz4.frame.compress(
            payload,
            block_size=self._frame_info["block_size_id"],
            block_linked=self._frame_info["block_linked"],
            content_checksum=self._frame_info["content_checksum"],
            block_checksum=self._frame_info["block_checksum"],
            store_size=bool(self._frame_info["content_size"]),
        )

    def _find_model(self, name: str) -> tuple[Field, Message]:
        matches = []
        expected_name = name.encode("utf-8")
        for field in self.message.fields(2):
            if field.wire_type != 2:
                raise SaveFormatError("DataSave 模型字段类型无效")
            model = Message.parse(field.value)
            if model.get_bytes(1) == expected_name:
                matches.append((field, model))
        if len(matches) != 1:
            raise SaveFormatError(f"存档模型 {name} 不存在或重复")
        return matches[0]

    def get_model(self, name: str) -> bytes:
        _, model = self._find_model(name)
        return model.get_bytes(2)

    def replace_model(self, name: str, data: bytes) -> None:
        original, model = self._find_model(name)
        model.get_bytes(2)  # 在修改前拒绝歧义数据，保留完整的未知字段。
        updated = model.replace(2, [Field.bytes(2, data)])
        fields = [Field.bytes(2, updated.to_bytes()) if field is original else field
                  for field in self.message.fields()]
        self.message = Message(fields)
