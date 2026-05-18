"""Vehicle Command Protocol — ECDH sessions + HMAC-signed protobuf commands."""

from hermes_tescmd_plugin.protocol.commands import (
    COMMAND_REGISTRY,
    CommandSpec,
    get_command_spec,
    get_domain,
    requires_signing,
)
from hermes_tescmd_plugin.protocol.protobuf.messages import Domain, MessageFault
from hermes_tescmd_plugin.protocol.session import Session, SessionManager

__all__ = [
    "COMMAND_REGISTRY",
    "CommandSpec",
    "Domain",
    "MessageFault",
    "Session",
    "SessionManager",
    "get_command_spec",
    "get_domain",
    "requires_signing",
]
