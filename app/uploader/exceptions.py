"""Domain exceptions raised by the uploader service."""


class UploaderError(RuntimeError):
    """Base class for expected uploader failures."""


class UploaderConfigurationError(UploaderError):
    """Raised when uploader settings are missing or invalid."""


class UploaderAuthenticationError(UploaderError):
    """Raised when the CMS login response has no supported redirect."""


class UploadFileError(UploaderError):
    """Raised when the processed file cannot be uploaded."""


class UploadResponseError(UploaderError):
    """Raised when the server response does not identify the uploaded file."""


class ImportQueueError(UploaderError):
    """Raised when the import task fails or does not complete in time."""
