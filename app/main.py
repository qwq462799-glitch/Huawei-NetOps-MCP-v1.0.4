import logging

from fastmcp import FastMCP
from app.config import settings
from app.storage import init_db
from app.mcp_tools import (
    device_tools,
    command_tools,
    change_tools,
    diagnostic_tools,
    terminal_tools,
    advanced_tools,
)
from app.services.rollback_worker import start_rollback_worker

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
mcp = FastMCP("Huawei NetOps MCP")

device_tools.register(mcp)
command_tools.register(mcp)
change_tools.register(mcp)
diagnostic_tools.register(mcp)
terminal_tools.register(mcp)
advanced_tools.register(mcp)


def main():
    init_db()
    # SQLite leader election prevents multiple Harness stdio profiles sharing one DB
    # from running duplicate rollback schedulers or classifying live rollbacks as stale.
    start_rollback_worker()
    # Harness owns this stdio process; no standalone HTTP or Web service is started.
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
