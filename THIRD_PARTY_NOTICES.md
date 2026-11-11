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
| openpyxl | 3.1.2 | MIT |
| xlrd | 2.0.1 | BSD |
| PyMuPDF | 1.28.2 | Dual: GNU AGPL-3.0 or Artifex Commercial |
| pytest (dev) | 9.1.1 | MIT |
| PyInstaller (build) | 6.11.1 | GPL-2.0 with bootloader exception |

## PyMuPDF license notice (important)

PyMuPDF is used for PDF parsing. It is offered by Artifex under the
**GNU Affero General Public License v3.0** or under a **commercial license**
from Artifex. Distribution of this application to clients may constitute
distribution of a combined work. The project owner must either:

1. Obtain an Artifex commercial license, or
2. Open-source the combined work under AGPL-3.0 terms, or
3. Replace PyMuPDF with a permissively licensed PDF library.

This was NOT resolved by the build; the flag is deliberate. Do not ship
paying-client installers until the project owner decides.

## PyInstaller bootloader

PyInstaller is GPL-2.0 with a bootloader exception that permits distributing
binaries produced by it without licensing the product under the GPL.

## Application assets

Inter (Variable) and IBM Plex Mono font files under static/fonts are bundled
unchanged under their respective open licenses (SIL Open Font License 1.1).
UI icons are inline SVG symbols defined in the application; no icon font or
third-party icon package is included. No external requests are made.
