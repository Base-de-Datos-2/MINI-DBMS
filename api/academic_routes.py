"""HTTP contract for grounded academic answers on the Part 5 application."""

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from .academic_config import AcademicSettings
from .academic_rag import (
    AcademicAnswer,
    AnswerNotConfigured,
    AnswerProviderError,
    AnswerProviderTimeout,
    ask_academic,
)
from .academic_retrieval import (
    EngineUnavailable,
    InvalidEngineResponse,
    InvalidQuestion,
    normalize_question,
)
from .errors import ServiceError


class AcademicQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str


def academic_router(settings: AcademicSettings | None) -> APIRouter:
    router = APIRouter()

    @router.post("/api/rag/ask")
    async def ask(payload: AcademicQuestionRequest) -> AcademicAnswer:
        try:
            if settings is None:
                normalize_question(payload.question)
                raise AnswerNotConfigured("Configure the academic backend to generate answers.")
            return await ask_academic(payload.question, settings=settings)
        except InvalidQuestion as error:
            raise ServiceError("INVALID_REQUEST", str(error)) from None
        except EngineUnavailable:
            raise ServiceError("ENGINE_UNAVAILABLE", "The academic engine is unavailable.") from None
        except InvalidEngineResponse:
            raise ServiceError("RAG_RETRIEVAL_ERROR", "The academic engine returned invalid source data.") from None
        except AnswerNotConfigured as error:
            raise ServiceError("RAG_NOT_CONFIGURED", str(error)) from None
        except AnswerProviderTimeout:
            raise ServiceError("RAG_PROVIDER_TIMEOUT", "The answer provider timed out.") from None
        except AnswerProviderError:
            raise ServiceError("RAG_PROVIDER_ERROR", "The answer provider could not complete the request.") from None

    return router
