import unittest

from tele_backup.message_rules import (
    build_txt_fingerprint,
    decide_file_handling,
    detect_extension,
    normalize_filename,
)


class MessageRulesTestCase(unittest.TestCase):
    def test_normalize_filename_uses_basename_and_lowercase(self) -> None:
        self.assertEqual(normalize_filename("C:/Temp/ABC.TXT"), "abc.txt")

    def test_detect_extension_returns_lowercase_suffix(self) -> None:
        self.assertEqual(detect_extension("Archive.RAR"), ".rar")

    def test_txt_goes_to_default_topic_without_caption(self) -> None:
        decision = decide_file_handling("sample.txt", 2085, 2088)
        self.assertEqual(decision.topic_id, 2085)
        self.assertTrue(decision.dedupe_txt)
        self.assertFalse(decision.preserve_caption)

    def test_archive_goes_to_archive_topic_with_caption(self) -> None:
        decision = decide_file_handling("secret.zip", 2085, 2088)
        self.assertEqual(decision.topic_id, 2088)
        self.assertFalse(decision.dedupe_txt)
        self.assertTrue(decision.preserve_caption)

    def test_build_txt_fingerprint_returns_none_without_metadata(self) -> None:
        self.assertIsNone(build_txt_fingerprint(None, 100, "a.txt"))
        self.assertIsNone(build_txt_fingerprint(1, None, "a.txt"))

    def test_build_txt_fingerprint_contains_expected_fields(self) -> None:
        self.assertEqual(build_txt_fingerprint(11, 22, "file.txt"), "11:22:file.txt")


if __name__ == "__main__":
    unittest.main()
