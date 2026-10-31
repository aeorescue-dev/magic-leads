"use client";

import { getToken, type AuthResponse } from "./api-client";

/**
 * WebAuthn / Passkeys — cliente.
 *
 * A biometria ocorre no dispositivo; o servidor recebe apenas a credencial
 * pública. Sem SDK pago: APIs nativas do browser + endpoints próprios.
 */

export type PasskeyErrorCode =
  | "unsupported"
  | "cancelled"
  | "no_credential"
  | "failed"
  | "server";

export class PasskeyError extends Error {
  code: PasskeyErrorCode;
  status?: number;
  constructor(code: PasskeyErrorCode, message: string, status?: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

const HINT_KEY = "garimpador.passkey.enabled";

export function isPasskeySupported(): boolean {
  if (typeof window === "undefined") return false;
  return (
    typeof window.PublicKeyCredential !== "undefined" &&
    typeof navigator !== "undefined" &&
    !!navigator.credentials &&
    typeof navigator.credentials.create === "function" &&
    typeof navigator.credentials.get === "function"
  );
}

export function hasPasskeyHint(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(HINT_KEY) === "1";
  } catch {
    return false;
  }
}

export function setPasskeyHint(enabled: boolean): void {
  if (typeof window === "undefined") return;
  try {
    if (enabled) window.localStorage.setItem(HINT_KEY, "1");
    else window.localStorage.removeItem(HINT_KEY);
  } catch {
    /* storage indisponível */
  }
}

function bufToB64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlToBuf(value: string): ArrayBuffer {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  const pad = padded.length % 4 === 0 ? "" : "=".repeat(4 - (padded.length % 4));
  const binary = atob(padded + pad);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function post<T>(
  path: string,
  body: unknown,
  authenticated = true
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(authenticated ? authHeaders() : {}),
      },
      body: JSON.stringify(body),
    });
  } catch {
    throw new PasskeyError("server", "Falha de rede. Tente novamente.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : data?.detail?.message || "Não foi possível concluir o pedido.";
    throw new PasskeyError("server", detail, res.status);
  }
  return data as T;
}

export interface PasskeyInfo {
  id: number;
  credential_id: string;
  device_label: string;
  created_at?: string | null;
  last_used_at?: string | null;
  cloned_warning?: boolean;
}

export async function fetchMyPasskeys(): Promise<PasskeyInfo[]> {
  const res = await fetch("/api/users/me/passkeys", {
    credentials: "include",
    headers: authHeaders(),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new PasskeyError("server", "Não foi possível listar as passkeys.", res.status);
  }
  return (data.passkeys || []) as PasskeyInfo[];
}

export async function deleteMyPasskey(credentialId: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(
      `/api/users/me/passkeys/${encodeURIComponent(credentialId)}`,
      { method: "DELETE", credentials: "include", headers: authHeaders() }
    );
  } catch {
    throw new PasskeyError("server", "Falha de rede. Tente novamente.");
  }
  if (!res.ok) {
    throw new PasskeyError("server", "Não foi possível remover a passkey.", res.status);
  }
}

export async function registerPasskey(): Promise<{ device_label: string }> {
  if (!isPasskeySupported()) {
    throw new PasskeyError("unsupported", "Este dispositivo não suporta Face ID.");
  }
  const options = await post<any>("/api/auth/webauthn/register/options", {});
  const publicKey: PublicKeyCredentialCreationOptions = {
    ...options,
    challenge: b64urlToBuf(options.challenge),
    user: { ...options.user, id: b64urlToBuf(options.user.id) },
    excludeCredentials: (options.excludeCredentials || []).map((c: any) => ({
      ...c,
      id: b64urlToBuf(c.id),
    })),
  };

  let cred: Credential | null;
  try {
    cred = await navigator.credentials.create({ publicKey });
  } catch (err: any) {
    if (err?.name === "NotAllowedError") {
      throw new PasskeyError("cancelled", "Registo cancelado.");
    }
    throw new PasskeyError("failed", "Não foi possível criar a passkey.");
  }
  if (!cred) throw new PasskeyError("cancelled", "Registo cancelado.");

  const attestation = cred as PublicKeyCredential;
  const response = attestation.response as AuthenticatorAttestationResponse & {
    getTransports?: () => string[];
  };
  const payload = {
    id: attestation.id,
    rawId: bufToB64url(attestation.rawId),
    type: attestation.type,
    response: {
      clientDataJSON: bufToB64url(response.clientDataJSON),
      attestationObject: bufToB64url(response.attestationObject),
      transports: response.getTransports?.() ?? [],
    },
    clientExtensionResults: attestation.getClientExtensionResults?.() ?? {},
  };
  const out = await post<{ device_label: string }>(
    "/api/auth/webauthn/register/verify",
    payload
  );
  setPasskeyHint(true);
  return out;
}

export async function loginWithPasskey(email?: string): Promise<AuthResponse> {
  if (!isPasskeySupported()) {
    throw new PasskeyError("unsupported", "Este dispositivo não suporta Face ID.");
  }
  const options = await post<any>(
    "/api/auth/webauthn/login/options",
    email ? { email } : {},
    false
  );
  const publicKey: PublicKeyCredentialRequestOptions = {
    ...options,
    challenge: b64urlToBuf(options.challenge),
    allowCredentials: (options.allowCredentials || []).map((c: any) => ({
      ...c,
      id: b64urlToBuf(c.id),
    })),
  };

  let cred: Credential | null;
  try {
    cred = await navigator.credentials.get({ publicKey });
  } catch (err: any) {
    if (err?.name === "NotAllowedError") {
      throw new PasskeyError("cancelled", "Face ID cancelado ou indisponível.");
    }
    if (err?.name === "SecurityError" || err?.name === "NotSupportedError") {
      throw new PasskeyError("unsupported", "Este navegador não permite passkeys.");
    }
    throw new PasskeyError("failed", "Não foi possível confirmar a passkey.");
  }
  if (!cred) throw new PasskeyError("no_credential", "Nenhuma passkey encontrada.");

  const assertion = cred as PublicKeyCredential;
  const response = assertion.response as AuthenticatorAssertionResponse;
  const payload = {
    id: assertion.id,
    rawId: bufToB64url(assertion.rawId),
    type: assertion.type,
    response: {
      clientDataJSON: bufToB64url(response.clientDataJSON),
      authenticatorData: bufToB64url(response.authenticatorData),
      signature: bufToB64url(response.signature),
      userHandle: response.userHandle ? bufToB64url(response.userHandle) : null,
    },
    clientExtensionResults: assertion.getClientExtensionResults?.() ?? {},
  };
  return post<AuthResponse>("/api/auth/webauthn/login/verify", payload, false);
}
