"""20 kuvan hirvitunnistustesti Groq/Llama 4 Scout -mallilla.
Vertaa tuloksia 20_test_pic_names.txt-labeleihin ja laskee accuracy/precision/recall.
Ajo: python testing/classify.py
"""

import base64
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

PROJECT_ROOT = Path(__file__).parent.parent

load_dotenv(PROJECT_ROOT / ".env")

IMAGE_DIR = PROJECT_ROOT / "20_test"
LABELS_FILE = Path(__file__).parent / "20_test_pic_names.txt"
MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}

OUTPUT_FILE = "20_test_groq_minimal.json"

PROMPT = """\
Riistakamerakuva Utsjoelta, Pohjois-Lapista. Onko kuvassa hirvi (Alces alces, moose)?

Hirvi on suuri, tumma hirvieläin jolla on pitkät jalat, kyttyräselkä ja leveä kuono. \
Jos kuvassa on iso hirvieläin, se on todennäköisesti hirvi. \
Jos kuvassa on eläin mutta et ole varma lajista, merkitse elain_kuvassa: true.

Kirjoita kuvaus kokeneen suomalaisen hirvenmetsästäjän äänellä — suorapuheisesti, \
rikkaalla kielellä. Hirven kohdalla saa myös kiroilla.

Vastaa JSON:
{"hirvi": true/false, "elain_kuvassa": true/false, \
"luottamus": 0.0-1.0, "kuvaus": "metsästäjän kommentti, max 15 sanaa"}

luottamus = kuinka varma olet omasta vastauksestasi."""

PROMPT_MINIMAL = """\
Onko kuvassa hirvi? Vastaa JSON:
{"hirvi": true/false, "elain_kuvassa": true/false, \
"luottamus": 0.0-1.0, "kuvaus": "max 10 sanaa"}

luottamus = kuinka varma olet omasta vastauksestasi."""


def encode_image(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    media_type = "image/png" if suffix == ".png" else "image/jpeg"
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return media_type, data


def classify_image(client: Groq, path: Path) -> dict:
    media_type, image_data = encode_image(path)

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=150,
        response_format={"type": "json_object"},
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
                    {"type": "text", "text": PROMPT_MINIMAL},
                ],
            }
        ],
    )

    result = json.loads(response.choices[0].message.content)
    result["tiedosto"] = path.name
    result["input_tokens"] = response.usage.prompt_tokens
    result["output_tokens"] = response.usage.completion_tokens
    return result


def load_labels() -> dict[str, bool]:
    if not LABELS_FILE.exists():
        return {}
    labels = {}
    for line in LABELS_FILE.read_text().splitlines():
        if "," not in line:
            continue
        name, label = line.split(",", 1)
        labels[name.strip() + ".jpg"] = label.strip().upper() == "HIRVI"
    return labels


def evaluate(results: list[dict], labels: dict[str, bool]):
    tp = fp = tn = fn = 0
    errors = []

    for r in results:
        if "virhe" in r:
            continue
        filename = r["tiedosto"]
        if filename not in labels:
            continue
        predicted = r.get("hirvi", False)
        actual = labels[filename]

        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
            errors.append(f"  FP: {filename} — malli sanoi HIRVI, oikeasti EI")
        elif not predicted and actual:
            fn += 1
            errors.append(f"  FN: {filename} — malli sanoi EI, oikeasti HIRVI")
        else:
            tn += 1

    total = tp + fp + tn + fn
    accuracy = (tp + tn) / total if total else 0
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0

    print(f"\n--- Evaluointi ({total} kuvaa) ---")
    print(f"Tarkkuus (accuracy):  {accuracy:.0%} ({tp + tn}/{total})")
    print(f"Precision:            {precision:.0%} (TP={tp}, FP={fp})")
    print(f"Recall:               {recall:.0%} (TP={tp}, FN={fn})")
    if errors:
        print("Virheet:")
        for e in errors:
            print(e)


def main():
    labels = load_labels()
    if labels:
        label_order = list(labels.keys())
        images = [
            IMAGE_DIR / name for name in label_order if (IMAGE_DIR / name).exists()
        ]
    else:
        images = sorted(
            p for p in IMAGE_DIR.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS
        )

    if not images:
        print(f"Ei kuvia kansiossa {IMAGE_DIR}")
        sys.exit(1)

    print(f"Löytyi {len(images)} kuvaa kansiosta {IMAGE_DIR.name}\n")

    client = Groq()
    results = []
    total_input = 0
    total_output = 0

    for i, img in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {img.name}...", end=" ", flush=True)
        try:
            result = classify_image(client, img)
            results.append(result)
            total_input += result["input_tokens"]
            total_output += result["output_tokens"]

            luottamus = result.get("luottamus", 0)
            if result["hirvi"]:
                status = "HIRVI"
            elif result.get("elain_kuvassa"):
                status = "eläin (muu)"
            else:
                status = "ei eläintä"
            print(f"{status} (luottamus: {luottamus:.0%}) — {result['kuvaus']}")
        except Exception as e:
            print(f"VIRHE: {e}")
            results.append({"tiedosto": img.name, "virhe": str(e)})

    print("\n" + "=" * 60)
    moose_count = sum(1 for r in results if r.get("hirvi"))
    print(f"Tulokset: {moose_count}/{len(results)} kuvassa hirvi")
    print(f"Tokenit: {total_input:,} input + {total_output:,} output")

    if labels:
        evaluate(results, labels)

    output_dir = PROJECT_ROOT / "tulokset"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / OUTPUT_FILE
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nTulokset tallennettu: {output_file}")


if __name__ == "__main__":
    main()
