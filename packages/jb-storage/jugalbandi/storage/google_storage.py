import logging
import os
from datetime import timedelta
from typing import AsyncIterator, Self

import aiohttp
from gcloud.aio.auth import Token
from gcloud.aio.storage import Storage as GoogleAioStorage  # for async operations
from google.cloud import storage  # for synchronous operations
from tenacity import (
    after_log,
    retry,
    retry_if_not_exception_type,
    wait_random_exponential,
)

from .storage import Storage

logger = logging.getLogger(__name__)


VERIFY_SSL = True

# STORAGE_EMULATOR_HOST can be used for fake gcs requests for testing
# See for example : https://github.com/fsouza/fake-gcs-server
# Also: https://github.com/talkiq/gcloud-aio/blob/master/storage/README.rst
STORAGE_EMULATOR_HOST = os.environ.get("STORAGE_EMULATOR_HOST")
if STORAGE_EMULATOR_HOST:
    VERIFY_SSL = False


@retry(
    wait=wait_random_exponential(multiplier=1, max=60),
    after=after_log(logger, logging.DEBUG),
)
async def _list_objects(client, bucket_name: str, params):
    data = await client.list_objects(
        bucket_name,
        params=params,
    )

    return data


@retry(
    wait=wait_random_exponential(multiplier=1, max=60),
    after=after_log(logger, logging.DEBUG),
)
async def _upload(client, bucket_name, object_name, content):
    status = await client.upload(bucket_name, object_name, content)
    return status


class GoogleStorage(Storage):
    def __init__(self, bucket_name: str, base_path: str):
        self.bucket_name = bucket_name
        self.base_path = base_path
        self._token_session: aiohttp.ClientSession | None = None
        self._token: Token | None = None
        self._connector: aiohttp.TCPConnector | None = None

    async def shutdown(self):
        try:
            if self._token is not None:
                await self._token.close()
            self._token = None
        except Exception:
            logger.exception("error closing token")

        try:
            if self._token_session is not None:
                await self._token_session.close()
            self._token_session = None
        except Exception:
            logger.exception("error closing token session")

        try:
            if self._connector is not None:
                await self._connector.close()
            self._connector = None
        except Exception:
            logger.exception("error closing connector")

    @property
    def connector(self) -> aiohttp.TCPConnector:
        if self._connector is None:
            self._connector = aiohttp.TCPConnector(ssl=VERIFY_SSL, limit=1000)
        return self._connector

    @property
    def token(self) -> Token:
        if self._token is None:
            self._token_session = aiohttp.ClientSession(
                connector=self.connector, connector_owner=False
            )
            self._token = Token(
                session=self._token_session,
                scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
            )
        return self._token

    async def write_file(self, file_path: str, content: bytes):
        object_name = f"{self.base_path}/{file_path}"
        async with aiohttp.ClientSession(
            connector=self.connector, connector_owner=False
        ) as session:
            async with GoogleAioStorage(session=session, token=self.token) as client:
                await _upload(client, self.bucket_name, object_name, content)

    @retry(
        wait=wait_random_exponential(multiplier=1, max=60),
        retry=retry_if_not_exception_type(FileNotFoundError),
    )
    async def read_file(self, file_path: str) -> bytes:
        object_name = f"{self.base_path}/{file_path}"
        async with aiohttp.ClientSession(
            connector=self.connector, connector_owner=False
        ) as session:
            async with GoogleAioStorage(session=session, token=self.token) as client:
                try:
                    content = await client.download(self.bucket_name, object_name)
                    return content
                except aiohttp.ClientResponseError as e:
                    if e.status == 404:
                        raise FileNotFoundError(f"file {file_path} not found")
                    else:
                        raise

    def _relative_path(self, path_suffix: str):
        if self.base_path is None or self.base_path == "":
            return path_suffix
        elif path_suffix == "":
            return self.base_path
        else:
            return f"{self.base_path}/{path_suffix}"

    def path(self, path_suffix: str):
        return f"gs://{self.bucket_name}/{self._relative_path(path_suffix)}"

    async def list_files(
        self,
        folder_path: str,
        start_offset: str = "",
        end_offset: str = "",
    ) -> AsyncIterator[str]:
        data = None
        prefix = f"{self._relative_path(folder_path)}/"

        async with aiohttp.ClientSession(
            connector=self.connector, connector_owner=False
        ) as session:
            async with GoogleAioStorage(session=session, token=self.token) as client:
                page_token = None
                max_results = 100
                params = {
                    "delimiter": "/",
                    "maxResults": str(max_results),
                    "prefix": prefix,
                }

                while True:
                    if page_token is not None:
                        params["pageToken"] = page_token

                    if end_offset != "":
                        params["startOffset"] = f"{prefix}{start_offset}"

                    if end_offset != "":
                        params["endOffset"] = f"{prefix}{end_offset}"

                    data = await _list_objects(client, self.bucket_name, params)

                    if "items" not in data or len(data["items"]) == 0:
                        return

                    for file_entry in data["items"]:
                        yield file_entry["name"][len(prefix) :]

                    if len(data["items"]) < max_results or "nextPageToken" not in data:
                        return

                    page_token = data["nextPageToken"]

    async def make_public(self, file_path: str) -> str:
        blob_name = f"{self.base_path}/{file_path}"
        storage_client = storage.Client()
        bucket = storage_client.bucket(self.bucket_name)
        blob = bucket.blob(blob_name)
        try:
            blob.make_public()
            return blob.public_url
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                raise FileNotFoundError(f"file {file_path} not found")
            else:
                raise

    async def public_url(self, file_path: str) -> str:
        # simple approach, but does not provide public url
        # see https://cloud.google.com/storage/docs/access-public-data
        # full_file_path = f"{self.base_path}/{file_path}"
        # return (
        #     "https://storage.googleapis.com/"
        #     f"{self.bucket_name}/{urllib.parse.quote(full_file_path)}"
        # )

        # synchronous method for getting public_url, throws exception if not available
        blob_name = f"{self.base_path}/{file_path}"
        storage_client = storage.Client()
        bucket = storage_client.bucket(self.bucket_name)
        blob = bucket.blob(blob_name)
        return blob.public_url

    async def signed_public_url(
        self, file_path: str, expiration_minutes: int = 15
    ) -> str:
        blob_name = f"{self.base_path}/{file_path}"
        storage_client = storage.Client()
        bucket = storage_client.bucket(self.bucket_name)
        blob = bucket.blob(blob_name)
        expiration_time = timedelta(minutes=expiration_minutes)

        # Generate the signed URL
        signed_url = blob.generate_signed_url(
            version="v4", expiration=expiration_time, method="GET"
        )
        return signed_url

    async def file_exists(self, file_path: str) -> bool:
        blob_name = f"{self.base_path}/{file_path}"
        client = storage.Client()
        bucket = client.get_bucket(self.bucket_name)
        blob = bucket.blob(blob_name)
        return blob.exists()

    def new_store(self, folder_suffix: str) -> "GoogleStorage":
        folder_path = self._relative_path(folder_suffix)
        return GoogleStorage(self.bucket_name, folder_path)

    async def list_subfolders(
        self, folder_path: str, start_offset: str = "", end_offset: str = ""
    ) -> AsyncIterator[str]:
        data = None
        prefix = f"{self._relative_path(folder_path)}/"

        async with aiohttp.ClientSession(
            connector=self.connector, connector_owner=False
        ) as session:
            async with GoogleAioStorage(session=session, token=self.token) as client:
                page_token = None
                max_results = 100
                params = {
                    "delimiter": "/",
                    "maxResults": str(max_results),
                    "startOffset": f"{prefix}{start_offset}",
                    "prefix": prefix,
                }
                while True:
                    if page_token is not None:
                        params["pageToken"] = page_token

                    if end_offset != "":
                        params["endOffset"] = f"{prefix}{end_offset}"

                    data = await _list_objects(client, self.bucket_name, params)

                    if "prefixes" not in data or len(data["prefixes"]) == 0:
                        return

                    for subfolder in data["prefixes"]:
                        yield subfolder[len(prefix) : -1]

                    if (
                        len(data["prefixes"]) < max_results
                        or "nextPageToken" not in data
                    ):
                        return

                    page_token = data["nextPageToken"]

    async def remove_file(self, file_path: str):
        full_file_path = self._relative_path(file_path)
        async with aiohttp.ClientSession(
            connector=self.connector, connector_owner=False
        ) as session:
            async with GoogleAioStorage(session=session, token=self.token) as client:
                objects = await client.list_objects(
                    self.bucket_name, params={"prefix": full_file_path}
                )
                for blob in objects["items"]:
                    await client.delete(self.bucket_name, blob["name"])

    async def list_all_files(self, folder_path: str):
        prefix = f"{self._relative_path(folder_path)}/"

        async with aiohttp.ClientSession(
            connector=self.connector, connector_owner=False
        ) as session:
            async with GoogleAioStorage(session=session, token=self.token) as client:
                page_token = None
                max_results = 100
                params = {
                    "maxResults": str(max_results),
                    "prefix": prefix,
                }

                while True:
                    if page_token is not None:
                        params["pageToken"] = page_token

                    data = await _list_objects(client, self.bucket_name, params)

                    if "items" not in data or len(data["items"]) == 0:
                        return

                    for file_entry in data["items"]:
                        yield file_entry["name"][len(prefix) :]

                    if len(data["items"]) < max_results or "nextPageToken" not in data:
                        return

                    page_token = data["nextPageToken"]

    async def copy_file(
        self, file_path: str, target_bucket: str, target_file_path: str
    ):
        full_file_path = self._relative_path(file_path)

        async with aiohttp.ClientSession(
            connector=self.connector, connector_owner=False
        ) as session:
            async with GoogleAioStorage(session=session, token=self.token) as client:
                await client.copy(
                    self.bucket_name,
                    full_file_path,
                    target_bucket,
                    new_name=target_file_path,
                )

    @classmethod
    def new_gcs_file_adapter(cls, base_path: str) -> Self:
        new_base_path = base_path[5:]
        path_elements = new_base_path.split("/", 1)
        bucket_name = path_elements[0]
        folder_path = ""
        if len(path_elements) > 1:
            folder_path = path_elements[1]
        return cls(bucket_name, folder_path)
