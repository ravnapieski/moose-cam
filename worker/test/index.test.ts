import { afterEach, describe, expect, it, vi } from "vitest";

import worker, { arrayBufferToBase64, buildMultipartBody } from "../src/index";

const ENV = {
	WEBHOOK_SECRET: "s3cret",
	BURREL_ACCESS_KEY: "burrel-key",
	GEMINI_API_KEY: "gemini-key",
	TELEGRAM_BOT_TOKEN: "bot-token",
	TELEGRAM_CHAT_ID: "chat-123",
};

function textToArrayBuffer(text: string): ArrayBuffer {
	return new TextEncoder().encode(text).buffer;
}

describe("arrayBufferToBase64", () => {
	it("empty buffer", () => {
		expect(arrayBufferToBase64(new ArrayBuffer(0))).toBe("");
	});

	it("matches btoa", () => {
		expect(arrayBufferToBase64(textToArrayBuffer("moose"))).toBe(btoa("moose"));
	});

	it("handles >8kb", () => {
		const raw = "x".repeat(8192 * 2 + 123);
		expect(arrayBufferToBase64(textToArrayBuffer(raw))).toBe(btoa(raw));
	});
});

describe("buildMultipartBody", () => {
	it("builds multipart body", () => {
		const image = textToArrayBuffer("JPEGDATA");
		const body = buildMultipartBody(image, "kuvaus", "chat-123");
		const decoded = new TextDecoder().decode(body);

		expect(decoded).toContain('name="chat_id"\r\n\r\nchat-123');
		expect(decoded).toContain('name="caption"\r\n\r\nkuvaus');
		expect(decoded).toContain("JPEGDATA");
		expect(decoded.endsWith("------MooseCamBoundary--\r\n")).toBe(true);
	});

	it("keeps image bytes intact", () => {
		const image = new Uint8Array(256);
		for (let i = 0; i < 256; i++) image[i] = i;
		const body = buildMultipartBody(image.buffer, "kuvaus", "chat-123");

		let at = -1;
		for (let i = 0; i + image.length <= body.length; i++) {
			if (body.subarray(i, i + image.length).every((b, j) => b === image[j])) {
				at = i;
				break;
			}
		}
		expect(at).toBeGreaterThan(-1);
	});
});

describe("handler gating", () => {
	function ctx() {
		const tasks: Promise<unknown>[] = [];
		return {
			waitUntil: (p: Promise<unknown>) => tasks.push(p),
			passThroughOnException: () => {},
			tasks,
		} as unknown as ExecutionContext & { tasks: Promise<unknown>[] };
	}

	it("405 on non-POST", async () => {
		const resp = await worker.fetch(
			new Request("https://w.dev/", { method: "GET" }),
			ENV,
			ctx(),
		);
		expect(resp.status).toBe(405);
	});

	it("401 on bad secret", async () => {
		const resp = await worker.fetch(
			new Request("https://w.dev/?secret=wrong", {
				method: "POST",
				body: JSON.stringify({ media: [] }),
			}),
			ENV,
			ctx(),
		);
		expect(resp.status).toBe(401);
	});

	it("200, no work on empty media", async () => {
		const c = ctx();
		const resp = await worker.fetch(
			new Request("https://w.dev/?secret=s3cret", {
				method: "POST",
				body: JSON.stringify({ media: [] }),
			}),
			ENV,
			c,
		);
		expect(resp.status).toBe(200);
		expect(c.tasks).toHaveLength(0);
	});
});

describe("handler background", () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	type Call = { url: string };

	function stubFetch(
		geminiResult: Record<string, unknown>,
		opts: { geminiOk?: boolean } = {},
	) {
		const calls: Call[] = [];
		vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
			const url = typeof input === "string" ? input : input.toString();
			calls.push({ url });

			if (url.includes("/auth")) {
				return new Response(JSON.stringify({ token: "jwt" }), { status: 200 });
			}
			if (url.includes("generativelanguage")) {
				if (opts.geminiOk === false) {
					return new Response("boom", { status: 500 });
				}
				return new Response(
					JSON.stringify({
						candidates: [
							{ content: { parts: [{ text: JSON.stringify(geminiResult) }] } },
						],
					}),
					{ status: 200 },
				);
			}
			if (url.includes("api.telegram.org")) {
				return new Response("{}", { status: 200 });
			}
			// Burrel image download.
			return new Response(textToArrayBuffer("IMAGEBYTES"), { status: 200 });
		});
		return calls;
	}

	function webhookRequest() {
		return new Request("https://w.dev/?secret=s3cret", {
			method: "POST",
			body: JSON.stringify({
				media: [
					{
						created: "2026-08-26T10:00:00Z",
						type: "image",
						url: "https://app.burrelcameras.com/media/1.jpg",
						thumbnail: "",
						temperature: -3,
					},
				],
			}),
		});
	}

	async function run(calls: Call[], c: any) {
		await Promise.all(c.tasks);
		return calls;
	}

	function ctx() {
		const tasks: Promise<unknown>[] = [];
		return {
			waitUntil: (p: Promise<unknown>) => tasks.push(p),
			passThroughOnException: () => {},
			tasks,
		} as any;
	}

	it("moose -> sendPhoto", async () => {
		const calls = stubFetch({
			hirvi: true,
			elain_kuvassa: true,
			luottamus: 0.9,
			kuvaus: "Iso otus seisoo tiellä.",
		});
		const c = ctx();
		await worker.fetch(webhookRequest(), ENV, c);
		await run(calls, c);

		expect(calls.some((x) => x.url.includes("/sendPhoto"))).toBe(true);
		expect(calls.some((x) => x.url.includes("/sendMessage"))).toBe(false);
	});

	it("other animal -> no photo", async () => {
		const calls = stubFetch({
			hirvi: false,
			elain_kuvassa: true,
			luottamus: 0.7,
			kuvaus: "Poro, ei hirvi.",
		});
		const c = ctx();
		await worker.fetch(webhookRequest(), ENV, c);
		await run(calls, c);

		expect(calls.some((x) => x.url.includes("/sendPhoto"))).toBe(false);
		expect(calls.some((x) => x.url.includes("/sendMessage"))).toBe(false);
	});

	it("empty frame -> no photo", async () => {
		const calls = stubFetch({
			hirvi: false,
			elain_kuvassa: false,
			luottamus: 0.8,
			kuvaus: "Tyhjä kuva.",
		});
		const c = ctx();
		await worker.fetch(webhookRequest(), ENV, c);
		await run(calls, c);

		expect(calls.some((x) => x.url.includes("/sendPhoto"))).toBe(false);
	});

	it("gemini error -> sendMessage", async () => {
		const calls = stubFetch({}, { geminiOk: false });
		const c = ctx();
		await worker.fetch(webhookRequest(), ENV, c);
		await run(calls, c);

		expect(calls.some((x) => x.url.includes("/sendMessage"))).toBe(true);
		expect(calls.some((x) => x.url.includes("/sendPhoto"))).toBe(false);
	});
});
