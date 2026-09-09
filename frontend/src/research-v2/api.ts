import type { ResearchEvent, ResearchRequest } from "./types";

const baseURL = (import.meta.env?.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export async function runResearchStream(
  payload: ResearchRequest,
  onEvent: (event: ResearchEvent) => void,
  options: { signal?: AbortSignal } = {}
): Promise<void> {
  const response = await fetch(`${baseURL}/research/v2/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(payload),
    signal: options.signal
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((item: { msg?: string }) => item.msg).join("；")
      : `研究请求失败（HTTP ${response.status}）`;
    throw new Error(message);
  }
  if (!response.body || !response.headers.get("content-type")?.includes("text/event-stream")) {
    throw new Error("未收到研究事件流，请检查后端地址");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal = false;
  let receivedReport = false;

  const dispatch = (frame: string) => {
    const data = frame.split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).replace(/^ /, "")).join("\n");
    if (!data) return; // SSE comments and heartbeat frames.
    let event: ResearchEvent;
    try {
      event = JSON.parse(data) as ResearchEvent;
      if (!event || typeof event.type !== "string") throw new Error();
    } catch {
      throw new Error("研究事件格式无效，请重试");
    }
    // Callback failures must propagate, not be mistaken for JSON failures.
    onEvent(event);
    if (event.type === "report_completed") receivedReport = !!event.report.trim();
    if (event.type === "error") throw new Error(event.detail);
    if (event.type === "done") {
      if (!receivedReport) throw new Error("研究已结束，但未收到有效报告");
      terminal = true;
    }
  };

  try {
    while (!terminal) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary: RegExpExecArray | null;
      while (!terminal && (boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        dispatch(frame);
      }
      if (done) {
        if (!terminal && buffer.trim()) dispatch(buffer);
        if (!terminal) throw new Error("连接提前断开，研究结果可能不完整，请重试");
        break;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
