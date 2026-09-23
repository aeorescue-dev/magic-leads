import { NextResponse } from "next/server";
import Stripe from "stripe";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { priceId, customerId, successUrl, cancelUrl } = body ?? {};

    if (!process.env.STRIPE_SECRET_KEY) {
      return NextResponse.json({ error: "STRIPE_SECRET_KEY nÃ£o configurada" }, { status: 500 });
    }

    const stripe = new Stripe(process.env.STRIPE_SECRET_KEY, {
      apiVersion: "2023-08-16",
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
    console.error("[stripe/checkout] Erro ao criar sessÃ£o", err);
    return NextResponse.json(
      { error: "Falha ao criar a sessÃ£o de checkout" },
      { status: 500 }
    );
  }
}
