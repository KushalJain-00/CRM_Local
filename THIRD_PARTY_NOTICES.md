# Third-party notices

CRM Local bundles the following open-source components in its Windows
distribution. Versions as pinned in requirements.txt at build time.

| Component | Version | License |
|---|---|---|
| FastAPI | 0.111.0 | MIT |
| Starlette | 0.37.2 | BSD-3-Clause |
| Pydantic | 2.14.3 | MIT |
| AnyIO | 4.16.0 | MIT |
| Uvicorn | 0.29.0 | BSD-3-Clause |
| httpx | 0.27.0 | BSD-3-Clause |
| python-multipart | 0.0.33 | Apache-2.0 |
| openpyxl | 3.1.2 | MIT |
| xlrd | 2.0.1 | BSD |
| pypdfium2 | 5.15.2 | BSD-3-Clause / Apache-2.0 |
| pdfminer.six | 20260107 | MIT |
| pdfplumber | 0.11.10 | MIT |
| Pillow | 13.0.0 | MIT-CMU |
| pypdf | (transitive) | BSD |
| pytest (dev) | 9.1.1 | MIT |
| reportlab (dev/test-only) | 4.4.4 | BSD |
| PyInstaller (build) | 6.11.1 | GPL-2.0 with bootloader exception |

## License summary

- **All runtime dependencies are permissively licensed** (MIT, BSD-2/3,
  Apache-2.0, MIT-CMU). No copyleft obligations arise for redistribution
  in a closed-source or commercial binary.
- **PyMuPDF (AGPL-3.0 / Artifex commercial) was removed** in favour of
  pdfplumber in release 1.0.0. No AGPL-licensed code is part of the product.
- **PyInstaller** is GPL-2.0 with a bootloader exception that explicitly
  permits distributing binaries produced by it without GPL-licensing the
  product.

## Application assets

Inter (Variable) and IBM Plex Mono font files under static/fonts are bundled
unchanged under their respective open licenses (SIL Open Font License 1.1).
UI icons are inline SVG symbols defined in the application; no icon font or
third-party icon package is included. No external requests are made.

## Application license

CRM Local's own license is **not yet provided** — see `LICENSE` status in
`DELIVERY_MANIFEST.md`. Until the project owner adds a `LICENSE` file, no
redistribution rights are granted by this package beyond what the project
owner has agreed with the client directly.
