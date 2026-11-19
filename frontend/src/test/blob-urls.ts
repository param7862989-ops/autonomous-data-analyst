import { vi } from "vitest";

/**
 * Replaces URL.createObjectURL / revokeObjectURL (jsdom lacks them) and records the blobs.
 * Only the two static methods are swapped; the URL constructor, which fetch needs, is kept.
 */
export function stubBlobUrls() {
  const blobs: Blob[] = [];
  const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
  const revoke = vi.fn();
  URL.createObjectURL = (blob: Blob | MediaSource) => {
    blobs.push(blob as Blob);
    return `blob:test-${blobs.length}`;
  };
  URL.revokeObjectURL = revoke;
  return {
    blobs,
    revoke,
    restore() {
      URL.createObjectURL = original.create;
      URL.revokeObjectURL = original.revoke;
    },
  };
}
