# factorio-rcon-py

A simple Factorio RCON client

## Install

Without async support
`pip install factorio-rcon-py`

With async support
`pip install factorio-rcon-py[async]`

Async support is available as soon as the required dependency (anyio) is installed, so `pip install factorio-rcon-py anyio` is mostly equivalent, but not recommended due to dependency versioning.

Python 3.8+ is required.

## Usage

Example:
```python
import factorio_rcon

client = factorio_rcon.RCONClient("127.0.0.1", 12345, "mypassword")
response = client.send_command("/help")
```

All documentation is in the docstrings of each class/method.

Asynchronous usage of this module is possible thanks to [anyio](https://github.com/agronholm/anyio). This means that you can use the async client with asyncio and trio. Use the AsyncRCONClient class. More details are in its docstring.

Available methods in both classes are (see docstrings for more info):
* connect - Connects to the RCON server.
* close - Closes the connection to the RCON server.
* send_packet - Sends a packet to the RCON server.
* receive_packet - Receives a packet from the RCON server.
* send_command - Sends a single command to the RCON server.
* send_commands - Sends multiple commands to the RCON server.

Note that both the sync/async clients can be used as sync/async context managers respectively.

The methods for sending/receiving packets are available in case you want to
write your own packet handlers, but in most cases you will never need to touch
these and can use send_command(s).

## Mentions

Thanks to:
- [Truman Kilen](https://github.com/trumank) for the initial code / idea.
- [De Sa Léo](https://github.com/desaleo) for contributing context manager support.

## License

LGPLv2.1
