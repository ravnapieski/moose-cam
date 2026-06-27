# Moose Cam

Automated moose detection from a [Burrel](https://www.burrelcameras.com/) trail camera in Utsjoki, northern Lapland. When the camera captures a photo with a moose, a Telegram alert is sent with the image and an AI-generated description — written in the voice of a Finnish moose hunter.

Uses vision language models (zero-shot, no fine-tuning) for classification. Tested with 477 trail camera images at 100% agreement between models.

## How it works

```
Burrel camera (Utsjoki)
  → motion trigger → photo
    → Burrel backend
      → Webhook POST → Cloudflare Worker
        → responds 200 OK immediately (<5s)
        → ctx.waitUntil() background:
          → fetch image from Burrel API
          → Gemini classifies: moose or not?
          → if moose → Telegram alert with photo + description
```

## Architecture decisions

| Component | Choice | Why |
|---|---|---|
| **Trigger** | Burrel webhook | Real-time push, no polling |
| **Backend** | Cloudflare Workers (TS) | `ctx.waitUntil()` solves Burrel's 5s timeout, zero cold start, 100K req/day free |
| **AI/Vision** | Google Gemini 3.1 Flash Lite | Fast, good Finnish, cheap, JSON mode built in |
| **Alerts** | Telegram Bot | Free API, supports photos + text, works with fetch() |

**Why Cloudflare Workers over GCP/Azure Functions?** Burrel's webhook requires a response within 5 seconds, but Gemini analysis takes 3–6s. Workers responds immediately and runs the analysis in the background with `ctx.waitUntil()`. On GCP this would require Pub/Sub + two separate functions.

## Project structure

```
moose_cam/
├── worker/                       # Cloudflare Worker (TypeScript)
│   ├── src/index.ts
│   ├── wrangler.toml
│   └── package.json
├── testing/                      # Python test scripts (model evaluation)
│   ├── classify.py               # 20-image test with labels
│   ├── ab_test.py                # A/B: 2 models × 2 prompts × 477 images
│   ├── burrel_classify.py        # Burrel API fetch + classify (deprecated)
│   ├── test_worker_local.py      # E2E test for local/prod Worker
│   └── copy_test_images.py
├── scripts/
│   └── telegram_send.py          # CLI: send Telegram messages/photos
├── docs/
│   ├── openapi.json              # Burrel API spec
│   └── burrel_tiketti.md
├── .github/workflows/deploy.yml  # Auto-deploy on push
├── .env.example
└── .gitignore
```

## Setup

### Worker (production pipeline)

```bash
cd worker
npm install
cp .dev.vars.example .dev.vars    # fill in secrets
npx wrangler dev                  # local dev server
npx wrangler deploy               # deploy to Cloudflare
```

Secrets (set with `npx wrangler secret put <NAME>`):
- `WEBHOOK_SECRET` — shared secret in the webhook URL query string
- `BURREL_ACCESS_KEY` — Burrel camera access key
- `GEMINI_API_KEY` — Google AI API key
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `TELEGRAM_CHAT_ID` — target Telegram chat/group ID

### Test scripts (Python)

```bash
pip install groq google-genai python-dotenv requests
cp .env.example .env              # fill in keys
```

## Auto-deploy

Pushing to `main` with changes in `worker/` triggers a GitHub Actions workflow:

1. `npm ci` — install dependencies
2. `tsc --noEmit` — type check (deploy blocked if this fails)
3. `wrangler deploy` — deploy to Cloudflare

Required GitHub repository secrets:
- `CLOUDFLARE_API_TOKEN` — API token with "Workers Scripts: Edit" permission
- `CLOUDFLARE_ACCOUNT_ID` — from Cloudflare dashboard → Workers & Pages

## Model testing

Before building the pipeline, models were tested locally with 954 SD card images.

| Model | API | JSON mode | Finnish | Status |
|---|---|---|---|---|
| Llama 4 Scout 17B | Groq | `response_format` | Weak | Removed from Groq 17.6.2026 |
| Gemini 3.1 Flash Lite | Google AI | `response_mime_type` | Good | **In production** |

**20-image test:** 100% accuracy, precision, and recall (20/20).

**A/B test (477 images):** 17 comparable images → 100% agreement between models.

### Prompt engineering lessons

- Adding reindeer instructions **degraded** results (100% → 80%) — the model started classifying moose as reindeer
- Simple prompt + "large cervid = probably moose" works best
- Confidence scores are unreliable
- "Hunter voice" produces entertaining descriptions

## Camera

- **Model:** Burrel N24
- **Location:** Utsjoki, northern Lapland
- **Settings:** Motion trigger, instant send, 10MP, normal sensitivity
- **Burrel API:** 7-day retention (app), 1 year (Pro)
- **OpenAPI spec:** `docs/openapi.json`
