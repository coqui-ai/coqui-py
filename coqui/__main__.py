import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from functools import wraps

import click
from . import Coqui


def coroutine(f):
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


BASE_URL = None
AuthInfo = PersistedConfig("~/.coqui/credentials")


@click.group()
@click.option("--base-url", default=None)
def main(base_url):
    global BASE_URL
    BASE_URL = base_url


# TODO: remove, keep token only
@main.command()
@click.option("--username", help="Username to login as")
@click.option("--password", help="Password", default=None)
@click.option("--password-stdin", help="Read password from stdin", is_flag=True)
@coroutine
async def login(username, password, password_stdin):
    if password_stdin:
        password = sys.stdin.read().strip()

    if not password:
        raise RuntimeError("Sign in requires either --password or --password-stdin")

    coqui = Coqui(base_url=BASE_URL)
    try:
        token = await coqui.password_login_async(username, password)
        AuthInfo.set(token)
        click.echo("Logged in!")
    except:
        click.echo("Error: Invalid credentials!")


@main.command()
@click.option("--token", help="API token to sign in with")
@coroutine
async def token_login(token):
    coqui = Coqui(base_url=BASE_URL)
    if await coqui.login_async(token):
        AuthInfo.set(token)
        click.echo("Logged in!")
    else:
        click.echo("Error: Invalid token!")


@main.group()
def tts():
    pass


@tts.command()
@coroutine
async def get_voices():
    coqui = Coqui(base_url=BASE_URL)
    await coqui.login_async(AuthInfo.get())
    voices = await coqui.cloned_voices_async()
    click.echo(voices)


@tts.command()
@click.option("--audio_file", help="Path of reference audio file to clone voice from")
@click.option("--name", help="Name of cloned voice")
@coroutine
async def clone_voice(audio_file, name):
    coqui = Coqui(base_url=BASE_URL)
    await coqui.login_async(AuthInfo.get())
    with open(audio_file, "rb") as fin:
        result = await coqui.clone_voice_async(fin, name)
    click.echo(result)


@tts.command()
@click.option("--voice", help="ID of voice to list existing samples for")
@coroutine
async def list_samples(voice):
    coqui = Coqui(base_url=BASE_URL)
    await coqui.login_async(AuthInfo.get())
    result = await coqui.list_samples_async(voice_id=voice)
    click.echo(result)


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
@coroutine
async def synthesize(voice, text, speed, name, save):
    coqui = Coqui(base_url=BASE_URL)
    await coqui.login_async(AuthInfo.get())
    sample = await coqui.synthesize_async(voice, text, speed, name or text[:30])
    # sample = {'id': '62151ee3-858f-4398-935d-e48481263927', 'name': 'test from the command line', 'created_at': '2022-06-14T20:15:33.016Z', 'voice_id': 'c97d34da-a677-4219-b4b2-9ec198c948e0', 'audio_url': 'https://coqui-dev-creator-app-synthesized-samples.s3.amazonaws.com/samples/sample_GAh7vFe.wav?AWSAccessKeyId=AKIAXW7NFYT5F2KY3J4D&Signature=CCz46wpRIHrkBT9TCx4vZMVkAQE%3D&Expires=1655241335'}
    with tempfile.NamedTemporaryFile("wb") as fout:
        await sample.download_async(fout)
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
