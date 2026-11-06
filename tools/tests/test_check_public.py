"""Tests for the check that stands between private data and the public repository."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_public as cp  # noqa: E402

DENY = [re.compile("Bluebird", re.I)]


class Builtin(unittest.TestCase):
    def assertFound(self, text, words):
        self.assertTrue(any(words in f for f in cp.builtin_findings(text)), cp.builtin_findings(text))

    def test_real_looking_phone_is_found_and_fictional_one_is_not(self):
        self.assertFound("call (312) 867-5309", "phone")
        self.assertFound("call 312-867-5309", "phone")
        self.assertEqual(cp.builtin_findings("call (555) 010-0142"), [])

    def test_personal_email_is_found_and_example_address_is_not(self):
        self.assertFound("write to someone@gmail.com", "personal email")
        self.assertEqual(cp.builtin_findings("alex.rivera@example.com, sam@contoso.com"), [])

    def test_private_network_details_are_found(self):
        self.assertFound("box.tailabc123.ts.net", "private network name")
        self.assertFound("100.68.1.2", "private network address")
        self.assertEqual(cp.builtin_findings("workstation.example-tailnet.ts.net and 8.8.8.8"), [])

    def test_home_folder_is_found(self):
        self.assertFound(r"C:\Users\somebody\project", "home folder")
        self.assertFound("/home/somebody/project", "home folder")

    def test_credentials_are_found(self):
        self.assertFound("key sk-ant-api03-abcdefgh", "credential")
        self.assertFound("ghp_" + "a" * 30, "credential")


class Blobs(unittest.TestCase):
    def scan(self, path, blob=b"", deny=DENY):
        return cp.scan_blob(path, blob, deny)

    def test_private_paths_are_refused_even_when_empty(self):
        for path in ("profile/facts.md", "applications/x/resume.md", "archive/a.pdf", "data/warroom.db",
                     "tools/copy.db", ".warroom-home", "somewhere/imap.env"):
            with self.subTest(path):
                self.assertIn("private path", self.scan(path))

    def test_example_workspace_is_allowed(self):
        self.assertEqual(self.scan("example/profile/facts.md", b"Alex Rivera"), [])
        self.assertEqual(self.scan("example/applications/a/resume.md", b"Alex Rivera"), [])

    def test_stray_documents_are_refused(self):
        self.assertTrue(self.scan("resume.pdf", b"%PDF"))
        self.assertTrue(self.scan("tools/resume.docx", b"x"))

    def test_denylist_terms_are_found_in_any_case(self):
        self.assertTrue(self.scan("tools/a.py", b"the BLUEBIRD project"))
        self.assertEqual(self.scan("tools/a.py", b"nothing to see"), [])

    def test_text_inside_a_docx_is_read(self):
        import io
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("docProps/core.xml", "<creator>Bluebird</creator>")
        self.assertTrue(self.scan("example/applications/a/x.docx", buffer.getvalue()))

    def test_text_inside_a_pdf_stream_is_read(self):
        import zlib
        blob = b"%PDF-1.7\nstream\n" + zlib.compress(b"Bluebird") + b"\nendstream\n"
        self.assertTrue(self.scan("example/applications/a/x.pdf", blob))

    @staticmethod
    def png(kind, data):
        chunk = len(data).to_bytes(4, "big") + kind + data + b"\0\0\0\0"
        return b"\x89PNG\r\n\x1a\n" + chunk

    def test_png_pixels_are_not_mistaken_for_text(self):
        self.assertEqual(self.scan("docs/screenshots/a.png", self.png(b"IDAT", b"bluebird")), [])

    def test_png_metadata_is_read(self):
        self.assertTrue(self.scan("docs/screenshots/a.png", self.png(b"tEXt", b"Author\0Bluebird")))

    def test_compressed_png_metadata_is_read(self):
        import zlib
        self.assertTrue(self.scan("docs/screenshots/a.png", self.png(b"zTXt", b"Author\0\0" + zlib.compress(b"Bluebird"))))

    def test_empty_denylist_file_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "deny.txt"
            path.write_text("# only a comment\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                cp.load_denylist(path)


if __name__ == "__main__":
    unittest.main()
