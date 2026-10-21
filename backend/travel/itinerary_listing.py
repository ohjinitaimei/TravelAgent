"""Owner-scoped saved facts only. Listing never invokes a provider or planner."""
import base64
import binascii
import hashlib
import json
import sqlite3

from travel.provider import TravelFailure
from travel.schemas import Itinerary, ItineraryList, ItineraryQuery


def _scope(query: ItineraryQuery, owner: str) -> str:
    values = query.model_dump(exclude={"cursor"})
    values["query"] = query.query.strip()
    return hashlib.sha256(json.dumps([owner, values], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _encode(snapshot: int, offset: int, scope: str) -> str:
    return base64.urlsafe_b64encode(json.dumps({"v": 1, "s": snapshot, "o": offset, "q": scope}, separators=(",", ":")).encode()).decode().rstrip("=")


def _decode(cursor: str, scope: str) -> tuple[int, int]:
    try:
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        data = json.loads(raw)
        if (not isinstance(data, dict) or set(data) != {"v", "s", "o", "q"}
                or type(data["v"]) is not int or data["v"] != 1 or data["q"] != scope
                or any(type(data[k]) is not int or not 0 <= data[k] <= 2**63-1 for k in ("s", "o"))
                or data["o"] > data["s"]):
            raise ValueError("invalid cursor")
        return data["s"], data["o"]
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        raise TravelFailure("invalid_itinerary_cursor", "列表游标无效或查询条件已变化，请刷新列表", status=422) from None


def itinerary_page(db: sqlite3.Connection, query: ItineraryQuery, owner: str) -> ItineraryList:
    scope = _scope(query, owner)
    # Immutable itineraries use an insertion watermark. New inserts cannot shift this traversal.
    # A cursor narrows this owner's reads; it never grants access to a different owner.
    if query.cursor:
        snapshot, offset = _decode(query.cursor, scope)
    else:
        snapshot = db.execute("SELECT COALESCE(MAX(i.rowid),0) FROM itineraries i JOIN resource_owners o ON o.kind='itinerary' AND o.resource_id=i.id WHERE o.owner_id=?", (owner,)).fetchone()[0]
        offset = 0
    where = ["o.owner_id=?", "i.rowid<=?"]
    params = [owner, snapshot]
    parent = "NULLIF(json_extract(i.data,'$.parent_id'),'')"
    if query.kind != "all":
        where.append(parent + (" IS NULL" if query.kind == "original" else " IS NOT NULL"))
    if query.parent_id is not None:
        where.append(parent + "=?")
        params.append(query.parent_id)
    if query.query.strip():
        expressions = ["i.id", "json_extract(i.data,'$.title')", "json_extract(i.data,'$.request.city')", "json_extract(i.data,'$.request.start_date')"]
        # instr treats %, _, quotes and backslashes as literals. lower covers ASCII case.
        where.append("(" + " OR ".join(f"instr(lower({expr}),lower(?))>0" for expr in expressions) + ")")
        params.extend([query.query.strip()] * len(expressions))
    joined = " FROM itineraries i JOIN resource_owners o ON o.kind='itinerary' AND o.resource_id=i.id WHERE " + " AND ".join(where)
    created = "julianday(json_extract(i.data,'$.created_at'))"
    order = {
        "newest": f"{created} DESC, i.rowid DESC",
        "oldest": f"{created} IS NULL, {created} ASC, i.rowid ASC",
        "departure": f"json_extract(i.data,'$.request.start_date') ASC, {created} DESC, i.rowid DESC",
    }[query.order]
    total = db.execute("SELECT COUNT(*)" + joined, params).fetchone()[0]
    rows = db.execute("SELECT i.data" + joined + " ORDER BY " + order + " LIMIT ? OFFSET ?", [*params, query.limit, offset]).fetchall()
    items = [Itinerary.from_saved_json(row[0]) for row in rows]
    counts = {item.id: 0 for item in items}
    if items:
        placeholders = ",".join("?" for _ in items)
        rows = db.execute("SELECT " + parent + ",COUNT(*) FROM itineraries i JOIN resource_owners o ON o.kind='itinerary' AND o.resource_id=i.id WHERE o.owner_id=? AND i.rowid<=? AND " + parent + f" IN ({placeholders}) AND i.id!=" + parent + " GROUP BY " + parent, [owner, snapshot, *counts]).fetchall()
        counts.update(dict(rows))
    return ItineraryList(items=items, total=total, direct_adjustment_counts=counts,
        page_cursor=_encode(snapshot, offset, scope),
        next_cursor=_encode(snapshot, offset + query.limit, scope) if offset + query.limit < total else None)
