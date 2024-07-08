import hashlib
import os
import random
import string
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from smtplib import SMTP
from typing import List

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from jinja2 import Template
from jose import JWTError, jwt
from jugalbandi.core.caching import aiocached
from jugalbandi.document_collection import (
    DocumentRepository,
    GoogleStorage,
    LocalStorage,
)
from jugalbandi.tenant.tenant_repository import TenantRepository
from passlib.context import CryptContext
from pydantic import BaseModel, ValidationError
from starlette.middleware.base import BaseHTTPMiddleware

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
jwt_secret_key = os.environ["JWT_TOKEN_SECRET_KEY"]
jwt_algorithm = os.environ["JWT_TOKEN_ALGORITHM"]
app_base_url = os.environ["APP_BASE_URL"]
app_sub_url = os.environ["APP_SUB_URL"]
base_email = os.environ["BASE_EMAIL"]
base_email_app_password = os.environ["BASE_EMAIL_APP_PASSWORD"]


class Document(BaseModel):
    id: str
    file_name: str


class DocumentsList(BaseModel):
    documents: List[Document]


class SignupRequest(BaseModel):
    name: str
    email: str
    phone_number: str
    password: str


class ResetPasswordRequest(BaseModel):
    email: str


class UpdatePasswordRequest(BaseModel):
    reset_password_id: str
    verification_code: str
    new_password: str


class TokenValidationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.endpoints = [
            "/",
            "/user/docs",
            "/user/openapi.json",
            "/user/redoc",
            "/user/config",
        ]

    async def dispatch(self, request: Request, call_next):
        if request.url.path not in self.endpoints:
            authorization_header = request.headers.get("Authorization")
            if not authorization_header:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"message": "Missing authorization header"},
                )

            scheme, token = authorization_header.split()
            if scheme.lower() != "bearer" or not token:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={
                        "message": "Invalid authorization scheme or missing token"
                    },
                )
            try:
                if not check_token_validity(token):
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"message": "Token expired"},
                    )
            except (JWTError, ValidationError):
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"message": "Token expired"},
                )
        response = await call_next(request)
        return response


async def get_tenant_repository() -> TenantRepository:
    return TenantRepository()


@aiocached(cache={})
async def get_document_repository() -> DocumentRepository:
    return DocumentRepository(
        LocalStorage(os.environ["DOCUMENT_LOCAL_STORAGE_PATH"]),
        GoogleStorage(
            os.environ["GCP_BUCKET_NAME"], os.environ["GCP_BUCKET_FOLDER_NAME"]
        ),
    )


def generate_api_key(length=32):
    timestamp = str(time.time()).encode("utf-8")
    random_data = "".join(
        random.choice(string.ascii_letters + string.digits + string.punctuation)
        for _ in range(length)
    ).encode("utf-8")
    combined_data = timestamp + random_data
    api_key = hashlib.sha256(combined_data).hexdigest()[:length]
    return api_key


def get_hashed_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_context.verify(password, hashed_password)


def create_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire_time = datetime.utcnow() + expires_delta
    else:
        expire_time = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire_time})
    encoded_jwt_token = jwt.encode(
        claims=to_encode, key=jwt_secret_key, algorithm=jwt_algorithm
    )
    return encoded_jwt_token


def decode_token(token: str) -> str:
    try:
        payload = jwt.decode(
            token=token,
            key=jwt_secret_key,
            algorithms=[jwt_algorithm],
        )
        if datetime.fromtimestamp(payload["exp"]) < datetime.now():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload["email"]
    except (JWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def check_token_validity(token: str) -> bool:
    payload = jwt.decode(
        token=token,
        key=jwt_secret_key,
        algorithms=[jwt_algorithm],
    )
    if datetime.fromtimestamp(payload["exp"]) < datetime.now():
        return False
    else:
        return True


async def send_email(
    recepient_email: str, recepient_name: str, reset_id: str, verification_code: str
):
    verification_link = (
        f"{app_base_url}/{app_sub_url}?reset_id={reset_id}"
        f"&verification_code={verification_code}"
    )
    server = SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(base_email, base_email_app_password)
    message = EmailMessage()
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
        body {
            font-family: Arial, sans-serif;
            background-color: #f2f2f2;
        }
        .container {
            padding: 20px;
            background-color: white;
            border-radius: 10px;
            box-shadow: 0px 0px 5px 2px gray;
        }
        .header {
            color: #333;
            font-size: 24px;
            text-align: center;
        }
        .content {
            color: #1c1c1c;
            font-size: 18px;
            margin-top: 20px;
            text-align: center;
        }
        .verification-link {
            color: black;
            font-family: Roboto-Regular, Helvetica, Arial, sans-serif;
            font-size: 24px;
            text-align: center;
        }
        .signature {
            font-size: 17px;
            margin-top: 40px;
            text-align: center;
        }
        .do-not-reply {
            color: red;
            font-style: italic;
            font-size: 12px;
            margin-top: 30px;
            text-align: center;
        }
        a:link {
            color: blue;
        }
        a:visited {
            color: purple;
        }
        </style>
    </head>
    <body>
        <div class="container">
        <div class="header">Hi {{recepient_name}}!</div>
        <div class="content">
            <p>
            Forgot your password?<br />We received a request to reset the password
            for your account.<br /><br />To reset your password, please click on
            the link given below:
            </p>
        </div>
        <div class="verification-link">
            <a href={{verification_link}}>Password Reset</a>
        </div>
        <div class="content">
            <p>This password reset link is only valid for the next 15 minutes.</p>
            <p>If you didn't make this request, please ignore this email.</p>
        </div>
        <div class="signature">Thanks,<br />Jiva team.</div>
        <div class="do-not-reply">Note: Please do not reply to this mail.</div>
        </div>
    </body>
    </html>
    """
    template = Template(html_template)
    html_content = template.render(
        recepient_name=recepient_name, verification_link=verification_link
    )
    message.add_alternative(html_content, subtype="html")
    message["Subject"] = "Password Reset Code"
    message["From"] = base_email
    message["To"] = recepient_email

    server.send_message(message)
    server.quit()
