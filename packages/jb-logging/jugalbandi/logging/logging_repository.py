from datetime import datetime
import operator
from typing import Dict
import asyncpg
import pytz
from jugalbandi.core.caching import aiocachedmethod
from .logging_settings import get_logging_settings


class LoggingRepository():
    def __init__(self) -> None:
        self.engine_cache: Dict[str, asyncpg.Pool] = {}
        self.logging_settings = get_logging_settings()

    @aiocachedmethod(operator.attrgetter("engine_cache"))
    async def _get_engine(self) -> asyncpg.Pool:
        engine = await self._create_engine()
        await self._create_schema(engine)
        return engine

    async def _create_engine(self, timeout=5):
        engine = await asyncpg.create_pool(
            host=self.logging_settings.logging_database_ip,
            port=self.logging_settings.logging_database_port,
            user=self.logging_settings.logging_database_username,
            password=self.logging_settings.logging_database_password,
            database=self.logging_settings.logging_database_name,
            max_inactive_connection_lifetime=timeout,
        )
        return engine

    async def _create_schema(self, engine):
        async with engine.acquire() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jb_users(
                    id SERIAL PRIMARY KEY,
                    first_name TEXT,
                    last_name TEXT,
                    phone_number BIGINT UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS jb_app(
                    id SERIAL PRIMARY KEY,
                    name TEXT,
                    phone_number BIGINT UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS jb_document_store_log(
                    user_id INTEGER,
                    app_id INTEGER,
                    uuid TEXT PRIMARY KEY,
                    documents_list TEXT[],
                    total_file_size FLOAT,
                    status_code INTEGER,
                    status_message TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    FOREIGN key (user_id) REFERENCES jb_users(id),
                    FOREIGN key (app_id) REFERENCES jb_app(id)
                );
                CREATE TABLE IF NOT EXISTS jb_qa_log(
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    app_id INTEGER,
                    document_uuid TEXT,
                    input_language TEXT DEFAULT 'en',
                    query TEXT,
                    audio_input_link TEXT,
                    response TEXT,
                    audio_output_link TEXT,
                    retrieval_k_value INTEGER,
                    retrieved_chunks TEXT[],
                    prompt TEXT,
                    gpt_model_name TEXT,
                    status_code INTEGER,
                    status_message TEXT,
                    response_time INTEGER,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    FOREIGN KEY (user_id) REFERENCES jb_users(id),
                    FOREIGN KEY (app_id) REFERENCES jb_app(id),
                    FOREIGN KEY (document_uuid) REFERENCES jb_document_store_log(uuid)
                );
                CREATE TABLE IF NOT EXISTS jb_stt_log(
                    id SERIAL PRIMARY KEY,
                    qa_log_id INTEGER,
                    audio_input_link TEXT,
                    model_name TEXT,
                    text TEXT,
                    status_code INTEGER,
                    status_message TEXT,
                    response_time INTEGER,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    FOREIGN KEY (qa_log_id) REFERENCES jb_qa_log(id)
                );
                CREATE TABLE IF NOT EXISTS jb_tts_log(
                    id SERIAL PRIMARY KEY,
                    qa_log_id INTEGER,
                    text TEXT,
                    model_name TEXT,
                    audio_output_link TEXT,
                    status_code INTEGER,
                    status_message TEXT,
                    response_time INTEGER,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    FOREIGN KEY (qa_log_id) REFERENCES jb_qa_log(id)
                );
                CREATE TABLE IF NOT EXISTS jb_translator_log(
                    id SERIAL PRIMARY KEY,
                    qa_log_id INTEGER,
                    text TEXT,
                    input_language TEXT,
                    output_language TEXT,
                    model_name TEXT,
                    translated_text TEXT,
                    status_code INTEGER,
                    status_message TEXT,
                    response_time INTEGER,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    FOREIGN KEY (qa_log_id) REFERENCES jb_qa_log(id)
                );
                CREATE TABLE IF NOT EXISTS jb_chat_history(
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    app_id INTEGER,
                    document_uuid TEXT,
                    message_owner TEXT NOT NULL,
                    preferred_language TEXT NOT NULL,
                    audio_url TEXT,
                    message TEXT,
                    message_in_english TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    FOREIGN key (user_id) REFERENCES jb_users(id),
                    FOREIGN KEY (app_id) REFERENCES jb_app(id),
                    FOREIGN KEY (document_uuid) REFERENCES jb_document_store_log(uuid)
                );

                CREATE INDEX IF NOT EXISTS jb_users_phone_number_idx ON jb_users(phone_number);
                CREATE INDEX IF NOT EXISTS jb_users_first_name_idx ON jb_users(first_name);
                CREATE INDEX IF NOT EXISTS jb_app_phone_number_idx ON jb_app(phone_number);
                CREATE INDEX IF NOT EXISTS jb_document_store_log_uuid_idx ON jb_document_store_log(uuid);
                CREATE INDEX IF NOT EXISTS jb_qa_log_user_id_idx ON jb_qa_log(user_id);
                CREATE INDEX IF NOT EXISTS jb_qa_log_app_id_idx ON jb_qa_log(app_id);
                CREATE INDEX IF NOT EXISTS jb_qa_log_document_uuid_idx ON jb_qa_log(document_uuid);
                CREATE INDEX IF NOT EXISTS jb_stt_log_qa_log_id_idx ON jb_stt_log(qa_log_id);
                CREATE INDEX IF NOT EXISTS jb_tts_log_qa_log_id_idx ON jb_tts_log(qa_log_id);
                CREATE INDEX IF NOT EXISTS jb_translator_log_qa_log_id_idx ON jb_translator_log(qa_log_id);
                CREATE INDEX IF NOT EXISTS jb_chat_history_user_id_idx ON jb_chat_history(user_id);
                CREATE INDEX IF NOT EXISTS jb_chat_history_app_id_idx ON jb_chat_history(app_id);
                CREATE INDEX IF NOT EXISTS jb_chat_history_document_uuid_idx ON jb_chat_history(document_uuid);
            """
            )

    async def insert_users_information(self, first_name: str,
                                       last_name: str,
                                       phone_number: int):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO jb_users
                (first_name, last_name, phone_number, created_at)
                VALUES ($1, $2, $3, $4)
                """,
                first_name,
                last_name,
                phone_number,
                datetime.now(pytz.UTC),
            )

    async def insert_app_information(self, name: str,
                                     phone_number: int):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO jb_app
                (name, phone_number, created_at)
                VALUES ($1, $2, $3)
                """,
                name,
                phone_number,
                datetime.now(pytz.UTC),
            )

    async def insert_document_store_log(self, user_id: int, app_id: int, uuid: str,
                                        documents_list: list, total_file_size: int,
                                        status_code: int, status_message: str):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO jb_document_store_log
                (user_id, app_id, uuid, documents_list,
                total_file_size, status_code, status_message, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                user_id,
                app_id,
                uuid,
                documents_list,
                total_file_size,
                status_code,
                status_message,
                datetime.now(pytz.UTC),
            )

    async def insert_qa_log(self, user_id: int, app_id: int, document_uuid: str, input_language: str,
                            query: str, audio_input_link: str, response: str, audio_output_link: str,
                            retrieval_k_value: int, retrieved_chunks: list, prompt: str, gpt_model_name: str,
                            status_code: int, status_message: str, response_time: int):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO jb_qa_log
                (user_id, app_id, document_uuid, input_language,
                query, audio_input_link, response, audio_output_link,
                retrieval_k_value, retrieved_chunks, prompt, gpt_model_name,
                status_code, status_message, response_time, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                $12, $13, $14, $15, $16)
                """,
                user_id,
                app_id,
                document_uuid,
                input_language,
                query,
                audio_input_link,
                response,
                audio_output_link,
                retrieval_k_value,
                retrieved_chunks,
                prompt,
                gpt_model_name,
                status_code,
                status_message,
                response_time,
                datetime.now(pytz.UTC),
            )

    async def insert_stt_log(self, qa_log_id: int, audio_input_link: str,
                             model_name: str, text: str, status_code: int,
                             status_message: str, response_time: int):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO jb_stt_log
                (qa_log_id, audio_input_link, model_name,
                text, status_code, status_message,
                response_time, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                qa_log_id,
                audio_input_link,
                model_name,
                text,
                status_code,
                status_message,
                response_time,
                datetime.now(pytz.UTC),
            )

    async def insert_tts_log(self, qa_log_id: int, text: str,
                             model_name: str, audio_output_link: str, status_code: int,
                             status_message: str, response_time: int):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO jb_tts_log
                (qa_log_id, text, model_name,
                audio_output_link, status_code, status_message,
                response_time, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                qa_log_id,
                text,
                model_name,
                audio_output_link,
                status_code,
                status_message,
                response_time,
                datetime.now(pytz.UTC),
            )

    async def insert_translator_log(self, qa_log_id: int, text: str, input_language: str,
                                    output_language: str, model_name: str, translated_text: str,
                                    status_code: int, status_message: str, response_time: int):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO jb_translator_log
                (qa_log_id, text, input_language, output_language,
                model_name, translated_text, status_code,
                status_message, response_time, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                qa_log_id,
                text,
                input_language,
                output_language,
                model_name,
                translated_text,
                status_code,
                status_message,
                response_time,
                datetime.now(pytz.UTC),
            )

    async def insert_chat_history(self, user_id: int, app_id: int, document_uuid: str,
                                  message_owner: str, preferred_language: str, audio_url: str,
                                  message: str, message_in_english: str):
        engine = await self._get_engine()
        async with engine.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO jb_chat_history
                (user_id, app_id, document_uuid,
                message_owner, preferred_language, audio_url,
                message, message_in_english, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                user_id,
                app_id,
                document_uuid,
                message_owner,
                preferred_language,
                audio_url,
                message,
                message_in_english,
                datetime.now(pytz.UTC),
            )
