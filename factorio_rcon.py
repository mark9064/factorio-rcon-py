"""RCON client for factorio servers"""
import socket

import construct

PACKET_PARSER = construct.Prefixed(construct.Int32sl, construct.Struct(
    "id" / construct.Int32sl,
    "type" / construct.Int32sl,
    "body" / construct.CString("utf8"),
    construct.Default(construct.CString("utf8"), "")
))


class RCONClient:
    """RCON client for factorio server"""
    def __init__(self, ip, port, password):
        self.rcon_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.rcon_socket.connect((ip, port))
        self.socket_iostream = self.rcon_socket.makefile(mode="rwb")
        auth_response = self.send_packet(0, 3, password)
        if auth_response.id == -1:
            raise ConnectionError("Invalid password")

    def send_packet(self, packet_id, packet_type, packet_body):
        """Sends a packet to the RCON server"""
        packet = PACKET_PARSER.build(dict(id=packet_id, type=packet_type, body=packet_body))
        try:
            self.socket_iostream.write(packet)
            self.socket_iostream.flush()
            return PACKET_PARSER.parse_stream(self.socket_iostream)
        except Exception:
            raise ConnectionError("Connection to server closed"
                                  " (failed to read/write packet from stream)")

    def send_command(self, command):
        """Sends a command to the RCON server"""
        response = self.send_packet(1, 2, command)
        if not response.body:
            return None
        return response.body.rstrip()
