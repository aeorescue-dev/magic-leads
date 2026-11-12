import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const API_URL = (
  process.env.API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "https://magic-leads-production.up.railway.app"
).replace(/\/$/, "");

/**
 * Proxy same-origin do beacon de analytics.
 *
 * A Vercel é o único ponto com os headers de geolocalização; o Railway só vê
 * o IP do proxy. O browser fala sempre com magicleads.app (sem CORS e menos
 * bloqueio por adblock), e a chave de ingestão fica só no servidor.
 *
 * Nunca rebenta a página: qualquer falha devolve 204 e o lote é perdido.
 */
export async function POST(request: NextRequest) {
  try {
    const raw = await request.text();
    if (!raw || raw.length > 24_000) {
      return new Response(null, { status: 204 });
    }
    const key = (process.env.ANALYTICS_INGEST_KEY || "").trim();
    if (!key) {
      return new Response(null, { status: 204 });
    }

    const body = JSON.parse(raw);
    const headers = request.headers;
    const cityHeader = headers.get("x-vercel-ip-city") || "";
    let city = cityHeader;
    try {
      city = decodeURIComponent(cityHeader);
    } catch {
      city = cityHeader;
    }
    const forwarded = (headers.get("x-forwarded-for") || "")
      .split(",")[0]
      .trim();
    const clientIp = forwarded || headers.get("x-real-ip") || "";

    const payload = {
      ...body,
      context: {
        ...(body?.context || {}),
        ua: headers.get("user-agent") || "",
        host:
          headers.get("x-forwarded-host") ||
          headers.get("host") ||
          "",
        referrer: body?.context?.referrer || headers.get("referer") || "",
        country: headers.get("x-vercel-ip-country") || "",
        region: headers.get("x-vercel-ip-country-region") || "",
        city,
      },
    };

    await fetch(`${API_URL}/api/analytics/ingest`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Analytics-Key": key,
        "X-Analytics-Client-IP": clientIp,
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(2500),
    }).catch(() => undefined);

    return new Response(null, { status: 204 });
  } catch {
    return new Response(null, { status: 204 });
  }
}
