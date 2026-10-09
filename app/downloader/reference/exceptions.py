"""Domain exceptions raised by the reference downloader."""


class ReferenceDownloaderError(RuntimeError):
    """Base class for expected reference download failures."""


class ReferenceConfigurationError(ReferenceDownloaderError):
    """Raised when required reference downloader configuration is invalid."""


class ReferenceAuthenticationError(ReferenceDownloaderError):
    """Raised when Google OAuth credentials cannot be obtained."""


class SpreadsheetDownloadError(ReferenceDownloaderError):
    """Raised when the spreadsheet cannot be read or saved."""
