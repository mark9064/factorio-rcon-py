"""RCON client for Factorio servers"""
import enum
import functools
import socket
import struct
from types import TracebackType
from typing import Any, Callable, Dict, NamedTuple, Optional, TypeVar, cast

try:
    import anyio
except ImportError:
    ASYNC_AVAILABLE = False
else:
    ASYNC_AVAILABLE = True

RECV_SIZE = 4096
T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])


class PacketType(enum.IntEnum):
    """RCON packet types"""

    RESPONSE_VALUE = 0
    EXECCOMMAND = 2
    AUTH_RESPONSE = 2
    AUTH = 3


class RCONMessage(NamedTuple):
    """RCON message

    Attrs:
        id: int; message id.
        type: PacketType; message type.
        body: Optional[str]; message body.
    """

    id: int
    type: PacketType
    body: Optional[str]


class RCONBaseError(Exception):
    """Exception base for all exceptions in this library"""


class InvalidPassword(RCONBaseError):
    """RCON password is incorrect"""


class InvalidResponse(RCONBaseError):
    """RCON server returned an unparsable response or one with an unknown ID"""


class RCONNetworkError(RCONBaseError):
    """Base for all network related exceptions"""


class RCONNotConnected(RCONNetworkError):
    """Client is not connected to the RCON server"""


class RCONClosed(RCONNetworkError):
    """RCON server closed the connection"""


class RCONConnectError(RCONNetworkError):
    """Error connecting to the RCON server"""


class RCONSendError(RCONNetworkError):
    """Error sending data to the RCON server"""


class RCONReceiveError(RCONNetworkError):
    """Error receiving data from the RCON server"""


class RCONSharedBase:
    """Methods and data shared between both client classes"""

    rcon_socket: Any
    message_format = "<iii{0}sH"
    fixed_length = 10  # the length of two int32s and the two terminating null bytes

    def __init__(self) -> None:
        self.id_seq = 0
        self.rcon_socket = None
        self.rcon_failure = False

    def get_id(self) -> int:
        """Gets an id for a command to be sent"""
        if self.id_seq == 2**31 - 1:  # signed int32 max
            self.id_seq = 0
        else:
            self.id_seq += 1
        return self.id_seq

    @classmethod
    def build_message(cls, message: RCONMessage) -> bytes:
        """Build a message into bytes"""
        if message.body is not None:
            encoded_body = message.body.encode("utf-8")
        else:
            encoded_body = b""
        return struct.pack(
            cls.message_format.format(len(encoded_body)),
            cls.fixed_length + len(encoded_body),
            message.id,
            message.type,
            encoded_body,
            0,
        )

    @classmethod
    def parse_message(cls, message: bytes, length: int) -> RCONMessage:
        """Parse a message into an RCONMessage tuple"""
        try:
            data = struct.unpack(
                cls.message_format.format(length - cls.fixed_length), message
            )
            return RCONMessage(
                data[1], data[2], data[3].decode("utf-8") if data[3] else None
            )
        except (struct.error, UnicodeError) as exc:
            raise InvalidResponse(PARSE_FAILED) from exc


def handle_socket_errors(alive_socket_required: bool = True) -> Callable[[F], F]:
    """Socket error checking decorator"""

    def real_decorator(function: F) -> F:
        @functools.wraps(function)
        # paramspec can be used to type here, but 3.10+ only
        def wrapper(self, *args, **kwargs):
            if alive_socket_required:
                if self.rcon_socket is None:
                    raise RCONNotConnected(NOT_CONNECTED)
                if self.rcon_failure:
                    raise RCONNotConnected(RCON_FAILED)
            try:
                return function(self, *args, **kwargs)
            except BaseException:
                self.rcon_failure = True
                self.close()
                raise

        return cast(F, wrapper)

    return real_decorator


def async_handle_socket_errors(alive_socket_required: bool = True) -> Callable[[F], F]:
    """Socket error checking decorator (async)"""

    def real_decorator(function: F) -> F:
        @functools.wraps(function)
        async def wrapper(self, *args, **kwargs):
            if alive_socket_required:
                if self.rcon_socket is None:
                    raise RCONNotConnected(NOT_CONNECTED)
                if self.rcon_failure:
                    raise RCONNotConnected(RCON_FAILED)
            try:
                return await function(self, *args, **kwargs)
            except BaseException:
                self.rcon_failure = True
                await self.close()
                raise

        return cast(F, wrapper)

    return real_decorator


class RCONClient(RCONSharedBase):
    """RCON client for Factorio servers

    Params:
        ip_address: str; IP address to connect to.
        port: int; port to connect to.
        password: str; password to use to authenticate.
        timeout (default None): Optional[float]; timeout for socket operations.
        connect_on_init (default True): bool; connect to the server when initialised.
    Raises:
        If connect_on_init is set, see RCONClient.connect().
        Else, no specific exceptions.
    Extra information:
        **All methods are not thread safe**
        Use AsyncRCONClient for coroutine based concurrency.
        This is usable as a context manager.
        If any exception is raised (all inherit from RCONBaseError) during operation,
        it is required that you reconnect to the RCON server (with .connect()).
        The server will not respond to any RCON requests if it is saving, so you should
        set a socket timeout if you are not prepared to wait a few seconds if the map is
        large or the server slow.
        A specified timeout of zero will disable any timeout rather than set non-blocking mode.
    """

    rcon_socket: Optional[socket.socket]

    def __init__(
        self,
        ip_address: str,
        port: int,
        password: str,
        timeout: Optional[float] = None,
        connect_on_init: bool = True,
    ) -> None:
        super().__init__()
        self.timeout = timeout
        if timeout == 0:
            self.timeout = None
        self.ip_address = ip_address
        self.port = port
        self.password = password
        if connect_on_init:
            self.connect()

    @handle_socket_errors(alive_socket_required=False)
    def connect(self) -> None:
        """Connects to the RCON server

        Params:
            No params.
        Raises:
            RCONConnectError: if there is an error connecting to the server.
            InvalidPassword: if the password is incorrect.
            InvalidResponse: if the server returns an invalid response.
        Returns:
            Nothing returned.
        Extra information:
            Use this function to reconnect to the RCON server after an error.
        """
        self.close()
        self.rcon_failure = False
        self.rcon_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.rcon_socket.settimeout(self.timeout)
        try:
            self.rcon_socket.connect((self.ip_address, self.port))
        except Exception as exc:
            raise RCONConnectError(CONNECT_SOCKET_ERROR) from exc
        self.id_seq = 0
        try:
            self.send_packet(self.id_seq, PacketType.AUTH, self.password)
            response = self.receive_packet()
        except RCONBaseError as exc:
            raise RCONConnectError(CONNECT_COMMUNICATION_ERROR) from exc
        if response.type != PacketType.AUTH_RESPONSE:
            raise InvalidResponse(INVALID_TYPE)
        if response.id == -1:
            raise InvalidPassword(INVALID_PASS)
        if response.id != self.id_seq:
            raise InvalidResponse(INVALID_ID)

    def close(self) -> None:
        """Closes the connection to the RCON server

        Params:
            No params.
        Raises:
            No specific exceptions.
        Returns:
            Nothing returned.
        Extra information:
            Guaranteed to succeed, even if the client is not currently connected.
            After closing, the client can still be reconnected using .connect().
        """
        if self.rcon_socket is not None:
            self.rcon_socket.close()
            self.rcon_socket = None

    def send_packet(
        self, packet_id: int, packet_type: PacketType, packet_body: str
    ) -> None:
        """Sends a packet to the RCON server

        Params:
            packet_id: int; id of packet being sent.
            packet_type: PacketType; type of packet being sent.
            packet_body: str; payload for the packet (usually a command).
        Raises:
            RCONNotConnected: if the client is not connected to the RCON server.
            RCONSendError: if any error occurs while sending the data (including a timeout).
        Returns:
            Nothing returned.
        Extra information:
            See RCON protocol specification for what the id and type represent.
        """
        if self.rcon_socket is None:
            raise RCONNotConnected(NOT_CONNECTED)
        packet = self.build_message(
            RCONMessage(id=packet_id, type=packet_type, body=packet_body)
        )
        try:
            self.rcon_socket.sendall(packet)
        except (socket.timeout, TimeoutError) as exc:
            raise RCONSendError(CONN_TIMEOUT) from exc
        except Exception as exc:
            raise RCONSendError(SEND_ERROR) from exc

    def receive_exactly(self, size: int) -> bytes:
        """Receive exactly size bytes"""
        assert self.rcon_socket is not None
        buffer = bytearray()
        while len(buffer) < size:
            read_data = self.rcon_socket.recv(min(size - len(buffer), RECV_SIZE))
            if not read_data:
                return b""
            buffer.extend(read_data)
        return buffer

    def receive_packet(self) -> RCONMessage:
        """Receives a packet from the RCON server

        Params:
            No params.
        Raises:
            RCONNotConnected: if the client is not connected to the RCON server.
            InvalidResponse: if the received data could not be parsed into a response.
            RCONClosed: if the server closes the connection.
            RCONReceiveError: if any other error occurs while receiving data (including a timeout).
        Returns:
            RCONMessage of the response.
        Extra information:
            See the docstring for RCONMessage for available attributes.
        """
        if self.rcon_socket is None:
            raise RCONNotConnected(NOT_CONNECTED)
        try:
            data = bytearray()
            data.extend(self.receive_exactly(4))
            if not data:
                raise RCONClosed(CONN_CLOSED)
            length = int.from_bytes(data, "little")
            read_data = self.receive_exactly(length)
            if not read_data:
                raise RCONClosed(CONN_CLOSED)
            data.extend(read_data)
            return self.parse_message(data, length)
        except (RCONClosed, InvalidResponse):
            raise
        except (socket.timeout, TimeoutError) as exc:
            raise RCONReceiveError(CONN_TIMEOUT) from exc
        except Exception as exc:
            raise RCONReceiveError(RECEIVE_ERROR) from exc

    def send_command(self, command: str) -> Optional[str]:
        """Sends a single command to the RCON server

        Params:
            command: str; the command to be executed.
        Raises:
            RCONNotConnected: if the client is not connected to the RCON server.
            InvalidResponse: if the server returns an invalid response.
            RCONClosed: if the server closes the connection.
            RCONSendError: if any other error occurs while sending the request (including a timeout).
            RCONReceiveError: if any other error occurs while receiving the response (including a timeout).
        Returns:
            str if data is returned.
            None if no data is returned.
        Extra information:
            **This method is NOT thread safe**
            Use send_commands if multiple commands are being executed,
            it will be much faster as all of the requests can be sent simultaneously.
        """
        return self.send_commands({"command": command})["command"]

    @handle_socket_errors()
    def send_commands(self, commands: Dict[T, str]) -> Dict[T, Optional[str]]:
        """Sends multiple commands to the RCON server

        Params:
            commands: Dict[T, str]; commands to be executed.
        Raises:
            RCONNotConnected: if the client is not connected to the RCON server.
            InvalidResponse: if the server returns an invalid response.
            RCONClosed: if the server closes the connection.
            RCONSendError: if any other error occurs while sending the request (including a timeout).
            RCONReceiveError: if any other error occurs while receiving the response (including a timeout).
        Returns:
            dict of format key: response.
        Extra information:
            **This method is NOT thread safe**
            Structure of the commands dictionary:
                key: an identifier for each command in the response.
                value: command to be executed.
        """
        id_map = {}
        results: Dict[T, Optional[str]] = {}
        for key, value in commands.items():
            packet_id = self.get_id()
            self.send_packet(packet_id, PacketType.EXECCOMMAND, value)
            id_map[packet_id] = key
        responses = [self.receive_packet() for _ in commands]
        for response in responses:
            if response.id not in id_map:
                raise InvalidResponse(INVALID_ID)
            if response.type != PacketType.RESPONSE_VALUE:
                raise InvalidResponse(INVALID_TYPE)
            if response.body is None:
                results[id_map[response.id]] = None
            else:
                results[id_map[response.id]] = response.body.rstrip()
        return results

    @handle_socket_errors(alive_socket_required=False)
    def __enter__(self) -> "RCONClient":
        if self.rcon_socket is None or self.rcon_failure:
            self.connect()
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        self.close()


class AsyncRCONClient(RCONSharedBase):
    """Asynchronous RCON client for Factorio servers

    Params:
        ip_address: str; IP address to connect to.
        port: int; port to connect to.
        password: str; password to use to authenticate.
        **connect_on_init is not supported**
    Raises:
        ImportError: if anyio is not installed.
    Extra information:
        **Async involving this module is performed using anyio**

        anyio allows you to use either asyncio or trio.
        All functions in this class are async.
        This is usable as an async context manager.
        If you want to set timeouts, use the cancellation system your existing framework
        provides or use anyio.move_on_after/fail_after.
        See https://anyio.readthedocs.io/en/latest/cancellation.html#timeouts.

        If any exception is raised (all inherit from RCONBaseError) during operation,
        it is required that you reconnect to the RCON server (with .connect()).
        The server will not respond to any RCON requests if it is saving, so you should
        use a timeout if you are not prepared to wait a few seconds if the map is
        large or the server slow.
    """

    rcon_socket: Optional["anyio.abc.SocketStream"]

    def __init__(self, ip_address: str, port: int, password: str) -> None:
        if not ASYNC_AVAILABLE:
            raise ImportError(
                "anyio must be installed to use the async client", name="anyio"
            )
        super().__init__()
        self.ip_address = ip_address
        self.port = port
        self.password = password

    @async_handle_socket_errors(alive_socket_required=False)
    async def connect(self) -> None:
        """Connects to the RCON server asynchronously

        Params:
            No params.
        Raises:
            RCONConnectError: if there is an error connecting to the server.
            InvalidPassword: if the password is incorrect.
            InvalidResponse: if the server returns an invalid response.
        Returns:
            Nothing returned.
        Extra information:
            Use this function to reconnect to the RCON server after an error.
        """
        await self.close()
        self.rcon_failure = False
        try:
            self.rcon_socket = await anyio.connect_tcp(self.ip_address, self.port)
        except Exception as exc:
            raise RCONConnectError(CONNECT_SOCKET_ERROR) from exc
        self.id_seq = 0
        try:
            await self.send_packet(self.id_seq, PacketType.AUTH, self.password)
            response = await self.receive_packet()
        except RCONBaseError as exc:
            raise RCONConnectError(CONNECT_COMMUNICATION_ERROR) from exc
        if response.type != PacketType.AUTH_RESPONSE:
            raise InvalidResponse(INVALID_TYPE)
        if response.id == -1:
            raise InvalidPassword(INVALID_PASS)
        if response.id != self.id_seq:
            raise InvalidResponse(INVALID_ID)

    async def close(self) -> None:
        """Closes the connection to the RCON server asynchronously

        Params:
            No params.
        Raises:
            No specific exceptions.
        Returns:
            Nothing returned.
        Extra information:
            Guaranteed to succeed, even if the client is not currently connected.
            After closing, the client can still be reconnected using .connect().
        """
        if self.rcon_socket is not None:
            await self.rcon_socket.aclose()
            self.rcon_socket = None

    async def send_packet(
        self, packet_id: int, packet_type: PacketType, packet_body: str
    ) -> None:
        """Sends a packet to the RCON server asynchronously

        Params:
            packet_id: int; id of packet being sent.
            packet_type: PacketType; type of packet being sent.
            packet_body: str; payload for the packet (usually a command).
        Raises:
            RCONNotConnected: if the client is not connected to the RCON server.
            RCONSendError: if any error occurs while sending the data.
        Returns:
            Nothing returned.
        Extra information:
            See RCON protocol specification for what the id and type represent.
        """
        if self.rcon_socket is None:
            raise RCONNotConnected(NOT_CONNECTED)
        packet = self.build_message(
            RCONMessage(id=packet_id, type=packet_type, body=packet_body)
        )
        try:
            await self.rcon_socket.send(packet)
        except Exception as exc:
            raise RCONSendError(SEND_ERROR) from exc

    async def receive_exactly(self, size: int) -> bytes:
        """Receive exactly size bytes"""
        assert self.rcon_socket is not None
        buffer = bytearray()
        while len(buffer) < size:
            buffer.extend(
                await self.rcon_socket.receive(min(size - len(buffer), RECV_SIZE))
            )
        return buffer

    async def receive_packet(self) -> RCONMessage:
        """Receives a packet from the RCON server asynchronously

        Params:
            No params.
        Raises:
            RCONNotConnected: if the client is not connected to the RCON server.
            InvalidResponse: if the received data could not be parsed into responses.
            RCONClosed: if the server closes the connection.
            RCONReceiveError: if any other error occurs while receiving data.
        Returns:
            RCONMessage of the response.
        Extra information:
            See the docstring for RCONMessage for available attributes.
        """
        if self.rcon_socket is None:
            raise RCONNotConnected(NOT_CONNECTED)
        try:
            data = bytearray()
            data.extend(await self.receive_exactly(4))
            length = int.from_bytes(data, "little")
            data.extend(await self.receive_exactly(length))
            return self.parse_message(data, length)
        except InvalidResponse:
            raise
        except anyio.EndOfStream as exc:
            raise RCONClosed(CONN_CLOSED) from exc
        except Exception as exc:
            raise RCONReceiveError(RECEIVE_ERROR) from exc

    async def send_command(self, command: str) -> Optional[str]:
        """Sends a command to the RCON server asynchronously

        Params:
            command: str; the command to be executed.
        Raises:
            RCONNotConnected: if the client is not connected to the RCON server.
            InvalidResponse: if the server returns an invalid response.
            RCONClosed: if the server closes the connection.
            RCONSendError: if any other error occurs while sending the request.
            RCONReceiveError: if any other error occurs while receiving the response.
        Returns:
            str if data is returned.
            None if no data is returned.
        Extra information:
            Use send_commands if multiple commands are being executed,
            it will be much faster as all of the requests can be sent simultaneously.
        """
        return (await self.send_commands({"command": command}))["command"]

    @async_handle_socket_errors()
    async def send_commands(self, commands: Dict[T, str]) -> Dict[T, Optional[str]]:
        """Sends multiple commands to the RCON server asynchronously

        Params:
            commands: dict; commands to be executed.
        Raises:
            RCONNotConnected: if the client is not connected to the RCON server.
            InvalidResponse: if the server returns an invalid response.
            RCONClosed: if the server closes the connection.
            RCONSendError: if any other error occurs while sending the request.
            RCONReceiveError: if any other error occurs while receiving the response.
        Returns:
            dict of format key: response.
        Extra information:
            Structure of the commands dictionary:
                key: an identifier for each command in the response.
                value: command to be executed
        """
        id_map = {}
        results: Dict[T, Optional[str]] = {}
        for key, value in commands.items():
            packet_id = self.get_id()
            await self.send_packet(packet_id, PacketType.EXECCOMMAND, value)
            id_map[packet_id] = key
        responses = [await self.receive_packet() for _ in commands]
        for response in responses:
            if response.id not in id_map:
                raise InvalidResponse(INVALID_ID)
            if response.type != PacketType.RESPONSE_VALUE:
                raise InvalidResponse(INVALID_TYPE)
            if response.body is None:
                results[id_map[response.id]] = None
            else:
                results[id_map[response.id]] = response.body.rstrip()
        return results

    @async_handle_socket_errors(alive_socket_required=False)
    async def __aenter__(self) -> "AsyncRCONClient":
        if self.rcon_socket is None or self.rcon_failure:
            await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        await self.close()


INVALID_PASS = "The RCON password is incorrect"
INVALID_ID = (
    "The RCON server returned a response with an unknown sequence ID. This means that "
    "a response was received for a command that was not sent. This situation implies "
    "a bug in this RCON library or the RCON server behaving incorrectly. "
    "If this behaviour is intentional, you can use receive_packet()."
)
INVALID_TYPE = (
    "The RCON server returned a response of unexpected or unknown type. This situation implies "
    "a bug in this RCON library or the RCON server behaving incorrectly. "
    "If this behaviour is intentional, you can use receive_packet()."
)
PARSE_FAILED = (
    "The RCON server returned data that could not be parsed into response messages"
)
NOT_CONNECTED = "The RCON client is currently not connected to the server"
RCON_FAILED = (
    "An error has occurred and the client is no longer connected to the RCON server "
    "(reconnect with connect())"
)
CONN_CLOSED = "The RCON server closed the connection"
CONN_TIMEOUT = "The connection timed out while communicating with the server"
CONNECT_SOCKET_ERROR = "Failed to establish a connection to the server"
CONNECT_COMMUNICATION_ERROR = "Failed to communicate authentication setup to the server"
SEND_ERROR = "Failed to send data to the RCON server"
RECEIVE_ERROR = "Failed to receive data from the RCON server"
