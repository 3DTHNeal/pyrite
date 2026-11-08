"""Reply detection over IMAP and the Gmail connector, and the scam rules. Read-only throughout."""
import json
import os
import subprocess
import unittest
import unittest.mock as mock
from datetime import UTC, datetime, timedelta
from pathlib import Path

from support import CFG, Base

from pyrite import claude_code, cli, inbox, server, store
from pyrite import mail as mailcheck


class FakeImap:
    """Refuses anything but login, a read-only select, UID SEARCH, UID FETCH and logout.

    Like a real server, it marks a message seen if fetched without PEEK, and hands
    back the body unless only header fields are requested.
    """

    def __init__(self, messages=(), folders=("[Gmail]/All Mail", "INBOX"), login_error=None):
        self.messages = dict(enumerate(messages, start=1))
        self.folders = folders
        self.login_error = login_error
        self.selected = []
        self.commands = []
        self.seen = set()
        self.logged_out = False

    def login(self, user, password):
        if self.login_error:
            raise inbox.imaplib.IMAP4.error(self.login_error)
        return "OK", [b"logged in"]

    def select(self, mailbox="INBOX", readonly=False):
        if not readonly:
            raise AssertionError("A folder was opened read-write.")
        self.selected.append(mailbox)
        return ("OK", [b"1"]) if mailbox.strip('"') in self.folders else ("NO", [b"no such folder"])

    def list(self):
        flags = lambda name: "\\All \\HasNoChildren" if name.startswith("[Gmail]/") else "\\HasNoChildren"
        return "OK", [f'({flags(name)}) "/" "{name}"'.encode() for name in self.folders]

    def uid(self, command, *args):
        self.commands.append((command, *args))
        if command == "SEARCH":
            return "OK", [" ".join(str(uid) for uid in self.messages).encode()]
        if command == "FETCH":
            spec = args[1]
            parts = []
            for uid in (int(u) for u in args[0].split(",")):
                if "PEEK" not in spec:
                    self.seen.add(uid)
                raw = self.messages[uid]
                if "HEADER.FIELDS" in spec:
                    raw = raw.split(b"\r\n\r\n")[0] + b"\r\n\r\n"
                parts += [(f"{uid} (UID {uid} BODY[...]".encode(), raw), b")"]
            return "OK", parts
        raise AssertionError(f"Command not allowed: {command}")

    def logout(self):
        self.logged_out = True
        return "BYE", [b""]

    def __getattr__(self, name):
        raise AssertionError(f"Method not allowed on a read-only mailbox: {name}")


def mail(sender, subject, date="Fri, 06 Nov 2026 16:30:00 +0000", extra=""):
    text = f"From: {sender}\r\nSubject: {subject}\r\nDate: {date}\r\n{extra}\r\nSECRET BODY TEXT\r\n"
    return text.encode()


APPLIED_AT = "2026-11-05T12:00:00+00:00"
FAR_FUTURE_LOOKBACK = {"inbox": {"lookback_days": 100000, "domains": {"Hooli": ["hooli-mail.example"]}}}


def share_with_others(path):
    if os.name == "nt":
        # S-1-1-0 is Everyone, whatever language Windows is set to.
        subprocess.run(["icacls", str(path), "/grant", "*S-1-1-0:R"], capture_output=True, check=True)
    else:
        path.chmod(0o644)


class InboxBase(Base):
    def setUp(self):
        super().setUp()
        self.creds = Path(self.tmp.name) / "imap.env"
        self.creds.write_text("IMAP_USER=me@example.test\nIMAP_PASSWORD=abcd efgh ijkl mnop\n", encoding="utf-8")
        self.creds.chmod(0o600)

    def applied(self, company="Contoso", **kw):
        fields = {"status": "applied", "applied_at": APPLIED_AT, "status_changed_at": APPLIED_AT,
                  "source_id": f"{company}-{len(self.conn.execute('SELECT id FROM jobs').fetchall())}", **kw}
        return self.add(company=company, **fields)

    def scan(self, *messages, fake=None):
        self.fake = fake or FakeImap(messages)
        return inbox.run(self.conn, FAR_FUTURE_LOOKBACK, self.creds, lambda creds: self.fake)

    def replies(self, job):
        return [r["detail"] for r in self.conn.execute(
            "SELECT detail FROM events WHERE job_id = ? AND kind = 'reply_detected'", (job,))]


class ReplyMatching(InboxBase):
    def test_mail_from_the_company_domain_is_recorded_with_only_sender_subject_and_date(self):
        job = self.applied()
        result = self.scan(mail("Sam Lee <sam@contoso.com>", "Your application"))
        self.assertEqual(result["state"], "ok")
        self.assertEqual([hit["job_id"] for hit in result["found"]], [job])
        self.assertEqual(self.replies(job), ["From Sam Lee <sam@contoso.com> | Subject: Your application | Date: 2026-11-06 16:30 UTC"])

    def test_subdomain_of_the_company_matches(self):
        job = self.applied()
        self.scan(mail("careers@email.careers.contoso.com", "Next steps"))
        self.assertEqual(len(self.replies(job)), 1)

    def test_tld_can_be_part_of_the_company_name(self):
        job = self.applied("Aperture AI")
        self.scan(mail("talent@aperture.ai", "Hello"))
        self.assertEqual(len(self.replies(job)), 1)

    def test_listed_domain_and_posting_link_count_as_the_employer(self):
        listed = self.applied("Hooli")
        linked = self.applied("Acme Widgets", url="https://careers.acmecorp.example/jobs/1")
        self.scan(mail("hr@hooli-mail.example", "Hello"), mail("hr@acmecorp.example", "Hello"))
        self.assertEqual(len(self.replies(listed)), 1)
        self.assertEqual(len(self.replies(linked)), 1)

    def test_ats_posting_link_does_not_make_the_ats_an_employer(self):
        job = self.applied("Acme", url="https://boards.greenhouse.io/acme/jobs/1")
        self.scan(mail("no-reply@greenhouse.io", "Your application to Globex"))
        self.assertEqual(self.replies(job), [])

    def test_ats_mail_matches_only_when_the_company_is_named(self):
        job = self.applied()
        other = self.applied("Initech")
        self.scan(mail("no-reply@us.greenhouse-mail.io", "Your application to Contoso"),
                  mail("Initech Talent <no-reply@hire.lever.co>", "Update"))
        self.assertEqual(len(self.replies(job)), 1)
        self.assertIn("Your application to Contoso", self.replies(job)[0])
        self.assertEqual(len(self.replies(other)), 1)
        self.assertIn("Initech Talent", self.replies(other)[0])

    def test_workday_tenant_address_matches(self):
        job = self.applied("Stark Dynamics", source_key="workday:stark")
        self.scan(mail("stark@myworkday.com", "Update"))
        self.assertEqual(len(self.replies(job)), 1)

    def test_legal_suffix_does_not_stop_a_match(self):
        job = self.applied("Acme, Inc.")
        self.scan(mail("hr@acme.example", "Hello"), mail("x@icims.com", "Your Acme application"))
        self.assertEqual(len(self.replies(job)), 2)

    def test_unrelated_companies_do_not_match(self):
        job = self.applied()
        initech = self.applied("Initech")
        self.scan(
            mail("sam@contosa.com", "Your application"),
            mail("sam@globex.com", "Your application"),
            mail("x@greenhouse.io", "Thank you for applying to Contosoville"),
            mail("x@greenhouse.io", "Your application to Applied Initechnics"),
            mail("friend@mail.example", "Did you hear back from Contoso?"),
        )
        self.assertEqual(self.replies(job), [])
        self.assertEqual(self.replies(initech), [])

    def test_lookalike_domains_do_not_match(self):
        job = self.applied()
        self.scan(mail("x@contoso.evil.example", "Interview"), mail("x@contoso.com.evil.example", "Interview"),
                  mail("x@contoso-careers.example", "Interview"), mail('"sam@contoso.com" <x@evil.example>', "Interview"))
        self.assertEqual(self.replies(job), [])

    def test_job_board_alerts_never_match(self):
        job = self.applied()
        linkedin = self.applied("LinkedIn")
        self.scan(mail("Contoso via LinkedIn <jobalerts-noreply@linkedin.com>", "Contoso is hiring a Principal Engineer"),
                  mail("alert@indeed.com", "New Contoso jobs"))
        self.assertEqual(self.replies(job), [])
        self.assertEqual(self.replies(linkedin), [])

    def test_marketing_list_mail_skipped_unless_about_hiring(self):
        job = self.applied()
        unsubscribe = "List-Unsubscribe: <mailto:u@contoso.com>\r\n"
        self.scan(mail("deals@contoso.com", "25% off running shoes", extra=unsubscribe),
                  mail("talent@contoso.com", "An update on your application", extra=unsubscribe))
        self.assertEqual(len(self.replies(job)), 1)
        self.assertIn("update on your application", self.replies(job)[0])

    def test_placeholder_company_never_matches(self):
        job = self.applied("Company not recorded")
        self.scan(mail("x@greenhouse.io", "Company not recorded"), mail("x@companynotrecorded.com", "Hi"))
        self.assertEqual(self.replies(job), [])

    def test_only_active_applied_jobs_are_checked(self):
        unsent = self.add(company="Contoso", status="ready", source_id="a")
        rejected = self.applied(status="rejected")
        self.scan(mail("sam@contoso.com", "Hello"))
        self.assertEqual(self.replies(unsent), [])
        self.assertEqual(self.replies(rejected), [])

    def test_mail_from_before_you_applied_or_last_updated_is_ignored(self):
        job = self.applied()
        confirmed = self.applied("Initech", status="responded", status_changed_at="2026-11-07T00:00:00+00:00")
        self.scan(mail("sam@contoso.com", "Earlier", date="Wed, 04 Nov 2026 12:00:00 +0000"),
                  mail("sam@initech.com", "Already logged", date="Fri, 06 Nov 2026 12:00:00 +0000"))
        self.assertEqual(self.replies(job), [])
        self.assertEqual(self.replies(confirmed), [])

    def test_your_own_mail_and_unparseable_mail_are_skipped(self):
        job = self.applied("Example")
        self.scan(mail("me@example.test", "Hi"), mail("not an address", "Hi"), mail("a@example.test", "Hi", date="garbage"),
                  mail("a@example.test, b@example.test", "Hi"))
        self.assertEqual(self.replies(job), [])

    def test_running_again_adds_nothing_new(self):
        job = self.applied()
        message = mail("sam@contoso.com", "Hello")
        self.scan(message)
        self.assertEqual(self.scan(message)["found"], [])
        self.assertEqual(len(self.replies(job)), 1)

    def test_two_roles_at_one_company_are_both_flagged(self):
        first, second = self.applied(), self.applied()
        self.scan(mail("sam@contoso.com", "Hello"))
        self.assertEqual(len(self.replies(first)), 1)
        self.assertEqual(len(self.replies(second)), 1)

    def test_a_subject_naming_one_role_goes_to_that_role_only(self):
        first = self.applied(title="Staff Firmware Engineer")
        second = self.applied(title="Engineering Manager, Platform")
        self.scan(mail("sam@contoso.com", "Your interview for Engineering Manager - Platform"))
        self.assertEqual(self.replies(first), [])
        self.assertEqual(len(self.replies(second)), 1)

    def test_receipts_and_account_mail_are_not_replies(self):
        job = self.applied()
        self.scan(
            mail("Contoso <contoso@myworkday.com>", "You have successfully applied to Contoso!"),
            mail("no-reply@us.greenhouse-mail.io", "Thank you for applying to Contoso"),
            mail("Contoso <contoso@otp.workday.com>", "Reset your password for your candidate account"),
            mail("sam@contoso.com", "We received your application"),
            mail("sam@contoso.com", "Your verification code"),
        )
        self.assertEqual(self.replies(job), [])
        # A rejection's usual wording is still flagged.
        self.scan(mail("Contoso <contoso@myworkday.com>", "Thank you for your interest in Contoso"))
        self.assertEqual(len(self.replies(job)), 1)


class ReplyMailboxAccess(InboxBase):
    def test_access_is_read_only_and_never_fetches_the_body(self):
        job = self.applied()
        self.scan(mail("sam@contoso.com", "Hello"))
        self.assertEqual(self.fake.selected, ['"[Gmail]/All Mail"'])  # The fake raises if readonly isn't set.
        self.assertEqual([c[0] for c in self.fake.commands], ["SEARCH", "FETCH"])
        spec = self.fake.commands[1][2]
        self.assertIn("BODY.PEEK[HEADER.FIELDS", spec)
        self.assertEqual(self.fake.seen, set())
        self.assertTrue(self.fake.logged_out)
        stored = " ".join(str(tuple(r)) for r in self.conn.execute("SELECT * FROM events"))
        self.assertNotIn("SECRET", stored)
        self.assertEqual(len(self.replies(job)), 1)

    def test_writing_to_the_mailbox_is_refused_by_the_fake(self):
        with self.assertRaises(AssertionError):
            FakeImap().store("1", "+FLAGS", "\\Seen")

    def test_falls_back_to_inbox_when_all_mail_is_hidden(self):
        job = self.applied()
        result = self.scan(fake=FakeImap([mail("sam@contoso.com", "Hello")], folders=("INBOX",)))
        self.assertEqual(result["folder"], "INBOX")
        self.assertEqual(len(self.replies(job)), 1)

    def test_all_mail_is_found_under_another_language_name(self):
        job = self.applied()
        result = self.scan(fake=FakeImap([mail("sam@contoso.com", "Hello")], folders=("INBOX", "[Gmail]/Alle Nachrichten")))
        self.assertEqual(result["folder"], "[Gmail]/Alle Nachrichten")
        self.assertEqual(len(self.replies(job)), 1)

    def test_login_is_still_checked_with_no_applications(self):
        result = self.scan(mail("sam@contoso.com", "Hello"))
        self.assertEqual((result["state"], result["jobs"], result["messages"]), ("ok", 0, 0))
        self.assertEqual(self.fake.selected, ['"[Gmail]/All Mail"'])
        self.assertEqual(self.fake.commands, [])

    def test_certificates_are_verified(self):
        contexts = []
        original = inbox.imaplib.IMAP4_SSL
        inbox.imaplib.IMAP4_SSL = lambda *a, **k: contexts.append(k["ssl_context"])
        try:
            inbox.open_client(inbox.Credentials("u", "p"))
        finally:
            inbox.imaplib.IMAP4_SSL = original
        self.assertEqual(contexts[0].verify_mode, inbox.ssl.CERT_REQUIRED)
        self.assertTrue(contexts[0].check_hostname)


class ReplyNeverChangesStatus(InboxBase):
    def test_job_row_and_response_rate_are_untouched(self):
        job = self.applied(next_action="Follow up", next_action_date="2026-11-12")
        self.conn.commit()
        before = dict(store.get_job(self.conn, job))
        rate = server.build_state(self.conn, CFG)["stats"]
        result = self.scan(mail("sam@contoso.com", "We'd like to interview you"))
        self.assertEqual(len(result["found"]), 1)
        self.assertEqual(dict(store.get_job(self.conn, job)), before)
        after = server.build_state(self.conn, CFG)["stats"]
        self.assertEqual(after["response_rate"], rate["response_rate"])
        self.assertEqual(after["heard"], 0)

    def test_flag_shows_on_the_dashboard_until_you_confirm(self):
        job = self.applied()
        self.scan(mail("sam@contoso.com", "Hello"))
        state = server.build_state(self.conn, CFG)
        card = next(j for j in state["jobs"] if j["id"] == job)
        self.assertIn("sam@contoso.com", card["possible_reply"]["detail"])
        self.assertEqual(state["orders"][0]["kind"], "Possible reply")
        self.assertTrue(server.job_detail(self.conn, job, CFG)["possible_reply"])
        server.apply_action(self.conn, job, {"action": "heard_back", "kind": "reply"}, CFG)
        self.assertIsNone(server.job_detail(self.conn, job, CFG)["possible_reply"])
        self.assertEqual(server.build_state(self.conn, CFG)["stats"]["heard"], 1)

    def test_dismiss_clears_the_flag_without_changing_status_and_it_stays_dismissed(self):
        job = self.applied()
        message = mail("sam@contoso.com", "Hello")
        self.scan(message)
        server.apply_action(self.conn, job, {"action": "dismiss_reply"}, CFG)
        self.assertIsNone(server.job_detail(self.conn, job, CFG)["possible_reply"])
        self.assertEqual(store.get_job(self.conn, job)["status"], "applied")
        self.assertIsNone(store.get_job(self.conn, job)["response_at"])
        self.scan(message)
        self.assertIsNone(server.job_detail(self.conn, job, CFG)["possible_reply"])
        self.scan(mail("sam@contoso.com", "A new one", date="Sat, 07 Nov 2026 16:30:00 +0000"))
        self.assertIn("A new one", server.job_detail(self.conn, job, CFG)["possible_reply"]["detail"])

    def test_hostile_header_text_is_stored_flat_and_inert(self):
        job = self.applied()
        subject = "=?utf-8?b?" + __import__("base64").b64encode("<img src=x onerror=alert(1)>\r\nBcc: x‮!".encode()).decode() + "?="
        self.scan(mail("sam@contoso.com", subject))
        detail = self.replies(job)[0]
        self.assertIn("<img src=x onerror=alert(1)>", detail)  # Kept as text. The page uses h(), which never parses HTML.
        self.assertNotIn("\n", detail)
        self.assertNotIn("\r", detail)
        self.assertNotIn("‮", detail)

    def test_long_subject_is_cut(self):
        job = self.applied()
        self.scan(mail("sam@contoso.com", "x" * 1000))
        self.assertLess(len(self.replies(job)[0]), 330)


class ReplySetup(InboxBase):
    def never_connect(self, creds):
        raise AssertionError("Connected without usable credentials.")

    def run_scan(self):
        return inbox.run(self.conn, CFG, self.creds, self.never_connect)

    def test_missing_file_is_reported_without_connecting(self):
        self.creds.unlink()
        self.assertEqual(self.run_scan()["state"], "not_configured")

    def test_unfilled_example_file_counts_as_not_configured(self):
        self.creds.write_text((store.CODE_ROOT / "tools/pyrite/imap.env.example").read_text(encoding="utf-8"), encoding="utf-8")
        self.assertEqual(self.run_scan()["state"], "not_configured")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM source_status").fetchone()[0], 0)

    def test_file_others_can_read_is_refused(self):
        share_with_others(self.creds)
        result = self.run_scan()
        self.assertEqual(result["state"], "error")
        self.assertIn("icacls" if os.name == "nt" else "chmod 600", result["message"])
        self.assertNotIn("abcd", result["message"])

    def test_app_password_spaces_are_removed_for_gmail(self):
        self.assertEqual(inbox.load_credentials(self.creds).password, "abcdefghijklmnop")

    def test_password_is_kept_out_of_repr_and_errors(self):
        creds = inbox.load_credentials(self.creds)
        self.assertNotIn(creds.password, repr(creds))
        self.applied()
        result = self.scan(fake=FakeImap(login_error="bad login for abcdefghijklmnop"))
        self.assertEqual(result["state"], "error")
        self.assertNotIn("abcdefghijklmnop", result["message"])
        self.assertTrue(self.fake.logged_out)

    def test_failure_shows_on_sources_and_recovery_clears_it(self):
        self.scan(fake=FakeImap(login_error="[AUTHENTICATIONFAILED] Invalid credentials"))
        row = self.conn.execute("SELECT * FROM source_status WHERE source_key = ?", (inbox.SOURCE_KEY,)).fetchone()
        self.assertIn("AUTHENTICATIONFAILED", row["last_error"])
        self.assertIsNone(row["last_ok"])
        self.scan()
        row = self.conn.execute("SELECT * FROM source_status WHERE source_key = ?", (inbox.SOURCE_KEY,)).fetchone()
        self.assertEqual(row["last_error"], "")
        self.assertTrue(row["last_ok"])

    def test_dropped_connection_is_a_reported_failure(self):
        class Dropped(FakeImap):
            def uid(self, command, *args):
                raise OSError("connection reset")

        self.applied()
        self.assertEqual(self.scan(fake=Dropped())["state"], "error")

    def _cli(self, path):
        out = __import__("io").StringIO()
        original_path, original_db = inbox.CREDENTIALS_PATH, store.DB_PATH
        inbox.CREDENTIALS_PATH, store.DB_PATH = path, Path(self.tmp.name) / "cli.db"
        try:
            with __import__("contextlib").redirect_stdout(out):
                cli.main(["inbox"])
        finally:
            inbox.CREDENTIALS_PATH, store.DB_PATH = original_path, original_db
        return out.getvalue()

    def test_command_exits_cleanly_when_not_configured(self):
        output = self._cli(Path(self.tmp.name) / "absent.env")  # Raises SystemExit if it fails.
        self.assertIn("isn't set up", output)

    def test_command_exits_nonzero_on_a_real_failure(self):
        share_with_others(self.creds)
        with self.assertRaises(SystemExit) as caught:
            self._cli(self.creds)
        self.assertEqual(caught.exception.code, 1)

    def test_sweep_unit_cannot_fail_because_of_mail(self):
        unit = (store.CODE_ROOT / "tools/pyrite/systemd/pyrite-sweep.service").read_text(encoding="utf-8")
        self.assertIn("ExecStart=-%h/pyrite/.venv/bin/python tools/pyrite.py inbox", unit)
        self.assertLess(unit.index("pyrite.py discover"), unit.index("pyrite.py inbox"))


def exported(from_address="sam@contoso.com", subject="Your application", **kw):
    """One message as Claude's mail check writes it."""
    entry = {"id": kw.pop("id", f"m-{from_address}-{subject}"), "thread_id": "t1", "from_name": "", "from_address": from_address,
             "reply_to": "", "date": "2026-11-06T16:30:00Z", "subject": subject, "snippet": "", "labels": ["INBOX"],
             "body": "", "links": []}
    entry.update(kw)
    return entry


GMAIL_CFG = {**FAR_FUTURE_LOOKBACK, "inbox": {**FAR_FUTURE_LOOKBACK["inbox"], "source": "gmail"}}


class MailBase(Base):
    """The Gmail path: a fake Claude writes the export file, and the code judges it."""

    def setUp(self):
        super().setUp()
        self.prompts = []

    def applied(self, company="Contoso", **kw):
        fields = {"status": "applied", "applied_at": APPLIED_AT, "status_changed_at": APPLIED_AT,
                  "source_id": f"{company}-{len(self.conn.execute('SELECT id FROM jobs').fetchall())}", **kw}
        return self.add(company=company, **fields)

    def scan(self, *entries, claude_error=None, answer=None):
        def fake_ask(conn, job_id, kind, cmd, text, cwd, seconds, limit):
            self.prompts.append((cmd, text))
            if claude_error:
                raise claude_code.ClaudeFailed(claude_error)
            return answer if answer is not None else json.dumps(list(entries))
        with mock.patch.object(claude_code, "signed_in", return_value=True):
            return mailcheck.run(self.conn, GMAIL_CFG, claude="claude", ask=fake_ask)

    def replies(self, job):
        return [r["detail"] for r in self.conn.execute(
            "SELECT detail FROM events WHERE job_id = ? AND kind = 'reply_detected'", (job,))]

    def alerts(self):
        return mailcheck.open_alerts(self.conn)


class MailExport(MailBase):
    def test_a_message_keeps_only_what_the_code_needs(self):
        items = mailcheck.parse_export(json.dumps([exported(["Sam Lee ", "sam@contoso.com>"][1].rstrip(">"), from_name="Sam Lee",
                                                        reply_to="Other <other@gmx.com>", links=["https://wa.me/123/x", "not a link"],
                                                        labels=["CATEGORY_PROMOTIONS"], body="B" * 10000)]))
        item = items[0]
        self.assertEqual((item.name, item.address, item.subject), ("Sam Lee", "sam@contoso.com", "Your application"))
        self.assertEqual(item.reply_domain, "gmx.com")
        self.assertEqual(item.links, ("wa.me",))
        self.assertTrue(item.bulk)
        self.assertLessEqual(len(item.text), mailcheck.MAX_TEXT)
        self.assertEqual(item.detail(), "From Sam Lee <sam@contoso.com> | Subject: Your application | Date: 2026-11-06 16:30 UTC")

    def test_malformed_entries_are_left_out_and_a_non_list_is_refused(self):
        raw = json.dumps([exported(), exported(from_address="not an address"), exported(date="yesterday"), "junk", 7,
                          exported(from_address="x@y", date="2026-11-06T16:30:00Z"),
                          exported(from_address="Pat <pat@y.example>", date="Fri, 06 Nov 2026 16:30:00 +0000")])
        self.assertEqual([item.address for item in mailcheck.parse_export(raw)], ["sam@contoso.com", "pat@y.example"])
        with self.assertRaises(ValueError):
            mailcheck.parse_export(json.dumps({"nope": 1}))
        with self.assertRaises(ValueError):
            mailcheck.parse_export("not json")

    def test_sender_text_is_cleaned_of_hidden_characters(self):
        item = mailcheck.parse_export(json.dumps([exported(from_name="Sam​\x00 Lee", subject="Hi there")]))[0]
        self.assertEqual((item.name, item.subject), ("Sam Lee", "Hi there"))


class ScamRules(unittest.TestCase):
    """The rules alone, on the kinds of mail job seekers get."""

    companies = {"Contoso": {"contoso.com"}, "Hooli Autonomy": {"hooli-mailcheck.example"}}

    def item(self, from_address="sam@contoso.com", subject="Your application", **kw):
        return mailcheck.parse_export(json.dumps([exported(from_address, subject, **kw)]))[0]

    def reasons(self, **kw):
        return mailcheck.assess(self.item(**kw), self.companies)

    def test_the_company_at_its_own_domain_or_its_tracking_system_is_fine(self):
        self.assertEqual(self.reasons(), [])
        self.assertEqual(self.reasons(from_address="no-reply@us.greenhouse-mailcheck.io", subject="Contoso: next steps"), [])
        self.assertEqual(self.reasons(from_address="hr@hooli-mailcheck.example", subject="Hooli Autonomy interview"), [])

    def test_a_lookalike_domain_is_a_strong_sign(self):
        reasons = self.reasons(from_address="hr@contoso-careers.com", subject="Contoso offer")
        self.assertEqual(len(reasons), 1)
        self.assertIn("looks like Contoso but isn't its domain", reasons[0])

    def test_a_personal_address_claiming_the_company_is_a_strong_sign(self):
        reasons = self.reasons(from_address="contoso.recruiting@gmx.com", from_name="Contoso HR", subject="Interview")
        self.assertTrue(any("personal gmx.com address" in reason for reason in reasons))
        # The addresses here use gmx.com so the privacy check never mistakes them for real ones; Gmail is judged the same way.
        self.assertIn("gmail.com", mailcheck.FREE_MAIL)

    def test_chat_apps_money_and_id_requests_are_strong_signs(self):
        self.assertTrue(any("WhatsApp" in r for r in self.reasons(from_address="jo@talent-x.com", subject="Job interview",
                                                                  body="Please add me on WhatsApp to begin the interview.")))
        self.assertTrue(any("gift card" in r for r in self.reasons(from_address="jo@talent-x.com", subject="Job offer",
                                                                    body="You will receive a check to buy gift cards.")))
        self.assertTrue(any("Links to wa.me" in r for r in self.reasons(from_address="jo@talent-x.com", subject="Hiring now",
                                                                         links=["https://wa.me/15551234"])))
        self.assertTrue(any("Replies would go to gmx.com" in r for r in self.reasons(
            from_address="jo@talent-x.com", subject="Position available", reply_to="jo.recruiting@gmx.com")))

    def test_weak_signs_need_company(self):
        one = self.reasons(from_address="jo@gmx.com", subject="Job opportunity", body="Please reply today.")
        self.assertEqual(one, [])
        two = self.reasons(from_address="jo@gmx.com", subject="Job opportunity", body="We found your resume. Respond within 24 hours.")
        self.assertGreaterEqual(len(two), 2)

    def test_a_verified_sender_gets_the_benefit_of_the_doubt_on_wording(self):
        # A real offer mentions ID checks and deadlines. From the company's own domain, that alone isn't a warning.
        self.assertEqual(self.reasons(subject="Contoso offer", body="Congratulations, you have been selected. Bring your passport "
                                                                   "for the I-9 and respond within 48 hours."), [])
        # The same words from a stranger are.
        self.assertTrue(self.reasons(from_address="jo@talent-x.com", subject="Job offer", body="Congratulations, you have been "
                                                                                             "selected. Bring your passport."))

    def test_mail_that_is_not_about_hiring_is_ignored(self):
        self.assertEqual(self.reasons(from_address="alerts@bank.example", subject="You've received a wire",
                                      body="Wire transfer received. Confirm your bank account details."), [])
        self.assertEqual(self.reasons(from_address="deals@shop.example", subject="Gift cards 50% off"), [])

    def test_task_scams_checks_for_equipment_and_chat_interviews_are_strong_signs(self):
        task = self.reasons(from_address="jo@talent-x.com", subject="Remote job opportunity",
                            body="Complete simple tasks rating apps and earn $300 per day, paid in USDT.")
        self.assertTrue(any("task scam" in r for r in task))
        check = self.reasons(from_address="jo@talent-x.com", subject="Job offer",
                             body="We will send you a check to purchase your home office equipment.")
        self.assertTrue(any("send you a check" in r or "equipment" in r for r in check))
        chat = self.reasons(from_address="jo@talent-x.com", subject="Interview invitation",
                            body="The interview will be on Microsoft Teams chat at 10am.")
        self.assertTrue(any("Wants to talk over" in r for r in chat))
        # The same words from the company's own domain are only weak, and one weak sign isn't a warning.
        self.assertEqual(self.reasons(subject="Contoso interview", body="We'll ship you a laptop and other equipment."), [])

    def test_job_boards_and_tracking_systems_never_look_like_lookalikes(self):
        self.assertEqual(self.reasons(from_address="jobs-noreply@linkedin.com", subject="Contoso is hiring"), [])
        self.assertEqual(self.reasons(from_address="contoso@myworkday.com", subject="Thanks for applying to Contoso"), [])


class MailScan(MailBase):
    def test_a_reply_from_the_company_is_recorded_like_the_imap_path(self):
        job = self.applied()
        result = self.scan(exported(from_name="Sam Lee"))
        self.assertEqual(result["state"], "ok")
        self.assertEqual([hit["job_id"] for hit in result["found"]], [job])
        self.assertEqual(self.replies(job), ["From Sam Lee <sam@contoso.com> | Subject: Your application | Date: 2026-11-06 16:30 UTC"])
        self.assertEqual(result["alerts"], [])

    def test_a_receipt_is_skipped_unless_its_text_is_an_answer(self):
        job = self.applied()
        receipt = self.scan(exported(subject="Thank you for applying to Contoso", snippet="We have received your application."))
        self.assertEqual(receipt["found"], [])
        answer = self.scan(exported(subject="Thank you for applying to Contoso", id="m2",
                                    snippet="Unfortunately we have decided to move forward with other candidates."))
        self.assertEqual([hit["job_id"] for hit in answer["found"]], [job])

    def test_a_scam_is_kept_once_with_reasons_and_tied_to_the_job_it_names(self):
        job = self.applied()
        scam = exported("contoso.hr@gmx.com", "Contoso interview", from_name="Contoso HR",
                        body="Download Telegram to start the interview.", id="scam-1")
        result = self.scan(scam)
        self.assertEqual(len(result["alerts"]), 1)
        self.assertEqual(self.replies(job), [])  # A lookalike is never a reply.
        alerts = self.alerts()
        self.assertEqual((alerts[0]["job_id"], alerts[0]["sender"], alerts[0]["subject"]), (job, "Contoso HR <contoso.hr@gmx.com>", "Contoso interview"))
        self.assertTrue(any("Telegram" in reason for reason in alerts[0]["reasons"]))
        self.assertNotIn("Download", json.dumps(alerts))  # Only the reasons are kept, never the text.
        self.assertEqual(self.scan(scam)["alerts"], [])  # Seen already.
        self.assertEqual(len(self.alerts()), 1)

    def test_a_warning_never_changes_a_job_and_is_cleared_by_dismissing_it(self):
        job = self.applied()
        before = dict(store.get_job(self.conn, job))
        self.scan(exported("contoso.hr@gmx.com", "Contoso offer", from_name="Contoso", body="Buy gift cards first."))
        self.assertEqual(dict(store.get_job(self.conn, job)), before)
        state = server.build_state(self.conn, CFG)
        order = state["orders"][0]
        self.assertEqual((order["kind"], order["job_id"]), ("Possible scam", job))
        self.assertIn("gift card", order["detail"])
        card = next(j for j in state["jobs"] if j["id"] == job)
        self.assertTrue(card["scam_alert"])
        self.assertTrue(server.job_detail(self.conn, job, CFG)["scam_alert"])
        mailcheck.dismiss_alert(self.conn, order["alert_id"])
        state = server.build_state(self.conn, CFG)
        self.assertEqual([o["kind"] for o in state["orders"] if o["kind"] == "Possible scam"], [])
        self.assertIsNone(next(j for j in state["jobs"] if j["id"] == job)["scam_alert"])
        with self.assertRaises(ValueError):
            mailcheck.dismiss_alert(self.conn, 999)

    def test_a_scam_naming_no_tracked_job_still_shows_on_the_list(self):
        self.scan(exported("jo@gmx.com", "Work from home job", body="We found your resume. Add me on WhatsApp."))
        order = server.build_state(self.conn, CFG)["orders"][0]
        self.assertEqual((order["kind"], order["job_id"]), ("Possible scam", None))

    def test_claude_gets_two_reading_tools_nothing_that_writes_and_the_companies(self):
        self.applied("Contoso")
        self.add(company="Hooli Autonomy", source_id="h1")
        self.scan()
        cmd, text = self.prompts[0]
        self.assertIn("--permission-mode", cmd)
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "dontAsk")
        allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
        self.assertEqual(allowed, ["mcp__claude_ai_Gmail__search_threads", "mcp__claude_ai_Gmail__get_message"])
        self.assertEqual(cmd[cmd.index("--tools") + 1], "ToolSearch")
        self.assertEqual(cmd[cmd.index("--model") + 1], "claude-sonnet-5-5")
        for tool in ("Write", "Edit", "Bash", "Read", "WebFetch"):
            self.assertIn(tool, cmd[cmd.index("--disallowedTools") + 1].split(","))
        self.assertIn("Never send, reply, forward", text)
        # Hooli comes from [inbox.domains] in the config: scams borrow names you watch, not only ones you applied to.
        self.assertIn("Companies the person has applied to or watches: Contoso, Hooli, Hooli Autonomy", text)
        self.assertRegex(text, r"after:\d{4}/\d{2}/\d{2} -in:sent -from:me \{category:primary category:updates\}")
        # Job-board alerts are never replies, so the search skips them rather than paying to page through them.
        self.assertIn("-from:linkedin.com", text)
        # Mail from a known domain is judged from its subject and snippet, so the run doesn't pay to read it.
        known = text.rsplit("Senders whose text you never read", 1)[1]
        for domain in ("greenhouse.io", "myworkday.com", "linkedin.com", "hooli-mail.example"):
            self.assertIn(domain, known)

    def test_the_list_is_taken_from_the_closing_message_even_with_words_around_it(self):
        job = self.applied()
        result = self.scan(answer=f"Here it is:\n```json\n{json.dumps([exported()])}\n```\nThat's 1 message.")
        self.assertEqual([hit["job_id"] for hit in result["found"]], [job])
        # Brackets in the prose, and a shorter list inside a message, don't confuse it.
        wrapped = f"[Note] I read 2 pages [1, 2]. {json.dumps([exported(), exported(subject='Re: [Urgent] offer')])} Done [sic]."
        self.assertEqual(len(mailcheck.parse_export(wrapped)), 2)
        self.assertEqual(mailcheck.parse_export("Nothing matched, so: []"), [])
        result = self.scan(answer="I couldn't reach Gmail.")
        self.assertEqual(result["state"], "error")
        self.assertIn("usable list", result["message"])
        self.assertIn("Its answer began: I couldn't reach Gmail.", result["message"])

    def test_trouble_is_reported_beside_the_job_boards_and_never_raised(self):
        result = self.scan(claude_error="Claude stopped with an error: no Gmail")
        self.assertEqual(result["state"], "error")
        row = self.conn.execute("SELECT * FROM source_status WHERE source_key = 'inbox:gmail'").fetchone()
        self.assertEqual((row["company"], row["last_error"]), ("Email replies (Gmail)", "Claude stopped with an error: no Gmail"))
        self.assertIsNone(row["last_ok"])
        self.scan()
        row = self.conn.execute("SELECT * FROM source_status WHERE source_key = 'inbox:gmail'").fetchone()
        self.assertEqual(row["last_error"], "")
        self.assertTrue(row["last_ok"])

    def test_the_window_shrinks_to_just_past_the_last_good_run(self):
        first = mailcheck.window(self.conn, GMAIL_CFG)
        self.scan()
        again = mailcheck.window(self.conn, GMAIL_CFG)
        self.assertGreater(again, first)
        self.assertLess(datetime.now(UTC) - again, timedelta(days=mailcheck.OVERLAP_DAYS, minutes=5))

    def test_the_run_is_counted_as_claude_usage(self):
        with mock.patch.object(claude_code, "signed_in", return_value=True), \
                mock.patch.object(subprocess, "run", return_value=mock.Mock(stdout=json.dumps(
                    {"type": "result", "result": "[]", "num_turns": 2, "usage": {"input_tokens": 10, "output_tokens": 5}, "total_cost_usd": 0.01}),
                    stderr="", returncode=0)):
            result = mailcheck.run(self.conn, GMAIL_CFG, claude="claude")
        self.assertEqual(result["state"], "ok")
        self.assertEqual([kind["label"] for kind in claude_code.usage(self.conn)["kinds"]], ["Checking mail"])

    def run_with_answers(self, *answers):
        """Claude Code finishing cleanly each time, with these closing messages in turn."""
        replies = iter(answers)
        outputs = lambda *a, **kw: mock.Mock(stdout=json.dumps({"type": "result", "result": next(replies), "num_turns": 1}),
                                             stderr="", returncode=0)
        with mock.patch.object(claude_code, "signed_in", return_value=True), \
                mock.patch.object(subprocess, "run", side_effect=outputs) as run:
            result = mailcheck.run(self.conn, GMAIL_CFG, claude="claude")
        runs = [row["ok"] for row in self.conn.execute("SELECT ok FROM claude_runs WHERE kind = 'mail' ORDER BY id")]
        return result, run, runs

    def test_a_tool_call_written_out_as_text_gets_one_more_try_and_counts_as_failed(self):
        job = self.applied()
        written = '<invoke name="ToolSearch"> <parameter name="query">select:x</parameter></invoke>'
        result, run, runs = self.run_with_answers(written, json.dumps([exported()]))
        self.assertEqual(result["state"], "ok")
        self.assertEqual([hit["job_id"] for hit in result["found"]], [job])
        self.assertEqual(runs, [0, 1])
        self.assertIn("wrote a tool call out as text", run.call_args_list[1].kwargs["input"])
        # Twice in a row is reported, and neither run counts as a good one.
        result, run, runs = self.run_with_answers(written, written)
        self.assertEqual(result["state"], "error")
        self.assertIn("tried twice", result["message"])
        self.assertEqual(runs[-2:], [0, 0])

    def test_other_unusable_answers_are_not_retried(self):
        result, run, runs = self.run_with_answers("I couldn't reach Gmail.")
        self.assertEqual(result["state"], "error")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(runs, [0])

    def test_doctor_reports_a_failed_last_check(self):
        from pyrite import doctor
        self.run_with_answers("I couldn't reach Gmail.")
        with mock.patch.object(doctor, "DB_PATH", Path(self.tmp.name) / "t.db"):
            self.assertIn("couldn't reach Gmail", doctor.last_mail_error("gmail"))
            self.assertEqual(doctor.last_mail_error("imap"), "")
            checks = doctor.tool_checks(GMAIL_CFG)
        self.assertIn({"ok": False, "what": "Reply detection's last check failed"},
                      [{"ok": c["ok"], "what": c["what"]} for c in checks])

    def test_an_export_made_by_hand_can_be_judged_from_the_command_line(self):
        job = self.applied()
        path = Path(self.tmp.name) / "by-hand.json"
        path.write_text(json.dumps([exported()]), encoding="utf-8")
        result = mailcheck.ingest_file(self.conn, GMAIL_CFG, path)
        self.assertEqual([hit["job_id"] for hit in result["found"]], [job])
        self.assertEqual(mailcheck.ingest_file(self.conn, GMAIL_CFG, Path(self.tmp.name) / "missing.json")["state"], "error")

    def test_the_sweep_picks_gmail_or_imap_from_the_config(self):
        with mock.patch.object(mailcheck, "run", return_value={"state": "ok", "found": [], "alerts": [1, 2]}) as gmail, \
                mock.patch.object(inbox, "run", return_value={"state": "not_configured", "message": "x"}) as imap:
            self.assertEqual(mailcheck.summary(mailcheck.check(self.conn, GMAIL_CFG)), "Mail checked: 0 possible replies, 2 possible scams.")
            self.assertEqual(mailcheck.summary(mailcheck.check(self.conn, CFG)), "Reply detection isn't set up, so no mail was checked.")
        gmail.assert_called_once()
        imap.assert_called_once()


if __name__ == "__main__":
    unittest.main()
