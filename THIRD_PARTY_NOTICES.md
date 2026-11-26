# Third-Party Notices & Licensing Recommendation

## Finora Repository License (Pending User Decision)

No `LICENSE` file has been finalized during Phase 1 so the project author retains full choice prior to public GitHub publication in Phase 5.

**Recommendation**: For a public portfolio desktop application built atop permissive BSD/MIT/ISC/PSF dependencies, either the **MIT License** (simple, widely recognized) or **Apache License 2.0** (adds explicit patent grant) is recommended before Phase 5 publication.

## Runtime & Bundled Assets

| Component | Version | License | Role |
| :--- | :--- | :--- | :--- |
| Python | 3.15.2 | PSF-2.0 | Embedded runtime inside packaged `.app` |
| Flask | 3.1.3 | BSD-3-Clause | Local web framework & routing |
| Jinja2 / Werkzeug / MarkupSafe / Click / Blinker / ItsDangerous | Locked in `requirements.lock` | BSD-3-Clause | Flask core dependencies |
| Waitress | 3.0.2 | ZPL-2.1 | Local loopback WSGI server |
| pywebview | 6.2.1 | BSD-3-Clause | Native `WKWebView` desktop window wrapper |
| PyObjC (`pyobjc-core`, Cocoa, WebKit, Quartz, Security, UTIs) | 13.1 | MIT | macOS Objective-C / Cocoa / WebKit bridge |
| bottle (`pywebview` dependency) | 0.13.4 | MIT | Transitive dependency of `pywebview` |
| proxy-tools (`pywebview` dependency) | 0.1.0 | BSD-3-Clause | Transitive dependency of `pywebview` |
| typing_extensions | 4.16.0 | PSF-2.0 | Transitive typing support |
| Lucide Icons (`lucide-static`, 35 selected SVGs) | 1.81.0 | ISC (select Feather-derived icons MIT) | Locally bundled monochrome UI & category SVG icons |

### Lucide Icons License Notice

```text
ISC License

Copyright (c) 2026 Lucide Icons and Contributors

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

*(Portions derived from Feather Icons: Copyright (c) 2013-present Cole Bemis, MIT License.)*

## Development, Testing & Packaging Tools (Not Redistributed at Runtime)

`pytest` (MIT), `ruff` (MIT), `playwright` (Apache-2.0), `bandit` (Apache-2.0), `pip-audit` (Apache-2.0), `pyinstaller` (GPL-2.0-with-bootloader-exception for packaged binaries), and `Pillow` (MIT-CMU, icon build tooling only).
