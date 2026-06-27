import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import urllib.request
import json

load_dotenv(Path(__file__).parent.parent / ".env")

TOKEN = os.getenv("TELEGRAM_BOT_API_KEY")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API = f"https://api.telegram.org/bot{TOKEN}"


def send_message(text: str):
    data = json.dumps({"chat_id": CHAT_ID, "text": text}).encode()
    req = urllib.request.Request(
        f"{API}/sendMessage", data=data,
        headers={"Content-Type": "application/json"},
    )
    resp = json.loads(urllib.request.urlopen(req).read())
    if not resp["ok"]:
        print(f"Virhe: {resp}")
    return resp


def send_photo(path: str, caption: str = ""):
    import urllib.parse
    boundary = "----MooseCamBoundary"
    photo = Path(path).read_bytes()
    filename = Path(path).name

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{CHAT_ID}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode() + photo + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{API}/sendPhoto", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    resp = json.loads(urllib.request.urlopen(req).read())
    if not resp["ok"]:
        print(f"Virhe: {resp}")
    return resp


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Käyttö:")
        print("  python telegram_send.py 'viesti tähän'")
        print("  python telegram_send.py --photo kuva.jpg 'kuvateksti'")
        sys.exit(1)

    if sys.argv[1] == "--photo":
        caption = sys.argv[3] if len(sys.argv) > 3 else ""
        send_photo(sys.argv[2], caption)
        print(f"Kuva lähetetty: {sys.argv[2]}")
    else:
        send_message(" ".join(sys.argv[1:]))
        print("Viesti lähetetty.")
