"""Preview: run the roles from worker/src/index.ts against the real Gemini API.
Shows what kind of captions each role produces from the same image.
Run: python testing/role_preview.py [image.jpg] [--rounds N]
"""

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MAX_TOKENS = 150
WORKER_INDEX = PROJECT_ROOT / "worker" / "src" / "index.ts"
DEFAULT_IMAGE = PROJECT_ROOT / "20_test" / "PICT2572.jpg"


def load_prompt_and_roles() -> tuple[str, list[str]]:
    src = WORKER_INDEX.read_text(encoding="utf-8")
    prompt = re.search(r"const PROMPT = `(.*?)`;", src, re.S)
    roles = re.search(r"const CAPTION_ROLES = \[(.*?)\];", src, re.S)
    if not prompt or not roles:
        sys.exit(f"PROMPT or CAPTION_ROLES not found in {WORKER_INDEX}")
    return prompt.group(1), re.findall(r'"([^"]*)"', roles.group(1))


def classify(image_b64: str, base_prompt: str, role: str, api_key: str) -> dict:
    url = f"{GEMINI_API_BASE}/models/{GEMINI_MODEL}:generateContent?key={api_key}"
    prompt = f"{base_prompt}\n\nRooli: {role}"

    resp = requests.post(
        url,
        json={
            "contents": [
                {
                    "parts": [
                        {"inlineData": {"mimeType": "image/jpeg", "data": image_b64}},
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": GEMINI_MAX_TOKENS,
                "temperature": 1.2,
            },
        },
    )
    resp.raise_for_status()
    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", nargs="?", default=str(DEFAULT_IMAGE))
    parser.add_argument("--rounds", type=int, default=1,
                        help="How many times to run each role (to see variation)")
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY missing from .env")
        sys.exit(1)

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"Image not found: {image_path}")
        sys.exit(1)

    base_prompt, roles = load_prompt_and_roles()

    image_b64 = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
    print(f"Image: {image_path.name}  |  rounds/role: {args.rounds}\n")

    for role in roles:
        print(f"### {role}")
        for _ in range(args.rounds):
            try:
                result = classify(image_b64, base_prompt, role, api_key)
                moose = "HIRVI" if result.get("hirvi") else "no moose"
                print(f"  [{moose} {result.get('luottamus', '?')}] {result.get('kuvaus', '')}")
            except Exception as e:
                print(f"  ERROR: {e}")
        print()


if __name__ == "__main__":
    main()
