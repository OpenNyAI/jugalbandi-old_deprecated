import os
import random
import time
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Cookie, Depends, FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2PasswordRequestForm,
)
from jugalbandi.tenant.tenant_repository import TenantRepository
from pytz import utc

from .helper import (
    ResetPasswordRequest,
    SignupRequest,
    UpdatePasswordRequest,
    check_token_validity,
    create_token,
    decode_token,
    generate_api_key,
    get_hashed_password,
    get_tenant_repository,
    send_email,
    verify_password,
)

auth_app = FastAPI()
ACCESS_TOKEN_EXPIRY_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRY_MINUTES"))
REFRESH_TOKEN_EXPIRY_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRY_DAYS"))


@auth_app.exception_handler(Exception)
async def custom_exception_handler(request, exception):
    if hasattr(exception, "status_code"):
        status_code = exception.status_code
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return JSONResponse(status_code=status_code, content={"message": str(exception)})


@auth_app.post(
    "/login",
    summary="Enables tenants to log in to the application",
    tags=["Authentication"],
)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    tenant_detail = await tenant_repository.get_tenant_details(
        email_id=form_data.username
    )
    if tenant_detail is None:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"message": "Invalid credentials"},
        )
    if not verify_password(
        password=form_data.password, hashed_password=tenant_detail.get("password")
    ):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"message": "Incorrect password"},
        )

    access_token = create_token(
        data={"email": form_data.username, "name": tenant_detail.get("name")},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRY_MINUTES),
    )
    refresh_token = create_token(
        data={"email": form_data.username},
        expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRY_DAYS),
    )
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRY_DAYS)
    response = JSONResponse(content={"access_token": access_token})
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        path="/auth/refresh-token",
        httponly=True,
        secure=True,
        samesite="Strict",
        expires=expire.strftime("%a, %d-%b-%Y %H:%M:%S GMT"),
    )
    return response


@auth_app.post(
    "/signup",
    summary="Create new tenant for the application",
    tags=["Authentication"],
)
async def signup(
    signup_request: SignupRequest,
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    tenant_detail = tenant_repository.get_tenant_details(email_id=signup_request.email)
    if tenant_detail is not None:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": "User with this email already exists"},
        )

    hashed_password = get_hashed_password(password=signup_request.password)
    await tenant_repository.insert_into_tenant(
        name=signup_request.name,
        email_id=signup_request.email,
        phone_number=signup_request.phone_number,
        api_key=generate_api_key(),
        password=hashed_password,
    )
    return JSONResponse(
        content={"detail": "User has successfully signed up"},
    )


@auth_app.get(
    "/refresh-token",
    summary="Create new access token for the application",
    tags=["Authentication"],
)
def refresh_token(refresh_token: str = Cookie(None)):
    if not refresh_token:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"message": "Missing refresh token in the cookie"},
        )

    username = decode_token(refresh_token)
    access_token = create_token(
        data={"username": username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRY_MINUTES),
    )
    response = JSONResponse(content={"access_token": access_token})
    return response


@auth_app.post(
    "/valid-token",
    summary="Check the validity of the token",
    tags=["Authentication"],
)
def valid_token(authorization: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
    if not authorization:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"message": "Missing authorization header"},
        )
    scheme = authorization.scheme
    token = authorization.credentials
    if scheme.lower() != "bearer":
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"message": "Invalid authorization scheme"},
        )
    try:
        if not check_token_validity(token):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"message": "Token expired"},
            )
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"message": "Token expired"},
        )
    return JSONResponse(content={"detail": "Given token is valid"})


@auth_app.post(
    "/reset-password",
    summary="Reset tenant user password",
    tags=["Authentication"],
)
async def reset_password(
    reset_password_request: ResetPasswordRequest,
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    email = reset_password_request.email
    tenant_details = await tenant_repository.get_tenant_details(email_id=email)
    if tenant_details is None:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"message": "Incorrect email"},
        )
    verification_code = str(
        ((int(time.time()) * 100000) + random.randint(0, 99999)) % 1000000
    ).zfill(6)
    expiry_time = datetime.utcnow() + timedelta(minutes=15)
    reset_password_id = await tenant_repository.insert_into_tenant_reset_password(
        tenant_api_key=tenant_details.get("api_key"),
        verification_code=verification_code,
        expiry_time=expiry_time,
    )
    await send_email(
        recepient_email=email,
        recepient_name=tenant_details.get("name"),
        reset_id=reset_password_id,
        verification_code=verification_code,
    )
    return JSONResponse(content={"detail": "Verification code sent successfully"})


@auth_app.post(
    "/update-password",
    summary="Update tenant user password",
    tags=["Authentication"],
)
async def update_password(
    update_password_request: UpdatePasswordRequest,
    tenant_repository: Annotated[TenantRepository, Depends(get_tenant_repository)],
):
    reset_password_details = await tenant_repository.get_reset_password_details(
        reset_password_id=update_password_request.reset_password_id,
        verification_code=update_password_request.verification_code,
    )
    if reset_password_details is None:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"message": "Incorrect credentials"},
        )
    current_timestamp = datetime.utcnow().astimezone(utc)
    if current_timestamp > reset_password_details.get("expiry_time"):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "message": "Time has expired for the verification code. Please try again."
            },
        )

    hashed_password = get_hashed_password(password=update_password_request.new_password)
    await tenant_repository.update_tenant_password(
        api_key=reset_password_details.get("tenant_api_key"),
        new_password=hashed_password,
    )
    return JSONResponse(content={"detail": "Successfully updated tenant password"})
