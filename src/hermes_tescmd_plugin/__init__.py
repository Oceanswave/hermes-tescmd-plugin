from __future__ import annotations

from pathlib import Path

from . import auth, client, config, dashboard, runtime, schemas, slash, tools

__version__ = "0.5.0a23"
PLUGIN_NAME = "hermes-tescmd-plugin"
TOOLSET_NAME = "tescmd"
SKILL_NAME = "tescmd-operator"


def registered_tool_specs() -> tuple[runtime.ToolSpec, ...]:
    """Return the full native Tesla Fleet catalog for specialist mode."""
    return tuple(runtime.list_tool_specs())


def register(ctx) -> None:
    config.register_editable_config(ctx)

    if config.get_tool_mode() == "full":
        for spec in registered_tool_specs():
            ctx.register_tool(
                name=spec.name,
                toolset=TOOLSET_NAME,
                schema=schemas.build_schema(spec),
                handler=runtime.make_handler(spec),
                description=spec.description,
            )
    else:
        ctx.register_tool(
            name="tescmd_catalog",
            toolset=TOOLSET_NAME,
            schema=schemas.build_compact_catalog_schema(),
            handler=runtime.compact_catalog,
            description="Discover Tesla Fleet operations and exact argument schemas on demand.",
        )
        ctx.register_tool(
            name="tescmd_execute",
            toolset=TOOLSET_NAME,
            schema=schemas.build_compact_execute_schema(),
            handler=runtime.compact_execute,
            description="Execute any catalogued Tesla operation with full validation and confirmation guards.",
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
