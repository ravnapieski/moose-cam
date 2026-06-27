# DEPRECATED: Käyttää Groq + vanhaa promptia.
# Tuotantopipeline: worker/src/index.ts

import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from groq import Groq

PROJECT_ROOT = Path(__file__).parent.parent

load_dotenv(PROJECT_ROOT / ".env")

BURREL_API = "https://app.burrelcameras.com/api/v1/public"
MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
DOWNLOAD_DIR = PROJECT_ROOT / "burrel_kuvat"
RESULTS_FILE = PROJECT_ROOT / "burrel_tulokset.json"
STATE_FILE = PROJECT_ROOT / ".last_fetch"

PROMPT = """\
Riistakamerakuva Utsjoelta, Pohjois-Lapista. Onko kuvassa hirvi (Alces alces, moose)?

Hirvi on suuri, tumma hirvieläin jolla on pitkät jalat, kyttyräselkä ja leveä kuono. \
Jos kuvassa on iso hirvieläin, se on todennäköisesti hirvi. \
Jos kuvassa on eläin mutta et ole varma lajista, merkitse elain_kuvassa: true.

Kirjoita kuvaus kuin kokenut hirvenmetsästäjä. Suorapuheisesti, \
kiroillen ja rikkaalla kielellä.

Vastaa JSON:
{"hirvi": true/false, "elain_kuvassa": true/false, \
"luottamus": 0.0-1.0, "kuvaus": "metsästäjän kommentti, max 15 sanaa"}

luottamus = kuinka varma olet omasta vastauksestasi."""


def get_token() -> str:
    resp = requests.post(f"{BURREL_API}/auth", json={
        "accessKey": os.getenv("BURREL_CAMERA_ACCESS_KEY"),
    })
    resp.raise_for_status()
    return resp.json()["token"]


def fetch_media(token: str, after: str | None = None) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    params = {"limit": 200}
    if after:
        params["after"] = after

    resp = requests.get(f"{BURREL_API}/media", headers=headers, params=params)
    resp.raise_for_status()
    return resp.json().get("media", [])


def download_image(url: str, token: str, filename: str) -> Path:
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    dest = DOWNLOAD_DIR / filename
    if dest.exists():
        return dest

    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def classify_image(client: Groq, path: Path) -> dict:
    media_type = "image/jpeg"
    image_data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=256,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_data}",
                        },
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    return json.loads(text)


def load_last_fetch() -> str | None:
    if STATE_FILE.exists():
        return STATE_FILE.read_text().strip()
    return None


def save_last_fetch(timestamp: str):
    STATE_FILE.write_text(timestamp)


def load_existing_results() -> list[dict]:
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    return []


def main():
    print("Yhdistetään Burrel API:in...")
    try:
        token = get_token()
    except requests.HTTPError as e:
        print(f"Autentikointi epäonnistui: {e}")
        print("Tarkista BURREL_CAMERA_ACCESS_KEY .env-tiedostossa.")
        sys.exit(1)

    print("Kirjautuminen onnistui!\n")

    after = load_last_fetch()
    if after:
        print(f"Haetaan kuvat ajankohdan {after} jälkeen...")
    else:
        print("Haetaan kaikki saatavilla olevat kuvat...")

    media = fetch_media(token, after)
    photos = [m for m in media if m.get("type") == "photo"]

    if not photos:
        print("Ei uusia kuvia.")
        sys.exit(0)

    print(f"Löytyi {len(photos)} uutta kuvaa.\n")

    groq_client = Groq()
    results = load_existing_results()
    latest_timestamp = after

    for i, item in enumerate(photos, 1):
        created = item["created"]
        filename = f"{created.replace(':', '-').replace('T', '_').split('+')[0]}.jpg"

        print(f"[{i}/{len(photos)}] {created}...", end=" ", flush=True)

        try:
            path = download_image(item["url"], token, filename)
            classification = classify_image(groq_client, path)

            result = {
                "tiedosto": filename,
                "aika": created,
                "lampotila": item.get("temperature"),
                "sijainti": item.get("location"),
                **classification,
            }
            results.append(result)

            status = "HIRVI" if result.get("hirvi") else "ei hirveä"
            confidence = result.get("luottamus", 0)
            print(f"{status} ({confidence:.0%}) — {result.get('kuvaus', '')}")

        except Exception as e:
            print(f"VIRHE: {e}")
            results.append({"tiedosto": filename, "aika": created, "virhe": str(e)})

        if not latest_timestamp or created > latest_timestamp:
            latest_timestamp = created

    if latest_timestamp:
        save_last_fetch(latest_timestamp)

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    moose_count = sum(1 for r in results if r.get("hirvi"))
    print(f"Hirviä yhteensä: {moose_count}/{len(results)} kuvassa")
    print(f"Kuvat tallennettu: {DOWNLOAD_DIR}")
    print(f"Tulokset tallennettu: {RESULTS_FILE.name}")


if __name__ == "__main__":
    main()
