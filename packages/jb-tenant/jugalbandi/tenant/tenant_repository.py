from datetime import datetime
from typing import Annotated

import psycopg2
import pytz
from cachetools import cached
from dotenv import load_dotenv
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

    def _get_engine(self) -> psycopg2:
        engine = self._create_engine()
        self._create_schema(engine)
        return engine

    def _create_engine(self):
        engine = psycopg2.connect(
            host=self.tenant_db_settings.tenant_database_ip,
            port=self.tenant_db_settings.tenant_database_port,
            user=self.tenant_db_settings.tenant_database_username,
            password=self.tenant_db_settings.tenant_database_password,
            database=self.tenant_db_settings.tenant_database_name,
        )
        return engine

    def _create_schema(self, engine: psycopg2):
        with engine.cursor() as connection:
            connection.execute(
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

    def insert_into_tenant(
        self,
        name: str,
        email_id: str,
        phone_number: str,
        api_key: str,
        password: str,
        weekly_quota: int = 125,
    ):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                INSERT INTO tenant
                (name, email_id, phone_number, api_key, password,
                weekly_quota, balance_quota, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    name,
                    email_id,
                    phone_number,
                    api_key,
                    password,
                    weekly_quota,
                    weekly_quota,
                    datetime.now(pytz.UTC),
                ),
            )
            engine.commit()

    def insert_into_tenant_document(
        self,
        document_uuid: str,
        document_name: str,
        documents_list: list,
        prompt: str,
        welcome_message: str,
    ):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                INSERT INTO tenant_document
                (document_uuid, document_name, documents_list, prompt,
                welcome_message, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    document_uuid,
                    document_name,
                    documents_list,
                    prompt,
                    welcome_message,
                    datetime.now(pytz.UTC),
                ),
            )
            engine.commit()

    def insert_into_tenant_bot(
        self,
        tenant_api_key: str,
        document_uuid: str,
        phone_number: str,
        country_code: str,
    ):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                INSERT INTO tenant_bot
                (tenant_api_key, document_uuid, phone_number, country_code, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    tenant_api_key,
                    document_uuid,
                    phone_number,
                    country_code,
                    datetime.now(pytz.UTC),
                ),
            )
            engine.commit()

    def insert_into_tenant_reset_password(
        self,
        tenant_api_key: str,
        verification_code: str,
        expiry_time: datetime,
    ):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                INSERT INTO tenant_reset_password
                (tenant_api_key, verification_code, expiry_time)
                VALUES (%s, %s, %s)
                RETURNING *
                """,
                (tenant_api_key, verification_code, expiry_time),
            )
            result = connection.fetchone()
            engine.commit()
            return result

    def get_reset_password_details(
        self, reset_password_id: str, verification_code: str
    ):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                SELECT * FROM tenant_reset_password
                WHERE id = %s and verification_code = %s
                """,
                (reset_password_id, verification_code),
            )
            return connection.fetchone()

    def get_balance_quota_from_api_key(self, api_key: str):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                SELECT balance_quota FROM tenant
                WHERE api_key = %s
                """,
                (api_key,),
            )
            return connection.fetchone()

    def get_tenant_details(self, email_id: str):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                SELECT * FROM tenant
                WHERE email_id = %s
                """,
                (email_id,),
            )
            return connection.fetchone()

    def get_all_tenant_emails(self):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                SELECT email_id FROM tenant
                """,
            )
            email_records = connection.fetchall()
            registered_emails = [email_record[0] for email_record in email_records]
            return registered_emails

    def get_tenant_bot_details(self, api_key: str):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                SELECT * FROM tenant_bot
                WHERE tenant_api_key = %s
                """,
                (api_key,),
            )
            return connection.fetchall()

    def get_tenant_document_details(self, document_uuid: str):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                SELECT * FROM tenant_document
                WHERE document_uuid = %s
                """,
                (document_uuid,),
            )
            return connection.fetchone()

    def get_tenant_document_details_from_email_id(self, email_id: str):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                SELECT tb.document_uuid, tb.phone_number, td.document_name, tb.country_code FROM tenant t
                JOIN tenant_bot tb ON t.api_key = tb.tenant_api_key
                JOIN tenant_document td ON td.document_uuid = tb.document_uuid
                WHERE t.email_id = %s
                """,
                (email_id,),
            )
            return connection.fetchall()

    def delete_tenant_bot_details(self, document_uuid: str):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                DELETE from tenant_bot
                WHERE document_uuid = %s
                """,
                (document_uuid,),
            )
            engine.commit()

    def update_tenant_bot_details(
        self, document_uuid: str, tenant_api_key: str, updated_bot_details: list
    ):
        self.delete_tenant_bot_details(document_uuid=document_uuid)
        for updated_bot_detail in updated_bot_details:
            self.insert_into_tenant_bot(
                tenant_api_key=tenant_api_key,
                document_uuid=document_uuid,
                phone_number=updated_bot_detail["country_code"]
                + updated_bot_detail["phone_number"],
                country_code=updated_bot_detail["country_code"],
            )

    def update_tenant_password(self, api_key: str, new_password: str):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                UPDATE tenant
                SET password = %s
                WHERE api_key = %s
                """,
                (
                    new_password,
                    api_key,
                ),
            )
            engine.commit()

    def update_balance_quota(self, api_key: str, balance_quota: str):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                UPDATE tenant
                SET balance_quota = %s
                WHERE api_key = %s and balance_quota = %s
                """,
                (
                    balance_quota - 1,
                    api_key,
                    balance_quota,
                ),
            )
            engine.commit()

    def update_tenant_information(
        self, name: str, email_id: str, api_key: str, weekly_quota: int
    ):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                UPDATE tenant
                SET name = %s, email_id = %s, weekly_quota = %s, balance_quota = %s
                WHERE api_key = %s
                """,
                (
                    name,
                    email_id,
                    weekly_quota,
                    weekly_quota,
                    api_key,
                ),
            )
            engine.commit()

    def reset_balance_quota_for_tenant(self, api_key: str):
        engine = self._get_engine()
        with engine.cursor() as connection:
            connection.execute(
                """
                UPDATE tenant
                SET balance_quota = weekly_quota
                WHERE api_key = %s
                """,
                (api_key,),
            )
            engine.commit()
