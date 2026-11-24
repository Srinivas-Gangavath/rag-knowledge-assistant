"""Safe application errors for document upload and ingestion."""


class DocumentServiceError(Exception):
    status_code = 500
    public_message = "Document processing failed."

    def __init__(self, public_message: str | None = None) -> None:
        self.public_message = public_message or self.public_message
        super().__init__(self.public_message)


class MissingUploadError(DocumentServiceError):
    status_code = 400
    public_message = "A PDF file is required."


class EmptyFileError(DocumentServiceError):
    status_code = 400
    public_message = "The uploaded file is empty."


class UnsupportedFileTypeError(DocumentServiceError):
    status_code = 415
    public_message = "Only PDF files are supported."


class FileTooLargeError(DocumentServiceError):
    status_code = 413
    public_message = "The uploaded file exceeds the maximum allowed size."


class InvalidPdfError(DocumentServiceError):
    status_code = 400
    public_message = "The uploaded file is not a valid PDF."


class EmptyPdfError(DocumentServiceError):
    status_code = 422
    public_message = "No extractable text was found in the PDF."


class StorageError(DocumentServiceError):
    status_code = 500
    public_message = "The document could not be stored."


class DocumentNotFoundError(DocumentServiceError):
    status_code = 404
    public_message = "Document not found."


class InvalidDocumentMetadataError(DocumentServiceError):
    status_code = 422
    public_message = "Document metadata is invalid."
