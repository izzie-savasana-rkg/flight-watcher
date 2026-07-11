/* GitHub REST API access for reading data/ and writing config files. */

const GH = {
  token: localStorage.getItem("fw_token") || "",
  repo: localStorage.getItem("fw_repo") || autoRepo(),
  shas: {},
};

function autoRepo() {
  // username.github.io/repo-name/ -> username/repo-name
  const host = location.hostname;
  const seg = location.pathname.split("/").filter(Boolean);
  if (host.endsWith(".github.io") && seg.length) {
    return `${host.split(".")[0]}/${seg[0]}`;
  }
  return "";
}

function ghHeaders(raw) {
  const h = { Accept: raw ? "application/vnd.github.raw+json" : "application/vnd.github+json" };
  if (GH.token) h.Authorization = `Bearer ${GH.token}`;
  return h;
}

async function readFile(path, fallback) {
  if (!GH.repo) {
    // local preview: site served from repo root (python -m http.server)
    try {
      const res = await fetch(`../${path}?t=${Date.now()}`);
      if (res.ok) return await res.json();
    } catch { /* not running locally */ }
    return fallback;
  }
  const url = `https://api.github.com/repos/${GH.repo}/contents/${path}?t=${Date.now()}`;
  const res = await fetch(url, { headers: ghHeaders(false) });
  if (!res.ok) {
    if (res.status !== 404) console.warn(`read ${path}: ${res.status}`);
    return fallback;
  }
  const body = await res.json();
  GH.shas[path] = body.sha;
  const text = new TextDecoder().decode(
    Uint8Array.from(atob(body.content.replace(/\n/g, "")), (c) => c.charCodeAt(0)));
  try { return JSON.parse(text); } catch { return fallback; }
}

async function writeFile(path, obj, message) {
  if (!GH.token) throw new Error("Add a GitHub token in Settings first.");
  if (!GH.shas[path]) await readFile(path, null); // fetch sha
  const content = btoa(unescape(encodeURIComponent(JSON.stringify(obj, null, 2) + "\n")));
  const res = await fetch(`https://api.github.com/repos/${GH.repo}/contents/${path}`, {
    method: "PUT",
    headers: ghHeaders(false),
    body: JSON.stringify({ message, content, sha: GH.shas[path] || undefined }),
  });
  if (!res.ok) throw new Error(`Save failed (${res.status}): ${(await res.text()).slice(0, 200)}`);
  const body = await res.json();
  GH.shas[path] = body.content.sha;
}

