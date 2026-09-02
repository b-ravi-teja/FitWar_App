"""Manual video-proof provider (Architecture §8, §20.5).

Unlike Apple Health, this provider cannot decide anything by itself: a video is not a
number, and V1 deliberately has no computer vision (§3 — no camera AI, no fake
automatic recognition). So it returns `PENDING_REVIEW` and a human decides later.

That is the whole point of the abstraction: the challenge and game systems consume a
`VerificationResult` and never learn that this one will take a reviewer and a day to
resolve, while HealthKit's resolved instantly.
"""

from datetime import datetime
from decimal import Decimal

from app.domain.verification.evidence import HealthEvidence
from app.domain.verification.metrics import METRIC_NAME
from app.domain.verification.result import (
    VerificationContext,
    VerificationResult,
    VerificationStatus,
)

SOURCE = "manual_proof"
AWAITING_REVIEW_REASON = "AWAITING_REVIEW"


class ManualProofProvider:
    """Implements `domain.verification.result.VerificationProvider`.

    `evidence.value` carries the participant's claimed figure and is recorded as
    submitted — it is never treated as proven. Only a reviewer's approval turns this
    record into a verified one, at which point the standard game pipeline runs.
    """

    source = SOURCE

    def evaluate(
        self, *, context: VerificationContext, evidence: HealthEvidence
    ) -> VerificationResult:
        return VerificationResult(
            # Never verified at submission time. Approval is a separate, human act.
            verified=False,
            source=self.source,
            metric=METRIC_NAME[context.activity],
            value=Decimal(evidence.value),
            target=context.target_value,
            status=VerificationStatus.PENDING_REVIEW,
            source_timestamp=evidence.period_end or datetime.now(tz=context.now.tzinfo),
            reason_code=AWAITING_REVIEW_REASON,
        )
