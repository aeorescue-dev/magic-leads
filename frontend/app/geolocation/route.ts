import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const ALIASES: Record<string, string> = {
  "new york": "New York",
  "new york city": "New York",
  nyc: "New York",
  boston: "Boston",
  dallas: "Dallas",
  chicago: "Chicago",
};

export async function GET(request: NextRequest) {
  const raw = request.headers.get("x-vercel-ip-city") || "";
  let city = raw;
  try {
    city = decodeURIComponent(raw);
  } catch {
    /* keep raw */
  }
  const key = city.toLowerCase().replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  const resolved = ALIASES[key] ?? (key.includes("new york") ? "New York" : null);
  return NextResponse.json({ city: resolved });
}
