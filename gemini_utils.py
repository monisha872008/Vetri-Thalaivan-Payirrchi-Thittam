"""
gemini_utils.py - recommendation engine for PocketSmart AI.

Responsibilities
  * build prompts for the Home / Party / Jewelry planners
  * call Gemini (text, or text + image for jewelry)
  * parse and VALIDATE the JSON (budget adherence, quantities, types)
  * fall back to a deterministic plan if the AI is missing/unavailable/invalid
  * attach shopping-search links for Indian platforms

This module takes plain objects with the attributes of the pydantic models in
models.py, so it has no import dependency on FastAPI.
"""
import json
import logging
import re
import urllib.parse
from typing import Any, Callable, Dict, List, Optional

from PIL import Image

import config

logger = logging.getLogger("pocketsmart.gemini")

# --------------------------------------------------------------------------- #
# Gemini client
# --------------------------------------------------------------------------- #
_client = None


def ai_enabled() -> bool:
    return bool(config.GEMINI_API_KEY)


def get_client():
    global _client
    if _client is None and ai_enabled():
        from google import genai

        _client = genai.Client(api_key=config.GEMINI_API_KEY, http_options={"timeout": 90_000})
    return _client


def extract_json_from_response(text: str) -> Any:
    """Parse JSON from a model reply, tolerating ```json fences and stray prose."""
    if not text or not text.strip():
        raise ValueError("Empty response from model")
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.I)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        return json.loads(cleaned[start : end + 1])
    raise ValueError("Model reply did not contain valid JSON")


def generate_json(prompt: str, image: Optional[Image.Image] = None) -> Any:
    """Call Gemini and return parsed JSON. Tries the configured model, then fallbacks."""
    client = get_client()
    if client is None:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    from google.genai import types

    contents: List[Any] = [prompt, image] if image is not None else [prompt]
    models = [config.GEMINI_MODEL] + [m for m in config.GEMINI_FALLBACK_MODELS if m != config.GEMINI_MODEL]
    last_error: Optional[Exception] = None
    for model in models:
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(temperature=0.4, response_mime_type="application/json"),
            )
            return extract_json_from_response(response.text)
        except Exception as exc:  # network, quota, bad model name, bad JSON ...
            last_error = exc
            logger.warning("Gemini model %s failed: %s", model, exc)
    raise last_error or RuntimeError("Gemini request failed")


def load_image(path: str, max_side: int = 1024) -> Image.Image:
    img = Image.open(path)
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    return img


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^\d.\-]", "", value)
        try:
            return float(cleaned)
        except ValueError:
            return default
    return default


def _str_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _clean_cat(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "misc").lower()).strip("_")
    return text or "misc"


def _inr(value: float) -> str:
    return f"{value:,.0f}"


# --------------------------------------------------------------------------- #
# Shopping links
# --------------------------------------------------------------------------- #
PLATFORMS = {
    "amazon": ("Amazon", "https://www.amazon.in/s?k={q}"),
    "flipkart": ("Flipkart", "https://www.flipkart.com/search?q={q}"),
    "ikea": ("IKEA", "https://www.ikea.com/in/en/search/?q={q}"),
    "pepperfry": ("Pepperfry", "https://www.pepperfry.com/site_product/search?q={q}"),
    "meesho": ("Meesho", "https://www.meesho.com/search?q={q}"),
    "myntra": ("Myntra", "https://www.myntra.com/search?q={q}"),
    "bigbasket": ("BigBasket", "https://www.bigbasket.com/ps/?q={q}"),
    "swiggy": ("Swiggy", "https://www.swiggy.com/search?query={q}"),
    "zomato": ("Zomato", "https://www.zomato.com/search?q={q}"),
    "bookmyshow": ("BookMyShow", "https://in.bookmyshow.com/search?q={q}"),
    "google": ("Google", "https://www.google.com/search?q={q}"),
    "maps": ("Google Maps", "https://www.google.com/maps/search/?api=1&query={q}"),
    "booking": ("Booking.com", "https://www.booking.com/searchresults.html?ss={q}"),
    "makemytrip": ("MakeMyTrip", "https://www.makemytrip.com/hotels/hotel-listing/?searchText={q}"),
    "oyo": ("OYO", "https://www.oyorooms.com/search/?location={q}"),
    "nobroker": ("NoBroker", "https://www.nobroker.in/property/search?searchTerm={q}"),
    "bluestone": ("BlueStone", "https://www.bluestone.com/search.html?query={q}"),
    "tanishq": ("Tanishq", "https://www.tanishq.co.in/search?q={q}"),
    "caratlane": ("CaratLane", "https://www.caratlane.com/search?q={q}"),
    "melorra": ("Melorra", "https://www.melorra.com/search?q={q}"),
}

HOME_PLATFORMS = ["amazon", "flipkart", "ikea", "pepperfry"]
JEWELRY_PLATFORMS = ["amazon", "flipkart", "bluestone", "tanishq", "caratlane", "melorra", "meesho"]
VENUE_PLATFORMS = ["maps", "google", "booking", "makemytrip", "oyo", "nobroker"]
PARTY_PLATFORMS = {
    "venue": ["maps", "google", "booking", "oyo", "makemytrip"],
    "cater": ["swiggy", "zomato"],
    "food": ["swiggy", "zomato", "bigbasket", "amazon"],
    "drink": ["swiggy", "zomato", "bigbasket", "amazon"],
    "decor": ["amazon", "flipkart", "meesho", "myntra"],
    "entertain": ["bookmyshow", "amazon", "flipkart"],
    "gift": ["amazon", "flipkart", "myntra", "meesho"],
    "photo": ["google", "amazon", "flipkart"],
    "music": ["amazon", "flipkart", "bookmyshow"],
    "game": ["amazon", "flipkart"],
    "transport": ["makemytrip", "google"],
}
PARTY_DEFAULT_PLATFORMS = ["amazon", "flipkart", "google"]


def make_links(search_terms: str, platform_keys: List[str]) -> List[Dict[str, str]]:
    q = urllib.parse.quote_plus((search_terms or "").strip() or "budget")
    links = []
    for key in platform_keys:
        label, template = PLATFORMS[key]
        links.append({"platform": key, "label": label, "url": template.format(q=q)})
    return links


def _party_platforms(category: str) -> List[str]:
    for fragment, keys in PARTY_PLATFORMS.items():
        if fragment in category:
            return keys
    return PARTY_DEFAULT_PLATFORMS


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
_PLAN_SCHEMA = """{
  "budget_breakdown": [
    {
      "category": "lighting",
      "items": [
        {"name": "", "description": "", "estimated_price": 0.0, "quantity": 1, "search_terms": ""}
      ]
    }
  ],
  "additional_suggestions": [""]
}"""

_PARTY_EXTRA_SCHEMA = """Also include this top-level key next to "budget_breakdown":
  "venue_suggestions": [
    {"name": "", "type": "", "capacity": 0, "estimated_cost": 0.0, "search_terms": ""}
  ]"""

_JEWELRY_SCHEMA = """{
  "jewelry_recommendations": [
    {"item_type": "necklace", "description": "", "style": "", "estimated_price": 0.0, "search_terms": ""}
  ],
  "styling_tips": [""]
}"""

_OUTFIT_SCHEMA = """Because an outfit photo is attached, also include this top-level key:
  "outfit_analysis": {"colors": [""], "style": "", "formality": ""}"""

_COMMON_RULES = """General rules:
- Reply with ONE valid JSON object only. No markdown, no commentary.
- All prices are in Indian Rupees (INR) and must be realistic for India.
- "estimated_price" is the price of ONE unit. The line total is estimated_price x quantity.
- The sum of all line totals MUST stay within the total budget (leave roughly 5-10% unspent).
- "search_terms" is 2-5 words that work well in a shopping-site search box.
- Prefer brands and services that are actually available in India."""


def build_home_prompt(b) -> str:
    rooms = [n for n, flag in (("Living room", b.has_living_room), ("Kitchen", b.has_kitchen), ("Bedroom", b.has_bedroom)) if flag]
    return (
        "You are PocketSmart, an interior-design budget planner for the Indian market.\n\n"
        f"Total budget: INR {b.total_budget:,.2f}\n"
        f"Requirements:\n- {b.num_lights} lights / lighting fixtures\n- {b.num_fans} ceiling fans\n"
        f"- {b.num_furniture} furniture pieces\n- {b.num_dining_tables} dining tables\n"
        f"Rooms to furnish: {', '.join(rooms) or 'not specified'}\n"
        f"Additional requirements: {b.additional_requirements or 'None'}\n\n"
        f"{_COMMON_RULES}\n"
        "- Use these category names (only when the count is above zero): lighting, ceiling_fans, furniture, dining_tables.\n"
        "- If budget remains and rooms were selected, add a \"decor\" category.\n"
        "- Item quantities must add up to the requested counts.\n\n"
        f"Return JSON in exactly this shape:\n{_PLAN_SCHEMA}"
    )


def build_party_prompt(b) -> str:
    return (
        "You are PocketSmart, an event-budget planner for the Indian market.\n\n"
        f"Total budget: INR {b.total_budget:,.2f}\n"
        f"Party type: {b.party_type}\nGuests: {b.num_guests}\nVenue type: {b.venue_type or 'Not specified'}\n"
        f"Catering needed: {'Yes' if b.needs_catering else 'No'}\n"
        f"Decoration needed: {'Yes' if b.needs_decoration else 'No'}\n"
        f"Entertainment needed: {'Yes' if b.needs_entertainment else 'No'}\n"
        f"Additional requirements: {b.additional_requirements or 'None'}\n\n"
        f"{_COMMON_RULES}\n"
        "- Split the budget across these category names: venue, catering, decoration, entertainment, contingency "
        "(only include the ones needed, but always keep a small contingency).\n"
        "- For catering use quantity = number of guests and estimated_price = cost per guest.\n"
        "- If the venue is the person's home, the venue cost is 0.\n"
        "- Food ideas should be searchable on Swiggy/Zomato; decor and games on Amazon/Flipkart.\n\n"
        f"Return JSON in exactly this shape:\n{_PLAN_SCHEMA}\n{_PARTY_EXTRA_SCHEMA}"
    )


def build_jewelry_prompt(b, has_image: bool) -> str:
    prompt = (
        "You are PocketSmart, a jewelry stylist for the Indian market.\n\n"
        f"Total budget: INR {b.total_budget:,.2f}\nOccasion: {b.occasion}\n"
        f"Style preferences: {b.preferences or 'Not specified'}\n\n"
        f"{_COMMON_RULES}\n"
        "- Recommend 3-6 complementary pieces (for example necklace, earrings, bracelet, ring, watch).\n"
        "- Mention metal/colour choices that suit the occasion.\n"
    )
    if has_image:
        prompt += (
            "- An outfit photo is attached. Pick jewelry that complements its colours, neckline and formality.\n"
            f"\n{_OUTFIT_SCHEMA}\n"
        )
    return prompt + f"\nReturn JSON in exactly this shape:\n{_JEWELRY_SCHEMA}"


# --------------------------------------------------------------------------- #
# Normalisation / validation
# --------------------------------------------------------------------------- #
def _normalize_plan(raw: Any, total_budget: float) -> Dict[str, Any]:
    """Clean AI output, enforce the budget, compute totals + calculation table."""
    if not isinstance(raw, dict):
        raise ValueError("Model output is not a JSON object")

    categories: List[Dict[str, Any]] = []
    for cat in raw.get("budget_breakdown") or []:
        if not isinstance(cat, dict):
            continue
        items = []
        for it in cat.get("items") or []:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()
            if not name:
                continue
            items.append(
                {
                    "name": name,
                    "description": str(it.get("description") or "").strip(),
                    "estimated_price": max(_num(it.get("estimated_price")), 0.0),
                    "quantity": max(int(round(_num(it.get("quantity"), 1))), 1),
                    "search_terms": str(it.get("search_terms") or name).strip(),
                }
            )
        if items:
            categories.append({"category": _clean_cat(cat.get("category")), "items": items})

    total = sum(i["estimated_price"] * i["quantity"] for c in categories for i in c["items"])
    adjusted = False
    if total > total_budget:
        factor = (total_budget * 0.97) / total
        for c in categories:
            for i in c["items"]:
                i["estimated_price"] *= factor
        adjusted = True

    table, grand = [], 0.0
    for c in categories:
        cat_total = 0.0
        for i in c["items"]:
            i["estimated_price"] = round(i["estimated_price"], 2)
            i["subtotal"] = round(i["estimated_price"] * i["quantity"], 2)
            cat_total += i["subtotal"]
        cat_total = round(cat_total, 2)
        c["allocation"] = cat_total
        c["percentage_of_budget"] = round(cat_total / total_budget * 100, 1)
        table.append(
            {
                "category": c["category"],
                "items_count": len(c["items"]),
                "total_cost": cat_total,
                "percentage_of_budget": c["percentage_of_budget"],
            }
        )
        grand += cat_total

    grand = round(grand, 2)
    return {
        "total_budget": round(total_budget, 2),
        "total_allocated": grand,
        "remaining_budget": max(round(total_budget - grand, 2), 0.0),
        "budget_breakdown": categories,
        "calculation_table": table,
        "additional_suggestions": _str_list(raw.get("additional_suggestions")),
        "budget_adjusted": adjusted,
        "_has_items": bool(categories) and grand > 0,
    }


def _normalize_venues(raw: Any) -> List[Dict[str, Any]]:
    venues = []
    for v in (raw.get("venue_suggestions") if isinstance(raw, dict) else None) or []:
        if not isinstance(v, dict) or not str(v.get("name") or "").strip():
            continue
        name = str(v["name"]).strip()
        venues.append(
            {
                "name": name,
                "type": str(v.get("type") or "").strip(),
                "capacity": int(_num(v.get("capacity"))),
                "estimated_cost": round(max(_num(v.get("estimated_cost")), 0.0), 2),
                "search_terms": str(v.get("search_terms") or name).strip(),
            }
        )
    return venues[:6]


def _normalize_jewelry(raw: Any, total_budget: float) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Model output is not a JSON object")
    items = []
    for it in raw.get("jewelry_recommendations") or []:
        if not isinstance(it, dict):
            continue
        item_type = str(it.get("item_type") or it.get("name") or "").strip()
        if not item_type:
            continue
        items.append(
            {
                "item_type": item_type,
                "description": str(it.get("description") or "").strip(),
                "style": str(it.get("style") or "").strip(),
                "estimated_price": max(_num(it.get("estimated_price")), 0.0),
                "search_terms": str(it.get("search_terms") or item_type).strip(),
            }
        )
    total = sum(i["estimated_price"] for i in items)
    adjusted = False
    if total > total_budget:
        factor = (total_budget * 0.97) / total
        for i in items:
            i["estimated_price"] *= factor
        adjusted = True
    for i in items:
        i["estimated_price"] = round(i["estimated_price"], 2)
    grand = round(sum(i["estimated_price"] for i in items), 2)

    outfit = raw.get("outfit_analysis")
    outfit_clean = None
    if isinstance(outfit, dict):
        outfit_clean = {
            "colors": _str_list(outfit.get("colors")),
            "style": str(outfit.get("style") or "").strip(),
            "formality": str(outfit.get("formality") or "").strip(),
        }
    return {
        "total_budget": round(total_budget, 2),
        "total_allocated": grand,
        "remaining_budget": max(round(total_budget - grand, 2), 0.0),
        "jewelry_recommendations": items,
        "styling_tips": _str_list(raw.get("styling_tips")),
        "outfit_analysis": outfit_clean,
        "budget_adjusted": adjusted,
        "_has_items": bool(items) and grand > 0,
    }


# --------------------------------------------------------------------------- #
# Deterministic fallbacks (used when the AI is missing, down, or returns junk)
# --------------------------------------------------------------------------- #
_HOME_TEMPLATES = {
    "lighting": ("LED light fixture (warm white)", "Energy-efficient LED panel or batten light, e.g. Philips or Wipro.", "led light warm white"),
    "ceiling_fans": ("BLDC ceiling fan 1200mm", "Energy-saving fan from Havells, Orient or Crompton.", "bldc ceiling fan 1200mm"),
    "furniture": ("Engineered-wood furniture piece", "Sturdy, budget-friendly sofa, chair or cabinet in a neutral tone.", "engineered wood furniture"),
    "dining_tables": ("Dining table set", "Compact wooden dining table with matching chairs.", "dining table set 4 seater"),
    "decor": ("Decor bundle", "Curtains, cushions and wall art to finish the rooms.", "home decor curtains cushions"),
}
_HOME_WEIGHTS = {"lighting": 0.15, "ceiling_fans": 0.25, "furniture": 0.35, "dining_tables": 0.15, "decor": 0.10}


def _fallback_home(b) -> Dict[str, Any]:
    counts = {
        "lighting": b.num_lights,
        "ceiling_fans": b.num_fans,
        "furniture": b.num_furniture,
        "dining_tables": b.num_dining_tables,
    }
    active = {k: _HOME_WEIGHTS[k] for k, n in counts.items() if n > 0}
    if b.has_living_room or b.has_kitchen or b.has_bedroom or not active:
        active["decor"] = _HOME_WEIGHTS["decor"]
    if not any(n > 0 for n in counts.values()):
        counts["furniture"] = 1
        active["furniture"] = _HOME_WEIGHTS["furniture"]

    spend = b.total_budget * 0.92
    weight_sum = sum(active.values())
    categories = []
    for key, weight in active.items():
        qty = max(counts.get(key, 1), 1)
        name, desc, terms = _HOME_TEMPLATES[key]
        categories.append(
            {
                "category": key,
                "items": [
                    {
                        "name": name,
                        "description": desc,
                        "estimated_price": spend * weight / weight_sum / qty,
                        "quantity": qty,
                        "search_terms": terms,
                    }
                ],
            }
        )
    return {
        "budget_breakdown": categories,
        "additional_suggestions": [
            "Compare prices on Amazon, Flipkart, IKEA and Pepperfry before you buy.",
            "Festive-season sales can cut furniture and fan prices noticeably.",
            "Buy BEE 5-star rated fans and LED lights to save on electricity.",
        ],
    }


def _fallback_party(b) -> Dict[str, Any]:
    at_home = (b.venue_type or "home").strip().lower() in ("home", "house", "my home", "")
    active = {}
    if not at_home:
        active["venue"] = 0.25
    if b.needs_catering:
        active["catering"] = 0.45
    if b.needs_decoration:
        active["decoration"] = 0.20
    if b.needs_entertainment:
        active["entertainment"] = 0.15
    active["contingency"] = 0.10

    spend = b.total_budget * 0.97
    weight_sum = sum(active.values())
    alloc = {k: spend * w / weight_sum for k, w in active.items()}

    categories = []
    if at_home:
        categories.append(
            {
                "category": "venue",
                "items": [{"name": "Home venue", "description": "Hosting at home keeps venue cost at zero.", "estimated_price": 0, "quantity": 1, "search_terms": f"{b.party_type} party at home ideas"}],
            }
        )
    if "venue" in alloc:
        categories.append(
            {
                "category": "venue",
                "items": [{"name": f"{b.venue_type or 'Party hall'} booking", "description": f"Venue for about {b.num_guests} guests.", "estimated_price": alloc["venue"], "quantity": 1, "search_terms": f"{b.venue_type or 'party hall'} for {b.num_guests} guests"}],
            }
        )
    if "catering" in alloc:
        categories.append(
            {
                "category": "catering",
                "items": [{"name": "Per-guest meal", "description": "Snacks and main course ordered in bulk or cooked at home.", "estimated_price": alloc["catering"] / b.num_guests, "quantity": b.num_guests, "search_terms": f"{b.party_type} party food for {b.num_guests}"}],
            }
        )
    if "decoration" in alloc:
        categories.append(
            {
                "category": "decoration",
                "items": [{"name": f"{b.party_type} decoration kit", "description": "Balloons, banners, lights and table decor.", "estimated_price": alloc["decoration"], "quantity": 1, "search_terms": f"{b.party_type} decoration kit"}],
            }
        )
    if "entertainment" in alloc:
        categories.append(
            {
                "category": "entertainment",
                "items": [{"name": "Games and music", "description": "Party games, speaker rental or a playlist setup.", "estimated_price": alloc["entertainment"], "quantity": 1, "search_terms": f"{b.party_type} party games"}],
            }
        )
    categories.append(
        {
            "category": "contingency",
            "items": [{"name": "Buffer for surprises", "description": "Extra ice, last-minute supplies, delivery charges.", "estimated_price": alloc["contingency"], "quantity": 1, "search_terms": "party supplies"}],
        }
    )
    venue_name = "Your home" if at_home else (b.venue_type or "Party hall")
    return {
        "budget_breakdown": categories,
        "venue_suggestions": [
            {"name": venue_name, "type": b.venue_type or "Home", "capacity": b.num_guests, "estimated_cost": alloc.get("venue", 0), "search_terms": f"{b.party_type} venue for {b.num_guests} guests"}
        ],
        "additional_suggestions": [
            "Confirm the final guest count 2-3 days before ordering food.",
            "Ask vendors for bulk discounts when ordering for more than 20 people.",
        ],
    }


def _fallback_jewelry(b, has_image: bool) -> Dict[str, Any]:
    occasion = b.occasion.lower()
    festive = any(k in occasion for k in ("wedding", "festival", "diwali", "anniversary", "reception", "engagement", "party"))
    style = b.preferences or ("traditional gold-plated / kundan" if festive else "minimal everyday")
    plan = [("necklace", 0.38), ("earrings", 0.22), ("bracelet", 0.15), ("ring", 0.12)]
    spend = b.total_budget * 0.87
    items = [
        {
            "item_type": name,
            "description": f"A {style} {name} that suits a {b.occasion} look.",
            "style": style,
            "estimated_price": b.total_budget * weight,
            "search_terms": f"{style.split('/')[0].strip()} {name}",
        }
        for name, weight in plan
    ]
    # keep within the 87% we intended to spend
    total = sum(i["estimated_price"] for i in items)
    for i in items:
        i["estimated_price"] = i["estimated_price"] * spend / total
    return {
        "jewelry_recommendations": items,
        "styling_tips": [
            "Pick one statement piece and keep the rest understated.",
            "Match metal tones (gold or silver) across every piece you wear.",
            "Earrings and necklace should not compete - choose a bold pair or a bold necklace.",
        ],
    }


# --------------------------------------------------------------------------- #
# Orchestration: AI first, validated, then fallback
# --------------------------------------------------------------------------- #
def _run(ai_call: Callable[[], Any], fallback_call: Callable[[], Any], normalize: Callable[[Any], Dict[str, Any]]):
    notice, source, result, raw = None, "gemini", None, None
    if ai_enabled():
        try:
            raw = ai_call()
            result = normalize(raw)
            if not result["_has_items"]:
                raise ValueError("AI returned no usable items")
        except Exception as exc:
            logger.warning("Falling back to default plan: %s", exc)
            notice = "The AI could not produce a usable plan, so a smart default plan is shown instead."
            result, raw = None, None
    else:
        notice = "Demo mode: no GEMINI_API_KEY is set, so this plan comes from the built-in planner."
    if result is None:
        raw = fallback_call()
        result = normalize(raw)
        source = "fallback"
    result.pop("_has_items", None)
    result["source"] = source
    result["model"] = config.GEMINI_MODEL if source == "gemini" else None
    result["notice"] = notice
    return result, raw


def get_home_recommendations(b) -> Dict[str, Any]:
    result, _ = _run(
        lambda: generate_json(build_home_prompt(b)),
        lambda: _fallback_home(b),
        lambda raw: _normalize_plan(raw, b.total_budget),
    )
    for cat in result["budget_breakdown"]:
        for item in cat["items"]:
            item["shopping_links"] = make_links(item["search_terms"], HOME_PLATFORMS)
    return result


def get_party_recommendations(b) -> Dict[str, Any]:
    result, raw = _run(
        lambda: generate_json(build_party_prompt(b)),
        lambda: _fallback_party(b),
        lambda r: _normalize_plan(r, b.total_budget),
    )
    for cat in result["budget_breakdown"]:
        platforms = _party_platforms(cat["category"])
        for item in cat["items"]:
            item["shopping_links"] = make_links(item["search_terms"], platforms)
    venues = _normalize_venues(raw)
    for v in venues:
        v["search_links"] = make_links(v["search_terms"], VENUE_PLATFORMS)
    result["venue_suggestions"] = venues
    return result


def get_jewelry_recommendations(b, image_path: Optional[str] = None) -> Dict[str, Any]:
    image = None
    if image_path:
        try:
            image = load_image(image_path)
        except Exception as exc:
            logger.warning("Could not read outfit image: %s", exc)
    result, _ = _run(
        lambda: generate_json(build_jewelry_prompt(b, image is not None), image),
        lambda: _fallback_jewelry(b, image is not None),
        lambda raw: _normalize_jewelry(raw, b.total_budget),
    )
    for item in result["jewelry_recommendations"]:
        item["shopping_links"] = make_links(item["search_terms"], JEWELRY_PLATFORMS)
    result["image_used"] = image is not None
    if image is not None and result["source"] == "fallback":
        extra = "The outfit photo was saved but could not be analysed without the AI."
        result["notice"] = f"{result['notice']} {extra}" if result["notice"] else extra
    return result
