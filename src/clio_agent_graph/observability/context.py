"""비동기 Agent 실행 경계를 넘는 W3C trace context 계약."""

import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

TRACEPARENT_PATTERN = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


class TelemetryEnvelope(BaseModel):
    """업무 payload와 분리해 전달하는 최소 trace context."""

    model_config = ConfigDict(extra="forbid")

    traceparent: str = Field(min_length=55, max_length=55)
    tracestate: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def validate_traceparent(self) -> "TelemetryEnvelope":
        if not TRACEPARENT_PATTERN.fullmatch(self.traceparent):
            raise ValueError("traceparent must use the W3C Trace Context format")
        _, trace_id, parent_id, _ = self.traceparent.split("-")
        if set(trace_id) == {"0"} or set(parent_id) == {"0"}:
            raise ValueError("traceparent identifiers must not be all zeroes")
        return self

    def carrier(self) -> dict[str, str]:
        """OpenTelemetry propagator가 읽는 HTTP carrier 형태를 반환한다."""

        carrier = {"traceparent": self.traceparent}
        if self.tracestate:
            carrier["tracestate"] = self.tracestate
        return carrier
