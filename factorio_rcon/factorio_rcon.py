"""RCON client for factorio servers"""
import socket

import construct

try:
    import anyio
except ImportError:
    ASYNC_AVAILABLE = False
else:
    ASYNC_AVAILABLE = True

PACKET_PARSER = construct.GreedyRange(
    construct.Prefixed(
        construct.Int32sl,
        construct.Struct(
            "id" / construct.Int32sl,
            "type" / construct.Int32sl,
            "body" / construct.CString("utf8"),
            construct.Default(construct.CString("utf8"), "")
        )
    )
)


class RCONSharedBase:
    """Methods and data shared between both client classes"""
    def __init__(self):
        self.id_seq = 0
        self.socket_locked = False
        self.rcon_socket = None

    def get_id(self):
        """Gets an id for a command to be sent"""
        if self.id_seq == 2 ** 31 - 1: # signed int32 max
            self.id_seq = 0
        self.id_seq += 1
        return self.id_seq


class RCONClient(RCONSharedBase):
    """RCON client for factorio servers

    Params:
        ip_address: str; IP address to connect to.
        port: int; port to connect to.
        password: str; password to use to authenticate.
        timeout (optional, default None): float; timeout for socket operations.
        connect_on_init (optional, default True): bool; connect to the server when initialised.
    Raises:
        If connect_on_init is set, see RCONClient.connect().
        Else, no specific exceptions.
    Extra information:
        If no timeout is descired, use None rather than 0. 0 is converted to None internally.
        This is as a timeout of 0 signifies non-blocking mode on the socket.
        If a ConnectionError is raised, it is strongly recommended to reconnect to
        the RCON server (with .connect()). However, this is not done automatically.
        The server will not respond to any RCON requests if it is saving, so you should
        set a socket timeout if you are not prepared to wait a few seconds if the map is
        large or the server slow.
    """
    def __init__(self, ip_address, port, password, timeout=None, connect_on_init=True):
        super().__init__()
        self.timeout = timeout
        if timeout == 0:
            self.timeout = None
        self.ip_address = ip_address
        self.port = port
        self.password = password
        if connect_on_init:
            self.connect()

    def connect(self):
        """Connects to the RCON server

        Params:
            No params.
        Raises:
            ConnectionError: if there is an error connecting to or communicating with the server.
            The error message details the exact nature of the error.
        Returns:
            Nothing returned.
        Extra information:
            If a connection dies at any point (ie raises an error), use this function to
            reconnect without having to create a new RCONClient.
        """
        if self.rcon_socket is not None:
            self.rcon_socket.close()
        self.socket_locked = False
        self.rcon_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.rcon_socket.settimeout(self.timeout)
        try:
            self.rcon_socket.connect((self.ip_address, self.port))
        except ConnectionError as exc:
            raise ConnectionError(CONNECT_ERROR) from exc
        self.id_seq = 0
        self.send_packet(0, 3, self.password)
        responses = self.receive_packets()
        for response in responses:
            if response.type == 2:
                if response.id == -1:
                    raise ConnectionError(INVALID_PASS)
                break
        else:
            raise ConnectionError(ID_ERROR)

    def send_packet(self, packet_id, packet_type, packet_body):
        """Sends a packet to the RCON server

        Params:
            packet_id: int; id of packet being sent.
            packet_type: int; type of packet being sent.
            packet_body: str; payload for the packet (usually a command).
        Raises:
            ConnectionError: if there is an error during sending the packet.
            The error message details the exact nature of the error.
        Returns:
            Nothing returned.
        Extra information:
            See RCON protocol specification for what the id and type represent.
        """
        packet = PACKET_PARSER.build([dict(id=packet_id, type=packet_type, body=packet_body)])
        try:
            self.rcon_socket.sendall(packet)
        except Exception as exc:
            raise ConnectionError(WRITE_ERROR) from exc

    def receive_packets(self):
        """Receives a variable number of packets from the RCON server

        Params:
            No params.
        Raises:
            ConnectionError: if there is an error during recieving packets.
            The error message details the exact nature of the error.
        Returns:
            list containing the responses received from the server.
        Extra information:
            Each element of the list will be a response with id, type and body.
            These attributes can be accessed with response.id, response.type etc.
        """
        try:
            data = b""
            while True:
                data += self.rcon_socket.recv(4096)
                if len(data) > 2:
                    if data[-2:] == b"\x00\x00":
                        break
            responses = PACKET_PARSER.parse(data)
        except Exception as exc:
            raise ConnectionError(READ_ERROR) from exc
        return responses

    def send_command(self, command):
        """Sends a single command to the RCON server

        Params:
            command: str; the command to be executed.
        Raises:
            OSError: if socket busy.
            ConnectionError: if there is an error sending/recieving the command.
            The error message details the exact nature of the error.
        Returns:
            str if data is returned.
            None if no data is returned.
        Extra information:
            Use send_commands if multiple commands are being executed at once,
            it will be much faster as all of the requests can be sent an once.
            This function cannot be run multiple times simultaneously, use send_commands.
            This limitation is due to sockets not being able to send/recieve simultaneously
            or have multiple things attempting to read/write at the same time.
            OSError will therefore be raised if the socket is busy to avoid socket errors.
        """
        return self.send_commands(dict(command=command))["command"]

    def send_commands(self, commands):
        """Sends multiple commands to the RCON server

        Params:
            commands: dict; the dict of commands to be executed.
        Raises:
            OSError if socket busy.
            ConnectionError if there is an error sending/recieving the commands.
            The error message details the exact nature of the error.
        Returns:
            dict of format key: response.
        Extra information:
            Structure of the commands dict:
                key: a name for identifying each command in the response
                value: command to be executed
            This function cannot be run multiple times simultaneously.
            This limitation is due to sockets not being able to send/recieve simultaneously
            or have multiple things attempting to read/write at the same time.
            OSError will therefore be raised if the socket is busy to avoid socket errors.
        """
        if self.socket_locked:
            raise OSError(SOCKET_BUSY)
        self.socket_locked = True
        id_map = {}
        results = {}
        for key, value in commands.items():
            packet_id = self.get_id()
            self.send_packet(packet_id, 2, value)
            id_map[packet_id] = key
        received = 0
        while received < len(commands):
            responses = self.receive_packets()
            for response in responses:
                received += 1
                if response.id not in id_map:
                    raise ConnectionError(ID_ERROR)
                if not response.body:
                    results[id_map[response.id]] = None
                else:
                    results[id_map[response.id]] = response.body.rstrip()
        self.socket_locked = False
        return results


class AsyncRCONClient(RCONSharedBase):
    """Aysnchronous RCON client for factorio servers

    Params:
        ip_address: str; IP address to connect to.
        port: int; port to connect to.
        password: str; password to use to authenticate.
        **connect_on_init is not supported**
    Raises:
        ImportError: if anyio is not installed.
    Extra information:
        **Async involving this module is performed using anyio**
        anyio allows you to use either asyncio, curio or trio.
        All functions in this class are async.
        If you want to set timeouts, use the cancellation system your existing framework
        provides or use anyio.move_on_after/fail_after.
        See https://anyio.readthedocs.io/en/latest/cancellation.html#timeouts.
        If a ConnectionError is raised, it is strongly recommended to reconnect to
        the RCON server (with .connect()). However, this is not done automatically.
        The server will not respond to any RCON requests if it is saving, so you should
        setup a timeout if you are not prepared to wait a few seconds if the map is
        large or the server slow.
        """
    def __init__(self, ip_address, port, password):
        if not ASYNC_AVAILABLE:
            raise ImportError("anyio must be installed to use the async client", name="anyio")
        super().__init__()
        self.ip_address = ip_address
        self.port = port
        self.password = password


    async def connect(self):
        """Connects to the RCON server asynchronously

        Params:
            No params.
        Raises:
            ConnectionError: if there is an error connecting to or communicating with the server.
            The error message details the exact nature of the error.
        Returns:
            Nothing returned.
        Extra information:
            If a connection dies at any point (ie raises an error), use this function to
            reconnect without having to create a new RCONClient.
        """
        if self.rcon_socket is not None:
            await self.rcon_socket.close()
        self.socket_locked = False
        try:
            self.rcon_socket = await anyio.connect_tcp(self.ip_address, self.port)
        except ConnectionError as exc:
            raise ConnectionError(CONNECT_ERROR) from exc
        await self.send_packet(0, 3, self.password)
        responses = await self.receive_packets()
        for response in responses:
            if response.type == 2:
                if response.id == -1:
                    raise ConnectionError(INVALID_PASS)
                break
        else:
            raise ConnectionError(ID_ERROR)

    async def send_packet(self, packet_id, packet_type, packet_body):
        """Sends a packet to the RCON server asynchronously

        Params:
            packet_id: int; id of packet being sent.
            packet_type: int; type of packet being sent.
            packet_body: str; payload for the packet (usually a command).
        Raises:
            ConnectionError if there is an error during sending the packet.
            The error message details the exact nature of the error.
        Returns:
            Nothing returned.
        Extra information:
            See RCON protocol specification for what the id and type represent.
        """
        packet = PACKET_PARSER.build([dict(id=packet_id, type=packet_type, body=packet_body)])
        try:
            await self.rcon_socket.send_all(packet)
        except Exception as exc:
            raise ConnectionError(WRITE_ERROR) from exc

    async def receive_packets(self):
        """Receives a variable number of packets from the RCON server asynchronously

        Params:
            No params.
        Raises:
            ConnectionError: if there is an error during recieving packets.
            The error message details the exact nature of the error.
        Returns:
            list containing the responses received from the server.
        Extra information:
            Each element of the list will be a response with id, type and body.
            These attributes can be accessed with response.id, response.type etc.
        """
        try:
            data = b""
            while True:
                data += await self.rcon_socket.receive_some(4096)
                if len(data) > 2:
                    if data[-2:] == b"\x00\x00":
                        break
            responses = PACKET_PARSER.parse(data)
        except Exception as exc:
            raise ConnectionError(READ_ERROR) from exc
        return responses

    async def send_command(self, command):
        """Sends a command to the RCON server asynchronously

        Params:
            command: str; the command to be executed.
        Raises:
            OSError: if socket busy.
            ConnectionError: if there is an error sending/recieving the command.
            The error message details the exact nature of the error.
        Returns:
            str if data is returned.
            None if no data is returned.
        Extra information:
            Use send_commands if multiple commands are being executed at once,
            it will be much faster as all of the requests can be sent an once.
            This function cannot be run multiple times simultaneously, use send_commands.
            This limitation is due to sockets not being able to send/recieve simultaneously
            or have multiple things attempting to read/write at the same time.
            This is especially important in an async context.
             OSError will therefore be raised if the socket is busy to avoid socket errors.
        """
        return (await self.send_commands(dict(command=command)))["command"]

    async def send_commands(self, commands):
        """Sends a dict of commands to the RCON server asynchronously

        Params:
            commands: dict; the dict of commands to be executed.
        Raises:
            OSError: if socket busy.
            ConnectionError: if there is an error sending/recieving the commands.
            The error message details the exact nature of the error.
        Returns:
            dict of format key: response.
        Extra information:
            Structure of the commands dict:
                key: a name for identifying each command in the response
                value: command to be executed
            This function cannot be run multiple times simultaneously.
            This limitation is due to sockets not being able to send/recieve simultaneously
            or have multiple things attempting to read/write at the same time.
            This is especially important in an async context.
            OSError will therefore be raised if the socket is busy to avoid socket errors.
        """
        if self.socket_locked:
            raise OSError(SOCKET_BUSY)
        self.socket_locked = True
        id_map = {}
        results = {}
        for key, value in commands.items():
            packet_id = self.get_id()
            await self.send_packet(packet_id, 2, value)
            id_map[packet_id] = key
        received = 0
        while received < len(commands):
            responses = await self.receive_packets()
            for response in responses:
                received += 1
                if response.id not in id_map:
                    raise ConnectionError(ID_ERROR)
                if not response.body:
                    results[id_map[response.id]] = None
                else:
                    results[id_map[response.id]] = response.body.rstrip()
        self.socket_locked = False
        return results


INVALID_PASS = "Invalid password"
ID_ERROR = "Received a packet with an ID that was not sent"
READ_ERROR = "Connection to server timed out / closed (failed to read packet from socket)"
WRITE_ERROR = "Connection to server timed out / closed (failed to write packet to socket)"
CONNECT_ERROR = "Connection to server timed out or was rejected"
SOCKET_BUSY = ("Socket cannot send/recieve simultaneously or have multiple things attempting "
               "to read/write at the same time. "
               "If sending multiple commands, use send_commands() rather than "
               "calling send_command() multiple times.")
