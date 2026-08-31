// Every write goes through here so the shared-instance token is attached once.
// Opening the tunnel URL with ?token=... stores it; the URL is then cleaned up.
const KEY = "screener-token";

const fromUrl = new URLSearchParams(window.location.search).get("token");
if (fromUrl) {
  localStorage.setItem(KEY, fromUrl);
  const url = new URL(window.location.href);
  url.searchParams.delete("token");
  window.history.replaceState({}, "", url);
}

export const token = () => localStorage.getItem(KEY) || "";

async function fetchWithTimeout(path, options, timeoutMs, consume = (response) => response) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal });
    return await consume(response);
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(`Request timed out after ${Math.ceil(timeoutMs / 1000)} seconds. Try again.`);
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

export async function fetchJson(path, { timeoutMs = 15_000 } = {}) {
  const { res, body } = await fetchWithTimeout(path, {}, timeoutMs, async (response) => ({
    res: response,
    body: await response.json().catch(() => null),
  }));
  if (!res.ok) {
    throw new Error(body?.detail ?? `HTTP ${res.status}: request failed`);
  }
  return body;
}

export async function send(path, { method = "POST", body, timeoutMs = 20_000 } = {}) {
  const res = await fetchWithTimeout(path, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(token() ? { "X-Screener-Token": token() } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    }, timeoutMs);
  if (res.status === 401) {
    const supplied = window.prompt("This instance is shared. Enter the access token:");
    if (supplied) {
      localStorage.setItem(KEY, supplied);
      return send(path, { method, body, timeoutMs });
    }
  }
  return res;
}
