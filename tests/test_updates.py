"""更新发现和下载均使用受控响应，不访问网络或替换真实程序。"""
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.error import URLError

from databody.updates import UpdateService, REPOSITORY_URL, RELEASE_API_URL


PAYLOAD = b'MZverified new program'
SHA = hashlib.sha256(PAYLOAD).hexdigest()


class Response(io.BytesIO):
    def __init__(self, data, *, url='', size=None):
        super().__init__(data)
        self.url = url
        self.headers = {} if size is None else {'Content-Length': str(size)}

    def geturl(self):
        return self.url


def release(tag='v1.10.0', **changes):
    result = {'tag_name': tag, 'draft': False, 'prerelease': False, 'body': '修正与改进', 'assets': [
        {'name': 'bb-ee-databody-tool.exe', 'size': len(PAYLOAD), 'digest': 'sha256:' + SHA},
        {'name': 'SHA256SUMS.txt', 'size': 100}]}
    return {**result, **changes}


class UpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.installer = Mock(can_install=True)
        self.installer.prepare.side_effect = lambda package, checksum, version: package.parent / 'plan.json'
        self.opener = Mock()
        self.updater = UpdateService('1.9.0', installer=self.installer,
                                     directory=self.root, opener=self.opener)

    def responses(self, document=None, payload=PAYLOAD, checksums=None):
        self.opener.side_effect = [Response(json.dumps(document or release()).encode()),
            Response((checksums if checksums is not None else SHA + '  bb-ee-databody-tool.exe\n').encode()),
            Response(payload, size=len(payload))]

    def test_numeric_versions_find_newer_release_without_writing_or_installing(self):
        self.responses()
        result = self.updater.check()
        self.assertTrue(result['available'])
        self.assertEqual(result['latest_version'], '1.10.0')
        self.assertEqual(result['current_version'], '1.9.0')
        self.assertEqual(result['release_url'], REPOSITORY_URL + '/releases/tag/v1.10.0')
        self.assertEqual(list(self.root.iterdir()), [])
        self.installer.prepare.assert_not_called()

    def test_current_or_older_version_never_downloads(self):
        for tag in ('v1.9.0', 'v1.8.0'):
            with self.subTest(tag=tag):
                self.opener.side_effect = [Response(json.dumps(release(tag)).encode())]
                self.assertFalse(self.updater.check()['available'])
                with self.assertRaisesRegex(ValueError, '新版本'):
                    self.updater.prepare()
        self.installer.prepare.assert_not_called()

    def test_network_failure_uses_only_official_release_redirect(self):
        self.opener.side_effect = [URLError('blocked'), Response(b'', url=REPOSITORY_URL + '/releases/tag/v1.10.0')]
        self.assertTrue(self.updater.check()['available'])
        self.assertEqual(self.opener.call_args_list[0].args[0].full_url, RELEASE_API_URL)
        self.assertEqual(self.opener.call_args_list[1].args[0].full_url, REPOSITORY_URL + '/releases/latest')
        self.assertTrue(all(0 < call.kwargs['timeout'] <= 15 for call in self.opener.call_args_list))

    def test_invalid_or_unstable_release_is_not_installed_or_silently_bypassed(self):
        for document in (release('v1.10.0-beta.1'), release(draft=True), release(prerelease=True),
                         release(assets=[])):
            with self.subTest(document=document):
                self.opener.side_effect = [Response(json.dumps(document).encode())]
                with self.assertRaises(ValueError):
                    self.updater.check()
        self.installer.prepare.assert_not_called()

    def test_failed_network_check_is_retryable_and_does_not_write(self):
        self.opener.side_effect = [URLError('offline'), URLError('offline')]
        with self.assertRaisesRegex(ValueError, 'GitHub'):
            self.updater.check()
        self.responses()
        self.assertTrue(self.updater.check()['available'])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_verified_download_is_prepared_before_explicit_install(self):
        self.responses()
        self.updater.check()
        result = self.updater.prepare()
        self.assertEqual(result['phase'], 'ready')
        self.assertEqual(self.updater.status()['received'], len(PAYLOAD))
        package, checksum, version = self.installer.prepare.call_args.args
        self.assertEqual(package.read_bytes(), PAYLOAD)
        self.assertEqual((checksum, version), (SHA, '1.10.0'))
        self.installer.launch.assert_not_called()
        self.updater.install()
        self.installer.launch.assert_called_once_with(package.parent / 'plan.json')

    def test_truncation_bad_checksum_and_non_executable_never_reach_installer(self):
        cases = [(PAYLOAD[:-1], None), (PAYLOAD, '0' * 64 + '  bb-ee-databody-tool.exe\n'),
                 (b'not an executable', hashlib.sha256(b'not an executable').hexdigest() + '  bb-ee-databody-tool.exe\n')]
        for payload, sums in cases:
            with self.subTest(payload=payload, sums=sums):
                doc = release()
                if payload == b'not an executable':
                    doc['assets'][0].update(size=len(payload), digest=None)
                self.responses(document=doc, payload=payload, checksums=sums)
                self.updater.check()
                with self.assertRaises(ValueError):
                    self.updater.prepare()
                self.assertEqual(list(self.root.iterdir()), [])
        self.installer.prepare.assert_not_called()

    def test_prepare_failure_keeps_retry_possible_and_source_mode_cannot_install(self):
        self.responses()
        self.updater.check()
        self.installer.prepare.side_effect = PermissionError('read only')
        with self.assertRaises(OSError):
            self.updater.prepare()
        self.assertEqual(self.updater.status()['phase'], 'error')
        self.assertEqual(list(self.root.iterdir()), [])
        self.installer.can_install = False
        with self.assertRaisesRegex(ValueError, 'EXE'):
            self.updater.prepare()
        self.installer.launch.assert_not_called()

    def test_close_during_download_discards_partial_update(self):
        self.responses()
        self.updater.check()
        self.updater.cancel()
        with self.assertRaisesRegex(ValueError, '取消'):
            self.updater.prepare()
        self.installer.prepare.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_close_after_first_download_chunk_removes_the_partial_file(self):
        updater = self.updater

        class Interrupted(Response):
            def read(self, *args):
                result = super().read(*args)
                updater.cancel()
                return result

        self.opener.side_effect = [Response(json.dumps(release()).encode()),
            Response((SHA + '  bb-ee-databody-tool.exe\n').encode()), Interrupted(PAYLOAD)]
        self.updater.check()
        with self.assertRaisesRegex(ValueError, '取消'):
            self.updater.prepare()
        self.installer.prepare.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_failed_download_can_be_retried_and_ready_download_is_discarded_on_close(self):
        self.responses(payload=PAYLOAD[:-1])
        self.updater.check()
        with self.assertRaises(ValueError):
            self.updater.prepare()
        self.opener.side_effect = [Response((SHA + '  bb-ee-databody-tool.exe\n').encode()), Response(PAYLOAD)]
        self.assertEqual(self.updater.prepare()['phase'], 'ready')
        self.updater.cancel()
        self.installer.discard.assert_called_once()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_official_redirect_fallback_downloads_with_checksum_and_rejects_other_hosts(self):
        self.opener.side_effect = [URLError('rate limit'),
            Response(b'', url=REPOSITORY_URL + '/releases/tag/v1.10.0'),
            Response((SHA + '  bb-ee-databody-tool.exe\n').encode()), Response(PAYLOAD)]
        self.assertTrue(self.updater.check()['available'])
        self.assertEqual(self.updater.prepare()['phase'], 'ready')
        self.updater.cancel()
        self.updater = UpdateService('1.9.0', installer=self.installer,
                                     directory=self.root, opener=self.opener)
        self.opener.side_effect = [URLError('blocked'), Response(b'', url='https://example.com/releases/tag/v9.0.0')]
        with self.assertRaisesRegex(ValueError, '官方'):
            self.updater.check()


if __name__ == '__main__':
    unittest.main()
