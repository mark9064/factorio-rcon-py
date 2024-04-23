from ._factorio_rcon import (
    AsyncRCONClient as AsyncRCONClient,
    InvalidPassword as InvalidPassword,
    InvalidResponse as InvalidResponse,
    PacketType as PacketType,
    RCONBaseError as RCONBaseError,
    RCONClient as RCONClient,
    RCONClosed as RCONClosed,
    RCONConnectError as RCONConnectError,
    RCONMessage as RCONMessage,
    RCONNetworkError as RCONNetworkError,
    RCONNotConnected as RCONNotConnected,
    RCONReceiveError as RCONReceiveError,
    RCONSendError as RCONSendError,
    RCONSharedBase as RCONSharedBase,
)

# update the module paths to avoid factorio_rcon.factorio_rcon.obj names
for value in locals().copy().values():
    if getattr(value, "__module__", "").startswith("factorio_rcon."):
        value.__module__ = __name__
# make sure value doesn't hang around as a module attribute
del value # pylint: disable=undefined-loop-variable
