import { describe, expect, it } from "vitest";

import { fmtBytes, fmtNum, fmtPct, humanize } from "../src/lib/format";

describe("format helpers", () => {
  it("formats bytes", () => {
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(1536)).toBe("1.5 KB");
    expect(fmtBytes(null)).toBe("—");
  });
  it("formats numbers without inventing precision", () => {
    expect(fmtNum(0.48648648, 3)).toBe("0.486");
    expect(fmtNum(2.47e-30)).toBe("2.47e-30");
    expect(fmtNum(null)).toBe("—");
    expect(fmtPct(0.05)).toBe("5.0%");
  });
  it("humanizes identifiers", () => {
    expect(humanize("evidence_of_recognized_watermark")).toBe("evidence of recognized watermark");
  });
});
