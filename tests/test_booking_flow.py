"""Booking through the conversation and over REST: propose, read back, confirm on a later turn, cancel."""

from __future__ import annotations


def tools_used(env):
    return [s.get("name") for s in env["trace"]["stages"] if s["stage"] == "tool"]


def test_two_step_confirm_through_chat(client):
    e = client.post(
        "/chat", json={"message": "show me the range rover velar", "name": "Booker"}
    ).json()
    uid, sid = e["user_id"], e["session_id"]
    e = client.post(
        "/chat",
        json={
            "message": "book a viewing for it tomorrow at 9am",
            "user_id": uid,
            "session_id": sid,
        },
    ).json()
    assert tools_used(e) == ["propose_viewing"] and e["intent"] == "booking"
    assert "Sunday" in e["reply"] and "Monday" in e["reply"] and e["pending_booking"] is None
    e = client.post(
        "/chat",
        json={"message": "book it for monday at 9am then", "user_id": uid, "session_id": sid},
    ).json()
    assert e["pending_booking"] and e["pending_booking"]["listing_id"] == "C-003"
    assert "Shall I book it" in e["reply"] and "Confirm the viewing" in e["suggested_actions"]
    assert client.get("/bookings", params={"user_id": uid}).json() == []
    e = client.post(
        "/chat", json={"message": "yes please", "user_id": uid, "session_id": sid}
    ).json()
    assert (
        tools_used(e) == ["confirm_viewing"]
        and "BK-" in e["reply"]
        and e["pending_booking"] is None
    )
    assert any(w["table"] == "bookings" for w in e["memory"]["writes"])
    mine = client.get("/bookings", params={"user_id": uid}).json()
    assert (
        len(mine) == 1
        and mine[0]["listing_id"] == "C-003"
        and mine[0]["slot_start"].startswith("2026-09-07T09:00")
    )
    prof = client.get(f"/users/{uid}/profile").json()
    assert prof["upcoming_bookings"] and prof["lead"]["status"] == "qualified"
    e = client.post(
        "/chat",
        json={"message": f"cancel booking {mine[0]['ref']}", "user_id": uid, "session_id": sid},
    ).json()
    assert "Cancelled" in e["reply"]


def test_confirm_without_proposal_does_nothing(client):
    e = client.post("/chat", json={"message": "show me a bmw", "name": "Confirmer"}).json()
    r = client.post(
        "/chat",
        json={"message": "yes confirm", "user_id": e["user_id"], "session_id": e["session_id"]},
    ).json()
    assert "confirm_viewing" not in tools_used(r)
    assert client.get("/bookings", params={"user_id": e["user_id"]}).json() == []


def test_booking_rest_endpoints(client):
    u = client.post("/users/identify", json={"name": "Rest Booker"}).json()
    grid = client.get("/inventory/C-003/availability", params={"week": "2026-09-07"}).json()
    assert grid["week_start"] == "2026-09-07" and len(grid["days"]) == 7
    r = client.post(
        "/bookings",
        json={"user_id": u["user_id"], "listing_id": "C-003", "slot_start": "2026-09-13T10:00"},
    )
    assert r.status_code == 409 and "Sunday" in r.json()["detail"]["reason"]
    r = client.post(
        "/bookings",
        json={"user_id": u["user_id"], "listing_id": "C-003", "slot_start": "2026-09-08T15:00"},
    )
    assert r.status_code == 200 and r.json()["ref"].startswith("BK-")
    ref = r.json()["ref"]
    assert client.delete(f"/bookings/{ref}", params={"user_id": u["user_id"]}).json()["ok"]
    assert client.delete(f"/bookings/{ref}", params={"user_id": u["user_id"]}).status_code == 404
    assert client.get("/inventory/Z-999/availability").status_code == 404
