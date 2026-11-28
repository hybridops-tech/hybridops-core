"""Continuity contract failure classification."""


class ContractFailure(ValueError):
    def __init__(self, reason_code: str, result: str) -> None:
        super().__init__(result)
        self.reason_code = reason_code
        self.result = result


class TerminalPersistenceError(RuntimeError):
    """Raised when a claimed operation cannot publish terminal evidence."""
