""" A Python API and CLI to use Coqui services programmatically """
__version__ = "0.0.10"

import asyncio
from collections import namedtuple
from contextlib import asynccontextmanager
from datetime import datetime
from functools import wraps
import inspect
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING, BinaryIO, List, Literal, NewType, Optional, Tuple

import aiohttp
import gql.transport.exceptions as gqlexceptions
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport

SampleQualityLevel = Literal["high", "average", "poor"]
SampleQualityRaw = NewType("SampleQualityRaw", float)


class _SyncReplacer(type):
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
                patched_orig_doc = dedent(orig.__doc__).replace(
                    ":group: Asynchronous API", ":group: Synchronous API"
                )
                meth.__doc__ = (
                    f"{patched_orig_doc}\n\n**Note**: This is an automatically "
                )
                meth.__signature__ = inspect.signature(orig)
                syncname = "{}_sync".format(name)
                new_dct[name] = orig
                new_dct[syncname] = meth
        dct.update(new_dct)
        return super().__new__(cls, clsname, bases, dct)

    @staticmethod
    def sync_maker(func):
        def sync_func(self, *args, **kwargs):
            meth = getattr(self, func)
            return asyncio.run(meth(*args, **kwargs))

        return sync_func


class CoquiException(Exception):
    """Base class for all exceptions raised by this module.

    :group: api
    :order: 10
    """

    pass


class AuthenticationError(CoquiException):
    """Raised when an authenticated operation is attempted without logging in first.

    :group: api
    :order: 10
    """

    pass


class SynthesisError(CoquiException):
    """Raised when synthesis fails due to invalid creation parameters.

    :group: api
    :order: 10
    """

    pass


class CloneVoiceError(CoquiException):
    """Raised when cloning a voice fails due to invalid cloning parameters.

    :group: api
    :order: 10
    """

    pass


class EstimateQualityError(CoquiException):
    """Raised when estimating quality of a sample fails due to invalid parameters.

    :group: api
    :order: 10
    """

    pass


class RateLimitExceededError(CoquiException):
    """
    Raised when a request is attempted that exceeds the API rate limit established for
    the account.

    :group: api
    :order: 10
    """

    pass


class BillingLimitExceededError(CoquiException):
    """
    Raised when a request is attempted that exceeds the quota allowed by the account's
    billing setup.

    :group: api
    :order: 10
    """

    pass


class ClonedVoice(namedtuple("ClonedVoice", "id, name, samples_count, created_at")):
    """
    Represents a cloned voice from the API

    :group: api
    :order: 2
    """

    id: str
    name: str
    created_at: datetime
    samples_count: int = 0

    _coqui: Optional["Coqui"]

    def __new__(
        cls,
        *,
        id: str,
        name: str,
        created_at: str,
        samples_count: Optional[int] = 0,
        _manager: Optional["Coqui"] = None,
    ):
        # returned timestamps are always at UTC so we strip the "Z" suffix as a hacky way to parse it
        created_at_dt = datetime.fromisoformat(created_at[:-1])
        obj = super(ClonedVoice, cls).__new__(
            cls, id=id, name=name, created_at=created_at_dt, samples_count=samples_count
        )
        obj._coqui = _manager
        return obj

    def samples(self, coqui: Optional["Coqui"] = None) -> List["Sample"]:
        """
        Return list of synthesized samples for this voice

        :param coqui: Optional Coqui instance to assign to this Sample. Only useful when
                      manually creating ClonedVoice objects.
        :return: The samples list.
        """
        if not self._coqui and not coqui:
            raise RuntimeError(
                "Sample object is missing a Coqui instance, so it must be passed "
                "as a parameter"
            )
        if not coqui:
            coqui = self._coqui
        assert coqui
        return coqui.list_samples_sync(voice_id=self.id)


class Sample(namedtuple("Sample", "id, name, text, created_at, audio_url")):
    """
    Representes a sample synthesized with the API.

    :group: api
    :order: 3
    """

    id: str
    name: str
    text: str
    created_at: datetime
    audio_url: str

    def __new__(cls, *, id: str, name: str, text: str, created_at: str, audio_url: str):
        # returned timestamps are always at UTC so we strip the "Z" suffix as a hacky way to parse it
        created_at_dt = datetime.fromisoformat(created_at[:-1])
        return super(Sample, cls).__new__(
            cls,
            id=id,
            name=name,
            text=text,
            created_at=created_at_dt,
            audio_url=audio_url,
        )

    def download_sync(self, dest_file: str | BinaryIO):
        """Downloads the sample audio to a local file.

        :param dest_file: must be either a string (file path) or an opened file with
                          mode="wb"
        """
        if isinstance(dest_file, str):
            with open(dest_file, "wb") as fout:
                Coqui.download_file_sync(self.audio_url, fout)
        else:
            Coqui.download_file_sync(self.audio_url, dest_file)

    async def download(self, dest_file: str | BinaryIO):
        """Downloads the sample audio to a local file.

        :param dest_file: must be either a string (file path) or an opened file with
                          mode="wb"
        """
        if isinstance(dest_file, str):
            with open(dest_file, "wb") as fout:
                return await Coqui.download_file(self.audio_url, fout)
        else:
            return await Coqui.download_file(self.audio_url, dest_file)


class Coqui(metaclass=_SyncReplacer):
    """
    A Coqui instance is the entry point for all API usage.

    :group: api
    :order: 1
    """

    def __init__(self, base_url: Optional[str] = None):
        """
        Create a Coqui instance.

        :param base_url: Optional override for API base URL, only useful for
                          development
        """
        base_url = "https://app.coqui.ai" if base_url is None else base_url
        self._base_url: str = base_url
        self._api_token: Optional[str] = None
        self._logged_in: bool = False

    @property
    def is_logged_in(self) -> bool:
        """
        Whether this instance has successfully authenticated with the backend.
        """
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

    if TYPE_CHECKING:

        def login_sync(self, token: str) -> bool:
            ...

    async def login(self, token: str) -> bool:
        """
        Login with the provided API token and validate it. If validation is successful,
        saves the authentication state for future usage of this instance.

        :param token: API token to use for authentication.
        :group: Asynchronous API
        """
        self._api_token = token
        return await self.validate_login()

    if TYPE_CHECKING:

        def validate_login_sync(self) -> bool:
            ...

    async def validate_login(self) -> bool:
        """
        Returns True if the saved authentication info is valid.

        :group: Asynchronous API
        """
        if self._logged_in:
            return True

        async with self._get_session(check=False) as session:
            query = gql(
                """{
                profile {
                    email
                }
            }"""
            )
            try:
                await session.execute(query)
                self._logged_in = True
            except gqlexceptions.TransportQueryError:
                self._logged_in = False

        return self._logged_in

    if TYPE_CHECKING:

        def cloned_voices_sync(self) -> List[ClonedVoice]:
            ...

    async def cloned_voices(self) -> List[ClonedVoice]:
        """
        Return the list of cloned voices for this account.

        :group: Asynchronous API
        """
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
            return [ClonedVoice(**v, _manager=self) for v in result["voices"]]

    if TYPE_CHECKING:

        def clone_voice_sync(
            self, audio_file: str | BinaryIO, name: str
        ) -> ClonedVoice:
            ...

    async def clone_voice(self, audio_file: str | BinaryIO, name: str) -> ClonedVoice:
        """
        Clone a voice from an audio file.

        :param audio_file: either a string (file path) or an opened file with
                           mode="wb"
        :param name: name of the cloned voice
        :return: A `ClonedVoice` instance for the newly created voice.
        :group: Asynchronous API
        """
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

    if TYPE_CHECKING:

        def estimate_quality_sync(
            self,
            *,
            audio_file: Optional[BinaryIO] = None,
            audio_path: Optional[Path] = None,
            audio_url: Optional[str] = None,
        ) -> Tuple[SampleQualityLevel, SampleQualityRaw]:
            ...

    async def estimate_quality(
        self,
        *,
        audio_file: Optional[BinaryIO] = None,
        audio_path: Optional[Path] = None,
        audio_url: Optional[str] = None,
    ) -> Tuple[SampleQualityLevel, SampleQualityRaw]:
        """
        Estimates quality of given audio file, return a quality level of "high",
        "average" or "poor", as well as the raw estimated sample quality numeric value.

        You must only specify one of `audio_file`, `audio_path` or `audio_url`.

        :param audio_file: open file with mode="rb"
        :param audio_path: path to audio file
        :param audio_url: URL of audio file, must be publicly accessible
        :group: Asynchronous API
        """
        if not audio_file and not audio_path and not audio_url:
            raise TypeError(
                "Must specify exactly one of: audio_file, audio_path, audio_url"
            )

        async with self._get_session() as session:
            query = gql(
                """
                query EstimateQuality($sample: Upload, $url: String) {
                    estimateQuality(sample: $sample, url: $url) {
                        quality
                        errors
                    }
                }
            """
            )
            try:
                if audio_url:
                    result = await session.execute(
                        query, variable_values={"url": audio_url}
                    )
                elif audio_path:
                    with open(audio_path, "rb") as fin:
                        result = await session.execute(
                            query,
                            variable_values={
                                "sample": fin,
                            },
                            upload_files=True,
                        )
                elif audio_file:
                    result = await session.execute(
                        query,
                        variable_values={
                            "sample": audio_file,
                        },
                        upload_files=True,
                    )
                else:
                    assert False, "unreachable!"

            except gqlexceptions.TransportQueryError as e:
                raise RateLimitExceededError(e)

            result = result["estimateQuality"]
            if result["errors"]:
                all_errors = "\n".join(result["errors"])
                raise EstimateQualityError(all_errors)

            raw: SampleQualityRaw = result["quality"]

            quality: SampleQualityLevel = "poor"
            if raw >= 2.5:
                quality = "high"
            elif raw >= 1.5:
                quality = "average"

            return quality, raw

    if TYPE_CHECKING:

        def list_samples_sync(self, voice_id: str) -> List[Sample]:
            ...

    async def list_samples(self, voice_id: str) -> List[Sample]:
        """
        Return a list of samples created from a given cloned voice.

        :param voice_id: ID of cloned voice to list samples for.
        :group: Asynchronous API
        """
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

    if TYPE_CHECKING:

        def synthesize_sync(
            self, voice_id: str, text: str, speed: float, name: str
        ) -> Sample:
            ...

    async def synthesize(
        self, voice_id: str, text: str, speed: float, name: str
    ) -> Sample:
        """
        Synthesize speech using an existing cloned voice.

        :param voice_id: ID of cloned voice to synthesize speech with.
        :param text: Text to synthesize. Maximum length is 250 characters per sample.
        :param speed: Synthesis speed. A value between 0.0 (non-inclusive) and 2.0,
                      slowest to fastest, respectively. A sample with speed=2.0 will
                      have exactly 1/2.0 (half) of the duration of the same sample
                      with speed=1.0.
        :param name: Name of synthesized sample.
        :group: Asynchronous API
        """
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
            """
            )
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
    def download_file_sync(url: str, f: BinaryIO, /, chunk_size: int = 5 * 2**20):
        """
        Convenience function to download an audio file from a URL.

        :param url: URL of file to download.
        :param f: open file with mode="wb"
        :param chunk_size: Optional chunk_size for streaming response to file.
                           Defaults to 5MB.
        :group: Helpers
        """

        asyncio.run(Coqui.download_file(url, f, chunk_size))

    @staticmethod
    async def download_file(url: str, f: BinaryIO, /, chunk_size: int = 5 * 2**20):
        """
        Convenience function to download an audio file from a URL.

        :param url: URL of file to download.
        :param f: open file with mode="wb"
        :param chunk_size: Optional chunk_size for streaming response to file.
                           Defaults to 5MB.
        :group: Helpers
        """
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
