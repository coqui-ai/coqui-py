import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager
from functools import wraps

import aiohttp
import click
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport


def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))

    return wrapper


class PersistedConfig:
    def __init__(self, path):
        self._path = os.path.expanduser(path)
        self._value = self._read()
        os.makedirs(os.path.dirname(self._path), exist_ok=True)

    def set(self, value):
        self._value = value
        with open(self._path, "w") as fout:
            json.dump(value, fout, indent=2)

    def get(self):
        return self._value

    def _read(self):
        if not os.path.exists(self._path):
            return None

        with open(self._path) as fin:
            return json.load(fin)


AuthInfo = PersistedConfig("~/.coqui/credentials")


def is_signed_in():
    # TODO: verify token
    auth = AuthInfo.get()
    return auth and auth["token"]


@asynccontextmanager
async def get_session(authed=True):
    headers = None

    if authed:
        if not is_signed_in():
            raise RuntimeError(
                "Tried to create authenticated session without signing in."
            )

        token = AuthInfo.get()["token"]
        headers = {"Authorization": f"JWT {token}"}

    transport = AIOHTTPTransport(url="http://localhost:8001/graphql/", headers=headers)
    async with Client(
        transport=transport,
    ) as session:
        yield session


@click.group()
def main():
    pass


# TODO: implement --password-stdin
@main.command()
@click.option("--username", help="Username to login as")
@click.option("--password", help="Password", default=None)
@click.option("--password-stdin", help="Read password from stdin", is_flag=True)
@coro
async def signin(username, password, password_stdin):
    if password_stdin:
        password = sys.stdin.read().strip()

    if not password:
        raise RuntimeError("Sign in requires either --password or --password-stdin")

    async with get_session(authed=False) as session:
        mutation = gql(
            """
            mutation Login($username: String!, $password: String!) {
                tokenAuth(username: $username, password: $password) {
                    token
                    refresh_token
                    payload
                }
            }
        """
        )
        result = await session.execute(
            mutation,
            variable_values={
                "username": username,
                "password": password,
            },
        )
        AuthInfo.set(result["tokenAuth"])
        click.echo("Signed in!")


@main.group()
def tts():
    pass


@tts.command()
@coro
async def get_voices():
    async with get_session() as session:
        query = gql(
            """{
            voices {
                id
                name
                samples_count
            }
        }"""
        )

        result = await session.execute(query)
        click.echo(result)


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


@tts.command()
@click.option("--voice", help="ID of voice to synthesize", type=click.UUID)
@click.option("--text", help="Text to synthesize")
@click.option("--speed", help="Speed parameter for synthesis", default=1.0)
@click.option("--name", help="Name of sample", default=None)
@click.option(
    "--save",
    help="If specified, save the synthesized sample instead of playing it",
    default=None,
)
@coro
async def synthesize(voice, text, speed, name, save):
    async with get_session() as session:
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
                        created_at
                        voice_id
                        audio_url
                    }
                }
            }
        """
        )
        result = await session.execute(
            mutation,
            variable_values={
                "voice_id": str(voice),
                "text": text,
                "speed": str(speed),
                "name": name or text[:30],
            },
        )
        # result = {'createSample': {'errors': None, 'sample': {'id': '62151ee3-858f-4398-935d-e48481263927', 'name': 'test from the command line', 'created_at': '2022-06-14T20:15:33.016Z', 'voice_id': 'c97d34da-a677-4219-b4b2-9ec198c948e0', 'audio_url': 'https://coqui-dev-creator-app-synthesized-samples.s3.amazonaws.com/samples/sample_GAh7vFe.wav?AWSAccessKeyId=AKIAXW7NFYT5F2KY3J4D&Signature=CCz46wpRIHrkBT9TCx4vZMVkAQE%3D&Expires=1655241335'}}}
        audio_url = result["createSample"]["sample"]["audio_url"]
        with tempfile.NamedTemporaryFile("wb") as fout:
            await download_file(audio_url, fout)
            if save:
                shutil.copy(fout.name, save)
                click.echo(f"Saved synthesized sample to {save}")
            else:
                subprocess.run(
                    ["play", fout.name],
                    check=True,
                    stdin=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
