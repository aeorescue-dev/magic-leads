import { NextResponse } from "next/server";
import Stripe from "stripe";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { priceId, customerId, successUrl, cancelUrl } = body ?? {};

    if (!process.env.STRIPE_SECRET_KEY) {
      return NextResponse.json({ error: "STRIPE_SECRET_KEY não configurada" }, { status: 500 });
    }

    const stripe = new Stripe(process.env.STRIPE_SECRET_KEY, {
      apiVersion: "2024-06-20",
    });

    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId as string, quantity: 1 }],
      customer: customerId as string | undefined,
      success_url: (successUrl as string) || "https://example.com/success",
      cancel_url: (cancelUrl as string) || "https://example.com/checkout",
    });

    return NextResponse.json({ url: session.url });
  } catch (err) {
    console.error("[stripe/checkout] Erro ao criar sessão", err);
    return NextResponse.json(
      { error: "Falha ao criar a sessão de checkout" },
      { status: 500 }
    );
  }
}
