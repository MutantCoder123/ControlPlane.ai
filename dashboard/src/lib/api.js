'use client';

/* Talking to the demo server.
 *
 * The whole client-side contract is: read events, render events. Nothing in
 * `dashboard/` re-derives a value the backend already computed. The build
 * this replaces broke that twice - it re-found placeholders with its own
 * regex (a live D15, since CONTRACTS section 4 says only Track A owns that
 * format) and it re-implemented the commit-point buffer. Both put the UI in
 * the position of quietly disagreeing with the engine.
 */

export const API = process.env.NEXT_PUBLIC_CONTROLPLANE_API ?? 'http://127.0.0.1:8000';

export async function get(path) {
  const res = await fetch(`${API}${path}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export async function post(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `${path} -> ${res.status}`);
  return data;
}

/* Stream `POST /demo/run`, calling `onEvent` per frame.
 *
 * Frames are split on the blank line that terminates an SSE event and the
 * payload is read off the `data:` line only - deliberately NOT with a regex
 * over the whole frame. Model output contains newlines constantly, and a
 * pattern like /event: (.*)\ndata: (.*)/ silently drops every frame that
 * carries one. That failure looks like the model going quiet, which is the
 * worst thing that can happen mid-take.
 */
export async function runStream(
  { prompt, profile, team = 'support', sessionId, agentSteps, sources },
  onEvent,
  signal,
) {
  const res = await fetch(`${API}/demo/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt,
      profile,
      team,
      session_id: sessionId ?? null,
      agent_steps: agentSteps ?? 0,
      sources: sources ?? '',
    }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`run -> ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let cut;
    while ((cut = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);

      const line = frame.split('\n').find((l) => l.startsWith('data:'));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(5).trim()));
      } catch {
        /* a truncated frame is not worth killing the run over */
      }
    }
  }
}

export const usd = (n, dp = 4) =>
  n === undefined || n === null ? '--' : `$${Number(n).toFixed(dp)}`;

export const ms = (n) => (n === undefined || n === null ? '--' : `${Math.round(n)}ms`);

export const pct = (n, dp = 1) =>
  n === undefined || n === null ? '--' : `${(Number(n) * 100).toFixed(dp)}%`;
