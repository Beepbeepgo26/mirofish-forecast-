"""Project-wide exceptions."""


class MissingMarketDataError(RuntimeError):
    """A required market price was unavailable.

    Never substitute a placeholder price. Callers must surface this to the user
    rather than returning a forecast built on fabricated data.
    """

    def __init__(self, instrument: str, field: str, context: str) -> None:
        self.instrument = instrument
        self.field = field
        self.context = context
        super().__init__(
            f"Live price unavailable for {instrument}: {field} missing in {context}. "
            "Forecast refused rather than estimated."
        )


def require_price(value: float | None, instrument: str, field: str, context: str) -> float:
    """Return ``value`` if it is a usable price, else raise MissingMarketDataError.

    ``None`` and non-positive values are both treated as missing.
    """
    if value is None or value <= 0:
        raise MissingMarketDataError(instrument, field, context)
    return value
