/**
 * Cloudflare Worker: Burrel webhook → Gemini vision classification → Telegram alert.
 * Responds to Burrel within 5s, processes images in the background via ctx.waitUntil().
 */

interface Env {
	WEBHOOK_SECRET: string;
	BURREL_ACCESS_KEY: string;
	GEMINI_API_KEY: string;
	TELEGRAM_BOT_TOKEN: string;
	TELEGRAM_CHAT_ID: string;
}

interface BurrelMedia {
	created: string;
	type: string;
	url: string;
	thumbnail: string;
	temperature: number | null;
}

interface BurrelWebhookPayload {
	status?: Record<string, unknown>;
	media?: BurrelMedia[];
}

interface GeminiResult {
	hirvi: boolean;
	elain_kuvassa: boolean;
	luottamus: number;
	kuvaus: string;
}

const BURREL_API = "https://app.burrelcameras.com/api/v1/public";
const GEMINI_MODEL = "gemini-3.1-flash-lite";
const GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta";
const GEMINI_MAX_TOKENS = 150;

const PROMPT = `Riistakamerakuva Utsjoelta, Pohjois-Lapista. Onko kuvassa hirvi (Alces alces, moose)?

Hirvi on suuri, tumma hirvieläin jolla on pitkät jalat, kyttyräselkä ja leveä kuono. \
Jos kuvassa on iso hirvieläin, se on todennäköisesti hirvi. \
Jos kuvassa on eläin mutta et ole varma lajista, merkitse elain_kuvassa: true.

Kirjoita kuvaus kuin kokenut hirvenmetsästäjä. Suorapuheisesti, \
kiroillen ja rikkaalla kielellä.

Vastaa JSON:
{"hirvi": true/false, "elain_kuvassa": true/false, \
"luottamus": 0.0-1.0, "kuvaus": "metsästäjän kommentti, max 15 sanaa"}

luottamus = kuinka varma olet omasta vastauksestasi.`;

async function getBurrelToken(accessKey: string): Promise<string> {
	const resp = await fetch(`${BURREL_API}/auth`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ accessKey }),
	});
	if (!resp.ok) {
		throw new Error(`Burrel auth failed: ${resp.status}`);
	}
	const data = await resp.json<{ token: string }>();
	return data.token;
}

async function fetchImage(url: string, token: string): Promise<ArrayBuffer> {
	const resp = await fetch(url, {
		headers: { Authorization: `Bearer ${token}` },
	});
	if (!resp.ok) {
		throw new Error(`Image fetch failed: ${resp.status}`);
	}
	return resp.arrayBuffer();
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
	const bytes = new Uint8Array(buffer);
	const CHUNK = 8192;
	const chunks: string[] = [];
	for (let i = 0; i < bytes.length; i += CHUNK) {
		chunks.push(String.fromCharCode(...bytes.subarray(i, i + CHUNK)));
	}
	return btoa(chunks.join(""));
}

async function classifyWithGemini(
	imageBase64: string,
	apiKey: string,
): Promise<GeminiResult> {
	const url = `${GEMINI_API_BASE}/models/${GEMINI_MODEL}:generateContent?key=${apiKey}`;

	const resp = await fetch(url, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			contents: [
				{
					parts: [
						{
							inlineData: {
								mimeType: "image/jpeg",
								data: imageBase64,
							},
						},
						{ text: PROMPT },
					],
				},
			],
			generationConfig: {
				responseMimeType: "application/json",
				maxOutputTokens: GEMINI_MAX_TOKENS,
			},
		}),
	});

	if (!resp.ok) {
		const body = await resp.text();
		throw new Error(`Gemini API error ${resp.status}: ${body}`);
	}

	const data = await resp.json<{
		candidates: Array<{ content: { parts: Array<{ text: string }> } }>;
	}>();

	return JSON.parse(data.candidates[0].content.parts[0].text);
}

async function sendTelegramPhoto(
	imageBytes: ArrayBuffer,
	caption: string,
	botToken: string,
	chatId: string,
): Promise<void> {
	const boundary = "----MooseCamBoundary";

	const prefix =
		`--${boundary}\r\n` +
		`Content-Disposition: form-data; name="chat_id"\r\n\r\n${chatId}\r\n` +
		`--${boundary}\r\n` +
		`Content-Disposition: form-data; name="caption"\r\n\r\n${caption}\r\n` +
		`--${boundary}\r\n` +
		`Content-Disposition: form-data; name="photo"; filename="moose.jpg"\r\n` +
		`Content-Type: image/jpeg\r\n\r\n`;

	const suffix = `\r\n--${boundary}--\r\n`;

	const prefixBytes = new TextEncoder().encode(prefix);
	const suffixBytes = new TextEncoder().encode(suffix);
	const photoBytes = new Uint8Array(imageBytes);

	const body = new Uint8Array(
		prefixBytes.length + photoBytes.length + suffixBytes.length,
	);
	body.set(prefixBytes, 0);
	body.set(photoBytes, prefixBytes.length);
	body.set(suffixBytes, prefixBytes.length + photoBytes.length);

	const resp = await fetch(
		`https://api.telegram.org/bot${botToken}/sendPhoto`,
		{
			method: "POST",
			headers: {
				"Content-Type": `multipart/form-data; boundary=${boundary}`,
			},
			body: body.buffer,
		},
	);

	if (!resp.ok) {
		const text = await resp.text();
		throw new Error(`Telegram sendPhoto failed ${resp.status}: ${text}`);
	}
}

async function sendTelegramMessage(
	text: string,
	botToken: string,
	chatId: string,
): Promise<void> {
	const resp = await fetch(
		`https://api.telegram.org/bot${botToken}/sendMessage`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ chat_id: chatId, text }),
		},
	);
	if (!resp.ok) {
		const body = await resp.text();
		throw new Error(`Telegram sendMessage failed ${resp.status}: ${body}`);
	}
}

async function processMedia(
	media: BurrelMedia,
	burrelToken: string,
	env: Env,
): Promise<void> {
	if (media.type !== "image") {
		console.log(`Skipping non-image media: ${media.type}`);
		return;
	}

	console.log(`Processing image from ${media.created}`);

	const imageBuffer = await fetchImage(media.url, burrelToken);
	const imageBase64 = arrayBufferToBase64(imageBuffer);

	console.log(`Image fetched, size: ${imageBuffer.byteLength} bytes`);

	const result = await classifyWithGemini(imageBase64, env.GEMINI_API_KEY);

	console.log(
		`Classification: hirvi=${result.hirvi}, luottamus=${result.luottamus}`,
	);

	if (result.hirvi) {
		const tempStr =
			media.temperature !== null ? `${media.temperature}°C` : "";
		const caption =
			`🦌 HIRVI!\n\n${result.kuvaus}\n\n` +
			`📷 ${media.created}` +
			(tempStr ? ` | 🌡️ ${tempStr}` : "");

		await sendTelegramPhoto(
			imageBuffer,
			caption,
			env.TELEGRAM_BOT_TOKEN,
			env.TELEGRAM_CHAT_ID,
		);
		console.log("Telegram alert sent");
	} else if (result.elain_kuvassa) {
		console.log(`Animal detected but not moose: ${result.kuvaus}`);
	} else {
		console.log(`No animal: ${result.kuvaus}`);
	}
}

export default {
	async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
		if (request.method !== "POST") {
			return new Response("Method not allowed", { status: 405 });
		}

		const url = new URL(request.url);
		if (url.searchParams.get("secret") !== env.WEBHOOK_SECRET) {
			return new Response("Unauthorized", { status: 401 });
		}

		const payload = await request.json<BurrelWebhookPayload>();

		const mediaItems = payload.media ?? [];

		if (mediaItems.length > 0) {
			ctx.waitUntil(
				(async () => {
					const burrelToken = await getBurrelToken(env.BURREL_ACCESS_KEY);
					for (const media of mediaItems) {
						try {
							await processMedia(media, burrelToken, env);
						} catch (err) {
							console.error(`Failed to process media: ${err}`);
							try {
								await sendTelegramMessage(
									`⚠️ Virhe kuvan käsittelyssä: ${err instanceof Error ? err.message : err}`,
									env.TELEGRAM_BOT_TOKEN,
									env.TELEGRAM_CHAT_ID,
								);
							} catch {
								console.error("Failed to send error notification");
							}
						}
					}
				})(),
			);
		}

		return new Response("OK", { status: 200 });
	},
} satisfies ExportedHandler<Env>;
