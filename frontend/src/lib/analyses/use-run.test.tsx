import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, mockFetch } from "@/test/utils";

import { useRun } from "./api";

/** A controllable stand-in for the browser's EventSource. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  closed = false;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, ((event: MessageEvent<string>) => void)[]>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close() {
    this.closed = true;
  }

  // Test controls.
  open() {
    this.onopen?.();
  }

  emit(type: string, data: unknown) {
    const event = new MessageEvent(type, { data: JSON.stringify(data) });
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }

  fail() {
    this.onerror?.();
  }
}

const run = (status: string, events = 0) => ({
  id: "run-1",
  conversation_id: "conv-1",
  dataset_id: "ds-1",
  question: "q",
  status,
  stop_reason: null,
  answer_summary: null,
  created_at: "2026-11-19T10:00:00Z",
  finished_at: null,
  error_code: null,
  error_message: null,
  model: null,
  cancel_requested: false,
  started_at: null,
  events: Array.from({ length: events }, (_, i) => ({ key: `k${i}` })),
  outcome: null,
});

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useRun live updates", () => {
  it("follows an active run over the stream and does not poll while connected", async () => {
    const fetchMock = mockFetch(() => jsonResponse(run("running")));
    const { result } = renderHook(() => useRun("run-1"), { wrapper: wrapper() });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const source = FakeEventSource.instances[0];
    expect(source.url).toBe("/api/analyses/run-1/events");

    act(() => source.open());
    act(() => source.emit("run", run("running", 3)));
    // React Query hands cache updates to components asynchronously.
    await waitFor(() => expect(result.current.data?.events).toHaveLength(3));

    // No polling requests while the stream is connected.
    const before = fetchMock.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 1300));
    expect(fetchMock.mock.calls.length).toBe(before);

    act(() => source.emit("run", run("completed", 4)));
    await waitFor(() => expect(result.current.data?.status).toBe("completed"));
    expect(source.closed).toBe(true);
  });

  it("falls back to polling when the stream fails", async () => {
    let status = "running";
    const fetchMock = mockFetch(() => jsonResponse(run(status)));
    const { result } = renderHook(() => useRun("run-1"), { wrapper: wrapper() });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const source = FakeEventSource.instances[0];
    act(() => source.open());
    act(() => source.fail());
    expect(source.closed).toBe(true);

    status = "completed";
    const before = fetchMock.mock.calls.length;
    await waitFor(() => expect(result.current.data?.status).toBe("completed"), { timeout: 3000 });
    expect(fetchMock.mock.calls.length).toBeGreaterThan(before);
    // A broken stream is not reopened in a loop.
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("falls back to polling when the server ends the stream early", async () => {
    mockFetch(() => jsonResponse(run("running")));
    renderHook(() => useRun("run-1"), { wrapper: wrapper() });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const source = FakeEventSource.instances[0];
    act(() => source.open());
    act(() => source.emit("end", { reason: "too_many_streams" }));
    expect(source.closed).toBe(true);
  });

  it("opens no stream for a finished run", async () => {
    mockFetch(() => jsonResponse(run("completed")));
    const { result } = renderHook(() => useRun("run-1"), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.data?.status).toBe("completed"));
    expect(FakeEventSource.instances).toHaveLength(0);
  });
});
