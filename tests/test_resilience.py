import argparse
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from test_sync import sync


class RequestResilienceTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.sleep = patch.object(sync.time, "sleep").start()
        patch.object(sync, "_pace").start()
        patch.object(sync.random, "uniform", return_value=0).start()
        self.post = patch.object(sync.SESSION, "post").start()

    def response(self, status, body=None, headers=None):
        response = Mock(status_code=status, headers=headers or {})
        response.json.return_value = body or {"data": {"ok": True}}
        if 400 <= status < 500:
            response.raise_for_status.side_effect = sync.requests.HTTPError(f"HTTP {status}")
        return response

    def test_503_honors_retry_after_and_recovers(self):
        self.post.side_effect = [
            self.response(503, headers={"Retry-After": "12"}),
            self.response(200),
        ]
        self.assertEqual(sync._post("/searchDocuments", {})["data"], {"ok": True})
        self.sleep.assert_called_once_with(12)
        self.assertEqual(self.post.call_count, 2)

    def test_repeated_429_reports_status_and_does_not_sleep_after_last_attempt(self):
        self.post.return_value = self.response(429)
        with self.assertRaisesRegex(sync.ApiUnavailableError, "HTTP 429"):
            sync._post("/searchDocuments", {}, attempts=2)
        self.assertEqual(self.post.call_count, 2)
        self.sleep.assert_called_once_with(2)

    def test_network_timeout_is_retryable(self):
        self.post.side_effect = sync.requests.Timeout("timed out")
        with self.assertRaises(sync.ApiUnavailableError):
            sync._post("/searchDocuments", {}, attempts=2)
        self.assertEqual(self.post.call_count, 2)

    def test_authentication_error_is_not_treated_as_outage(self):
        self.post.return_value = self.response(403)
        with self.assertRaises(sync.ApiError) as error:
            sync._post("/searchDocuments", {})
        self.assertNotIsInstance(error.exception, sync.ApiUnavailableError)
        self.post.assert_called_once()
        self.sleep.assert_not_called()

    def test_malformed_json_is_not_treated_as_outage(self):
        self.post.return_value = self.response(200)
        self.post.return_value.json.side_effect = ValueError("bad json")
        with self.assertRaises(sync.ApiError) as error:
            sync._post("/searchDocuments", {})
        self.assertNotIsInstance(error.exception, sync.ApiUnavailableError)
        self.post.assert_called_once()


class CatalogSafetyTest(unittest.TestCase):
    def test_repeated_page_stops_instead_of_looping_forever(self):
        body = {"data": {"total": 2, "mevzuatList": [{"mevzuatId": "1"}]}}
        with patch.object(sync, "_post", return_value=body) as post:
            with self.assertRaisesRegex(sync.ApiError, "ilerlemiyor"):
                sync._list_type("KANUN")
        self.assertEqual(post.call_count, 2)

    def test_truncated_catalog_is_rejected(self):
        bodies = [
            {"data": {"total": 2, "mevzuatList": [{"mevzuatId": "1"}]}},
            {"data": {"total": 2, "mevzuatList": []}},
        ]
        with patch.object(sync, "_post", side_effect=bodies):
            with self.assertRaisesRegex(sync.ApiError, "katalog eksik"):
                sync._list_type("KANUN")

    def test_missing_total_is_not_accepted_as_complete_catalog(self):
        with patch.object(sync, "_post", return_value={"data": {"mevzuatList": []}}):
            with self.assertRaisesRegex(sync.ApiError, "toplamı"):
                sync._list_type("KANUN")


class DailyResilienceTest(unittest.TestCase):
    def setUp(self):
        # Simüle edilen kesintiler GitHub'da gerçek servis uyarısı oluşturmasın.
        for capture in (redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO())):
            capture.__enter__()
            self.addCleanup(capture.__exit__, None, None, None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = {
            "ROOT": self.root,
            "LAWS_DIR": self.root / "kanunlar",
            "STATE_PATH": self.root / "catalog.json",
            "INDEX_PATH": self.root / "indeks.json",
        }
        for key, value in self.paths.items():
            patcher = patch.object(sync, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(sync.os.environ, {"GITHUB_STEP_SUMMARY": ""})
        env.start()
        self.addCleanup(env.stop)
        self.docs = [
            {"mevzuatId": str(i), "mevzuatNo": str(i), "mevzuatAdi": f"Deneme {i}",
             "_source_type": "MULGA" if i == 4 else "KANUN"}
            for i in range(1, 5)
        ]
        self.text = "Kabul Tarihi: 1.1.2020\n" + "Resmî deneme metni. " * 10 + "\n"
        for item in self.docs:
            slug = sync.directory_name(item)
            meta = sync.build_metadata(item, slug, self.text, True)
            directory = sync.LAWS_DIR / slug
            sync.save_json(directory / "ustveri.json", meta)
            (directory / "metin.md").write_text(sync.render_markdown(meta, self.text))
        sync.save_json(sync.STATE_PATH, sync.catalog_state(self.docs))
        sync.save_json(sync.INDEX_PATH, sync.rebuild_index(sync.LAWS_DIR))
        self.args = argparse.Namespace(types="KANUN,MULGA", min_documents=2,
                                       max_backfill=20, rotation_buckets=1)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def test_catalog_outage_refreshes_content_without_changing_catalog_or_removing_laws(self):
        before_catalog = sync.STATE_PATH.read_bytes()
        before_laws = set(sync.existing_by_id(sync.LAWS_DIR))
        output = io.StringIO()
        with patch.object(sync, "list_documents", side_effect=sync.ApiUnavailableError("HTTP 503")), \
             patch.object(sync, "get_document_text", return_value=(self.text + "Güncelleme\n", "text/plain")) as get, \
             redirect_stdout(output):
            self.assertEqual(sync.mode_daily(self.args), 0)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(sync.STATE_PATH.read_bytes(), before_catalog)
        self.assertEqual(set(sync.existing_by_id(sync.LAWS_DIR)), before_laws)
        self.assertIn("katalog güncel değil", output.getvalue())
        self.assertIn("Güncelleme", (sync.LAWS_DIR / "1-deneme-1" / "metin.md").read_text())

    def test_complete_outage_fails_fast_and_keeps_every_file_unchanged(self):
        before = self.snapshot()
        with patch.object(sync, "list_documents", side_effect=sync.ApiUnavailableError("HTTP 503")), \
             patch.object(sync, "get_document_text", side_effect=sync.ApiUnavailableError("HTTP 503")) as get:
            with self.assertRaisesRegex(sync.ApiUnavailableError, "art arda 3"):
                sync.mode_daily(self.args)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_live_catalog_does_not_fall_back_or_change_files(self):
        before = self.snapshot()
        with patch.object(sync, "list_documents", side_effect=sync.ApiError("katalog eksik")), \
             patch.object(sync, "get_document_text") as get:
            with self.assertRaisesRegex(sync.ApiError, "katalog eksik"):
                sync.mode_daily(self.args)
        get.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_untrusted_or_incomplete_cache_is_rejected(self):
        state = sync.catalog_state(self.docs)
        for invalid in [
            {**state, "source": "https://example.com"},
            {**state, "documents_total": 100},
            {**state, "documents": [state["documents"][0]] * 4},
        ]:
            with self.subTest(cache=invalid):
                sync.save_json(sync.STATE_PATH, invalid)
                with self.assertRaises(sync.ApiError):
                    sync.cached_documents(["KANUN", "MULGA"], 2)

    def test_live_catalog_recovers_and_removes_only_confirmed_deleted_record(self):
        with patch.object(sync, "list_documents", return_value=self.docs[:3]), \
             patch.object(sync, "get_document_text", return_value=(self.text, "text/plain")):
            self.assertEqual(sync.mode_daily(self.args), 0)
        self.assertEqual(set(sync.existing_by_id(sync.LAWS_DIR)), {"1", "2", "3"})
        self.assertEqual(json.loads(sync.STATE_PATH.read_text())["documents_total"], 3)

    def test_failed_metadata_change_remains_pending(self):
        before_catalog = sync.STATE_PATH.read_bytes()
        changed = [{**d, "resmiGazeteSayisi": "999"} for d in self.docs]

        def content(sid):
            if sid == "4":
                raise sync.ApiUnavailableError("HTTP 503")
            return self.text, "text/plain"

        with patch.object(sync, "list_documents", return_value=changed), \
             patch.object(sync, "get_document_text", side_effect=content):
            self.assertEqual(sync.mode_daily(self.args), 0)
        self.assertEqual(sync.STATE_PATH.read_bytes(), before_catalog)
        meta = sync.load_json(sync.LAWS_DIR / "4-deneme-4" / "ustveri.json", {})
        self.assertIsNone(meta["official_gazette"]["number"])

    def test_distinct_official_ids_with_same_number_and_title_never_overwrite(self):
        duplicate_title = {**self.docs[0], "mevzuatId": "99"}
        original = sync.LAWS_DIR / "1-deneme-1"
        before = (original / "ustveri.json").read_bytes()
        with patch.object(sync, "list_documents", return_value=self.docs + [duplicate_title]), \
             patch.object(sync, "get_document_text", return_value=(self.text, "text/plain")):
            self.assertEqual(sync.mode_daily(self.args), 0)
        by_id = sync.existing_by_id(sync.LAWS_DIR)
        self.assertEqual(set(by_id), {"1", "2", "3", "4", "99"})
        self.assertNotEqual(by_id["1"], by_id["99"])
        self.assertEqual((original / "ustveri.json").read_bytes(), before)
        self.assertEqual(sync.load_json(sync.INDEX_PATH, {})["documents_total"], 5)

    def test_title_change_updates_existing_official_id_without_leaving_duplicate_directory(self):
        renamed = {**self.docs[0], "mevzuatAdi": "Yeni başlık"}
        with patch.object(sync, "get_document_text", return_value=(self.text, "text/plain")):
            slug, fetched = sync.write_document(renamed, sync.LAWS_DIR, preserve_good_on_error=True)
        self.assertTrue(fetched)
        self.assertEqual(slug, "1-deneme-1")
        self.assertEqual(len(list(sync.LAWS_DIR.glob("*/ustveri.json"))), 4)
        self.assertEqual(sync.load_json(sync.LAWS_DIR / slug / "ustveri.json", {})["title"], "Yeni başlık")

    def test_main_uses_retry_exit_code_only_for_temporary_outage(self):
        for error, expected in [(sync.ApiUnavailableError("HTTP 503"), 75), (sync.ApiError("bad data"), 1)]:
            with self.subTest(error=error), \
                 patch.object(sync.sys, "argv", ["senkronize.py"]), \
                 patch.object(sync, "mode_daily", side_effect=error), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(sync.main(), expected)


if __name__ == "__main__":
    unittest.main()
