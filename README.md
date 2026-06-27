# Moose Cam — Riistakameran hirvitunnistus

Riistakamerakuvien automaattinen hirvitunnistus ja -hälytys vision-kielimalleilla (zero-shot, ei fine-tuningia).

## Arkkitehtuuri

```
Burrel-kamera (Utsjoki)
  → kuva liiketunnistimella
    → Burrel backend
      → Webhook POST → Cloudflare Worker (TypeScript)
        → ctx.waitUntil(): kuittaa Burrelille heti (<5s)
          → Gemini API analysoi kuvan taustalla
            → Jos hirvi → Telegram-viesti kuvalla + kuvauksella
```

### Tekniset päätökset

| Komponentti | Valinta | Miksi |
|---|---|---|
| **Trigger** | Burrel webhook | Reaaliaikainen push, ei turhaa pollausta |
| **Backend** | Cloudflare Workers (TS) | `ctx.waitUntil()` ratkaisee Burrelin 5s timeout, nolla cold start, 100K req/pv ilmaiseksi |
| **AI/Vision** | Google Gemini API | Nopea, hyvä suomen kieli, edullinen, API-avain valmiina |
| **Ilmoitukset** | Telegram Bot | Ilmainen API, tukee kuvia + tekstiä, fetch()-yhteensopiva |

### Miksi Cloudflare Workers (eikä GCP/Azure Functions)?

1. **`ctx.waitUntil()`** — Burrelin webhook vaatii <5s kuittauksen, mutta Gemini-analyysi kestää 3–6s. Workers kuittaa heti ja ajaa analyysin taustalla. GCP:ssä tarvittaisiin Pub/Sub + 2 funktiota.
2. **Nolla cold start** — V8-isolaatit, ei herätysviivettä vaikka kamera olisi hiljaa päiviä.
3. **Yksinkertainen koodi** — koko pipeline mahtuu yhteen tiedostoon, pelkkiä fetch()-kutsuja.
4. **Ilmainen ja huoltovapaa** — 100K req/päivä, ei palvelimia päivitettäväksi.

## Kansiorakenne

```
moose_cam/
├── worker/                       # Cloudflare Worker (TypeScript) — TODO
│   ├── src/index.ts
│   ├── wrangler.toml
│   └── package.json
├── testing/                      # Python-testiskriptit (mallin evaluointi)
│   ├── classify.py
│   ├── ab_test.py
│   ├── burrel_classify.py
│   └── copy_test_images.py
├── scripts/                      # Apuskriptit
│   └── telegram_send.py
├── docs/                         # Dokumentaatio
│   ├── openapi.json
│   └── burrel_tiketti.md
├── .env.example
└── .gitignore
```

## Kamera

- **Malli:** Burrel N24
- **Sijainti:** Utsjoki, Pohjois-Lappi
- **Asetukset:** Liiketunnistin, instant send, 10M kuva, normaali herkkyys
- **Kuvia SD-kortilla:** 954 kpl (päivä + yö/IR)
- **Burrel API:** Toimii (autentikaatio OK 2026-06-27), 7 päivän säilytys

## Mallin testaus (Python)

Ennen pipeline-toteutusta mallit testattiin paikallisesti Pythonilla SD-kortin kuvilla.

### Setup (testiskriptit)

```bash
pip install groq google-genai python-dotenv requests
cp .env.example .env  # täytä oikeat avaimet
```

### Skriptit

| Skripti | Tarkoitus |
|---|---|
| `testing/classify.py` | 20 kuvan testi, evaluointi oikeita vastauksia vasten |
| `testing/ab_test.py` | Laaja A/B-testi: 2 mallia × 2 promptia × 477 kuvaa |
| `testing/burrel_classify.py` | Burrel API → hae kuvat → luokittele |
| `testing/copy_test_images.py` | Kopioi testikuvat `riistakamera_kuvat/` → `20_test/` |
| `scripts/telegram_send.py` | CLI: `python scripts/telegram_send.py "viesti"` |

### Testatut mallit

| Malli | API | Hinta | JSON-pakotus | Suomen kieli |
|---|---|---|---|---|
| Llama 4 Scout 17B | Groq | 0 € | `response_format` | Heikko |
| Gemini 3.1 Flash Lite | Google AI | 0 € | `response_mime_type` | Hyvä |

**Huom:** Llama 4 Scout poistettiin Groqista 17.6.2026.

### Tulokset

**20 kuvan testi (V4-prompti):** 100% accuracy, precision ja recall (20/20).

**A/B-testi (477 kuvaa):** Gemini detailed valmis, Groq kesken (TPD-rajoitus). 17 yhteistä testikuvaa → 100% yksimielisyys mallien välillä.

### Prompt engineering -opit

- Poro-ohjeen lisääminen **heikensi** tuloksia (100% → 80%) — malli luokitteli hirviä poroiksi
- Yksinkertainen prompti + "iso hirvieläin = todennäköisesti hirvi" toimii parhaiten
- Luottamusarvot eivät ole luotettavia
- "Metsästäjä-ääni" tuottaa viihdyttäviä kuvauksia

## Burrel Public API

- **Base URL:** `https://app.burrelcameras.com/api/v1/public`
- **Docs:** `https://app.burrelcameras.com/api/v1/public/info/`
- **Auth:** `POST /auth` + accessKey → 1h token
- **Webhook:** `PUT /webhook` — 5s timeout, auto-deregister after 5 failures
- **Säilytys:** 7 päivää (app), 1 vuosi (Pro)
- **OpenAPI spec:** `docs/openapi.json`
