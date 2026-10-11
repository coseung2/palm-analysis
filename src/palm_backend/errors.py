class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


class ProviderError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.message = message
        self.retryable = retryable
