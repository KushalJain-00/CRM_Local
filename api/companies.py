from pydantic import BaseModel
# api/companies.py — Company management (D-032)
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
import db
from datetime import datetime

router = APIRouter()




# ── Schemas ──────────────────────────────────────────────────────────────

class CompanyIn(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    product: Optional[str] = None


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/companies")
async def list_companies(
    q: Optional[str] = None,
):
    """List companies with optional search."""
    con = db.connect()
    try:
        where = "1=1"
        params = []

        if q:
            where += " AND name LIKE ?"
            params.append(f"%{q}%")

        count_sql = f"SELECT COUNT(*) FROM companies WHERE {where}"
        total = con.execute(count_sql, params).fetchone()[0]

        list_sql = f"""
            SELECT * FROM companies WHERE {where}
            ORDER BY name LIMIT 50 OFFSET 0
        """
        rows = con.execute(list_sql, params).fetchall()

        companies = [dict(r) for r in rows]
        return {
            "rows": companies,
            "total": total,
            "page": 1,
            "pageSize": 50,
            "totalPages": math.ceil(total / 50) if total > 0 else 0,
        }
    finally:
        con.close()


import math

@router.get("/companies/{company_id}")
async def get_company(company_id: int):
    """Get a single company by ID."""
    con = db.connect()
    try:
        row = con.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Company not found")
        return dict(row)
    finally:
        con.close()


@router.post("/companies")
async def create_company(
    body: CompanyIn,
):
    """Create a new company."""
    con = db.connect()
    try:
        now = datetime.utcnow().isoformat()
        con.execute(
            """INSERT INTO companies (
                name, address, city, pincode, website, industry, product, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                body.name, body.address, body.city, body.pincode,
                body.website, body.industry, body.product, now, now,
            )
        )
        con.commit()
        # Return the created company with the generated ID
        row = con.execute("SELECT * FROM companies WHERE name = ? ORDER BY id DESC LIMIT 1", (body.name or "",)).fetchone()
        result = dict(row) if row else {}
        con.close()
        return {"ok": True, "company": result}
    finally:
        con.close()


@router.put("/companies/{company_id}")
async def update_company(
    company_id: int,
    body: CompanyIn,
):
    """Update a company."""
    con = db.connect()
    try:
        # Check if company exists
        existing = con.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
        if existing is None:
            con.close()
            raise HTTPException(404, "Company not found")

        now = datetime.utcnow().isoformat()
        update_parts = []
        update_vals = []

        if body.name is not None:
            update_parts.append("name = ?")
            update_vals.append(body.name)
        if body.address is not None:
            update_parts.append("address = ?")
            update_vals.append(body.address)
        if body.city is not None:
            update_parts.append("city = ?")
            update_vals.append(body.city)
        if body.pincode is not None:
            update_parts.append("pincode = ?")
            update_vals.append(body.pincode)
        if body.website is not None:
            update_parts.append("website = ?")
            update_vals.append(body.website)
        if body.industry is not None:
            update_parts.append("industry = ?")
            update_vals.append(body.industry)
        if body.product is not None:
            update_parts.append("product = ?")
            update_vals.append(body.product)

        if not update_parts:
            con.close()
            return {"ok": True}

        update_vals.append(company_id)
        con.execute(
            f"UPDATE companies SET {', '.join(update_parts)} WHERE id = ?",
            update_vals
        )
        con.commit()
        con.close()
        return {"ok": True}
    finally:
        con.close()


@router.delete("/companies/{company_id}")
async def delete_company(
    company_id: int,
):
    """Delete a company (not supported - check for dependents)."""
    con = db.connect()
    try:
        existing = con.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
        if existing is None:
            con.close()
            raise HTTPException(404, "Company not found")

        # Check for dependent contacts
        deps = con.execute(
            "SELECT COUNT(*) FROM contacts WHERE company = ?",
            (existing["name"],)
        ).fetchone()[0]

        con.close()
        if deps > 0:
            return {"ok": False, "error": f"Company has {deps} dependent contacts. Re-assign contacts first."}

        con.close()
        # Actually delete
        con2 = db.connect()
        con2.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        con2.commit()
        con2.close()
        return {"ok": True}
    except HTTPException:
        con.close()
        raise
    except Exception as e:
        con.close()
        raise HTTPException(500, str(e))
