"""Tests for the check that stands between private data and the public repository."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_public as cp

DENY = [re.compile("Bluebird", re.I)]
EXAMPLE_PDF = (Path(__file__).resolve().parents[2] / "example" / "applications"
               / "2026-11-acme-principal-robotics-software-engineer" / "Alex_Rivera_Resume_Acme_Robotics.pdf")


class Builtin(unittest.TestCase):
    def assertFound(self, text, words):
        self.assertTrue(any(words in f for f in cp.builtin_findings(text)), cp.builtin_findings(text))

    def test_real_looking_phone_is_found_and_fictional_one_is_not(self):
        self.assertFound("call (312) 867-5309", "phone")
        self.assertFound("call 312-867-5309", "phone")
        self.assertEqual(cp.builtin_findings("call (555) 010-0142"), [])

    def test_phone_numbers_with_spaces_or_a_country_code_are_found(self):
        for number in ("312 867 5309", "(312) 867 5309", "+1 312 867 5309", "+44 20 7946 0958", "+49 (30) 901820"):
            with self.subTest(number):
                self.assertFound(f"call {number} today", "phone")
        self.assertEqual(len(cp.builtin_findings("call +1 312-867-5309")), 1)

    def test_only_a_555_area_code_or_exchange_marks_a_number_as_fictional(self):
        self.assertEqual(cp.builtin_findings("call 312-555-0142 or (555) 010-0142"), [])
        self.assertFound("call 312-867-5550", "phone")

    def test_ordinary_numbers_are_not_phone_numbers(self):
        self.assertEqual(cp.builtin_findings("score +15, about 1,400 robots, 2026-11-06, build 3.14.159, +250 lines"), [])

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
        for path in ("profile/facts.md", "applications/x/resume.md", "archive/a.pdf", "data/pyrite.db",
                     "tools/copy.db", ".pyrite-home", "somewhere/imap.env"):
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

    def test_a_denylisted_name_in_a_path_is_found(self):
        found = self.scan("example/applications/2026-11-bluebird-staff-engineer/notes.md", b"fit notes")
        self.assertTrue(any("in the file's path" in f for f in found), found)
        self.assertEqual(self.scan("example/applications/2026-11-acme-staff-engineer/notes.md", b"fit notes"), [])

    def test_branch_and_tag_names_are_checked(self):
        self.assertTrue(cp.ref_findings(["refs/heads/main", "refs/heads/bluebird-application"], DENY))
        self.assertEqual(cp.ref_findings(["refs/heads/main", "refs/tags/v1"], DENY), [])

    def test_binary_content_is_refused_whatever_its_extension(self):
        for path in ("backup/search.sqlite3", "notes/export.doc", "tools/readme.txt"):
            with self.subTest(path):
                self.assertTrue(any("binary file" in f for f in self.scan(path, b"SQLite format 3\x00" + bytes(range(200)))))
        self.assertEqual(self.scan("tools/readme.txt", "plain text, with an é".encode()), [])

    def test_pdf_author_written_as_utf16_is_read(self):
        literal = b"%PDF-1.7\n<< /Author (\xfe\xff" + "Bluebird (team)".encode("utf-16-be").replace(b"(", b"\\(").replace(b")", b"\\)") + b") >>"
        hexed = b"%PDF-1.7\n<< /Author <FEFF" + "Bluebird".encode("utf-16-be").hex().upper().encode() + b"> >>"
        for blob in (literal, hexed):
            self.assertIn("Bluebird", cp.pdf_metadata(blob))

    @unittest.skipUnless(cp.pdf_text((EXAMPLE_PDF).read_bytes()), "needs pypdf or poppler's pdftotext")
    def test_words_on_a_pdf_page_are_read(self):
        blob = EXAMPLE_PDF.read_bytes()
        self.assertEqual(self.scan("example/applications/a/x.pdf", blob), [])
        found = self.scan("example/applications/a/x.pdf", blob, [re.compile("Northbridge Robotics", re.I)])
        self.assertTrue(any("denylisted" in f for f in found), found)

    def test_a_pdf_nothing_can_read_is_refused(self):
        from unittest import mock
        with mock.patch.object(cp, "pdf_text", return_value=None):
            found = self.scan("example/applications/a/x.pdf", EXAMPLE_PDF.read_bytes())
        self.assertIn(cp.UNREADABLE_PDF, found)

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
