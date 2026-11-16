import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const gate =
    process.env.STAGING_GATE === "1" || process.env.STAGING_GATE === "true";
  const expected = process.env.STAGING_ACCESS_TOKEN || "";
  if (!gate || !expected) {
    return NextResponse.json({ error: "staging_gate_disabled" }, { status: 404 });
  }
  let token = "";
  try {
    const body = await request.json();
    token = String(body?.token || "");
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }
  if (token !== expected) {
    return NextResponse.json({ error: "invalid_token" }, { status: 401 });
  }
  const response = NextResponse.json({ ok: true });
  const secure = request.url.startsWith("https://");
  response.cookies.set("staging_gate", expected, {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: 7 * 24 * 60 * 60,
  });
  return response;
}
