import json

# Load cookies exported from Cookie-Editor
with open("musaffa_cookies.json", "r") as f:
    raw_cookies = json.load(f)

playwright_cookies = []
for c in raw_cookies:
    cookie_entry = {
        "name": c.get("name"),
        "value": c.get("value"),
        "domain": c.get("domain"),
        "path": c.get("path", "/"),
        "secure": c.get("secure", False),
        "httpOnly": c.get("httpOnly", False),
    }
    # Handle SameSite matching
    same_site = c.get("sameSite", "").capitalize()
    if same_site in ["Strict", "Lax", "None"]:
        cookie_entry["sameSite"] = same_site
    else:
        cookie_entry["sameSite"] = "Lax"

    if "expirationDate" in c:
        cookie_entry["expires"] = c["expirationDate"]

    playwright_cookies.append(cookie_entry)

# Save into storage_state format
storage_state = {"cookies": playwright_cookies, "origins": []}

with open("musaffa_state.json", "w") as f:
    json.dump(storage_state, f, indent=2)

print("✅ musaffa_state.json successfully generated! You won't need to sign in again.")