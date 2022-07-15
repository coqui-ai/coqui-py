# Coqui CLI

🐸CLI lets you use our services programmatically.

## Installation

```bash
$ pip install coqui
```

## Usage

From CLI:

```
$ coqui token-login --login YOUR_API_TOKEN_HERE
Logged in!
$ coqui tts get-voices
[ClonedVoice(id='030527c9-1ae6-4e14-a4de-e063816d0fe4', name='once upon a time', samples_count=3, created_at=datetime.datetime(2022, 7, 13, 18, 38, 8, 725000)), ClonedVoice(id='04dd7d71-f474-45d1-8743-a7fcb4f8b3c4', name='once upon a time 2', samples_count=0, created_at=datetime.datetime(2022, 7, 15, 11, 55, 17, 155000))]
$ coqui tts clone-voice --audio_file ~/Downloads/blob_PSxUPIV.wav --name "once upon a time 3"
ClonedVoice(id='4b7a1b08-67f9-4bf2-8600-f97cd39bd39c', name='once upon a time 3', samples_count=0, created_at=datetime.datetime(2022, 7, 15, 12, 37, 3, 111000))
$ coqui tts synthesize --voice 4b7a1b08-67f9-4bf2-8600-f97cd39bd39c --text "hello from the world of synthesis" --save foo.wav
Saved synthesized sample to foo.wav
$ play foo.wav

foo.wav:

 File Size: 175k      Bit Rate: 706k
  Encoding: Signed PCM
  Channels: 1 @ 16-bit
Samplerate: 44100Hz
Replaygain: off
  Duration: 00:00:01.99

In:100%  00:00:01.99 [00:00:00.00] Out:95.3k [      |      ] Hd:0.0 Clip:0
Done.
$ coqui tts list-samples --voice  4b7a1b08-67f9-4bf2-8600-f97cd39bd39c
[Sample(id='33115d0a-e555-4fb0-9a66-98edf56143a9', name='hello from the world of synthe', text='hello from the world of synthesis', created_at=datetime.datetime(2022, 7, 15, 12, 40, 19, 981000), audio_url='https://coqui-dev-creator-app-synthesized-samples.s3.amazonaws.com/samples/sample_wqmGJri.wav?AWSAccessKeyId=AKIAXW7NFYT5F2KY3J4D&Signature=wU3Px%2FgnuK7TMghRRFRRPKfUuXs%3D&Expires=1657892449')]
```

Programmatically:

```python
from coqui import Coqui
API_TOKEN = "your token goes here"
coqui = Coqui()
coqui.login(API_TOKEN)
print("\n".join(f"{v.id - v.name}" for v in coqui.cloned_voices()))
```

Async APIs:

```python
$ python -m asyncio
asyncio REPL 3.10.2 (main, Feb  8 2022, 18:36:32) [Clang 13.0.0 (clang-1300.0.29.30)] on darwin
Use "await" directly instead of "asyncio.run()".
Type "help", "copyright", "credits" or "license" for more information.
>>> import asyncio
>>> from coqui import Coqui
>>> await coqui.cloned_voices_async()
Traceback (most recent call last):
  File "/Users/reuben/.pyenv/versions/3.10.2/lib/python3.10/concurrent/futures/_base.py", line 446, in result
    return self.__get_result()
  File "/Users/reuben/.pyenv/versions/3.10.2/lib/python3.10/concurrent/futures/_base.py", line 391, in __get_result
    raise self._exception
  File "<console>", line 1, in <module>
  File "/Users/reuben/Development/coqui-py/coqui/__init__.py", line 225, in cloned_voices
    async with self._get_session() as session:
  File "/Users/reuben/.pyenv/versions/3.10.2/lib/python3.10/contextlib.py", line 199, in __aenter__
    return await anext(self.gen)
  File "/Users/reuben/Development/coqui-py/coqui/__init__.py", line 164, in _get_session
    raise AuthenticationError(
coqui.AuthenticationError: Tried to create authenticated session without logging in.
>>> # Oops, forgot to login!
>>> API_TOKEN = "your token goes here"
>>> await coqui.login_async(API_TOKEN)
True
>>> await coqui.cloned_voices_async()
[ClonedVoice(id='030527c9-1ae6-4e14-a4de-e063816d0fe4', name='once upon a time', samples_count=3, created_at=datetime.datetime(2022, 7, 13, 18, 38, 8, 725000)), ClonedVoice(id='04dd7d71-f474-45d1-8743-a7fcb4f8b3c4', name='once upon a time 2', samples_count=0, created_at=datetime.datetime(2022, 7, 15, 11, 55, 17, 155000)), ClonedVoice(id='4b7a1b08-67f9-4bf2-8600-f97cd39bd39c', name='once upon a time 3', samples_count=5, created_at=datetime.datetime(2022, 7, 15, 12, 37, 3, 111000))]
>>> coqui.cloned_voices()
Traceback (most recent call last):
  File "/Users/reuben/.pyenv/versions/3.10.2/lib/python3.10/concurrent/futures/_base.py", line 446, in result
    return self.__get_result()
  File "/Users/reuben/.pyenv/versions/3.10.2/lib/python3.10/concurrent/futures/_base.py", line 391, in __get_result
    raise self._exception
  File "/Users/reuben/.pyenv/versions/3.10.2/lib/python3.10/asyncio/__main__.py", line 34, in callback
    coro = func()
  File "<console>", line 1, in <module>
  File "/Users/reuben/Development/coqui-py/coqui/__init__.py", line 44, in sync_func
    return asyncio.run(meth(*args, **kwargs))
  File "/Users/reuben/.pyenv/versions/3.10.2/lib/python3.10/asyncio/runners.py", line 33, in run
    raise RuntimeError(
RuntimeError: asyncio.run() cannot be called from a running event loop
>>> # Don't call sync methods in async contexts!
```

## Development

```bash
$ python -m pip install flit
# Below, -s means editable mode, symlinked. Using it lets you edit the code and
# test changes without having to reinstall the package.
$ python -m flit install -s
$ coqui --help
$ coqui token-login --help
$ # etc
```
