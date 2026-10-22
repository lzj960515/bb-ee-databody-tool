"""存档编解码的回归契约：完整保留未编辑字节，拒绝损坏输入。"""
import unittest

from databody.save_codec import Field, Message, SaveDocument, SaveFormatError
import lz4.frame


def saved_model(name, data):
    return Message([Field.bytes(1, name.encode()), Field.bytes(2, data)]).to_bytes()


class WireMessageTests(unittest.TestCase):
    def test_unedited_message_is_byte_exact_including_noncanonical_varints(self):
        original = b"\x08\x81\x00\x12\x03abc\xa0\x06\x96\x01"
        message = Message.parse(original)
        self.assertEqual(message.get_varint(1), 1)
        self.assertEqual(message.get_bytes(2), b"abc")
        self.assertEqual(message.to_bytes(), original)

    def test_replace_repeated_field_keeps_unrelated_raw_fields_and_order(self):
        original = b"\x08\x81\x00\x12\x01a\xa0\x06\x96\x01\x12\x01b\x18\x05"
        message = Message.parse(original)
        changed = message.replace(2, [Field.bytes(2, b"new"), Field.bytes(2, b"two")])
        self.assertEqual(changed.to_bytes(), b"\x08\x81\x00\x12\x03new\x12\x03two\xa0\x06\x96\x01\x18\x05")
        self.assertEqual(message.to_bytes(), original)

    def test_append_remove_and_fixed_width_unknown_fields(self):
        original = b"\x09abcdefgh\x15abcd"
        message = Message.parse(original)
        changed = message.replace(3, [Field.varint(3, 42)])
        self.assertEqual(changed.to_bytes(), original + b"\x18\x2a")
        self.assertEqual(changed.replace(3, []).to_bytes(), original)
        self.assertEqual(Field.fixed64(1, b"abcdefgh").raw, original[:9])
        self.assertEqual(Field.fixed32(2, b"abcd").raw, original[9:])

    def test_scalar_read_rejects_duplicate_or_wrong_wire_type(self):
        for data in (b"\x08\x01\x08\x02", b"\x0a\x00"):
            with self.subTest(data=data), self.assertRaises(SaveFormatError):
                Message.parse(data).get_varint(1)

    def test_replace_requires_matching_field_numbers(self):
        with self.assertRaises(ValueError):
            Message().replace(1, [Field.varint(2, 4)])

    def test_bad_protobuf_is_rejected(self):
        invalid = [b"\x00", b"\x08\x80", b"\x0a\x04abc", b"\x09short", b"\x15abc",
                   b"\x0e", b"\x08" + b"\xff" * 9 + b"\x02", b"\x80\x80\x80\x80\x10\x01"]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(SaveFormatError):
                Message.parse(data)

    def test_uint64_boundaries_and_factory_validation(self):
        value = (1 << 64) - 1
        self.assertEqual(Message.parse(Field.varint(1, value).raw).get_varint(1), value)
        for number, value in [(0, 1), (1 << 29, 1), (1, -1), (1, 1 << 64)]:
            with self.subTest(number=number, value=value), self.assertRaises(ValueError):
                Field.varint(number, value)


class SaveDocumentTests(unittest.TestCase):
    def setUp(self):
        self.target = saved_model("ModelPlayerNewFesActorPack", b"\x08\x01") + b"\xa0\x06\x81\x00"
        self.other = saved_model("ModelOther", b"untouched")
        self.original = Message([
            Field.bytes(1, b"AutoSave"), Field.bytes(2, self.target),
            Field.bytes(2, self.other), Field.varint(6, 9), Field.bytes(101, b"future"),
        ]).to_bytes()
        self.compressed = lz4.frame.compress(self.original, block_linked=True, block_size=lz4.frame.BLOCKSIZE_MAX64KB)

    def test_compressed_roundtrip_preserves_entire_payload(self):
        document = SaveDocument.from_compressed(self.compressed)
        self.assertEqual(document.get_model("ModelPlayerNewFesActorPack"), b"\x08\x01")
        self.assertEqual(lz4.frame.decompress(document.to_compressed()), self.original)

    def test_replace_model_only_changes_requested_payload(self):
        document = SaveDocument.from_compressed(self.compressed)
        document.replace_model("ModelPlayerNewFesActorPack", b"\x08\x03")
        result = SaveDocument.from_compressed(document.to_compressed())
        self.assertEqual(result.get_model("ModelPlayerNewFesActorPack"), b"\x08\x03")
        self.assertEqual(result.get_model("ModelOther"), b"untouched")
        expected = self.original.replace(self.target, self.target.replace(b"\x12\x02\x08\x01", b"\x12\x02\x08\x03"))
        self.assertEqual(result.message.to_bytes(), expected)

    def test_missing_or_ambiguous_model_is_rejected(self):
        document = SaveDocument.from_compressed(self.compressed)
        for action in (lambda: document.get_model("Missing"), lambda: document.replace_model("Missing", b"")):
            with self.assertRaises(SaveFormatError):
                action()
        duplicate = document.message.replace(2, [Field.bytes(2, self.target), Field.bytes(2, self.target)])
        ambiguous = SaveDocument.from_compressed(lz4.frame.compress(duplicate.to_bytes()))
        with self.assertRaises(SaveFormatError):
            ambiguous.get_model("ModelPlayerNewFesActorPack")

    def test_empty_model_payload_is_allowed(self):
        root = Message([Field.bytes(1, b"AutoSave"), Field.bytes(2, Message([Field.bytes(1, b"Empty")]).to_bytes())])
        document = SaveDocument.from_compressed(lz4.frame.compress(root.to_bytes()))
        self.assertEqual(document.get_model("Empty"), b"")
        document.replace_model("Empty", b"\x08\x01")
        self.assertEqual(document.get_model("Empty"), b"\x08\x01")

    def test_corrupt_frame_trailing_data_and_wrong_document_are_rejected(self):
        invalid = [b"NOAH", self.compressed[:-1], self.compressed + b"garbage",
                   lz4.frame.compress(b"\x08\x80"), lz4.frame.compress(b"\x0a\x05Other")]
        for data in invalid:
            with self.subTest(data=data[:16]), self.assertRaises(SaveFormatError):
                SaveDocument.from_compressed(data)


if __name__ == "__main__":
    unittest.main()
