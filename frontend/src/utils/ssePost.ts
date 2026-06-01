/**
 * Consume a POST endpoint that returns text/event-stream.
 * EventSource only supports GET, so we use fetch + ReadableStream.
 *
 * SSE wire format (RFC):
 *   event: <name>\n       ← named event type
 *   data: <json>\n
 *   \n                    ← blank line terminates the event block
 *
 * sse-starlette sends CRLF line endings (\r\n), so we normalize to \n
 * immediately after decoding each chunk before any splitting.
 */
export async function* ssePost<T>(
  url: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<{ event: string; data: T }> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok || !response.body) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      // Normalize CRLF → LF so the rest of the parser only needs to handle \n.
      // sse-starlette 3.x emits \r\n line endings; splitting on \n\n would miss
      // \r\n\r\n delimiters without this step.
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');

      // SSE events are delimited by a blank line (\n\n).
      // Keep the last (possibly incomplete) fragment in the buffer.
      const parts = buffer.split('\n\n');
      buffer = parts.pop() ?? '';

      for (const block of parts) {
        if (!block.trim()) continue; // skip empty / comment-only blocks

        let eventType = 'message';
        let dataStr = '';

        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) {
            eventType = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            dataStr = line.slice(5).trim();
          }
          // id:, retry:, and comment lines (:) are intentionally ignored.
        }

        if (dataStr) {
          try {
            yield { event: eventType, data: JSON.parse(dataStr) as T };
          } catch (parseErr) {
            console.error('[ssePost] Failed to parse event data:', parseErr, '\nRaw block:', block);
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
