// Talking to the KOII server: JSON commands, state, and the live event stream.

export class CommandError extends Error {
  constructor(message, issues) {
    super(message);
    this.issues = issues || [];
  }
}

export async function command(name, body = {}) {
  const response = await fetch(`/api/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Koii": "1" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!data.ok) throw new CommandError(data.error, data.issues);
  return data.result;
}

export async function getState() {
  const response = await fetch("/api/state", { cache: "no-store" });
  const data = await response.json();
  if (!data.ok) throw new CommandError(data.error);
  return data.result;
}

/** Stream server events. The browser reconnects by itself; onStatus(true/false) tracks it. */
export function listen(onEvent, onStatus) {
  const source = new EventSource("/api/events");
  source.onopen = () => onStatus(true);
  source.onerror = () => onStatus(false);
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data));
    } catch (error) {
      console.error("bad event", error, message.data);
    }
  };
  return source;
}

export function midiUrl(what) {
  return `/api/midi?what=${encodeURIComponent(what)}`;
}
