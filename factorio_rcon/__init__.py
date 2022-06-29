from ._factorio_rcon import (
    AsyncRCONClient,
    InvalidPassword,
    InvalidResponse,
    PacketType,
    RCONBaseError,
    RCONClient,
    RCONClosed,
    RCONConnectError,
    RCONMessage,
    RCONNetworkError,
    RCONNotConnected,
    RCONReceiveError,
    RCONSendError,
    RCONSharedBase,
)

# update the module paths to avoid factorio_rcon.factorio_rcon.obj names
for value in locals().copy().values():
    if getattr(value, "__module__", "").startswith("factorio_rcon."):
        value.__module__ = __name__
# make sure value doesn't hang around as a module attribute
del value # pylint: disable=undefined-loop-variable
