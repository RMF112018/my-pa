/** Browser WebAuthn ceremony. Maps platform errors; never logs crypto material. */

import { base64UrlToBuffer, bufferToBase64Url } from "@/lib/auth/webauthn-bytes";

export type CeremonyFailure =
  | "unsupported"
  | "cancelled"
  | "failed";

export class WebAuthnBrowserError extends Error {
  constructor(readonly code: CeremonyFailure) {
    super(code);
    this.name = "WebAuthnBrowserError";
  }
}

export function webAuthnSupported(): boolean {
  return typeof window !== "undefined" && typeof window.PublicKeyCredential !== "undefined";
}

function reviveCreateOptions(options: Record<string, unknown>): CredentialCreationOptions {
  const publicKey = { ...(options as PublicKeyCredentialCreationOptions) };
  publicKey.challenge = base64UrlToBuffer(String(options.challenge));
  const user = options.user as { id: string; name: string; displayName: string };
  publicKey.user = { ...user, id: base64UrlToBuffer(user.id) };
  if (Array.isArray(options.excludeCredentials)) {
    publicKey.excludeCredentials = options.excludeCredentials.map((item) => {
      const descriptor = item as { id: string; type: PublicKeyCredentialType };
      return { ...descriptor, id: base64UrlToBuffer(descriptor.id) };
    });
  }
  return { publicKey };
}

function reviveRequestOptions(options: Record<string, unknown>): CredentialRequestOptions {
  const publicKey = { ...(options as PublicKeyCredentialRequestOptions) };
  publicKey.challenge = base64UrlToBuffer(String(options.challenge));
  if (Array.isArray(options.allowCredentials)) {
    publicKey.allowCredentials = options.allowCredentials.map((item) => {
      const descriptor = item as { id: string; type: PublicKeyCredentialType };
      return { ...descriptor, id: base64UrlToBuffer(descriptor.id) };
    });
  }
  return { publicKey };
}

function serializeCredential(credential: PublicKeyCredential): Record<string, unknown> {
  const response = credential.response;
  const body: Record<string, unknown> = {
    id: credential.id,
    rawId: bufferToBase64Url(credential.rawId),
    type: credential.type,
    response: {},
  };
  const encoded = body.response as Record<string, string>;
  if (response instanceof AuthenticatorAttestationResponse) {
    encoded.clientDataJSON = bufferToBase64Url(response.clientDataJSON);
    encoded.attestationObject = bufferToBase64Url(response.attestationObject);
  } else if (response instanceof AuthenticatorAssertionResponse) {
    encoded.clientDataJSON = bufferToBase64Url(response.clientDataJSON);
    encoded.authenticatorData = bufferToBase64Url(response.authenticatorData);
    encoded.signature = bufferToBase64Url(response.signature);
    if (response.userHandle) encoded.userHandle = bufferToBase64Url(response.userHandle);
  }
  return body;
}

function mapFailure(error: unknown): WebAuthnBrowserError {
  if (error instanceof WebAuthnBrowserError) return error;
  if (error instanceof DOMException && error.name === "NotAllowedError") {
    return new WebAuthnBrowserError("cancelled");
  }
  return new WebAuthnBrowserError("failed");
}

export async function createPasskey(options: Record<string, unknown>): Promise<Record<string, unknown>> {
  if (!webAuthnSupported() || !navigator.credentials?.create) {
    throw new WebAuthnBrowserError("unsupported");
  }
  try {
    const credential = await navigator.credentials.create(reviveCreateOptions(options));
    if (!(credential instanceof PublicKeyCredential)) throw new WebAuthnBrowserError("failed");
    return serializeCredential(credential);
  } catch (error) {
    throw mapFailure(error);
  }
}

export async function getPasskey(options: Record<string, unknown>): Promise<Record<string, unknown>> {
  if (!webAuthnSupported() || !navigator.credentials?.get) {
    throw new WebAuthnBrowserError("unsupported");
  }
  try {
    const credential = await navigator.credentials.get(reviveRequestOptions(options));
    if (!(credential instanceof PublicKeyCredential)) throw new WebAuthnBrowserError("failed");
    return serializeCredential(credential);
  } catch (error) {
    throw mapFailure(error);
  }
}
