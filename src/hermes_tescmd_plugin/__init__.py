from __future__ import annotations

from pathlib import Path

from . import auth, client, config, dashboard, runtime, schemas, slash, tools

__version__ = "0.5.0a20"
PLUGIN_NAME = "hermes-tescmd-plugin"
TOOLSET_NAME = "tescmd"
SKILL_NAME = "tescmd-operator"


def registered_tool_specs() -> tuple[runtime.ToolSpec, ...]:
    """Return the full native Tesla Fleet tool surface.

    Keep registration exhaustive by default. The bottleneck to optimize is command
    invocation latency, not tool catalog loading, and hiding dedicated tools makes
    normal Tesla operations harder to discover.
    """
    return tuple(runtime.list_tool_specs())


def register(ctx) -> None:
    for spec in registered_tool_specs():
        ctx.register_tool(
            name=spec.name,
            toolset=TOOLSET_NAME,
            schema=schemas.build_schema(spec),
            handler=runtime.make_handler(spec),
            description=spec.description,
        )

    if hasattr(ctx, "register_command"):
        slash.register_commands(ctx)

    dashboard.ensure_dashboard_installed()

    skill_path = Path(__file__).parent / "skills" / SKILL_NAME / "SKILL.md"
    if skill_path.exists():
        ctx.register_skill(SKILL_NAME, skill_path)


__all__ = [
    "PLUGIN_NAME",
    "SKILL_NAME",
    "TOOLSET_NAME",
    "__version__",
    "auth",
    "client",
    "config",
    "dashboard",
    "register",
    "registered_tool_specs",
    "runtime",
    "schemas",
    "slash",
    "tools",
]
