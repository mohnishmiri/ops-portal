/**
 * Key Vault helpers: certificate search across fields, UTF-8-safe Base64,
 * and naive-UTC timestamps.
 */

import { describe, expect, it } from "vitest";
import { certificateMatchFields, decodeBase64Utf8, encodeBase64Utf8, expiryLabel, parseUtc } from "./kvShared";

const cert = {
  name: "attccdashboard-web-att-com",
  cn_name: "attccgui.web.att.com",
  san: ["attccgui.web.att.com", "horizonreports.web.att.com", "kibana.web.att.com"],
  serial_number: "BA10CEDB97F1435",
  thumbprint: "5F5819E3F9C7C4E0A1B2",
  tags: { owner: "commissions" },
};

describe("certificateMatchFields", () => {
  it("matches every searchable field by default", () => {
    expect(certificateMatchFields(cert, "horizonreports")).toEqual(["san"]);
    expect(certificateMatchFields(cert, "attccgui")).toEqual(["cn", "san"]);
    expect(certificateMatchFields(cert, "dashboard")).toEqual(["name"]);
    expect(certificateMatchFields(cert, "owner=comm")).toEqual(["tags"]);
  });

  it("compares serials and thumbprints without colons, spaces or case", () => {
    expect(certificateMatchFields(cert, "ba:10:ce:db")).toEqual(["serial"]);
    expect(certificateMatchFields(cert, "5f 58 19")).toEqual(["thumbprint"]);
  });

  it("limits the match to the chosen field", () => {
    expect(certificateMatchFields(cert, "attccgui", "cn")).toEqual(["cn"]);
    expect(certificateMatchFields(cert, "horizonreports", "name")).toEqual([]);
  });

  it("matches nothing for an empty term", () => {
    expect(certificateMatchFields(cert, "  ")).toEqual([]);
  });
});

describe("Base64 helpers", () => {
  it("round-trips non-ASCII text, which atob/btoa alone garble or reject", () => {
    const text = "pässwörd — 秘密";
    expect(decodeBase64Utf8(encodeBase64Utf8(text))).toBe(text);
  });

  it("rejects values that are not Base64 text", () => {
    expect(decodeBase64Utf8("not base64!")).toBeNull();
    expect(decodeBase64Utf8("")).toBeNull();
    // Valid Base64 of bytes that are not UTF-8 (a binary blob).
    expect(decodeBase64Utf8("/w==")).toBeNull();
  });
});

describe("parseUtc", () => {
  it("reads zone-less API timestamps as UTC, not local time", () => {
    expect(parseUtc("2026-10-07T03:00:00")?.toISOString()).toBe("2026-10-07T03:00:00.000Z");
    expect(parseUtc("2026-10-07T03:00:00+05:30")?.toISOString()).toBe("2026-10-06T21:30:00.000Z");
    expect(parseUtc("2026-10-07")?.toISOString()).toBe("2026-10-07T00:00:00.000Z");
    expect(parseUtc(null)).toBeNull();
    expect(parseUtc("garbage")).toBeNull();
  });
});

describe("expiryLabel", () => {
  it("says how long ago an item expired", () => {
    expect(expiryLabel(-3)).toBe("Expired 3d ago");
    expect(expiryLabel(12)).toBe("12d");
    expect(expiryLabel(null)).toBe("No expiry");
  });
});
