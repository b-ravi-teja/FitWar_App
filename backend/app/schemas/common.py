from pydantic import BaseModel


class ProblemDetail(BaseModel):
    """The one error envelope shape used across the whole API (Architecture §12).

    `code` is what clients should switch on; `detail` is for logs/debugging and is
    not guaranteed-stable copy.
    """

    type: str
    title: str
    status: int
    detail: str
    code: str
