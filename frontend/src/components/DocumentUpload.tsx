import { useRef, useState, type DragEvent, type FormEvent } from "react";

import { MAX_UPLOAD_SIZE_BYTES, MAX_UPLOAD_SIZE_MB } from "../config";
import { api } from "../services/api";
import { userFacingError } from "../services/errors";
import { formatFileSize } from "../utils/format";
import { Card, CardHeader, CardTitle, CardDescription, CardContent, Button, Toast } from "./ui";

type DocumentUploadProps = {
  uploading: boolean;
  onUploadingChange: (value: boolean) => void;
  onUploaded: () => Promise<void> | void;
};

function isPdfFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return file.type === "application/pdf" || name.endsWith(".pdf");
}

export function validateSelectedFile(file: File | null): string | null {
  if (!file) {
    return "Please select a PDF file.";
  }
  if (!isPdfFile(file)) {
    return "Please select a PDF file.";
  }
  if (file.size === 0) {
    return "The uploaded file is empty.";
  }
  if (file.size > MAX_UPLOAD_SIZE_BYTES) {
    return `File is too large. Maximum supported size is ${MAX_UPLOAD_SIZE_MB}MB.`;
  }
  return null;
}

export function DocumentUpload({
  uploading,
  onUploadingChange,
  onUploaded,
}: DocumentUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  function assignFile(file: File | null) {
    setError(null);
    setSuccess(null);
    if (!file) {
      setSelectedFile(null);
      return;
    }
    const validationError = validateSelectedFile(file);
    if (validationError) {
      setSelectedFile(null);
      setError(validationError);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
      return;
    }
    setSelectedFile(file);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    const file = event.dataTransfer.files[0] ?? null;
    assignFile(file);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSuccess(null);
    const validationError = validateSelectedFile(selectedFile);
    if (validationError || !selectedFile) {
      setError(validationError ?? "Please select a PDF file.");
      return;
    }

    onUploadingChange(true);
    setError(null);
    try {
      const document = await api.uploadDocument(selectedFile);
      if (document.status === "COMPLETED") {
        setSuccess(`"${document.original_filename}" uploaded and ready for retrieval.`);
      } else if (document.status === "PROCESSING") {
        setSuccess(`"${document.original_filename}" uploaded. Processing has started.`);
      } else if (document.status === "FAILED") {
        setError(`"${document.original_filename}" uploaded, but initial processing failed.`);
      } else {
        setSuccess(`"${document.original_filename}" uploaded successfully.`);
      }
      setSelectedFile(null);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
      await onUploaded();
    } catch (err) {
      setError(userFacingError(err, "upload"));
    } finally {
      onUploadingChange(false);
    }
  }

  return (
    <Card aria-labelledby="upload-heading" id="document-upload-card">
      <CardHeader className="pb-3 border-b border-slate-100">
        <div>
          <CardTitle id="upload-heading">Add Documents</CardTitle>
          <CardDescription>
            Upload PDF documents to expand your workspace knowledge base (up to {MAX_UPLOAD_SIZE_MB}MB).
          </CardDescription>
        </div>
      </CardHeader>

      <CardContent className="pt-4">
        <form onSubmit={handleSubmit}>
          {!selectedFile ? (
            <div
              className={[
                "rounded-xl border border-dashed px-4 py-6 text-center transition-colors cursor-pointer",
                dragActive
                  ? "border-brand-500 bg-brand-50/70"
                  : "border-slate-300 bg-slate-50/50 hover:bg-slate-50 hover:border-slate-400",
              ].join(" ")}
              onDragOver={(event) => {
                event.preventDefault();
                setDragActive(true);
              }}
              onDragLeave={() => setDragActive(false)}
              onDrop={handleDrop}
              onClick={() => inputRef.current?.click()}
            >
              <div className="flex justify-center mb-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white border border-slate-200 text-slate-500 shadow-xs">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75} aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                </div>
              </div>
              <label htmlFor="pdf-upload-input" className="cursor-pointer block">
                <span className="text-xs font-semibold text-slate-800">
                  Drag a PDF here, or <span className="text-brand-600 underline">browse files</span>
                </span>
                <span className="mt-0.5 block text-[11px] text-slate-500">
                  PDF format only • Maximum {MAX_UPLOAD_SIZE_MB} MB
                </span>
              </label>
              <input
                ref={inputRef}
                id="pdf-upload-input"
                className="sr-only"
                type="file"
                accept="application/pdf,.pdf"
                aria-label="PDF file"
                disabled={uploading}
                onChange={(event) => assignFile(event.target.files?.[0] ?? null)}
              />
            </div>
          ) : (
            <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3 min-w-0 pr-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600 border border-brand-200/60">
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.75} aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
                    </svg>
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-slate-900 truncate">
                      {selectedFile.name}
                    </p>
                    <p className="text-[11px] text-slate-500">
                      {formatFileSize(selectedFile.size)}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={uploading}
                    onClick={() => {
                      setSelectedFile(null);
                      if (inputRef.current) inputRef.current.value = "";
                    }}
                    className="!text-slate-500 hover:!text-rose-600"
                  >
                    Remove
                  </Button>
                  <Button
                    type="submit"
                    variant="primary"
                    size="sm"
                    isLoading={uploading}
                  >
                    {uploading ? "Uploading…" : "Upload PDF"}
                  </Button>
                </div>
              </div>
            </div>
          )}

          {error && (
            <div className="mt-3">
              <Toast type="error" message={error} onClose={() => setError(null)} />
            </div>
          )}
          {success && (
            <div className="mt-3">
              <Toast type="success" message={success} onClose={() => setSuccess(null)} />
            </div>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
