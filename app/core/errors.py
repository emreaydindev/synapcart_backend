from fastapi import status


class CodedError(Exception):
    """An HTTP error whose body is {"detail": <string>, "code": <machine code>}.

    Clients branch on `code` (e.g. the app opens the paywall on 402
    `quota_exceeded` / `premium_required` / `history_locked`).
    """

    def __init__(self, status_code: int, detail: str, code: str):
        self.status_code = status_code
        self.detail = detail
        self.code = code


def quota_exceeded(limit: int) -> CodedError:
    return CodedError(
        status.HTTP_402_PAYMENT_REQUIRED,
        f"Bugünkü {limit} mesaj hakkını kullandın. Premium ile daha fazla mesaj gönderebilir ya da yarın tekrar deneyebilirsin.",
        "quota_exceeded",
    )


def premium_required() -> CodedError:
    return CodedError(
        status.HTTP_402_PAYMENT_REQUIRED,
        "Bu özellik Premium üyelere özeldir.",
        "premium_required",
    )


def history_locked() -> CodedError:
    return CodedError(
        status.HTTP_402_PAYMENT_REQUIRED,
        "Bu eski sohbet ücretsiz planda kilitli. Tüm geçmişine erişmek için Premium'a geç.",
        "history_locked",
    )
