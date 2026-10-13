import { describe, expect, it } from "vitest";
import { formatApiErrorDetail, formatAxiosError } from "./apiErrors";

describe("formatApiErrorDetail", () => {
  it("returns strings unchanged", () => {
    expect(formatApiErrorDetail("Vault not found")).toBe("Vault not found");
  });

  it("formats FastAPI validation error arrays", () => {
    const detail = [
      {
        type: "string_pattern_mismatch",
        loc: ["body", "secrets", 0, "name"],
        msg: "String should match pattern '^[a-zA-Z0-9-]+$'",
        input: "bad_name",
      },
    ];
    expect(formatApiErrorDetail(detail)).toContain("secrets.0.name");
    expect(formatApiErrorDetail(detail)).toContain("String should match pattern");
  });

  it("formats structured bulk validation failures", () => {
    const detail = {
      message: "Bulk validation failed",
      validation: {
        errors: [
          { row: 1, name: "bad_name", error: "Secret name must be alphanumeric and hyphens only" },
        ],
      },
    };
    expect(formatApiErrorDetail(detail)).toContain("Bulk validation failed");
    expect(formatApiErrorDetail(detail)).toContain("Row 1");
  });
});

describe("formatAxiosError", () => {
  it("extracts detail from axios-like errors", () => {
    const error = {
      response: {
        data: {
          detail: [{ loc: ["body", "vault_uri"], msg: "Field required", type: "missing" }],
        },
      },
    };
    expect(formatAxiosError(error, "fallback")).toContain("vault_uri");
  });
});

describe("formatAxiosError — failures with no detail", () => {
  it("names a server error rather than blaming the request", () => {
    const error = { response: { status: 500, data: {} } };

    expect(formatAxiosError(error, "Could not save the account.")).toBe(
      "Could not save the account. The backend returned HTTP 500 — check the backend log.",
    );
  });

  it("says when nothing answered at all", () => {
    expect(formatAxiosError(new Error("Network Error"), "Could not save the account.")).toBe(
      "Could not save the account. The backend did not respond — it may be restarting.",
    );
  });

  it("leaves a refusal the server explained alone", () => {
    const error = { response: { status: 409, data: { detail: "Already in the inventory." } } };

    expect(formatAxiosError(error, "Could not save the account.")).toBe("Already in the inventory.");
  });

  it("does not editorialise a plain 4xx with no detail", () => {
    expect(formatAxiosError({ response: { status: 403, data: {} } }, "Not allowed.")).toBe("Not allowed.");
  });
});
