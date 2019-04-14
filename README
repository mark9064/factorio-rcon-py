# factorio-rcon-py

A simple factorio RCON client

## Usage

Example:
```python
import factorio_rcon

client = factorio_rcon.RCONClient("127.0.0.1", 12345, "mypassword")
response = client.send_command("/help")
```

Return values:

String if data was returned, else None

Types:
- ip - string
- port - int
- password - string

Raised exceptions:

All exceptions are raised as ConnectionError or a subset of it. Exceptions can be raised due a refused connection (wrong ip/port), incorrect password or the server going down.


## License

GPLV3
