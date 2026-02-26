import asyncio
import websockets
import json
import logging
import os
import threading

class WebSocketServer:
    def __init__(self, host="0.0.0.0", port=8001):
        self.host = host
        self.port = port
        self.connected_clients = set()
        self.loop = None

    async def register(self, websocket):
        self.connected_clients.add(websocket)
        logging.info(f"New WS Client: {websocket.remote_address}")

    async def unregister(self, websocket):
        self.connected_clients.remove(websocket)
        logging.info(f"WS Client Disconnected")

    async def broadcast(self, message):
        """Kirim pesan ke semua client yang terhubung (Desktop Dashboard)"""
        if self.connected_clients:
            logging.info(f"Broadcasting to {len(self.connected_clients)} clients: {message}")
            disconnected = set()
            for client in self.connected_clients:
                try:
                    await client.send(json.dumps(message))
                except Exception:
                    disconnected.add(client)
            
            for client in disconnected:
                await self.unregister(client)

    async def handler(self, websocket, path=None):
        await self.register(websocket)
        try:
            async for message in websocket:
                data = json.loads(message)
                logging.info(f"Received WS Message: {data}")
        except Exception as e:
            logging.error(f"WS Error: {e}")
        finally:
            await self.unregister(websocket)

    def run_server(self):
        """Run the server in a separate event loop (for threading)"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        start_server = websockets.serve(self.handler, self.host, self.port)
        self.loop.run_until_complete(start_server)
        logging.info(f"🚀 WebSocket Server running on ws://{self.host}:{self.port}")
        self.loop.run_forever()

    def start_in_thread(self):
        thread = threading.Thread(target=self.run_server, daemon=True)
        thread.start()
        return thread
