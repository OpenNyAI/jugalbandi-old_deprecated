import hashlib
import json
import os
import random
import string
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.security.api_key import APIKeyHeader
from jose import JWTError
from jugalbandi.auth_token.token import decode_token
from jugalbandi.core.caching import aiocached
from jugalbandi.core.errors import QuotaExceededException  # , UnAuthorisedException
from jugalbandi.document_collection import (
    DocumentCollection,
    DocumentRepository,
    GoogleStorage,
    LocalStorage,
)
from jugalbandi.feedback import FeedbackRepository, QAFeedbackRepository
from jugalbandi.logging import LoggingRepository
from jugalbandi.qa import (
    GPTIndexQAEngine,
    LangchainQAEngine,
    LangchainQAModel,
    TextConverter,
)
from jugalbandi.speech_processor import (
    AzureSpeechProcessor,
    CompositeSpeechProcessor,
    DhruvaSpeechProcessor,
    GoogleSpeechProcessor,
)
from jugalbandi.tenant import TenantRepository
from jugalbandi.translator import (
    AzureTranslator,
    CompositeTranslator,
    DhruvaTranslator,
    GoogleTranslator,
    Translator,
)
from pydantic import BaseModel
from starlette.concurrency import iterate_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from .server_env import init_env

init_env()
reusable_oauth = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


class TenantSignupRequest(BaseModel):
    name: str
    email_id: str
    phone_number: str
    password: str


class TenantLoginRequest(BaseModel):
    email_id: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str


def generate_api_key(length=32):
    timestamp = str(time.time()).encode("utf-8")
    random_data = "".join(
        random.choice(string.ascii_letters + string.digits + string.punctuation)
        for _ in range(length)
    ).encode("utf-8")
    combined_data = timestamp + random_data
    api_key = hashlib.sha256(combined_data).hexdigest()[:length]
    return api_key


async def verify_access_token(token: Annotated[str, Depends(reusable_oauth)]):
    if os.getenv("ALLOW_AUTH_ACCESS") == "true" and token is None:
        return None
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        username: str = payload
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return User(username=username, email=username)


@aiocached(cache={})
async def get_document_repository() -> DocumentRepository:
    # TODO: Rename the env variable
    return DocumentRepository(
        LocalStorage(os.getenv("DOCUMENT_LOCAL_STORAGE_PATH")),
        GoogleStorage(
            os.getenv("GCP_BUCKET_NAME"), os.getenv("GCP_BUCKET_FOLDER_NAME")
        ),
    )


async def get_document_collection(
    uuid_number: str,
    document_repository: Annotated[
        DocumentRepository, Depends(get_document_repository)
    ],
) -> DocumentCollection:
    return document_repository.get_collection(uuid_number)


async def get_speech_processor():
    return CompositeSpeechProcessor(
        DhruvaSpeechProcessor(), AzureSpeechProcessor(), GoogleSpeechProcessor()
    )


async def get_translator():
    return CompositeTranslator(
        AzureTranslator(), DhruvaTranslator(), GoogleTranslator()
    )


async def get_gpt_index_qa_engine(
    document_collection: Annotated[
        DocumentCollection, Depends(get_document_collection)
    ],
    speech_processor: Annotated[DocumentCollection, Depends(get_speech_processor)],
    translator: Annotated[Translator, Depends(get_translator)],
):
    return GPTIndexQAEngine(document_collection, speech_processor, translator)


@aiocached(cache={})
async def get_feedback_repository() -> FeedbackRepository:
    return QAFeedbackRepository()


@aiocached(cache={})
async def get_logging_repository() -> LoggingRepository:
    return LoggingRepository()


@aiocached(cache={})
async def get_tenant_repository() -> TenantRepository:
    return TenantRepository()


@aiocached(cache={})
async def get_text_converter() -> TextConverter:
    return TextConverter()


async def get_langchain_qa_engine(
    document_collection: Annotated[
        DocumentCollection, Depends(get_document_collection)
    ],
    speech_processor: Annotated[DocumentCollection, Depends(get_speech_processor)],
    translator: Annotated[Translator, Depends(get_translator)],
    gpt_model: LangchainQAModel,
    logging_repository: Annotated[LoggingRepository, Depends(get_logging_repository)],
):
    return LangchainQAEngine(
        document_collection, speech_processor, translator, gpt_model, logging_repository
    )


class User(BaseModel):
    username: str
    email: str | None = None


api_key_header = APIKeyHeader(name="api_key", auto_error=False)


async def get_api_key(
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
    api_key_header: str = Security(api_key_header),
):
    if os.getenv("ALLOW_INVALID_API_KEY") != "true":
        if api_key_header:
            balance_quota = tenant_repository.get_balance_quota_from_api_key(
                api_key_header
            )
            if balance_quota is None:
                os.environ["API_KEY_STATUS"] = "false"
                # raise UnAuthorisedException("API key is invalid")
            else:
                if balance_quota[0] > 0:
                    tenant_repository.update_balance_quota(
                        api_key_header, balance_quota[0]
                    )
                else:
                    raise QuotaExceededException("You have exceeded the Quota limit")
        else:
            os.environ["API_KEY_STATUS"] = "false"
            # raise UnAuthorisedException("API Key is missing")


class PreResponseMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.endpoints = [
            "/rephrased-query",
            "/upload-files",
            "/query",
            "/speech-to-text",
            "/text-to-speech",
        ]
        self.trial_message = (
            "Your free subscription is going to end in 2 weeks. "
            "Please contact here for registration: XXX. Response: "
        )

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            if request.url.path in self.endpoints:
                if os.getenv("API_KEY_STATUS") == "false":
                    response_body = [
                        section async for section in response.body_iterator
                    ]
                    response.body_iterator = iterate_in_threadpool(iter(response_body))
                    response_dict = json.loads(response_body[0].decode())
                    if "rephrased_query" in response_dict:
                        response_dict["rephrased_query"] = (
                            self.trial_message + response_dict["rephrased_query"]
                        )
                    if "message" in response_dict:
                        response_dict["message"] = (
                            self.trial_message + response_dict["message"]
                        )
                    if "answer" in response_dict:
                        response_dict["answer"] = (
                            self.trial_message + response_dict["answer"]
                        )
                    if "text" in response_dict:
                        response_dict["text"] = (
                            self.trial_message + response_dict["text"]
                        )
                    if "audio_bytes" in response_dict:
                        response_dict["audio_bytes"] = (
                            self.trial_message + response_dict["audio_bytes"]
                        )
                    return JSONResponse(response_dict)
            return response
        except Exception as exception:
            if hasattr(exception, "status_code"):
                status_code = exception.status_code
            else:
                status_code = 500
            return JSONResponse(
                status_code=status_code, content={"error_message": str(exception)}
            )
