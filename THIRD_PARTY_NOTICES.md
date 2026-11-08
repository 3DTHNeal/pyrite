# Third-party notices

Pyrite's own code is under the [MIT License](LICENSE). It doesn't bundle or vendor any third-party code, fonts or assets: the dashboard's HTML, CSS and JavaScript are its own, and the core runs on the Python standard library.

The software below is installed or run separately, under its own license. It's listed here so you know what you're agreeing to when you install it.

## Python packages you install

| Package | Used for | License |
|---|---|---|
| [python-docx](https://github.com/python-openxml/python-docx) | Building `.docx` resumes and letters (`tools/requirements.txt`) | MIT |
| [Playwright for Python](https://github.com/microsoft/playwright-python) | Experimental Workday autofill (`tools/requirements-autofill.txt`) | Apache License 2.0 |

`python -m playwright install chromium` downloads a Chromium build. Chromium and the components it includes have their own licenses, which come with the download.

## Programs Pyrite runs, if you have them

| Program | Used for | Terms |
|---|---|---|
| [Claude Code](https://claude.com/claude-code) | Triage, drafting, refreshes, interview prep and the Gmail connector | Anthropic's terms for your account |
| [LibreOffice](https://www.libreoffice.org/) | Converting `.docx` to `.pdf` | Mozilla Public License 2.0 |
| Microsoft Word | Converting `.docx` to `.pdf`, instead of LibreOffice | Microsoft's license for your copy |
| [poppler](https://poppler.freedesktop.org/) `pdftotext` or [pypdf](https://github.com/py-pdf/pypdf) | Reading PDFs in `tools/check_public.py` | GPL 2.0 or later (poppler), BSD 3-Clause (pypdf) |

## Used only in CI

| Tool | Used for | License |
|---|---|---|
| [gitleaks](https://github.com/gitleaks/gitleaks) | Scanning for credentials | MIT |
| [gitleaks-action](https://github.com/gitleaks/gitleaks-action) | Running gitleaks in GitHub Actions | Its own license: free on a personal account, while a repository owned by an organization needs a license key |

## Outside sources in the documentation

[docs/resume-playbook.md](docs/resume-playbook.md) summarizes and cites published research, vendor guides and documentation, with a link to each. Those works belong to their authors. The playbook paraphrases them and doesn't reproduce them.
