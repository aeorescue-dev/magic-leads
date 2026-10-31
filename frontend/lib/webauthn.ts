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
  | "timeout"
  | "no_credential"
  | "origin"
  | "already_registered"
  | "unreadable"
  | "failed"
  | "server";

/** Plataformas com nomes de biometria diferentes (UX honesta). */
export type PasskeyPlatform = "apple" | "android" | "windows" | "other";

/**
 * Deteta a plataforma para escolher o vocabulário certo. No Android a
 * biometria primária é a impressão digital (ou o bloqueio do ecrã), não há
 * "Face ID"; em Windows é Windows Hello.
 */
export function passkeyPlatform(): PasskeyPlatform {
  if (typeof navigator === "undefined") return "other";
  const ua = navigator.userAgent || "";
  if (/android/i.test(ua)) return "android";
  if (/iphone|ipad|ipod|macintosh|mac os x/i.test(ua)) return "apple";
  if (/windows/i.test(ua)) return "windows";
  return "other";
}

/** Sufixo i18n por plataforma (`auth.passkey.login_<suffix>`). */
export function passkeyPlatformSuffix(platform: PasskeyPlatform): string {
  return platform === "other" ? "default" : platform;
}

/** Contexto técnico do browser/servidor, para o utilizador reportar suporte. */
export interface PasskeyErrorDetail {
  browserError?: string;
  serverCode?: string;
}

export class PasskeyError extends Error {
  code: PasskeyErrorCode;
  status?: number;
  detail?: PasskeyErrorDetail;
  constructor(
    code: PasskeyErrorCode,
    message: string,
    status?: number,
    detail?: PasskeyErrorDetail
  ) {
    super(message);
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Traduz a DOMException real do browser. Sem isto, um SecurityError (RP ID
 * errado, ex.: preview Vercel) aparecia como "tente novamente" e escondia a
 * causa. `phase` entra só no detalhe técnico.
 */
export function passkeyErrorFromException(
  err: unknown,
  phase: "register" | "login"
): PasskeyError {
  const e = err as { name?: string; message?: string } | null;
  const name = e?.name || "Error";
  const detail: PasskeyErrorDetail = {
    browserError: `${name}: ${e?.message || "sem mensagem"}`,
  };
  switch (name) {
    case "NotAllowedError": {
      // "timed out" = o gestor de credenciais não respondeu a tempo (típico
      // quando o telemóvel bloqueia ou já existe uma chave travada). Sem esta
      // distinção o utilizador via "cancelado" sem ter cancelado nada.
      const timedOut = /timed out/i.test(e?.message || "");
      return new PasskeyError(
        timedOut ? "timeout" : "cancelled",
        timedOut
          ? "O telemóvel não respondeu a tempo. Desbloqueie o ecrã e tente novamente."
          : "Operação cancelada ou não autorizada pelo dispositivo.",
        undefined,
        detail
      );
    }
    case "InvalidStateError":
      return new PasskeyError(
        "already_registered",
        "Este dispositivo já tem uma passkey registada nesta conta.",
        undefined,
        detail
      );
    case "SecurityError":
      return new PasskeyError(
        "origin",
        "O domínio atual não corresponde ao domínio autorizado para a chave de acesso.",
        undefined,
        detail
      );
    case "NotSupportedError":
      return new PasskeyError(
        "unsupported",
        "Este dispositivo ou navegador não suporta chaves de acesso.",
        undefined,
        detail
      );
    case "AbortError":
      return new PasskeyError("cancelled", "Operação cancelada.", undefined, detail);
    case "ConstraintError":
      return new PasskeyError(
        "failed",
        "O dispositivo não cumpriu os requisitos de segurança.",
        undefined,
        detail
      );
    case "NotReadableError":
    case "UnknownError":
      // Android/Chromium: o Credential Manager (Google Password Manager)
      // falhou ou expirou durante o desbloqueio. Não é "tente novamente" cego:
      // o utilizador tem de desbloquear o gestor de senhas.
      return new PasskeyError(
        "unreadable",
        "O gestor de chaves do dispositivo não respondeu. Desbloqueie o ecrã, " +
          "confirme que o gestor de senhas está ativo e tente novamente.",
        undefined,
        detail
      );
    default:
      return new PasskeyError(
        "failed",
        phase === "register"
          ? "Não foi possível criar a chave de acesso neste dispositivo."
          : "Não foi possível confirmar a chave de acesso.",
        undefined,
        detail
      );
  }
}

/** Chave i18n (`*.passkey.<key>`) para cada código de erro. */
export function passkeyMessageKey(
  code: PasskeyErrorCode
):
  | "unsupported"
  | "not_setup"
  | "cancelled"
  | "timeout"
  | "origin"
  | "already_registered"
  | "unreadable"
  | "failed" {
  switch (code) {
    case "unsupported":
      return "unsupported";
    case "no_credential":
      return "not_setup";
    case "cancelled":
      return "cancelled";
    case "timeout":
      return "timeout";
    case "origin":
      return "origin";
    case "already_registered":
      return "already_registered";
    case "unreadable":
      return "unreadable";
    default:
      return "failed";
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

const DEVICE_KEY = "garimpador.passkey.device";

/**
 * Id opaco deste browser/perfil. Permite ao servidor e à UI distinguirem
 * "este dispositivo" de outro Android com o mesmo rótulo — e evitarem o
 * registo duplicado que no Android acaba em NotAllowedError/timeout.
 */
export function getPasskeyDeviceId(): string {
  if (typeof window === "undefined") return "";
  try {
    let id = window.localStorage.getItem(DEVICE_KEY);
    if (!id) {
      id =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
      id = id.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 64);
      window.localStorage.setItem(DEVICE_KEY, id);
    }
    return id;
  } catch {
    return "";
  }
}

/** Rótulo que o servidor usa (derivado do UA) para este dispositivo. */
export function passkeyDeviceLabel(platform: PasskeyPlatform): string {
  switch (platform) {
    case "android":
      return "Android";
    case "apple":
      return /ipad/i.test(typeof navigator !== "undefined" ? navigator.userAgent : "")
        ? "iPad"
        : /iphone|ipod/i.test(
            typeof navigator !== "undefined" ? navigator.userAgent : ""
          )
          ? "iPhone"
          : "Mac";
    case "windows":
      return "Windows";
    default:
      return "Dispositivo";
  }
}

/**
 * Falha antes de tocar no autenticador quando o servidor devolveu um RP ID
 * que não cobre o host atual (ex.: backend configurado para magicleads.app e
 * a página servida num preview). Mensagem clara em vez de SecurityError.
 */
function assertRpIdMatches(rpId?: string): void {
  if (typeof window === "undefined" || !rpId) return;
  const expected = String(rpId).toLowerCase();
  const host = window.location.hostname.toLowerCase();
  if (host === expected || host.endsWith(`.${expected}`)) return;
  throw new PasskeyError(
    "origin",
    "O domínio atual não corresponde ao domínio autorizado para chaves de acesso.",
    undefined,
    { browserError: `rpId "${expected}" ≠ host "${host}"` }
  );
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
    const serverCode =
      typeof data?.detail?.error === "string" ? data.detail.error : undefined;
    throw new PasskeyError("server", detail, res.status, { serverCode });
  }
  return data as T;
}

export interface PasskeyInfo {
  id: number;
  credential_id: string;
  device_label: string;
  device_id?: string | null;
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

export async function registerPasskey(
  opts: { replaceCredentialId?: string } = {}
): Promise<{ device_label: string; credential_id?: string }> {
  if (!isPasskeySupported()) {
    throw new PasskeyError("unsupported", "Este dispositivo não suporta chaves de acesso.");
  }
  const options = await post<any>(
    "/api/auth/webauthn/register/options",
    opts.replaceCredentialId
      ? { replace_credential_id: opts.replaceCredentialId }
      : {}
  );
  assertRpIdMatches(options?.rp?.id);
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
  } catch (err) {
    throw passkeyErrorFromException(err, "register");
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
    device_id: getPasskeyDeviceId(),
    response: {
      clientDataJSON: bufToB64url(response.clientDataJSON),
      attestationObject: bufToB64url(response.attestationObject),
      transports: response.getTransports?.() ?? [],
    },
    clientExtensionResults: attestation.getClientExtensionResults?.() ?? {},
  };
  const out = await post<{ device_label: string; credential_id?: string }>(
    "/api/auth/webauthn/register/verify",
    payload
  );
  setPasskeyHint(true);
  return out;
}

export async function loginWithPasskey(email?: string): Promise<AuthResponse> {
  if (!isPasskeySupported()) {
    throw new PasskeyError("unsupported", "Este dispositivo não suporta chaves de acesso.");
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
  } catch (err) {
    throw passkeyErrorFromException(err, "login");
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
