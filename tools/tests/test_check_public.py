"""Tests for the check that stands between private data and the public repository."""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock
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

    def test_phone_numbers_written_without_separators_are_found(self):
        for text in ("+13128675309", "+1.312.867.5309", "call 3128675309 today", "Phone: 13128675309", "mobile | 3128675309"):
            with self.subTest(text):
                self.assertFound(text, "phone")
        # 555 still marks one as made up, and ten digits with nothing saying they're a phone number are just a number.
        self.assertEqual(cp.builtin_findings("+15550100142, +1.555.010.0142, | Phone number | 5550100142 |, order 3128675309"), [])

    def test_a_home_folder_in_any_case_is_found_but_a_web_address_is_not(self):
        self.assertFound(r"c:\users\somebody\Downloads", "home folder")
        self.assertFound("C:/USERS/somebody/AppData", "home folder")
        self.assertEqual(cp.builtin_findings("https://api.example.com/users/somebody"), [])

    def test_more_kinds_of_credentials_are_found(self):
        for text in ("github_pat_" + "A1b2" * 10, "OPENAI_API_KEY=sk-proj-" + "a1B2" * 8, "AIza" + "x1Y2z3" * 5 + "abcde",
                     "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc", "https://hooks.slack.com/services/T000/B000/" + "x" * 24,
                     "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "password = 'Hunter2Hunter2!'",
                     "IMAP_PASSWORD=qwer tyui opas dfgh",
                     # Joined at run time, so gitleaks doesn't take the sample token for a real one.
                     "eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0" + ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"):
            with self.subTest(text[:20]):
                self.assertFound(text, "credential")
        # Code that passes a secret along, a type, and the usual stand-ins aren't secrets.
        self.assertEqual(cp.builtin_findings("token = cfg.token\npassword: str\nIMAP_PASSWORD=abcd efgh ijkl mnop\n"
                                             "password = os.environ['IMAP_PASSWORD']\napi_key = your_api_key_here\n"
                                             "token_url: https://oauth2.example.com/token\n"), [])

    def test_more_personal_email_domains_are_found(self):
        for address in ("someone@fastmail.com", "someone@comcast.net", "someone@pm.me", "someone@GMAIL.COM"):
            with self.subTest(address):
                self.assertFound(address, "personal email")


class Blobs(unittest.TestCase):
    def scan(self, path, blob=b"", deny=DENY):
        return cp.scan_blob(path, blob, deny)

    def test_private_paths_are_refused_even_when_empty(self):
        for path in ("profile/facts.md", "applications/x/resume.md", "archive/a.pdf", "data/pyrite.db",
                     "tools/copy.db", ".pyrite-home", "somewhere/imap.env", "Profile/facts.md", "DATA/pyrite.db", ".env.local",
                     "tools/imap.env.bak", "backup/pyrite.db-journal", "backup/pyrite.sqlite3", "backup/pyrite.db.bak"):
            with self.subTest(path):
                self.assertIn("private path", self.scan(path))
        for path in ("tools/pyrite/imap.env.example", ".env.example", "tools/pyrite/static/profile/basics.js"):
            with self.subTest(path):
                self.assertNotIn("private path", self.scan(path))

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

    def test_icons_and_doc_images_may_be_pngs_but_nothing_else_binary(self):
        for folder in ("tools/pyrite/static/icons/", "docs/images/"):
            with self.subTest(folder):
                self.assertEqual(self.scan(folder + "mark.png", self.png(b"IDAT", b"bluebird")), [])
                self.assertTrue(self.scan(folder + "mark.png", self.png(b"tEXt", b"Author\0Bluebird")))
                self.assertTrue(any("of a kind this doesn't read" in f for f in self.scan(folder + "favicon.ico", b"\0\0\1\0")))
        self.assertTrue(any("binary file outside" in f for f in self.scan("tools/pyrite/static/mark.png", self.png(b"IDAT", b""))))

    def test_compressed_png_metadata_is_read(self):
        import zlib
        self.assertTrue(self.scan("docs/screenshots/a.png", self.png(b"zTXt", b"Author\0\0" + zlib.compress(b"Bluebird"))))

    def test_documents_are_read_as_a_reader_sees_them(self):
        # A name split across runs, as Word does where the formatting changes, and one written with entities.
        split = self.docx('<w:p><w:r><w:t>Blue</w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>bird</w:t></w:r></w:p>')
        self.assertTrue(any("denylisted" in f for f in self.scan("example/applications/a/x.docx", split)))
        entities = self.docx("<w:p><w:r><w:t>Blue&#98;ir&#x64; call 312&#45;867-5309</w:t></w:r></w:p>")
        found = self.scan("example/applications/a/x.docx", entities)
        self.assertTrue(any("denylisted" in f for f in found), found)
        self.assertTrue(any("phone number" in f for f in found), found)
        self.assertEqual(self.scan("example/applications/a/x.docx", self.docx("<w:p><w:r><w:t>Alex Rivera</w:t></w:r></w:p>")), [])

    def test_only_documents_and_screenshots_this_reads_are_allowed(self):
        import io
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("xl/sharedStrings.xml", "<sst><si><t>Bluebird</t></si></sst>")
        for path in ("example/applications/a/tracker.xlsx", "example/applications/a/sent.zip", "docs/screenshots/deck.pptx",
                     "docs/screenshots/a.jpg"):
            with self.subTest(path):
                found = self.scan(path, buffer.getvalue())
                self.assertTrue(any("of a kind this doesn't read" in f for f in found), found)
        # A zip's members are read wherever it is, so what's inside is named too.
        self.assertTrue(any("denylisted" in f for f in self.scan("example/applications/a/tracker.xlsx", buffer.getvalue())))
        found = self.scan("example/applications/a/x.docx", b"PK\x03\x04 not really a document")
        self.assertTrue(any(cp.UNREADABLE_ARCHIVE in f for f in found), found)

    def test_utf16_text_in_png_metadata_is_read(self):
        exif = b"MM\0*" + "XPAuthor Bluebird".encode("utf-16-le")
        self.assertTrue(self.scan("docs/screenshots/a.png", self.png(b"eXIf", exif)))
        self.assertTrue(self.scan("docs/screenshots/a.png", self.png(b"eXIf", b"\0" + "Bluebird".encode("utf-16-le"))))

    @staticmethod
    def docx(body):
        import io
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", f'<w:document xmlns:w="w"><w:body>{body}</w:body></w:document>')
        return buffer.getvalue()

    def test_empty_denylist_file_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "deny.txt"
            path.write_text("# only a comment\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                cp.load_denylist(path)


@unittest.skipUnless(shutil.which("git"), "needs git")
class Repository(unittest.TestCase):
    """What a push publishes besides the files: a submodule, and the tags with their messages."""

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Sam Doe", "-c", "user.email=sam@example.com", *args],
                              capture_output=True, text=True, check=True).stdout.strip()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.git("init", "-q")
        (self.repo / "README.md").write_text("A project.\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-q", "-m", "Start")
        patcher = mock.patch.object(cp, "REPO", self.repo)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_clean_repository_passes(self):
        self.assertEqual(cp.scan_repository([]), [])

    def test_a_submodule_is_named_rather_than_crashing_the_check(self):
        commit = self.git("rev-parse", "HEAD")
        self.git("update-index", "--add", "--cacheinfo", f"160000,{commit},vendor/lib")
        self.assertEqual(cp.scan_repository([]), [f"vendor/lib: {cp.SUBMODULE}"])
        self.git("commit", "-q", "-m", "Add a submodule")
        self.assertEqual(cp.scan_repository([]), [f"vendor/lib: {cp.SUBMODULE}"])

    def test_an_annotated_tags_message_and_tagger_are_checked(self):
        self.git("tag", "-a", "v1", "-m", "Release. Questions to 312-867-5309.")
        self.git("tag", "v2")  # A lightweight tag has no message of its own.
        found = cp.scan_repository([re.compile("Sam Doe")])
        self.assertIn("tag v1: phone number 312-867-5309", found)
        self.assertIn("tag v1: denylisted term 'Sam Doe'", found)


if __name__ == "__main__":
    unittest.main()
