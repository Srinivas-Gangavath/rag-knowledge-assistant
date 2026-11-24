export type SseEvent = {
  event: string;
  data: string;
};

/** Split a growing SSE buffer into complete events. Incomplete tail stays in `rest`. */
export function consumeSse(buffer: string): { events: SseEvent[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const events: SseEvent[] = [];
  let rest = normalized;
  while (true) {
    const boundary = rest.indexOf("\n\n");
    if (boundary === -1) {
      break;
    }
    const raw = rest.slice(0, boundary);
    rest = rest.slice(boundary + 2);
    const parsed = parseSseBlock(raw);
    if (parsed) {
      events.push(parsed);
    }
  }
  return { events, rest };
}

function parseSseBlock(block: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) {
      continue;
    }
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (dataLines.length === 0) {
    return null;
  }
  return { event, data: dataLines.join("\n") };
}
