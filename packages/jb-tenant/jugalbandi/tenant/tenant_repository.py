import operator
from datetime import datetime
from typing import Annotated, Dict

import asyncpg
import pytz
from cachetools import cached
from dotenv import load_dotenv
from jugalbandi.core.caching import aiocachedmethod
from pydantic import BaseSettings, Field


class TenantDBSettings(BaseSettings):
    tenant_database_ip: Annotated[str, Field(..., env="POSTGRES_DATABASE_IP")]
    tenant_database_port: Annotated[str, Field(..., env="POSTGRES_DATABASE_PORT")]
    tenant_database_username: Annotated[
        str, Field(..., env="POSTGRES_DATABASE_USERNAME")
    ]
    tenant_database_password: Annotated[
        str, Field(..., env="POSTGRES_DATABASE_PASSWORD")
    ]
    tenant_database_name: Annotated[str, Field(..., env="POSTGRES_DATABASE_NAME")]


@cached(cache={})
def get_tenant_db_settings():
    load_dotenv()
    return TenantDBSettings()


class TenantRepository:
    def __init__(self) -> None:
        self.tenant_db_settings = get_tenant_db_settings()
        self.engine_cache: Dict[str, asyncpg.Pool] = {}

    @aiocachedmethod(operator.attrgetter("engine_cache"))
    async def _get_engine(self) -> asyncpg.Pool:
        engine = await self._create_engine()
        await self._create_schema(engine)
        return engine

    async def _create_engine(self, timeout=5):
        engine = await asyncpg.create_pool(
            host=self.tenant_db_settings.tenant_database_ip,
            port=self.tenant_db_settings.tenant_database_port,
            user=self.tenant_db_settings.tenant_database_username,
            password=self.tenant_db_settings.tenant_database_password,
            database=self.tenant_db_settings.tenant_database_name,
            max_inactive_connection_lifetime=timeout,
        )
        return engine

    async def _create_schema(self, engine):
        async with engine.acquire() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant(
                    name TEXT,
                    email_id TEXT,
                    phone_number TEXT,
                    api_key TEXT PRIMARY KEY,
                    password TEXT,
                    weekly_quota INTEGER DEFAULT 125,
                    balance_quota INTEGER DEFAULT 125,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS tenant_document(
                    document_uuid TEXT PRIMARY KEY,
                    document_name TEXT NOT NULL,
                    documents_list TEXT[],
                    prompt TEXT NOT NULL,
                    welcome_message TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS tenant_bot(
                    tenant_api_key TEXT,
                    document_uuid TEXT,
                    country_code TEXT,
                    phone_number TEXT,
                    FOREIGN KEY (tenant_api_key) REFERENCES tenant (api_key),
                    FOREIGN KEY (document_uuid) REFERENCES tenant_document (document_uuid),
                    PRIMARY KEY (tenant_api_key, document_uuid, phone_number),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS tenant_reset_password (
                    id SERIAL PRIMARY KEY,
                    tenant_api_key TEXT,
                    verification_code TEXT,
                    expiry_time TIMESTAMPTZ NOT NULL,
                    FOREIGN KEY (tenant_api_key) REFERENCES tenant (api_key)
                );
            """
            )

    async def insert_into_tenant(
        self,
        name: str,
        email_id: str,
        phone_number: str,
        api_key: str,
        password: str,
        weekly_quota: int = 125,
    ):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO tenant
                (name, email_id, phone_number, api_key, password,
                weekly_quota, balance_quota, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                name,
                email_id,
                phone_number,
                api_key,
                password,
                weekly_quota,
                weekly_quota,
                datetime.now(pytz.UTC),
            )

    async def insert_into_tenant_document(
        self,
        document_uuid: str,
        document_name: str,
        documents_list: list,
        prompt: str,
        welcome_message: str,
    ):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO tenant_document
                (document_uuid, document_name, documents_list, prompt,
                welcome_message, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                document_uuid,
                document_name,
                documents_list,
                prompt,
                welcome_message,
                datetime.now(pytz.UTC),
            )

    async def insert_into_tenant_bot(
        self,
        tenant_api_key: str,
        document_uuid: str,
        phone_number: str,
        country_code: str,
    ):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO tenant_bot
                (tenant_api_key, document_uuid, phone_number, country_code, created_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                tenant_api_key,
                document_uuid,
                phone_number,
                country_code,
                datetime.now(pytz.UTC),
            )

    async def insert_into_tenant_reset_password(
        self,
        tenant_api_key: str,
        verification_code: str,
        expiry_time: datetime,
    ) -> int:
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            return await connection.fetchval(
                """
                INSERT INTO tenant_reset_password
                (tenant_api_key, verification_code, expiry_time)
                VALUES ($1, $2, $3)
                RETURNING id
                """,
                tenant_api_key,
                verification_code,
                expiry_time,
            )

    async def get_reset_password_details(
        self, reset_password_id: str, verification_code: str
    ):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            return await connection.fetchrow(
                """
                SELECT * FROM tenant_reset_password
                WHERE id = $1 and verification_code = $2
                """,
                int(reset_password_id),
                verification_code,
            )

    async def get_balance_quota_from_api_key(self, api_key: str):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            return await connection.fetchval(
                """
                SELECT balance_quota FROM tenant
                WHERE api_key = $1
                """,
                api_key,
            )

    async def get_tenant_details(self, email_id: str):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            return await connection.fetchrow(
                """
                SELECT * FROM tenant
                WHERE email_id = $1
                """,
                email_id,
            )

    async def get_all_tenant_emails(self):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            email_records = await connection.fetch(
                """
                SELECT email_id FROM tenant
                """,
            )
            registered_emails = [email_record[0] for email_record in email_records]
            return registered_emails

    async def get_tenant_bot_details(self, api_key: str):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            return await connection.fetch(
                """
                SELECT * FROM tenant_bot
                WHERE tenant_api_key = $1
                """,
                api_key,
            )

    async def get_tenant_document_details(self, document_uuid: str):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            return await connection.fetchrow(
                """
                SELECT * FROM tenant_document
                WHERE document_uuid = $1
                """,
                document_uuid,
            )

    async def get_tenant_document_details_from_email_id(self, email_id: str):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            return await connection.fetch(
                """
                SELECT tb.document_uuid, tb.phone_number, td.document_name, tb.country_code FROM tenant t
                JOIN tenant_bot tb ON t.api_key = tb.tenant_api_key
                JOIN tenant_document td ON td.document_uuid = tb.document_uuid
                WHERE t.email_id = $1
                """,
                email_id,
            )

    async def delete_tenant_bot_details(self, document_uuid: str):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                DELETE from tenant_bot
                WHERE document_uuid = $1
                """,
                document_uuid,
            )

    async def update_tenant_bot_details(
        self, document_uuid: str, tenant_api_key: str, updated_bot_details: list
    ):
        await self.delete_tenant_bot_details(document_uuid=document_uuid)
        for updated_bot_detail in updated_bot_details:
            await self.insert_into_tenant_bot(
                tenant_api_key=tenant_api_key,
                document_uuid=document_uuid,
                phone_number=updated_bot_detail["country_code"]
                + updated_bot_detail["phone_number"],
                country_code=updated_bot_detail["country_code"],
            )

    async def update_tenant_password(self, api_key: str, new_password: str):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                UPDATE tenant
                SET password = $1
                WHERE api_key = $2
                """,
                new_password,
                api_key,
            )

    async def update_balance_quota(self, api_key: str, balance_quota: str):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                UPDATE tenant
                SET balance_quota = $1
                WHERE api_key = $2 and balance_quota = $3
                """,
                balance_quota - 1,
                api_key,
                balance_quota,
            )

    async def update_tenant_information(
        self, name: str, email_id: str, api_key: str, weekly_quota: int
    ):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                UPDATE tenant
                SET name = $1, email_id = $2, weekly_quota = $3, balance_quota = $4
                WHERE api_key = $5
                """,
                name,
                email_id,
                weekly_quota,
                weekly_quota,
                api_key,
            )

    async def reset_balance_quota_for_tenant(self, api_key: str):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                UPDATE tenant
                SET balance_quota = weekly_quota
                WHERE api_key = $1
                """,
                api_key,
            )
