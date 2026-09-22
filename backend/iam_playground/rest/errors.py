"""REST errors. Details are safe to return and contain no credentials."""


class RestError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(detail)
