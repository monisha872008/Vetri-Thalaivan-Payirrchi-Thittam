"""
End-to-end tests. They run fully offline: the AI key is blanked so the
built-in planner answers, and all data goes to a temporary folder.

Run from the project root:   pytest -v
"""
import io
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

# --- must happen before the app is imported ---------------------------------
os.environ["GEMINI_API_KEY"] = ""
os.environ["GOOGLE_API_KEY"] = ""
os.environ["POCKETSMART_DATA_DIR"] = tempfile.mkdtemp(prefix="pocketsmart_test_")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import gemini_utils
from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def logged_in(client):
    r = client.post("/register", json={"username": "tester", "email": "t@example.com", "password": "secret12"})
    assert r.status_code == 201, r.text
    r = client.post("/token", data={"username": "tester", "password": "secret12"})
    assert r.status_code == 200, r.text
    return client


# ---------------------------------------------------------------- pure logic
def test_extract_json_handles_fences_and_prose():
    assert gemini_utils.extract_json_from_response('```json\n{"a": 1}\n```') == {"a": 1}
    assert gemini_utils.extract_json_from_response('Sure! {"a": 2} hope that helps') == {"a": 2}


def test_over_budget_ai_output_is_scaled_down():
    raw = {"budget_breakdown": [{"category": "Living Room", "items": [
        {"name": "Sofa", "estimated_price": "₹90,000", "quantity": 2, "search_terms": "sofa"}]}]}
    out = gemini_utils._normalize_plan(raw, 100_000)
    assert out["budget_adjusted"] is True
    assert out["total_allocated"] <= 100_000
    assert out["budget_breakdown"][0]["category"] == "living_room"


def test_fallback_home_stays_within_budget():
    b = SimpleNamespace(total_budget=50_000, num_lights=5, num_fans=3, num_furniture=4, num_dining_tables=1,
                        has_living_room=True, has_kitchen=False, has_bedroom=False, additional_requirements=None)
    r = gemini_utils.get_home_recommendations(b)
    assert r["source"] == "fallback"
    assert 0 < r["total_allocated"] <= 50_000
    assert r["remaining_budget"] >= 0


# ------------------------------------------------------------------- pages
def test_public_pages(client):
    for path in ("/", "/login", "/register", "/health"):
        assert client.get(path).status_code == 200


def test_protected_page_redirects_browsers(client):
    with TestClient(app) as anon:
        r = anon.get("/dashboard", headers={"accept": "text/html"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
        assert anon.get("/history-data").status_code == 401


def test_wrong_password_rejected(client):
    assert client.post("/token", data={"username": "tester", "password": "nope"}).status_code == 401


def test_duplicate_registration_rejected(logged_in):
    r = logged_in.post("/register", json={"username": "tester", "email": "x@example.com", "password": "secret12"})
    assert r.status_code == 409


def test_authenticated_pages(logged_in):
    for path in ("/dashboard", "/home-planner", "/party-planner", "/jewelry-planner", "/history"):
        assert logged_in.get(path).status_code == 200, path


# --------------------------------------------------------------- planners
def test_generate_home(logged_in):
    r = logged_in.post("/generate-home", json={
        "total_budget": 50000, "num_lights": 5, "num_fans": 3, "num_furniture": 4, "num_dining_tables": 1,
        "has_living_room": True, "has_kitchen": True, "has_bedroom": False})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_allocated"] <= 50000
    assert data["budget_breakdown"][0]["items"][0]["shopping_links"]


def test_generate_party(logged_in):
    r = logged_in.post("/generate-party", json={
        "total_budget": 25000, "num_guests": 20, "party_type": "Birthday", "venue_type": "Banquet hall",
        "needs_catering": True, "needs_decoration": True, "needs_entertainment": True})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_allocated"] <= 25000
    assert data["venue_suggestions"]


def test_generate_jewelry_with_and_without_image(logged_in):
    r = logged_in.post("/generate-jewelry", data={"total_budget": "15000", "occasion": "Wedding"})
    assert r.status_code == 200, r.text
    assert r.json()["jewelry_recommendations"]

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 60)).save(buf, "PNG")
    r = logged_in.post("/generate-jewelry", data={"total_budget": "15000", "occasion": "Wedding"},
                       files={"image": ("outfit.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["image_used"] is True


def test_fake_image_rejected(logged_in):
    r = logged_in.post("/generate-jewelry", data={"total_budget": "15000", "occasion": "Wedding"},
                       files={"image": ("evil.png", b"not an image", "image/png")})
    assert r.status_code == 400


def test_validation_errors(logged_in):
    assert logged_in.post("/generate-home", json={"total_budget": -5}).status_code == 422
    assert logged_in.post("/generate-party", json={"total_budget": 1000, "num_guests": 0}).status_code == 422
    assert logged_in.post("/generate-jewelry", data={"total_budget": "0", "occasion": "Wedding"}).status_code == 422


# ----------------------------------------------------------------- history
def test_history_and_details(logged_in):
    h = logged_in.get("/history-data").json()["history"]
    assert len(h) >= 4
    assert "full_result" not in h[0]
    d = logged_in.get(f"/recommendation-details/{h[0]['id']}")
    assert d.status_code == 200 and "full_result" in d.json()
    assert logged_in.get("/recommendation-details/does-not-exist").status_code == 404


def test_session_endpoints(logged_in):
    assert logged_in.get("/session-info").json()["username"] == "tester"
    r = logged_in.post("/session-data", json={"favourite": "home"})
    assert r.json()["data"]["favourite"] == "home"


def test_logout_invalidates_token(logged_in):
    token = logged_in.cookies.get("access_token")
    r = logged_in.post("/logout", follow_redirects=False)
    assert r.status_code == 303
    r = logged_in.get("/history-data", headers={"authorization": f"Bearer {token}"})
    assert r.status_code == 401
