import os
from typing import Annotated

from fastapi import Depends, FastAPI, Request, status
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from jugalbandi.document_collection import DocumentRepository
from jugalbandi.tenant import TenantRepository

from .helper import (
    Document,
    DocumentsList,
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
    "/documents/{document_id}",
    summary="Get a document from id",
    tags=["Document"],
)
async def get_document_info(
    document_id: str,
    document_repository: Annotated[
        DocumentRepository, Depends(get_document_repository)
    ],
):
    document_collection = document_repository.get_collection(doc_id=document_id)
    files = document_collection.list_files()
    file_links = []
    async for file in files:
        signed_url = await document_collection.remote_store.signed_public_url(
            file_path=file
        )
        file_links.append({"file_name": file, "signed_url": signed_url})
    return JSONResponse(content=file_links)


@user_app.get(
    "/users/documents",
    summary="Get documents for the current user",
    response_model=DocumentsList,
    tags=["Document"],
)
async def get_documents_for_given_user(
    request: Request,
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    _, token = request.headers.get("authorization").split()
    email = decode_token(token=token)
    documents_list = await tenant_repository.get_document_details_from_user_email(
        email=email
    )
    documents = [
        Document(
            id=str(document.get("document_uuid")),
            file_name=document.get("document_name"),
        )
        for document in documents_list
    ]
    return DocumentsList(documents=documents)


@user_app.get(
    "/config",
    summary="Get config for the current environment",
)
async def config():
    return JSONResponse(content={"app_state": os.environ["APP_STATE"]})
