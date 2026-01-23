#!/usr/bin/env python3
"""
Hanzo-Vim Bridge Server

Bridges between:
- Vim (via channel on localhost:PORT, JSON mode)
- AI agents (via WebSocket on localhost:PORT+1)

This allows hanzo-tools-ide to control Vim just like VS Code.

Architecture:
┌─────────────┐     Channel      ┌──────────────┐     WebSocket    ┌─────────────┐
│    Vim      │ ◄───────────────► │ Python Bridge │ ◄───────────────► │ AI Agent    │
│             │   localhost:9228  │              │  localhost:9229   │ (hanzo-mcp) │
└─────────────┘                   └──────────────┘                   └─────────────┘
"""

import asyncio
import json
import sys
import uuid
from typing import Any

# Try websockets, fall back to simple socket server
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


class VimBridge:
    """Bridge between Vim channel and WebSocket clients."""

    def __init__(self, port: int = 9228):
        self.port = port
        self.vim_port = port  # Vim connects here
        self.ws_port = port + 1  # WebSocket on next port
        self.vim_reader: asyncio.StreamReader | None = None
        self.vim_writer: asyncio.StreamWriter | None = None
        self.pending: dict[str, asyncio.Future] = {}
        self.ws_clients: set = set()

    async def start(self):
        """Start the bridge server."""
        # Start TCP server for Vim channel
        vim_server = await asyncio.start_server(
            self.handle_vim_connection,
            'localhost',
            self.port,
        )
        print(f"Vim bridge listening on localhost:{self.port}")

        if HAS_WEBSOCKETS:
            # Start WebSocket server on port+1 for AI agents
            ws_server = await websockets.serve(
                self.handle_ws_connection,
                'localhost',
                self.ws_port,
            )
            print(f"WebSocket server on localhost:{self.ws_port}")
            await asyncio.gather(
                vim_server.serve_forever(),
                ws_server.wait_closed(),
            )
        else:
            print("websockets not installed, WebSocket disabled")
            print("Install with: pip install websockets")
            await vim_server.serve_forever()

    async def handle_vim_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle Vim channel connection."""
        print("Vim connected")
        self.vim_reader = reader
        self.vim_writer = writer

        try:
            buffer = b""
            while True:
                data = await reader.read(4096)
                if not data:
                    break

                buffer += data

                # Parse JSON messages (Vim sends [id, msg] format)
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    if not line.strip():
                        continue

                    try:
                        msg = json.loads(line.decode('utf-8'))
                        await self.on_vim_message(msg)
                    except json.JSONDecodeError as e:
                        print(f"JSON error: {e}")

        except Exception as e:
            print(f"Vim connection error: {e}")
        finally:
            print("Vim disconnected")
            self.vim_reader = None
            self.vim_writer = None

    async def handle_ws_connection(self, websocket):
        """Handle WebSocket connection from AI agent."""
        print("AI agent connected")
        self.ws_clients.add(websocket)

        try:
            async for message in websocket:
                try:
                    msg = json.loads(message)
                    response = await self.handle_agent_request(msg)
                    await websocket.send(json.dumps(response))
                except json.JSONDecodeError as e:
                    await websocket.send(json.dumps({"error": str(e)}))
        except Exception as e:
            print(f"WebSocket error: {e}")
        finally:
            self.ws_clients.discard(websocket)
            print("AI agent disconnected")

    async def on_vim_message(self, msg: Any):
        """Handle message from Vim."""
        # Vim sends [id, data] for responses
        if isinstance(msg, list) and len(msg) >= 2:
            msg_id, data = msg[0], msg[1]
            if msg_id in self.pending:
                self.pending[msg_id].set_result(data)
                return

        # Broadcast events to WebSocket clients
        for client in self.ws_clients:
            try:
                await client.send(json.dumps({"event": "vim", "data": msg}))
            except Exception:
                pass

    async def send_to_vim(self, action: str, **params) -> dict:
        """Send request to Vim and wait for response."""
        if not self.vim_writer:
            return {"error": "Vim not connected"}

        msg_id = str(uuid.uuid4())[:8]
        request = {"id": msg_id, "action": action, **params}

        # Create future for response
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self.pending[msg_id] = future

        try:
            # Vim channel expects [id, msg] format
            data = json.dumps([msg_id, request]) + "\n"
            self.vim_writer.write(data.encode('utf-8'))
            await self.vim_writer.drain()

            # Wait for response
            result = await asyncio.wait_for(future, timeout=30.0)
            return result
        except asyncio.TimeoutError:
            return {"error": "Timeout"}
        finally:
            self.pending.pop(msg_id, None)

    async def handle_agent_request(self, msg: dict) -> dict:
        """Handle request from AI agent."""
        action = msg.get("action", "")
        params = msg.get("params", {})

        # Map IDE tool actions to Vim actions
        action_map = {
            # File operations
            "file.open": "file.open",
            "file.save": "file.save",
            "file.close": "file.close",
            "file.info": "file.info",

            # Editor operations
            "editor.selection": "editor.selection",
            "editor.select": "editor.goto",
            "editor.insert": "editor.insert",
            "editor.replace": "editor.replace",
            "editor.text": "editor.text",
            "editor.goto": "editor.goto",

            # Navigation
            "nav.goto": "editor.goto",

            # Commands
            "command": "command",

            # Diagnostics
            "diagnostics": "diagnostics",

            # REPL
            "repl.start": "repl.start",
            "repl.eval": "repl.eval",
            "repl.stop": "repl.stop",

            # IDE-specific aliases
            "open": "file.open",
            "save": "file.save",
            "close": "file.close",
            "status": "file.info",
            "insert": "editor.insert",
            "replace": "editor.replace",
            "goto": "editor.goto",
        }

        vim_action = action_map.get(action, action)
        return await self.send_to_vim(vim_action, **params)


async def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9228
    bridge = VimBridge(port)
    await bridge.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
