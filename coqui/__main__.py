import asyncio
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, date
from getpass import getpass
from functools import wraps

import click
from . import Coqui, ClonedVoice, Sample


def coroutine(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))

    return wrapper


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError ("Type %s not serializable" % type(obj))


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


@main.command()
@click.option("--token", help="API token to sign in with")
@coroutine
async def login(token):
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
@click.option("--fields", help=f"CSV output, specify which attributes of the available cloned voices to print. Comma separated list, eg: -f id,name. Available fields: {', '.join(ClonedVoice._fields)}")
@click.option("--json", "json_out", is_flag=True, help="Print output as JSON")
@coroutine
async def list_voices(fields, json_out):
    coqui = Coqui(base_url=BASE_URL)
    await coqui.login_async(AuthInfo.get())
    voices = await coqui.cloned_voices_async()
    if json_out:
        click.echo(json.dumps([v._asdict() for v in voices], default=json_serial))
    elif not fields:
        click.echo(voices)
    else:
        writer = csv.writer(sys.stdout, lineterminator=os.linesep)
        for v in voices:
            writer.writerow([getattr(v, f) for f in fields.split(',')])


@tts.command()
@click.option("--audio_file", help="Path of reference audio file to clone voice from")
@click.option("--name", help="Name of cloned voice")
@click.option("--json", "json_out", is_flag=True, help="Print output as JSON")
@coroutine
async def clone_voice(audio_file, name, json_out):
    coqui = Coqui(base_url=BASE_URL)
    await coqui.login_async(AuthInfo.get())
    with open(audio_file, "rb") as fin:
        voice = await coqui.clone_voice_async(fin, name)
    if json_out:
        click.echo(json.dumps(voice._asdict(), default=json_serial))
    else:
        click.echo(voice)


@tts.command()
@click.option("--voice", help="ID of voice to list existing samples for")
@click.option("--fields", "-f", help=f"CSV output, speicfy which attributes of the available samples to print out. Comma separated list, eg: -f id,name. Available fields: {', '.join(Sample._fields)}")
@click.option("--json", "json_out", is_flag=True, help="Print output as JSON")
@coroutine
async def list_samples(voice, fields, json_out):
    coqui = Coqui(base_url=BASE_URL)
    await coqui.login_async(AuthInfo.get())
    samples = await coqui.list_samples_async(voice_id=voice)
    if json_out:
        click.echo(json.dumps([s._asdict() for s in samples], default=json_serial))
    elif not fields:
        click.echo(samples)
    else:
        writer = csv.writer(sys.stdout, lineterminator=os.linesep)
        for s in samples:
            writer.writerow([getattr(s, f) for f in fields.split(',')])


@tts.command()
@click.option("--voice", help="ID of voice to synthesize", type=click.UUID)
@click.option("--text", help="Text to synthesize")
@click.option("--speed", help="Speed parameter for synthesis", default=1.0)
@click.option("--name", help="Name of sample", default=None)
@click.option(
    "--save",
    help="If specified, save the synthesized sample to this file name.",
    default=None,
)
@click.option(
    "--play",
    help="If specified, play the synthesized sample",
    is_flag=True,
)
@click.option("--json", "json_out", is_flag=True, help="Print output as JSON")
@coroutine
async def synthesize(voice, text, speed, name, save, play, json_out):
    coqui = Coqui(base_url=BASE_URL)
    await coqui.login_async(AuthInfo.get())
    sample = await coqui.synthesize_async(voice, text, speed, name or text[:30])
    # sample = {'id': '62151ee3-858f-4398-935d-e48481263927', 'name': 'test from the command line', 'created_at': '2022-06-14T20:15:33.016Z', 'voice_id': 'c97d34da-a677-4219-b4b2-9ec198c948e0', 'audio_url': 'https://coqui-dev-creator-app-synthesized-samples.s3.amazonaws.com/samples/sample_GAh7vFe.wav?AWSAccessKeyId=AKIAXW7NFYT5F2KY3J4D&Signature=CCz46wpRIHrkBT9TCx4vZMVkAQE%3D&Expires=1655241335'}
    with tempfile.NamedTemporaryFile("wb") as fout:
        await sample.download_async(fout)
        if save:
            shutil.copy(fout.name, save)
            click.echo(f"Saved synthesized sample to {save}")
        elif play:
            subprocess.run(
                ["play", fout.name],
                check=True,
                stdin=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif json_out:
            click.echo(json.dumps(sample._asdict(), default=json_serial))
        else:
            click.echo(sample)
