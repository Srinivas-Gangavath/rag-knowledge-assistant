export class ApiClientError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
  }
}

export class StreamAbortedError extends Error {
  constructor() {
    super("Generation stopped.");
    this.name = "StreamAbortedError";
  }
}

type ErrorBody = {
  detail?: unknown;
};

function detailFromBody(body: ErrorBody): string | null {
  if (typeof body.detail === "string" && body.detail.trim()) {
    return body.detail;
  }
  if (Array.isArray(body.detail) && body.detail.length > 0) {
    const first = body.detail[0] as { msg?: unknown };
    if (typeof first?.msg === "string" && first.msg.toLowerCase().includes("question")) {
      return "Please enter a question.";
    }
    return "Please check your request and try again.";
  }
  return null;
}

export async function errorFromResponse(response: Response): Promise<ApiClientError> {
  let message = "The request could not be completed.";
  try {
    const body = (await response.json()) as ErrorBody;
    message = detailFromBody(body) ?? message;
  } catch {
    // Keep the generic message when the body is not JSON.
  }
  return new ApiClientError(message, response.status);
}

export function userFacingError(
  error: unknown,
  context: "upload" | "chat" | "list" | "auth" | "action" = "list",
): string {
  if (error instanceof StreamAbortedError) {
    return error.message;
  }
  if (error instanceof ApiClientError) {
    if (error.status === 401) {
      return "Your session has expired. Please sign in again.";
    }
    if (error.status === 403) {
      return "Permission denied. You do not have permission to perform this action.";
    }
    if (error.status === 404) {
      return "The requested resource was not found.";
    }
    if (error.status === 409) {
      return error.message && error.message !== "The request could not be completed."
        ? error.message
        : "A conflict occurred with the current resource state.";
    }
    if (error.status === 413) {
      return "File is too large. Please choose a smaller document.";
    }
    if (error.status >= 500) {
      return context === "chat"
        ? "The assistant is temporarily unavailable. Please try again."
        : "The service is temporarily unavailable. Please try again.";
    }
    return error.message;
  }
  if (error instanceof TypeError) {
    return "Connection unavailable. Check your connection and try again.";
  }
  if (error instanceof Error && error.message) {
    if (error.message.toLowerCase().includes("failed to fetch") || error.message.toLowerCase().includes("networkerror")) {
      return "Connection unavailable. Check your connection and try again.";
    }
    return error.message;
  }
  return "Something went wrong. Please try again.";
}
