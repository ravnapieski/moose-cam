import base64
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from groq import Groq

PROJECT_ROOT = Path(__file__).parent.parent

load_dotenv(PROJECT_ROOT / ".env")

IMAGE_DIR = PROJECT_ROOT / "riistakamera_kuvat"
RESULTS_DIR = PROJECT_ROOT / "tulokset"
SUPPORTED_EXTENSIONS = {".jpg"}

PROMPT_DETAILED = """\
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

PROMPT_MINIMAL = """\
Onko kuvassa hirvi? Vastaa JSON:
{"hirvi": true/false, "elain_kuvassa": true/false, \
"luottamus": 0.0-1.0, "kuvaus": "max 10 sanaa"}

luottamus = kuinka varma olet omasta vastauksestasi."""

VARIANTS = {
    "groq_detailed": {
        "backend": "groq",
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "prompt": PROMPT_DETAILED,
        "delay": 4,
    },
    "groq_minimal": {
        "backend": "groq",
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "prompt": PROMPT_MINIMAL,
        "delay": 4,
    },
    "gemini_detailed": {
        "backend": "gemini",
        "model": "gemini-3.1-flash-lite",
        "prompt": PROMPT_DETAILED,
        "delay": 5,
    },
    "gemini_minimal": {
        "backend": "gemini",
        "model": "gemini-3.1-flash-lite",
        "prompt": PROMPT_MINIMAL,
        "delay": 5,
    },
}


def classify_groq(client: Groq, path: Path, model: str, prompt: str) -> dict:
    media_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    image_data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")

    response = client.chat.completions.create(
        model=model,
        max_tokens=150,
        response_format={"type": "json_object"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_data}"}},
                {"type": "text", "text": prompt},
            ],
        }],
    )

    result = json.loads(response.choices[0].message.content)
    result["tiedosto"] = path.name
    result["input_tokens"] = response.usage.prompt_tokens
    result["output_tokens"] = response.usage.completion_tokens
    return result


def classify_gemini(client: genai.Client, path: Path, model: str, prompt: str) -> dict:
    image_bytes = path.read_bytes()
    media_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"

    response = client.models.generate_content(
        model=model,
        contents=[
            genai.types.Part.from_bytes(data=image_bytes, mime_type=media_type),
            prompt,
        ],
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=150,
        ),
    )

    text = response.text.strip()
    result = json.loads(text)
    result["tiedosto"] = path.name
    result["input_tokens"] = response.usage_metadata.prompt_token_count
    result["output_tokens"] = response.usage_metadata.candidates_token_count
    return result


def load_progress(variant: str) -> dict[str, dict]:
    path = RESULTS_DIR / f"tulokset_{variant}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return {r["tiedosto"]: r for r in data if "virhe" not in r}
    return {}


def save_progress(variant: str, results: dict[str, dict]):
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"tulokset_{variant}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(results.values()), f, ensure_ascii=False, indent=2)


def run_variant(images: list[Path], variant_name: str, config: dict,
                groq_client: Groq | None, gemini_client: genai.Client | None):
    results = load_progress(variant_name)
    remaining = [img for img in images if img.name not in results]

    total = len(images)
    done = total - len(remaining)
    print(f"\n{'='*60}")
    print(f"{variant_name}: {done}/{total} tehty, {len(remaining)} jäljellä")
    print(f"  malli: {config['model']}")
    print(f"{'='*60}")

    if not remaining:
        print("Kaikki kuvat jo luokiteltu.")
        return results

    for i, img in enumerate(remaining, 1):
        print(f"  [{done + i}/{total}] {img.name}...", end=" ", flush=True)
        try:
            if config["backend"] == "groq":
                result = classify_groq(groq_client, img, config["model"], config["prompt"])
            else:
                result = classify_gemini(gemini_client, img, config["model"], config["prompt"])

            results[img.name] = result
            status = "HIRVI" if result.get("hirvi") else "—"
            print(f"{status} ({result.get('luottamus', '?')}) {result.get('kuvaus', '')}")

        except Exception as e:
            if "429" in str(e):
                print(f"\nPäiväraja täynnä — tallennetaan ja lopetetaan.")
                print(f"Jatka huomenna: python ab_test.py")
                save_progress(variant_name, results)
                return results
            print(f"VIRHE: {e}")
            results[img.name] = {"tiedosto": img.name, "virhe": str(e)}

        time.sleep(config["delay"])

        if i % 50 == 0:
            save_progress(variant_name, results)
            print(f"  --- tallennettu ({done + i}/{total}) ---")

    save_progress(variant_name, results)
    return results


def compare_all(all_results: dict[str, dict[str, dict]]):
    variant_names = list(all_results.keys())
    filenames = sorted(set().union(*(r.keys() for r in all_results.values())))

    print(f"\n{'='*60}")
    print(f"VERTAILU — {len(variant_names)} varianttia, {len(filenames)} kuvaa")
    print(f"{'='*60}")

    for name in variant_names:
        results = all_results[name]
        moose = sum(1 for r in results.values() if r.get("hirvi"))
        errors = sum(1 for r in results.values() if "virhe" in r)
        print(f"  {name:20s}: {moose} hirveä, {errors} virhettä")

    disagree = []
    for filename in filenames:
        predictions = {}
        for name in variant_names:
            r = all_results[name].get(filename, {})
            if "virhe" not in r:
                predictions[name] = r.get("hirvi", False)

        if len(set(predictions.values())) > 1:
            entry = {"tiedosto": filename}
            for name, pred in predictions.items():
                entry[name] = "HIRVI" if pred else "ei"
                entry[f"kuvaus_{name}"] = all_results[name].get(filename, {}).get("kuvaus", "")[:40]
            disagree.append(entry)

    total_comparable = sum(
        1 for f in filenames
        if all("virhe" not in all_results[n].get(f, {"virhe": True}) for n in variant_names)
    )
    agree = total_comparable - len(disagree)

    print(f"\nVertailtavissa: {total_comparable} kuvaa")
    if total_comparable:
        print(f"Kaikki samaa mieltä: {agree} ({agree/total_comparable:.0%})")
        print(f"Erimielisyyksiä: {len(disagree)} ({len(disagree)/total_comparable:.0%})")

    if disagree:
        print(f"\n--- Erimielisyydet ({len(disagree)} kpl) ---")
        for d in disagree:
            print(f"\n  {d['tiedosto']}:")
            for name in variant_names:
                if name in d:
                    print(f"    {name:20s}: {d[name]:5s} — {d.get(f'kuvaus_{name}', '')}")

    RESULTS_DIR.mkdir(exist_ok=True)
    with open(RESULTS_DIR / "erimielisyydet.json", "w", encoding="utf-8") as f:
        json.dump(disagree, f, ensure_ascii=False, indent=2)

    if disagree:
        print(f"\nErimielisyydet tallennettu: ab_tulokset/erimielisyydet.json")
        print("Tarkista nämä kuvat käsin!")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--gemini", choices=["detailed", "minimal"],
                        help="Aja yksi Gemini-variantti (esim. --gemini detailed)")
    args = parser.parse_args()

    all_images = sorted(
        p for p in IMAGE_DIR.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    images = all_images[::2]

    if not images:
        print(f"Ei kuvia kansiossa {IMAGE_DIR}")
        sys.exit(1)

    print(f"Kuvia yhteensä: {len(all_images)}, testataan joka toinen: {len(images)}")

    groq_client = Groq()
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    if args.gemini:
        variant_name = f"gemini_{args.gemini}"
        config = VARIANTS[variant_name]
        print(f"Ajetaan: {variant_name}")
        all_results = {variant_name: run_variant(
            images, variant_name, config, groq_client, gemini_client
        )}
        for groq_name in ["groq_detailed", "groq_minimal"]:
            prev = load_progress(groq_name)
            if prev:
                all_results[groq_name] = prev
    else:
        print("Ajetaan: groq_detailed, groq_minimal")
        all_results = {}
        for name in ["groq_detailed", "groq_minimal"]:
            all_results[name] = run_variant(
                images, name, VARIANTS[name], groq_client, gemini_client
            )

    if len(all_results) > 1:
        compare_all(all_results)


if __name__ == "__main__":
    main()
