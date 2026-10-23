// Tiny in-process FIFO queue (concurrency 1). Job STATE lives in the store, so the UI can poll.
// Swap for BullMQ + Redis later without touching the routes: only enqueue() changes.
const waiting = [];
let busy = false;

export function enqueue(task) {
  waiting.push(task);
  pump();
}

async function pump() {
  if (busy) return;
  busy = true;
  while (waiting.length) {
    const task = waiting.shift();
    try { await task(); } catch (e) { console.error('Job crashed:', e); }
  }
  busy = false;
}
