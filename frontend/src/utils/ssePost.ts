/**
 * Consume a POST endpoint that returns text/event-stream.
 * EventSource only supports GET, so we use fetch + ReadableStream.
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

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() ?? '';

      for (const block of parts) {
        const lines = block.split('\n');
        let eventType = 'message';
        let dataStr = '';

        for (const line of lines) {
          if (line.startsWith('event:')) eventType = line.slice(6).trim();
          else if (line.startsWith('data:')) dataStr = line.slice(5).trim();
        }

        if (dataStr) {
          yield { event: eventType, data: JSON.parse(dataStr) as T };
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
