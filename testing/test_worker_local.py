"""Fetch a recent image from Burrel API and send it as a fake webhook to the Worker."""

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

BURREL_API = "https://app.burrelcameras.com/api/v1/public"
WORKER_LOCAL = "http://localhost:8787"
WORKER_PROD = "https://moose-cam.moose-cam.workers.dev"


def get_burrel_media() -> dict:
    resp = requests.post(f"{BURREL_API}/auth", json={
        "accessKey": os.getenv("BURREL_CAMERA_ACCESS_KEY"),
    })
    resp.raise_for_status()
    token = resp.json()["token"]

    resp = requests.get(f"{BURREL_API}/media", headers={
        "Authorization": f"Bearer {token}",
    }, params={"limit": 1})
    resp.raise_for_status()

    media = resp.json().get("media", [])
    if not media:
        print("Ei kuvia Burrel API:ssa.")
        sys.exit(1)

    return media[0]


def send_to_worker(media: dict, secret: str, worker_url: str):
    payload = {"media": [media]}
    resp = requests.post(
        f"{worker_url}?secret={secret}",
        json=payload,
    )
    print(f"Worker response: {resp.status_code} {resp.text}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", action="store_true",
                        help="Lähetä tuotanto-Workerille lokaalin sijaan")
    args = parser.parse_args()

    worker_url = WORKER_PROD if args.prod else WORKER_LOCAL

    secret = os.getenv("WEBHOOK_SECRET")
    if not secret:
        secret = input("WEBHOOK_SECRET: ").strip()

    print("Haetaan tuorein kuva Burrel API:sta...")
    media = get_burrel_media()
    print(f"  type: {media.get('type')}")
    print(f"  created: {media.get('created')}")
    print(f"  temperature: {media.get('temperature')}")
    print(f"  url: {media.get('url')[:80]}...")

    print(f"\nLähetetään webhook → {worker_url}")
    send_to_worker(media, secret, worker_url)
    print("\nTarkista Telegram-ryhmä viestistä.")


if __name__ == "__main__":
    main()
