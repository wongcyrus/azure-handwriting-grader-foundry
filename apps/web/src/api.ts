export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function request<T>(
  path: string,
  token: string,
  options: { method?: string; body?: unknown; etag?: string } = {},
): Promise<{ value: T; etag: string }> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.etag) headers["If-Match"] = options.etag;
  const response = await fetch(path, {
    method: options.method || "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    cache: "no-store",
  });
  const value = await response.json();
  if (!response.ok) {
    const message =
      value.error?.message ||
      (Array.isArray(value.detail)
        ? value.detail.map((item: { msg: string }) => item.msg).join("; ")
        : "The request failed.");
    throw new ApiError(response.status, message);
  }
  return { value: value as T, etag: response.headers.get("ETag") || "" };
}
