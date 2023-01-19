Usage
=====

Account setup
-------------

To use coqui-py, first you must `create a Coqui account <https://app.coqui.ai/auth/signup>`_, if you don't already have one.

.. note::

   API access is currently in closed beta, if you want to try it out contact us at `info@coqui.ai <mailto:info@coqui.ai?subject=Coqui%20API%20access>`_.

Then you can create an API key in your `account page <https://app.coqui.ai/account>`_. Your API key will be shown only once on creation, so make sure you
save it.


Installation
------------

Install the coqui-py package using pip:

.. code-block:: console

   (venv) $ pip install coqui


Test your installation
----------------------

To verify your installation, let's use the CLI client to login using your token, and then list your existing voices:

.. code-block:: console

   (venv) $ coqui login --token your-API-token-goes-here
   Logged in!
   (venv) $ coqui tts list-voices
   ClonedVoice(id='52105d07-b8f6-4088-8864-b7fdb9f642cc', name='my cool voice', samples_count=10, created_at=datetime.datetime(2022, 8, 23, 16, 43, 40, 139000))
   ClonedVoice(id='9a543712-96ae-4513-bee6-646ba1e7ca74', name='my ice cold voice', samples_count=8, created_at=datetime.datetime(2022, 7, 19, 15, 12, 51, 781000))
