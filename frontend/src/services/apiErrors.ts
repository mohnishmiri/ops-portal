type ValidationErrorItem = {
  loc?: unknown;
  msg?: string;
  type?: string;
};

/**
 * Convert FastAPI error `detail` payloads into user-readable strings.
 * Prevents React error #31 when detail is an array/object instead of a string.
 */
export function formatApiErrorDetail(detail: unknown, fallback = "Request failed"): string {
  if (detail == null || detail === "") return fallback;
  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const err = item as ValidationErrorItem;
          const loc = Array.isArray(err.loc) ? err.loc.filter((part) => part !== "body").join(".") : "";
          const msg = err.msg ?? "";
          return loc ? `${loc}: ${msg}` : msg;
        }
        return null;
      })
      .filter((msg): msg is string => Boolean(msg));
    return messages.length > 0 ? messages.join("; ") : fallback;
  }

  if (typeof detail === "object") {
    const obj = detail as Record<string, unknown>;
    if (typeof obj.message === "string") {
      const validation = obj.validation as { errors?: { row: number; error: string }[] } | undefined;
      if (validation?.errors?.length) {
        const preview = validation.errors
          .slice(0, 3)
          .map((err) => `Row ${err.row}: ${err.error}`)
          .join("; ");
        const suffix = validation.errors.length > 3 ? ` (+${validation.errors.length - 3} more)` : "";
        return `${obj.message}. ${preview}${suffix}`;
      }
      return obj.message;
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }

  return String(detail);
}

export function formatAxiosError(error: unknown, fallback = "Request failed"): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return formatApiErrorDetail(detail, fallback);
}
