import os
import subprocess
import logging
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport  # The SSE transport layer
from mcp.server import Server

from starlette.applications import Starlette  # Web framework to define routes
from starlette.routing import Route, Mount  # Routing for HTTP and message endpoints
from starlette.requests import Request  # HTTP request objects

import uvicorn  # ASGI server to run the Starlette app

print("entered into server main")

# -------------------------
# MCP setup
# -------------------------
mcp = FastMCP("terminal")

# Expand ~ and make path absolute
DEFAULT_WORKSPACE = os.path.abspath(os.path.expanduser("~/mcp"))

# -------------------------
# Logging configuration
# -------------------------

LOG_DIR = os.path.join(DEFAULT_WORKSPACE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "mcp_terminal.log") 

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ],force=True
)

logger = logging.getLogger(LOG_FILE)

logger.info("MCP Terminal starting")
logger.info("Default workspace set to: %s", DEFAULT_WORKSPACE)

# Ensure workspace exists
os.makedirs(DEFAULT_WORKSPACE, exist_ok=True)

@mcp.tool()
async def run_command(command: str) -> str:
    """
    Execute a shell command inside the configured MCP workspace directory.
    """
    logger.info("Received command: %s", command)
    logger.debug("Executing in workspace: %s", DEFAULT_WORKSPACE)

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=DEFAULT_WORKSPACE,
            capture_output=True,
            text=True
        )

        logger.info(
            "Command finished | returncode=%s",
            result.returncode
        )

        if result.stdout:
            logger.debug("STDOUT:\n%s", result.stdout)

        if result.stderr:
            logger.warning("STDERR:\n%s", result.stderr)

        return result.stdout or result.stderr or ""

    except Exception as e:
        logger.exception("Command execution failed")
        return str(e)
    
@mcp.tool()
async def hello_world() -> str:
    """
    Return a simple Hello World message.
    """
    logger.info("hello_world tool invoked")
    return "Hello World"

# --------------------------------------------------------------------------------------
# STEP 2: Create the Starlette app to expose the tools via HTTP (using SSE)
# --------------------------------------------------------------------------------------
def create_starlette_app(mcp_server: Server, *, debug: bool = False) -> Starlette:
    """
    Constructs a Starlette app with SSE and message endpoints.

    Args:
        mcp_server (Server): The core MCP server instance.
        debug (bool): Enable debug mode for verbose logs.

    Returns:
        Starlette: The full Starlette app with routes.
    """
    # Create SSE transport handler to manage long-lived SSE connections
    sse = SseServerTransport("/messages/")

    # This function is triggered when a client connects to `/sse`
    async def handle_sse(request: Request) -> None:
        """
        Handles a new SSE client connection and links it to the MCP server.
        """
        # Open an SSE connection, then hand off read/write streams to MCP
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,  # Low-level send function provided by Starlette
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    # Return the Starlette app with configured endpoints
    return Starlette(
        debug=debug,
        routes=[
            Route("/sse", endpoint=handle_sse),          # For initiating SSE connection
            Mount("/messages/", app=sse.handle_post_message),  # For POST-based communication
        ],
    )


# --------------------------------------------------------------------------------------
# STEP 3: Start the server using Uvicorn if this file is run directly
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    # Get the underlying MCP server instance from FastMCP
    mcp_server = mcp._mcp_server  # Accessing private member (acceptable here)

    # Command-line arguments for host/port control
    import argparse

    parser = argparse.ArgumentParser(description='Run MCP SSE-based server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8081, help='Port to listen on')
    args = parser.parse_args()

    # Build the Starlette app with debug mode enabled
    starlette_app = create_starlette_app(mcp_server, debug=True)

    # Launch the server using Uvicorn
    uvicorn.run(starlette_app, host=args.host, port=args.port)

