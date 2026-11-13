# services/ai_assist.py — LLM assist for documents, shared by intake and the
# folder-scan pipeline. Deterministic Layer-1 results are never discarded;
# AI fills gaps. Failures degrade to Layer-1, never to fabricated output.

import llm
from services.chunking import build_doc_chunks, merge_extraction
from services.contract import validate_extraction_result
from services.prompts import store as prompt_store

def ai_contacts_to_staged(c: dict) -> dict:
    phone2 = c.get("phone_secondary")
    return {
        "name": c.get("name"),
        "email_primary": c.get("email_primary"),
        "email_secondary": c.get("email_secondary"),
        "phone_primary": c.get("phone_primary"),
        "phone_secondary": phone2,
        "whatsapp": c.get("whatsapp"),
        "company": c.get("company_name"),
        "designation": c.get("position"),
        "address": c.get("address"),
        "city": c.get("city"),
        "pincode": c.get("pincode"),
        "website": c.get("website"),
        "field_origin": {"source": "ai"},
        "confidence": {"high": 0.9, "medium": 0.6, "low": 0.3}.get(
            str(c.get("confidence") or "low").lower(), 0.3),
    }

async def assist_document(table: dict, *, name: str, chain: list, cfg: dict,
                          source_type: str = "spreadsheet",
                          say=None) -> tuple[list[dict], list[str]]:
    """Run contract-validated LLM assist over a parsed table.

    Returns (staged-ready contact dicts, warnings). Every failure yields []
    with a warning explaining why — deterministic results are never blocked.
    """
    say = say or (lambda level, msg: None)
    notes: list[str] = []
    chunks = build_doc_chunks(table, source_type=source_type,
                              layer1={"mapped": table.get("mapped"),
                                      "confidence": table.get("confidence")})
    results, failed = [], []
    for n, chunk in enumerate(chunks, start=1):
        payload, label = await llm.extract(
            chain, chunk, system=prompt_store.text("contact"),
            reliability=cfg.get("reliability"))
        if payload is None:
            failed.append(f"chunk {n}: {label}")
            notes.append(f"chunk {n}: AI unavailable ({label})")
            say("warn", f"{name}: AI chunk {n}/{len(chunks)} failed ({label})")
            continue
        data, issues = validate_extraction_result(payload, source_type)
        if data is None:
            failed.append(f"chunk {n}: contract rejected ({len(issues)} issue(s))")
            notes.append(f"chunk {n}: AI output failed contract validation")
            say("warn", f"{name}: AI chunk {n}/{len(chunks)} failed contract validation")
            continue
        results.append(data)
    if not results:
        notes.append("AI enrichment produced no usable output — deterministic extraction used")
        return [], notes
    merged = merge_extraction(results)
    for w in failed:
        merged.setdefault("warnings", []).append(
            {"field": "chunk", "message": f"{w} — deterministic values retained"})
    contacts = [ai_contacts_to_staged(c) for c in merged.get("contacts") or []]
    return contacts, notes
