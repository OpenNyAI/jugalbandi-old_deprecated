import os
from typing import Annotated

from fastapi import Depends, FastAPI, Request, status
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from jugalbandi.document_collection import DocumentRepository
from jugalbandi.tenant import TenantRepository

from .helper import (
    BasicDocument,
    BotUserPhoneNumber,
    Document,
    DocumentsList,
    PostDocumentRequest,
    PutDocumentRequest,
    TokenValidationMiddleware,
    decode_token,
    get_document_repository,
    get_tenant_repository,
)

user_app = FastAPI()


def custom_openapi():
    if user_app.openapi_schema:
        return user_app.openapi_schema
    openapi_schema = get_openapi(
        title=user_app.title,
        version=user_app.version,
        description=user_app.description,
        routes=user_app.routes,
        servers=user_app.servers,
    )
    openapi_schema["openapi"] = "3.1.0"
    if "components" not in openapi_schema:
        openapi_schema["components"] = {}
    if "securitySchemes" not in openapi_schema["components"]:
        openapi_schema["components"]["securitySchemes"] = {}
    openapi_schema["components"]["securitySchemes"]["bearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    openapi_schema["security"] = [{"bearerAuth": []}]
    user_app.openapi_schema = openapi_schema
    return user_app.openapi_schema


user_app.openapi = custom_openapi
user_app.add_middleware(TokenValidationMiddleware)


@user_app.exception_handler(Exception)
async def custom_exception_handler(request, exception):
    if hasattr(exception, "status_code"):
        status_code = exception.status_code
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return JSONResponse(status_code=status_code, content={"message": str(exception)})


@user_app.get(
    "/documents/{document_id}/files/{file_name}",
    summary="Get a signed public file url for a given file",
    tags=["Document"],
)
async def get_signed_public_file_url(
    document_id: str,
    file_name: str,
    document_repository: Annotated[
        DocumentRepository, Depends(get_document_repository)
    ],
):
    document_collection = document_repository.get_collection(doc_id=document_id)
    signed_url = await document_collection.remote_store.signed_public_url(
        file_path=os.path.join(document_id, file_name)
    )
    return JSONResponse(
        content={"file_name": file_name, "signed_public_url": signed_url}
    )


@user_app.get(
    "/documents/{document_id}",
    summary="Get a document information from id",
    response_model=Document,
    tags=["Document"],
)
async def get_document_info(
    document_id: str,
    request: Request,
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    _, token = request.headers.get("authorization").split()
    email = decode_token(token=token)
    document_details = await tenant_repository.get_tenant_document_details(
        document_uuid=document_id
    )
    bot_details = await tenant_repository.get_tenant_bot_details_from_email_id(
        email_id=email
    )
    phone_numbers = [
        BotUserPhoneNumber(
            phone_number=bot_detail.get("phone_number"),
            country_code=bot_detail.get("country_code"),
        )
        for bot_detail in bot_details
    ]
    document = Document(
        id=document_details.get("document_uuid"),
        name=document_details.get("document_name"),
        files=document_details.get("documents_list"),
        prompt=document_details.get("prompt"),
        created_at=document_details.get("created_at"),
        updated_at=document_details.get("updated_at"),
        description=document_details.get("description"),
        welcome_message=document_details.get("welcome_message"),
        phone_numbers=phone_numbers,
    )
    return document


@user_app.get(
    "/documents",
    summary="Get documents for the current user",
    response_model=DocumentsList,
    tags=["Document"],
)
async def get_documents(
    request: Request,
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    _, token = request.headers.get("authorization").split()
    email = decode_token(token=token)
    documents_list = await tenant_repository.get_document_details_from_user_email(
        email=email
    )
    documents = [
        BasicDocument(
            id=str(document.get("document_uuid")),
            name=document.get("document_name"),
            created_at=document.get("created_at"),
            updated_at=document.get("updated_at"),
            description=document.get("description"),
        )
        for document in documents_list
    ]
    return DocumentsList(documents=documents)


@user_app.post(
    "/documents/{document_id}",
    summary="Create a new document bot",
    tags=["Document"],
)
async def post_documents(
    document_id: str,
    post_document_request: PostDocumentRequest,
    request: Request,
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    _, token = request.headers.get("authorization").split()
    email = decode_token(token=token)
    tenant_details = await tenant_repository.get_tenant_details(email_id=email)
    await tenant_repository.insert_into_tenant_document(
        document_uuid=document_id,
        document_name=post_document_request.document_name,
        documents_list=post_document_request.documents_list,
        prompt=post_document_request.prompt,
        description=post_document_request.description,
        welcome_message=post_document_request.welcome_message,
    )
    for bot_user_phone_number in post_document_request.phone_numbers:
        await tenant_repository.insert_into_tenant_bot(
            tenant_api_key=tenant_details.get("api_key"),
            document_uuid=document_id,
            phone_number=bot_user_phone_number.phone_number,
            country_code=bot_user_phone_number.country_code,
        )
    return JSONResponse(content="Posted details successfully")


@user_app.put(
    "/documents/{document_id}",
    summary="Update a document bot",
    tags=["Document"],
)
async def put_documents(
    document_id: str,
    put_document_request: PutDocumentRequest,
    request: Request,
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    _, token = request.headers.get("authorization").split()
    email = decode_token(token=token)
    tenant_details = await tenant_repository.get_tenant_details(email_id=email)
    await tenant_repository.update_tenant_document(
        document_uuid=document_id,
        prompt=put_document_request.prompt,
        description=put_document_request.description,
        welcome_message=put_document_request.welcome_message,
    )
    await tenant_repository.delete_tenant_bot(
        tenant_api_key=tenant_details.get("api_key"), document_uuid=document_id
    )
    for bot_user_phone_number in put_document_request.phone_numbers:
        await tenant_repository.insert_into_tenant_bot(
            tenant_api_key=tenant_details.get("api_key"),
            document_uuid=document_id,
            phone_number=bot_user_phone_number.phone_number,
            country_code=bot_user_phone_number.country_code,
        )
    return JSONResponse(content="Updated details successfully")
