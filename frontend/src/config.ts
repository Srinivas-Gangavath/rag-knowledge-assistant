/** V1 client-side upload limit. Server-side MAX_UPLOAD_SIZE_MB remains authoritative. */
const parsed = Number(import.meta.env.VITE_MAX_UPLOAD_SIZE_MB);
export const MAX_UPLOAD_SIZE_MB =
  Number.isFinite(parsed) && parsed > 0 ? parsed : 10;
export const MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024;
