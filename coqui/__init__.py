""" A Python API and CLI to use Coqui services programmatically """
__version__ = "0.0.8"

import asyncio
from collections import namedtuple
from datetime import datetime
from contextlib import asynccontextmanager
from functools import wraps
from typing import BinaryIO, List, Optional

import aiohttp
import gql.transport.exceptions as gqlexceptions
import json5
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport


class SyncReplacer(type):
    """A metaclass which adds synchronous version of coroutines.

    This metaclass finds all coroutine functions defined on a class
    and adds a synchronous version with a '_sync' suffix appended to the
    original function name.
    """

    def __new__(cls, clsname, bases, dct, **kwargs):
        new_dct = {}
        for name, orig in dct.items():
            # Make a sync version of all coroutine functions
            if asyncio.iscoroutinefunction(orig):
                meth = cls.sync_maker(name)
                asyncname = "{}_async".format(name)
                orig.__name__ = asyncname
                orig.__qualname__ = "{}.{}".format(clsname, asyncname)
                new_dct[name] = meth
                new_dct[asyncname] = orig
        dct.update(new_dct)
        return super().__new__(cls, clsname, bases, dct)

    @staticmethod
    def sync_maker(func):
        def sync_func(self, *args, **kwargs):
            meth = getattr(self, f"{func}_async")
            return asyncio.run(meth(*args, **kwargs))

        return sync_func


class AuthenticationError(Exception):
    """Raised when an authenticated operation is attempted without logging in first."""

    pass


class SynthesisError(Exception):
    """Raised when synthesis fails due to invalid creation parameters."""

    pass


class CloneVoiceError(Exception):
    """Raised when cloning a voice fails due to invalid cloning parameters."""

    pass


class RateLimitExceededError(Exception):
    """
    Raised when a request is attempted that exceeds the API rate limit established for the account.
    """

    pass


class BillingLimitExceededError(Exception):
    """
    Raised when a request is attempted that exceeds the quota allowed by the account's billing setup.
    """

    pass


class ClonedVoice(namedtuple("ClonedVoice", "id, name, samples_count, created_at")):
    id: str
    name: str
    created_at: datetime
    samples_count: int = 0

    _coqui: Optional["Coqui"]

    def __new__(cls, **kwargs):
        manager = kwargs.get("coqui", None)
        if manager:
            del kwargs["coqui"]
        # returned timestamps are always at UTC so we strip the "Z" suffix as a hacky way to parse it
        kwargs["created_at"] = datetime.fromisoformat(kwargs["created_at"][:-1])
        if not kwargs.get("samples_count", None):
            kwargs["samples_count"] = 0
        obj = super(ClonedVoice, cls).__new__(cls, **kwargs)
        if manager:
            obj._coqui = manager
        return obj

    def samples(self, coqui: Optional["Coqui"] = None):
        """Get list of synthesized samples for this voice"""
        if not self._coqui and not coqui:
            raise RuntimeError(
                "Sample object is missing a Coqui instance, so it must be passed as a parameter"
            )
        if not coqui:
            coqui = self._coqui
        assert coqui
        return coqui.list_samples(voice_id=self.id)


class Sample(namedtuple("Sample", "id, name, text, created_at, audio_url")):
    id: str
    name: str
    text: str
    created_at: datetime
    audio_url: str

    def __new__(cls, **kwargs):
        # returned timestamps are always at UTC so we strip the "Z" suffix as a hacky way to parse it
        kwargs["created_at"] = datetime.fromisoformat(kwargs["created_at"][:-1])
        return super(Sample, cls).__new__(cls, **kwargs)

    def download(self, dest_file):
        """Downloads the sample audio to a local file.

        dest_file must be either a string (file path) or an opened file with mode="wb"
        """
        if isinstance(dest_file, str):
            with open(dest_file, "wb") as fout:
                asyncio.run(Coqui.download_file(self.audio_url, fout))
        else:
            asyncio.run(Coqui.download_file(self.audio_url, dest_file))

    async def download_async(self, dest_file):
        """Downloads the sample audio to a local file.

        dest_file must be either a string (file path) or an opened file with mode="wb"
        """
        if isinstance(dest_file, str):
            with open(dest_file, "wb") as fout:
                return await Coqui.download_file(self.audio_url, fout)
        else:
            return await Coqui.download_file(self.audio_url, dest_file)


class Coqui(metaclass=SyncReplacer):
    def __init__(self, base_url=None):
        base_url = (
            "https://app.coqui.ai" if base_url is None else base_url
        )
        self._base_url = base_url
        self._api_token = None
        self._logged_in = False

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    @asynccontextmanager
    async def _get_session(self, authed=True, check=True):
        headers = None

        if authed:
            if check and not self.is_logged_in:
                raise AuthenticationError(
                    "Tried to create authenticated session without logging in."
                )

            headers = {"X-Api-Key": f"{self._api_token}"}

        transport = AIOHTTPTransport(url=f"{self._base_url}/api/v1", headers=headers)
        async with Client(
            transport=transport,
        ) as session:
            yield session

    async def login(self, token) -> bool:
        self._api_token = token
        return await self.validate_login_async()  # type: ignore

    async def validate_login(self) -> bool:
        if self._logged_in:
            return self._logged_in

        async with self._get_session(check=False) as session:
            query = gql(
                """{
                profile {
                    email
                }
            }"""
            )
            try:
                result = await session.execute(query)
                self._logged_in = True
            except gqlexceptions.TransportQueryError:
                self._logged_in = False

        return self._logged_in

    async def cloned_voices(self) -> List[ClonedVoice]:
        async with self._get_session() as session:
            query = gql(
                """{
                voices {
                    id
                    name
                    samples_count
                    created_at
                }
            }"""
            )

            result = await session.execute(query)
            return [ClonedVoice(**v, coqui=self) for v in result["voices"]]

    async def clone_voice(self, audio_file, name: str) -> ClonedVoice:
        async with self._get_session() as session:
            mutation = gql(
                """
                mutation CreateVoice($name: String!, $voice: Upload!) {
                    createVoice(name: $name, voice: $voice) {
                        errors {
                            field
                            errors
                        }
                        voice {
                            id
                            name
                            created_at
                        }
                    }
                }
            """
            )
            try:
                if isinstance(audio_file, str):
                    with open(audio_file, "rb") as fin:
                        result = await session.execute(
                            mutation,
                            variable_values={
                                "voice": fin,
                                "name": name,
                            },
                            upload_files=True,
                        )
                else:
                    result = await session.execute(
                        mutation,
                        variable_values={
                            "voice": audio_file,
                            "name": name,
                        },
                        upload_files=True,
                    )
            except gqlexceptions.TransportQueryError as e:
                raise RateLimitExceededError(e)

            result = result["createVoice"]
            if result["errors"]:
                all_errors = "\n".join(
                    f"{err['field']}: {', '.join(err['errors'])}"
                    for err in result["errors"]
                )
                raise CloneVoiceError(all_errors)
            return ClonedVoice(**result["voice"])

    async def list_samples(self, voice_id) -> List[Sample]:
        async with self._get_session() as session:
            query = gql(
                """
                query Samples($voice_id: String!) {
                    samples(voice_id: $voice_id) {
                        id
                        name
                        text
                        created_at
                        audio_url
                    }
                }
            """
            )
            result = await session.execute(
                query,
                variable_values={
                    "voice_id": voice_id,
                },
            )
            return [Sample(**s) for s in result["samples"]]

    async def synthesize(self, voice_id, text, speed, name) -> Sample:
        async with self._get_session() as session:
            mutation = gql(
                """
                mutation createSample($name: String!, $voice_id: String!, $text: String!, $speed: String!) {
                    createSample(name: $name, voice_id: $voice_id, text: $text, speed: $speed) {
                        errors {
                            field
                            errors
                        }
                        sample {
                            id
                            name
                            text
                            created_at
                            audio_url
                        }
                    }
                }
            """
            )
            query = gql(
                """
                    query Sample($id: String!) {
                        sample(id: $id) {
                            id
                            name
                            text
                            created_at
                            audio_url
                        }
                    }
            """)
            try:
                result = await session.execute(
                    mutation,
                    variable_values={
                        "voice_id": str(voice_id),
                        "text": text,
                        "speed": str(speed),
                        "name": name,
                    },
                )
            except gqlexceptions.TransportQueryError as e:
                raise RateLimitExceededError(e)
            # result = {'createSample': {'errors': None, 'sample': {'id': '62151ee3-858f-4398-935d-e48481263927', 'name': 'test from the command line', 'created_at': '2022-06-14T20:15:33.016Z', 'voice_id': 'c97d34da-a677-4219-b4b2-9ec198c948e0', 'audio_url': 'https://coqui-dev-creator-app-synthesized-samples.s3.amazonaws.com/samples/sample_GAh7vFe.wav?AWSAccessKeyId=AKIAXW7NFYT5F2KY3J4D&Signature=CCz46wpRIHrkBT9TCx4vZMVkAQE%3D&Expires=1655241335'}}}
            result = result["createSample"]
            if result["errors"]:
                all_errors = "\n".join(
                    f"{err['field']}: {', '.join(err['errors'])}"
                    for err in result["errors"]
                )
                raise SynthesisError(all_errors)

            sample = Sample(**result["sample"])
            while sample.audio_url is None:
                result = await session.execute(query, variable_values={"id": sample.id})
                sample = Sample(**result["sample"])
            return sample

    @staticmethod
    async def download_file(url, f, chunk_size=5 * 2**20):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data_to_read = True
                while data_to_read:
                    data = bytearray()
                    red = 0
                    while red < chunk_size:
                        chunk = await response.content.read(chunk_size - red)
                        if not chunk:
                            data_to_read = False
                            break
                        data.extend(chunk)
                        red += len(chunk)

                    f.write(data)
