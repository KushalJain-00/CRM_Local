# Legal notes for the release owner (v1.0.0)

This file records the engineering-side license analysis for CRM Local 1.0.0.
It is NOT legal advice; the project owner should confirm with counsel before
first client distribution.

## What is settled

1. **No copyleft obligations in the shipping binary.** All runtime
   dependencies are MIT/BSD/Apache-2.0/MIT-CMU (see THIRD_PARTY_NOTICES.md).
   PyMuPDF was removed specifically to avoid the AGPL/Artifex obligation.
2. **PyInstaller's bootloader exception applies.** Distribution of the
   frozen executable does not GPL-license the product.
3. **Bundled fonts (Inter, IBM Plex Mono) are OFL-1.1.** Redistribution in
   software is expressly permitted by the OFL; keep `static/fonts/` intact
   and keep the font license texts (see static/fonts or the upstream
   SIL OFL 1.1 text) with distributions.

## What is NOT settled — owner decisions required

1. **CRM Local's own license.** The repository contains no LICENSE file and
   no owner statement of copyright holder. The product is clearly intended
   for commercial client delivery (not open-source), so the recommended
   choice is a **proprietary all-rights-reserved license** naming the actual
   legal copyright holder (person or company) with year 2026.
   - Required input: legal name of the copyright holder (e.g., "Acme Pvt
     Ltd", or an individual name).
   - Do not publish or distribute publicly until this is decided; the
     DELIVERY_MANIFEST will flag it either way.
2. **No code-signing certificate.** Windows SmartScreen will show
   "Unknown publisher". Options: purchase an OV/EV code-signing cert
   (needs owner identity + budget), or accept the warning and document it
   honestly in client install instructions (current README does the latter).
3. **Client distribution agreement.** If a client receives this build, a
   written agreement (or license grant in the client SOW/order form) is the
   actual legal instrument; the LICENSE file and this notice support it but
   do not replace it.

## Third-party attribution requirements (all satisfied by shipping THIRD_PARTY_NOTICES.md)

- MIT components: keep the copyright notices in the notices file — done.
- BSD-3-Clause components (starlette, uvicorn, httpx): retain notice +
  license text — done via THIRD_PARTY_NOTICES.md (keep this file in every
  distribution).
- pypdfium2 (BSD/Apache-2.0): retain its license texts — done.
- Apache-2.0 (python-multipart): retain NOTICE — done.

## Distinction between licenses and credentials

- CRM Local license: governs the application code and branding.
- Third-party licenses: govern the dependencies.
- User-provided AI provider credentials: belong to the user; stored locally
  in config.json (0600 on POSIX); used only when the user configures a
  provider; the app never reads, copies or transmits them anywhere except to
  the configured endpoint.
- Local database (crm.db): the user's data; the owner/operator of the app
  deployment has no claim on it. Uninstall does not delete it.
