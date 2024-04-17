import base64
import uuid
from typing import Annotated, List

import httpx
from auth_service import auth_app
from auth_service.password import get_hashed_password, verify_password
from fastapi import Depends, FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security.api_key import APIKey
from jugalbandi.audio_converter import convert_to_wav_with_ffmpeg
from jugalbandi.auth_token import create_access_token, create_refresh_token
from jugalbandi.core import (
    IncorrectInputException,
    InternalServerException,
    Language,
    MediaFormat,
)
from jugalbandi.core import SpeechProcessor as SpeechProcessorEnum
from jugalbandi.document_collection import DocumentRepository, DocumentSourceFile
from jugalbandi.feedback import FeedbackRepository
from jugalbandi.logging import Logger, LoggingRepository
from jugalbandi.qa import (
    LangchainIndexer,
    QAEngine,
    QueryResponse,
    TextConverter,
    rephrased_question,
)
from jugalbandi.speech_processor import (
    AzureSpeechProcessor,
    DhruvaSpeechProcessor,
    GoogleSpeechProcessor,
    SpeechProcessor,
)
from jugalbandi.tenant import TenantRepository
from jugalbandi.translator import Translator
from opentelemetry.propagate import inject

from .query_with_tfidf import querying_with_tfidf
from .server_env import init_env
from .server_helper import (
    PreResponseMiddleware,
    TenantLoginRequest,
    TenantSignupRequest,
    TokenResponse,
    User,
    generate_api_key,
    get_api_key,
    get_document_repository,
    get_feedback_repository,
    get_langchain_qa_engine,
    get_logging_repository,
    get_speech_processor,
    get_tenant_repository,
    get_text_converter,
    get_translator,
    verify_access_token,
)

# from tools.utils import PrometheusMiddleware, metrics, setting_otlp


init_env()
logger = Logger("generic_qa")

api_description = """
Jugalbandi.ai has a vector datastore that allows you to get factual Q&A over
a document set.

API is currently available in it's alpha version. We are currently gaining test
data to improve our systems and predictions. 🚀

## Factual Q&A over large documents

You will be able to:

* **Upload documents** (_implemented_).
Allows you to upload documents and create a vector space for semantic similarity search.
Basically a better search than Ctrl+F

* **Factual Q&A** (_implemented_).
Allows you to pass uuid for a document set and ask a question for factual
response over it.
"""


app = FastAPI(
    title="Jugalbandi.ai",
    description=api_description,
    version="0.0.1",
    terms_of_service="http://example.com/terms/",
    license_info={
        "name": "MIT License",
        "url": "https://www.jugalbandi.ai/",
    },
)


# APP_NAME = os.environ.get("APP_NAME", "generic_qa")
# EXPOSE_PORT = os.environ.get("EXPOSE_PORT", 8080)
# OTLP_GRPC_ENDPOINT = os.environ.get("OTLP_GRPC_ENDPOINT", "http://tempo:4317")

# # Setting metrics middleware
# app.add_middleware(PrometheusMiddleware, app_name=APP_NAME)
# app.add_route("/metrics", metrics)

# # Setting OpenTelemetry exporter
# setting_otlp(app, APP_NAME, OTLP_GRPC_ENDPOINT)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(PreResponseMiddleware)


# @app.exception_handler(Exception)
# async def custom_exception_handler(request, exception):
#     if hasattr(exception, "status_code"):
#         status_code = exception.status_code
#     else:
#         status_code = 500
#     logger.exception(str(exception))
#     return JSONResponse(
#         status_code=status_code, content={"error_message": str(exception)}
#     )


@app.get("/")
async def root():
    return {"message": "Welcome to Jugalbandi API"}


@app.get("/chain")
async def chain(response: Response):
    headers = {}
    inject(headers)  # inject trace info to header
    logger.critical(headers)

    async with httpx.AsyncClient() as client:
        await client.get(
            "http://localhost:8080/",
            headers=headers,
        )
    logger.info("Chain Finished")
    return {"path": "/chain"}


@app.get(
    "/user-logged-in", summary="Check if the user is logged in", tags=["Authentication"]
)
async def get_me(authorization: Annotated[User, Depends(verify_access_token)]):
    return {}


@app.post(
    "/upload-files",
    summary="Upload files to store the document set for querying",
    tags=["Document Store"],
)
async def upload_files(
    authorization: Annotated[User, Depends(verify_access_token)],
    api_key: Annotated[APIKey, Depends(get_api_key)],
    files: List[UploadFile],
    document_repository: Annotated[
        DocumentRepository, Depends(get_document_repository)
    ],
    text_converter: Annotated[TextConverter, Depends(get_text_converter)],
    logging_repository: Annotated[LoggingRepository, Depends(get_logging_repository)],
):
    document_collection = document_repository.new_collection()
    uuid_number = document_collection.id
    logger.info(f"UUID number: {uuid_number}")

    source_files = []
    filenames = []
    file_size = 0
    for file in files:
        source_files.append(DocumentSourceFile(file.filename, file))
        filenames.append(file.filename)
        file_size += file.size
        logger.info(f"File name: {file.filename}")

    try:
        await document_collection.init_from_files(source_files)
        async for filename in document_collection.list_files():
            await text_converter.textify(filename, document_collection)
        logger.info(f"Textification is successful for {uuid_number}")
        langchain_indexer = LangchainIndexer()
        await langchain_indexer.index(document_collection)
        logger.info(f"Langchain Indexing is successful for {uuid_number}")
    except Exception as exception:
        error_message = f"Request failed with this error: {exception}"
        logger.error(error_message)
        await logging_repository.insert_document_store_log(
            tenant_api_key=api_key,
            uuid=uuid_number,
            documents_list=filenames,
            total_file_size=file_size,
            status_code=500,
            status_message=error_message,
        )
        raise InternalServerException(error_message)

    await logging_repository.insert_document_store_log(
        tenant_api_key=api_key,
        uuid=uuid_number,
        documents_list=filenames,
        total_file_size=file_size,
        status_code=200,
        status_message="Files uploading is successful",
    )
    return {
        "uuid_number": uuid_number,
        "message": "Files uploading is successful",
    }


@app.get(
    "/query",
    summary="Query using langchain models with custom prompt",
    tags=["Q&A over Document Store"],
)
async def query(
    authorization: Annotated[User, Depends(verify_access_token)],
    api_key: Annotated[APIKey, Depends(get_api_key)],
    langchain_qa_engine: Annotated[QAEngine, Depends(get_langchain_qa_engine)],
    input_language: Language,
    output_format: MediaFormat,
    query_text: str = "",
    audio_url: str = "",
    prompt: str = Query(
        default="",
        description=(
            "Give prompts in this format. "
            "The first sentence of the prompt is necessary. "
            "The second sentence can be customized. \n\n"
            "You are a helpful assistant who helps with answering "
            "questions based on the provided information. If the "
            "information cannot be found in the text provided, "
            "you admit that you don't know"
        ),
    ),
) -> QueryResponse:

    logger.info("Querying started")
    return await langchain_qa_engine.query(
        api_key=api_key,
        query=query_text,
        speech_query_url=audio_url,
        prompt=prompt,
        input_language=input_language,
        output_format=output_format,
    )


@app.get("/rephrased-query")
async def get_rephrased_query(
    authorization: Annotated[User, Depends(verify_access_token)],
    api_key: Annotated[APIKey, Depends(get_api_key)],
    query_string: str,
):
    answer = await rephrased_question(query_string)
    logger.info(f"Query: {query_string}")
    logger.info(f"Answer: {answer}")
    return {"given_query": query_string, "rephrased_query": answer}


# Tenant endpoints
@app.get(
    "/tenant-balance-quota",
    summary="Get a tenant's balance quota using api key",
    tags=["Tenant"],
)
async def get_tenant_balance_quota(
    authorization: Annotated[User, Depends(verify_access_token)],
    api_key: str,
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    response = await tenant_repository.get_balance_quota_from_api_key(api_key)
    if response is None:
        raise IncorrectInputException("Invalid API key")
    return {"balance_quota": response}


@app.post(
    "/tenant-login",
    summary="Tenant login",
    tags=["Tenant"],
)
async def tenant_login(
    authorization: Annotated[User, Depends(verify_access_token)],
    tenant_login_request: TenantLoginRequest,
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    tenant_detail = tenant_repository.get_tenant_details(tenant_login_request.email_id)
    if tenant_detail is None:
        raise IncorrectInputException("Invalid login credentials")
    else:
        if verify_password(tenant_login_request.password, tenant_detail[5]):
            return TokenResponse(
                access_token=create_access_token(
                    data={"sub": tenant_login_request.email_id}
                ),
                token_type="bearer",
                refresh_token=create_refresh_token(
                    data={"sub": tenant_login_request.email_id}
                ),
            )
        else:
            raise IncorrectInputException("Incorrect password")


@app.post(
    "/tenant-signup",
    summary="Tenant signup",
    tags=["Tenant"],
)
async def tenant_signup(
    authorization: Annotated[User, Depends(verify_access_token)],
    tenant_signup_request: TenantSignupRequest,
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    registered_emails = tenant_repository.get_all_tenant_emails()
    if tenant_signup_request.email_id in registered_emails:
        raise Exception("Email is already registered")
    tenant_repository.insert_into_tenant(
        name=tenant_signup_request.name,
        email_id=tenant_signup_request.email_id,
        phone_number=tenant_signup_request.phone_number,
        api_key=generate_api_key(),
        password=get_hashed_password(password=tenant_signup_request.password),
    )


@app.get(
    "/tenant-details",
    summary="Get a tenant's details using Email ID",
    tags=["Tenant"],
)
async def get_tenant_details(
    authorization: Annotated[User, Depends(verify_access_token)],
    email: str,
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    response = await tenant_repository.get_tenant_details(email)
    if response is None:
        raise IncorrectInputException("Invalid Email ID")

    return {"tenant_detail": response}


@app.get(
    "/all-tenant-emails",
    summary="Get all tenant Email IDs",
    tags=["Tenant"],
)
async def get_all_tenant_emails(
    authorization: Annotated[User, Depends(verify_access_token)],
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    response = await tenant_repository.get_all_tenant_emails()
    return {"all_tenant_emails": response}


@app.post(
    "/tenant-details",
    summary="Insert tenant details",
    tags=["Tenant"],
)
async def post_tenant_details(
    authorization: Annotated[User, Depends(verify_access_token)],
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
    name: str,
    email_id: str,
    phone_number: str,
    api_key: str,
    password: str,
):
    await tenant_repository.insert_into_tenant(
        name=name,
        email_id=email_id,
        phone_number=phone_number,
        api_key=api_key,
        password=password,
    )
    return "Tenant information insertion is successful"


@app.post(
    "/tenant-document-details",
    summary="Insert tenant document details",
    tags=["Tenant"],
)
async def post_tenant_document_details(
    authorization: Annotated[User, Depends(verify_access_token)],
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
    document_uuid: str,
    document_name: str,
    documents_list: list,
    prompt: str,
    welcome_message: str,
):
    await tenant_repository.insert_into_tenant_document(
        document_uuid=document_uuid,
        document_name=document_name,
        documents_list=documents_list,
        prompt=prompt,
        welcome_message=welcome_message,
    )
    return "Tenant document information insertion is successful"


@app.post(
    "/tenant-bot-details",
    summary="Insert tenant bot details",
    tags=["Tenant"],
)
async def post_tenant_bot_details(
    authorization: Annotated[User, Depends(verify_access_token)],
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
    tenant_api_key: str,
    document_uuid: str,
    phone_number: list,
    country_code: str,
):
    await tenant_repository.insert_into_tenant_bot(
        tenant_api_key=tenant_api_key,
        document_uuid=document_uuid,
        phone_number=phone_number,
        country_code=country_code,
    )
    return "Tenant bot information insertion is successful"


@app.get(
    "/tenant-document-details",
    summary="Get a tenant's document details using Email ID",
    tags=["Tenant"],
)
async def get_tenant_document_details(
    authorization: Annotated[User, Depends(verify_access_token)],
    email: str,
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    response = await tenant_repository.get_tenant_document_details_from_email_id(email)
    if response is None:
        raise IncorrectInputException("Invalid Email ID")
    return {"tenant_document_detail": response}


@app.put(
    "/tenant-bot-details",
    summary="Update tenant bot details",
    tags=["Tenant"],
)
async def put_tenant_bot_details(
    authorization: Annotated[User, Depends(verify_access_token)],
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
    document_uuid: str,
    tenant_api_key: str,
    updated_bot_details: list,
):
    await tenant_repository.update_tenant_bot_details(
        document_uuid=document_uuid,
        tenant_api_key=tenant_api_key,
        updated_bot_details=updated_bot_details,
    )
    return "Tenant bot information updation is successful"


@app.delete(
    "/tenant-bot-details",
    summary="Delete tenant bot details",
    tags=["Tenant"],
)
async def delete_tenant_bot_details(
    authorization: Annotated[User, Depends(verify_access_token)],
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
    document_uuid: str,
):
    await tenant_repository.delete_tenant_bot_details(document_uuid=document_uuid)
    return "Tenant bot information deletion is successful"


@app.post("/response-feedback", include_in_schema=False)
async def response_feedback(
    authorization: Annotated[User, Depends(verify_access_token)],
    feedback_repository: Annotated[
        FeedbackRepository, Depends(get_feedback_repository)
    ],
    uuid_number: str,
    query: str,
    response: str,
    feedback: bool,
):
    await feedback_repository.insert_response_feedback(
        uuid_number=uuid_number,
        query=query,
        response=response,
        feedback=feedback,
    )
    return "Feedback update is successful"


@app.post(
    "/source-document",
    summary="Get source document using keyword",
    tags=["Source Document over Document Store"],
)
async def get_source_document(
    authorization: Annotated[User, Depends(verify_access_token)],
    translator: Annotated[Translator, Depends(get_translator)],
    speech_processor: Annotated[SpeechProcessor, Depends(get_speech_processor)],
    query_string: str = "",
    input_language: Language = Language.EN,
    audio_file: UploadFile = File(None),
):
    answer = await querying_with_tfidf(
        translator, speech_processor, query_string, input_language, audio_file
    )
    return answer


# Testing STT endpoint
@app.get(
    "/speech-to-text",
    summary="Testing STT endpoint",
    tags=["Language Processing"],
)
async def get_speech_to_text(
    authorization: Annotated[User, Depends(verify_access_token)],
    api_key: Annotated[APIKey, Depends(get_api_key)],
    speech_query_url: str,
    language: Language,
    speech_processor_enum: SpeechProcessorEnum,
):
    if speech_processor_enum.value == "Azure":
        speech_processor = AzureSpeechProcessor()
    elif speech_processor_enum.value == "Google":
        speech_processor = GoogleSpeechProcessor()
    else:
        speech_processor = DhruvaSpeechProcessor()

    wav_data = await convert_to_wav_with_ffmpeg(speech_query_url)
    text = await speech_processor.speech_to_text(str(uuid.uuid4()), wav_data, language)
    return {"text": text}


# Testing TTS endpoint
@app.get(
    "/text-to-speech",
    summary="Testing TTS endpoint",
    tags=["Language Processing"],
)
async def get_text_to_speech(
    authorization: Annotated[User, Depends(verify_access_token)],
    api_key: Annotated[APIKey, Depends(get_api_key)],
    text_query: str,
    language: Language,
    speech_processor_enum: SpeechProcessorEnum,
):
    if speech_processor_enum.value == "Azure":
        speech_processor = AzureSpeechProcessor()
    elif speech_processor_enum.value == "Google":
        speech_processor = GoogleSpeechProcessor()
    else:
        speech_processor = DhruvaSpeechProcessor()

    print(text_query)
    audio_bytes = await speech_processor.text_to_speech(
        str(uuid.uuid4()), text_query, language
    )
    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
    return {"audio_bytes": audio_base64}


app.mount("/auth", auth_app)
