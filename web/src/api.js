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

export async function send(path, { method = "POST", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token() ? { "X-Screener-Token": token() } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    const supplied = window.prompt("This instance is shared. Enter the access token:");
    if (supplied) {
      localStorage.setItem(KEY, supplied);
      return send(path, { method, body });
    }
  }
  return res;
}
