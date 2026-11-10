"""The assay package stays general and self-contained, so another tool can use it and it can move to a repository of
its own. Nothing in it may know about Pyrite, and nothing in it may do more than read the text it's given."""
import ast
import re
import unittest
from pathlib import Path

from support import CODE_ROOT

from assay import claims, factbank, names, numbers, seal, terms
from assay import text as reading

PACKAGE = CODE_ROOT / "tools" / "assay"
# The standard library the assay may use: text, numbers, hashes and types. No subprocess, socket, os, sqlite3 or
# urllib, so it can't start a program, reach the network, or read a database. pathlib is only for hashing a file a
# caller names.
ALLOWED = {"re", "unicodedata", "decimal", "hashlib", "json", "pathlib", "typing", "collections", "collections.abc",
           "dataclasses", "__future__"}
# Words that would mean the general checker has learned about one use of it.
DOMAIN_WORDS = ("pyrite", "search.toml", "[guard]", "cover letter", "cover-letter", "PYRITE_HOME")


def imports(path: Path) -> list[tuple[str, int]]:
    """Each module a file imports, as (name, level): level is 0 for an absolute import, 1 or more for a relative one."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [(alias.name, 0) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module or "", node.level))
    return found


class StaysSelfContained(unittest.TestCase):
    def files(self) -> list[Path]:
        found = sorted(PACKAGE.glob("*.py"))
        self.assertGreater(len(found), 5)
        return found

    def test_imports_only_itself_and_a_short_list_of_the_standard_library(self):
        for path in self.files():
            for module, level in imports(path):
                with self.subTest(file=path.name, module=module):
                    if level:
                        self.assertEqual(level, 1, "a relative import may only reach a module beside it")
                    else:
                        self.assertIn(module, ALLOWED | {"assay"} | {f"assay.{p.stem}" for p in self.files()})

    def test_knows_nothing_about_pyrite(self):
        for path in self.files():
            source = path.read_text(encoding="utf-8")
            for word in DOMAIN_WORDS:
                with self.subTest(file=path.name, word=word):
                    self.assertNotIn(word.lower(), source.lower())


class WorksOnItsOwn(unittest.TestCase):
    """The core judges plain text against plain evidence, with no config or workspace: what a second tool would do."""

    FACTS = "# Fact bank\n- Cut build time from 42 s to 9 s with Bazel\n## Do not use\n- Bluebird\n## Unsupported\n- Kubernetes\n"

    def test_numbers_need_a_source(self):
        known = factbank.claimable(self.FACTS)
        self.assertEqual(numbers.number_errors("Draft", "Cut build time from 42 s to 9 s", known, "not in the sources"), [])
        errors = " ".join(numbers.number_errors("Draft", "Cut build time by 79%, a 4.7x gain", known, "not in the sources"))
        self.assertIn("79%", errors)  # Worked out from 42 and 9, which approves nothing.
        self.assertIn("4.7x", errors)

    def test_a_listed_name_is_blocked_however_its_split(self):
        listed = names.unguarded_terms(self.FACTS, [])
        self.assertEqual(listed, ["Bluebird"])
        pattern = names.flexible(listed[0])
        for written in ("Blue-bird", "blue_bird", "BLUEBIRDS", reading.matchable("**Blue**bird")):
            with self.subTest(written=written):
                self.assertTrue(re.search(pattern, written, re.I))

    def test_an_unsupported_claim_may_be_named_only_to_deny_it(self):
        patterns, disclaimers = [r"\bkubernetes\b"], [r"\bnot\b", r"\bno\b"]
        errors, denied = claims.unsupported("I have not run Kubernetes.", patterns, disclaimers, "Draft")
        self.assertEqual((errors, denied), ([], ["Kubernetes"]))
        errors, _denied = claims.unsupported("Ran Kubernetes with no downtime.", patterns, disclaimers, "Draft")
        self.assertEqual(len(errors), 1)

    def test_a_term_no_source_uses_is_novel(self):
        known = terms.vocabulary(factbank.claimable(self.FACTS))
        self.assertEqual(terms.novel_terms("Cut build time with Bazel and Terraform.", known), ["Terraform"])

    def test_a_seal_names_what_changed(self):
        before = {"facts.md": seal.digest(b"one"), "rules": seal.value_digest({"b": 1, "a": 2})}
        after = {"facts.md": seal.digest(b"two"), "rules": seal.value_digest({"a": 2, "b": 1})}
        self.assertEqual(seal.changed(before, after), ["facts.md"])


if __name__ == "__main__":
    unittest.main()
