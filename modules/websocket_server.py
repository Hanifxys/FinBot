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
        self.user_connections = {} # Map user_id -> set of websockets
        self.loop = None

    async def register(self, websocket, user_id):
        if user_id not in self.user_connections:
            self.user_connections[user_id] = set()
        self.user_connections[user_id].add(websocket)
        logging.info(f"User {user_id} connected to WS")

    async def unregister(self, websocket):
        for user_id, connections in self.user_connections.items():
            if websocket in connections:
                connections.remove(websocket)
                if not connections:
                    del self.user_connections[user_id]
                break
        logging.info(f"WS Client Disconnected")

    async def broadcast_to_user(self, user_id, message):
        """Kirim pesan HANYA ke user yang berhak (Security Isolation)"""
        if user_id in self.user_connections:
            logging.info(f"Sending to User {user_id}: {message}")
            disconnected = set()
            for client in self.user_connections[user_id]:
                try:
                    await client.send(json.dumps(message))
                except Exception:
                    disconnected.add(client)
            
            for client in disconnected:
                await self.unregister(client)

    async def handler(self, websocket, path=None):
        # First message from client should be authentication/user_id
        try:
            auth_msg = await websocket.recv()
            auth_data = json.loads(auth_msg)
            user_id = auth_data.get("user_id")
            
            if not user_id:
                await websocket.close(1008, "User ID required")
                return

            await self.register(websocket, user_id)
            
            async for message in websocket:
                data = json.loads(message)
                logging.info(f"Received from {user_id}: {data}")
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
