import tempfile
import unittest
from pathlib import Path

from tele_backup.store import (
    STATUS_FAILED,
    STATUS_SYNCED,
    SourceRecord,
    SyncStateRecord,
    SyncStore,
)


class SyncStoreTestCase(unittest.TestCase):
    def test_source_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'state.sqlite'
            store = SyncStore(db_path)
            try:
                source = SourceRecord(
                    source_chat_id=123,
                    dest_chat_id=-1001,
                    dest_topic_default=2085,
                    dest_topic_archive=2088,
                    label='demo',
                    allow_protected_fallback=True,
                )
                store.upsert_source(source)

                loaded = store.get_source(123)
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.source_chat_id, 123)
                self.assertEqual(loaded.dest_chat_id, -1001)
                self.assertTrue(loaded.allow_protected_fallback)

                listed = store.list_sources(enabled_only=True)
                self.assertEqual(len(listed), 1)
                self.assertEqual(listed[0].label, 'demo')

                store.set_source_enabled(123, False)
                loaded = store.get_source(123)
                self.assertFalse(loaded.enabled)
            finally:
                store.close()

    def test_cursor_and_failed_records_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'state.sqlite'
            store = SyncStore(db_path)
            try:
                store.set_cursor(123, 50)
                self.assertEqual(store.get_cursor(123), 50)

                store.upsert_record(
                    SyncStateRecord(
                        source_chat_id=123,
                        source_msg_id=51,
                        status=STATUS_FAILED,
                        extension='.txt',
                        document_id=999,
                        filename='a.txt',
                        normalized_filename='a.txt',
                        size=1024,
                        fingerprint='999:1024:a.txt',
                        error_text='oops',
                    )
                )
                failed = store.list_failed(123)
                self.assertEqual(len(failed), 1)
                self.assertEqual(failed[0]['source_msg_id'], 51)

                store.upsert_record(
                    SyncStateRecord(
                        source_chat_id=123,
                        source_msg_id=51,
                        status=STATUS_SYNCED,
                        extension='.txt',
                        document_id=999,
                        filename='a.txt',
                        normalized_filename='a.txt',
                        size=1024,
                        dest_chat_id=-1001,
                        dest_topic_id=2085,
                        dest_msg_id=700,
                        fingerprint='999:1024:a.txt',
                    )
                )
                failed = store.list_failed(123)
                self.assertEqual(failed, [])
            finally:
                store.close()

    def test_txt_fingerprint_is_inserted_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'state.sqlite'
            store = SyncStore(db_path)
            try:
                self.assertFalse(store.has_txt_fingerprint('abc'))
                store.add_txt_fingerprint('abc', 1, 2, -100, 2085, 300)
                self.assertTrue(store.has_txt_fingerprint('abc'))
                store.add_txt_fingerprint('abc', 1, 2, -100, 2085, 300)
                self.assertTrue(store.has_txt_fingerprint('abc'))
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
