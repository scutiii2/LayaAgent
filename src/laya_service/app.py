"""HTTP face of the Laya models.

POST /v1/ask {"strategy", "text", "questions", ...} answers typed questions with the chosen decision
strategy (see strategies.py); callers pick a strategy, never a model.
POST /v1/validate checks a question set against the one set of rules.
POST /v1/combine mixes a caller's own voter (Garrison's cloud fallback) into the local models' answers.
GET /v1/strategies lists the strategies; GET /health reports which models are loaded."""

from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Literal

import anyio.to_thread
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from laya_service import strategies
from laya_service.answers import InputTooLong, check_questions
from laya_service.registry import Registry

_log = logging.getLogger(__name__)

StrategyName = Literal[tuple(strategies.STRATEGIES)]  # type: ignore[valid-type]
_Thresholds = dict[Literal["2", "3+"], dict[Literal["laya-english", "laya-typed"], float]]


class AskRequest(BaseModel):
    strategy: StrategyName = strategies.DEFAULT_STRATEGY
    text: str = Field(min_length=1, max_length=100_000)
    questions: dict[str, Any]
    max_len: int = Field(512, ge=16, le=8192)
    min_confidence: float | None = Field(None, gt=0, le=1)
    thresholds: _Thresholds = Field(default_factory=dict)
    prune_ratio: float = Field(strategies.PRUNE_RATIO, ge=0, lt=1)
    pair_ratio: float = Field(strategies.PAIR_RATIO, gt=0, le=1)
    trace: bool = False


class ValidateRequest(BaseModel):
    questions: Any


class CombineRequest(BaseModel):
    voters: dict[str, dict[str, Any]] = Field(min_length=1, max_length=4)
    options: list[str] | None = Field(None, min_length=2, max_length=10)
    prune_ratio: float = Field(strategies.PRUNE_RATIO, ge=0, lt=1)
    pair_ratio: float = Field(strategies.PAIR_RATIO, gt=0, le=1)


def create_app(registry: Registry | None = None, token: str | None = None, warm: bool = False) -> FastAPI:
    """`token` (LAYA_TOKEN), when set, must arrive in the X-Internal-Token header."""
    registry = registry or Registry(offline=os.environ.get("LAYA_OFFLINE") == "1")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if warm:
            await anyio.to_thread.run_sync(registry.warm)
        yield

    def authorize(x_internal_token: str = Header("")) -> None:
        if token and not hmac.compare_digest(x_internal_token, token):
            raise HTTPException(401, "Invalid token")

    app = FastAPI(title="Laya service", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "models": registry.loaded()}

    @app.get("/v1/strategies")
    def list_strategies() -> dict[str, Any]:
        return {"default": strategies.DEFAULT_STRATEGY, "strategies": list(strategies.STRATEGIES)}

    @app.post("/v1/ask", dependencies=[Depends(authorize)])
    async def ask(body: AskRequest) -> Any:
        try:
            check_questions(body.questions)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        tuning = strategies.Tuning(body.min_confidence, body.thresholds, body.prune_ratio, body.pair_ratio)

        def failure(status: int, error: ValueError) -> HTTPException:
            return HTTPException(status, {"message": str(error), "calls": getattr(error, "calls", [])})

        try:
            return await anyio.to_thread.run_sync(
                strategies.run, registry, body.strategy, body.text, body.questions, body.max_len, tuning, body.trace,
            )
        except InputTooLong as error:
            raise failure(413, error) from None
        except ValueError as error:
            raise failure(502, error) from None
        except Exception:
            _log.exception("Laya strategy failed")
            raise HTTPException(500, "Laya could not answer") from None

    @app.post("/v1/validate", dependencies=[Depends(authorize)])
    def validate(body: ValidateRequest) -> dict[str, bool]:
        """The one definition of a valid question set; callers check theirs here instead of keeping a copy."""
        try:
            check_questions(body.questions)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        return {"ok": True}

    @app.post("/v1/combine", dependencies=[Depends(authorize)])
    def combine(body: CombineRequest) -> Any:
        try:
            return strategies.combine(body.voters, body.options, body.prune_ratio, body.pair_ratio)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise HTTPException(422, "voters must be answers to one choice question over the same options") from None

    return app


def main() -> None:
    import uvicorn

    app = create_app(token=os.environ.get("LAYA_TOKEN") or None, warm=os.environ.get("LAYA_WARM", "1") == "1")
    uvicorn.run(app, host=os.environ.get("LAYA_HOST", "127.0.0.1"), port=int(os.environ.get("LAYA_PORT", "9120")))


if __name__ == "__main__":
    main()
