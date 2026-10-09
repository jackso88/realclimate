"""Domain exceptions raised by the catalog processing pipeline."""


class CoreProcessingError(RuntimeError):
    """Base class for expected catalog processing failures."""


class SourceDataError(CoreProcessingError):
    """Raised when the supplier source file cannot be read or parsed."""


class CurrentCatalogError(CoreProcessingError):
    """Raised when the current product export cannot be loaded or saved."""
