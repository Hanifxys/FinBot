import asyncio
import websockets
import json
import logging
import os

class WebSocketServer:
    def __init__(self, host="0.0.0.0", port=8001):
        self.host = host
        self.port = port
        self.connected_clients = set()

    async def register(self, websocket):
        self.connected_clients.add(websocket)
        logging.info(f"New WS Client: {websocket.remote_address}")

    async def unregister(self, websocket):
        self.connected_clients.remove(websocket)
        logging.info(f"WS Client Disconnected")

    async def broadcast(self, message):
        """Kirim pesan ke semua client yang terhubung (Dashboard/Bot)"""
        if self.connected_clients:
            await asyncio.gather(
                *[client.send(json.dumps(message)) for client in self.connected_clients]
            )

    async def handler(self, websocket, path):
        await self.register(websocket)
        try:
            async for message in websocket:
                # Handle pesan masuk dari client jika perlu
                data = json.loads(message)
                logging.info(f"Received WS Message: {data}")
        except Exception as e:
            logging.error(f"WS Error: {e}")
        finally:
            await self.unregister(websocket)

    def start_server(self):
        start_server = websockets.serve(self.handler, self.host, self.port)
        asyncio.get_event_loop().run_until_complete(start_server)
        logging.info(f"🚀 WebSocket Server running on ws://{self.host}:{self.port}")
