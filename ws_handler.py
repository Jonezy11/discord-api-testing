import asyncio
import websockets
import random
import json


class WebsocketHandler:
    def __init__(self, bot):
        self.bot = bot
        self.uri = f"{self.bot.request_handler.get_gateway_uri()}/?v=10&encoding=json"
        self.ws = None
        self.heartbeat_interval = None
        self.heartbeat_ack = None

    async def setup(self):
        await self.bot.loop.create_task(self.connect())
        self.bot.loop.create_task(self.heartbeat())
        await self.bot.loop.create_task(self.identify())
        self.bot.loop.create_task(self.monitor())

    async def connect(self):
        """
        Connects to the main WebSocket.
        """
        # Connect to main WebSocket
        self.ws = await websockets.connect(self.uri)
        # Await Opcode 10 Hello
        result = await self.ws.recv()
        print(result)
        # Store heartbeat interval from 'Hello' payload
        self.heartbeat_interval = json.loads(result)["d"]["heartbeat_interval"] / 1000
        # Add tasks for Heartbeat and Identify to main event loop

    async def heartbeat(self):
        """
        Sends Opcode 1 Heartbeat at specified interval.
        """
        # Wait specified interval
        await asyncio.sleep(self.heartbeat_interval + random.random())
        i = 0
        while True:
            # Create 'Heartbeat' payload
            payload = json.dumps({"op": 1, "s": i, "d": {}, "t": None})
            # Establish Future object to receive ACK
            self.heartbeat_ack = self.bot.loop.create_future()
            # Send payload over WebSocket
            await self.ws.send(payload)
            try:
                # Await ACK
                await asyncio.wait_for(self.heartbeat_ack, timeout=5.0)
            except asyncio.TimeoutError:
                # If ACK not received timeout and disconnect
                # TODO: Implement Resume functionality
                print('Timed out waiting for ACK')
                await self.disconnect()
            print("Received ACK")
            i += 1
            await asyncio.sleep(self.heartbeat_interval)

    async def identify(self):
        """
        Sends Opcode 2 Identify and establishes Monitor task.
        """
        # Create 'Identify' payload
        payload = json.dumps({"op": 2, "d": {"token": self.bot.token, "intents": 641,
                                             "properties": {"$os": "linux",
                                                            "$browser": "disco",
                                                            "$device": "disco"},
                                             "presence": {
                                                 "activities": [{
                                                     "name": "T-Swizzle",
                                                     "type": 2
                                                 }],
                                                 "status": "online",
                                                 "afk": False}}})
        # Send payload over WebSocket
        await self.ws.send(payload)
        # Await 'Ready' event
        result = await self.ws.recv()
        print(result)
        # self.loop.create_task(self.register_commands())

    async def monitor(self):
        """
        Awaits incoming messages on the main Websocket.
        """
        while True:
            result = await self.ws.recv()
            print(result)

            # Opcode 11 Heartbeat ACK
            if json.loads(result)["op"] == 11:
                self.heartbeat_ack.set_result(True)

            # TODO: Place event responses in separate functions

            # Cache events if currently attempting to join a channel

            if json.loads(result)["t"] == "VOICE_STATE_UPDATE" and self.bot.vws_handler.is_joining:
                if json.loads(result)["d"]["member"]["user"]["id"] == self.bot.bot_id:
                    self.bot.vws_handler.voice_state_cache.set_result(json.loads(result))
            if json.loads(result)["t"] == "VOICE_SERVER_UPDATE" and self.bot.vws_handler.is_joining:
                self.bot.vws_handler.voice_server_cache.set_result(json.loads(result))

            # Responses to command interactions
            if json.loads(result)["t"] == "INTERACTION_CREATE":
                if json.loads(result)["d"]["data"]["name"] == "summon":
                    await self.bot.request_handler.respond_summon(result)
                    self.bot.loop.create_task(self.voice_connect())
                if json.loads(result)["d"]["data"]["name"] == "jack":
                    await self.bot.request_handler.respond_jack(result)

    async def voice_connect(self):
        # Create 'Gateway Voice State Update' payload
        payload = json.dumps({"op": 4, "d": {"guild_id": "727908432753066190",
                                             "channel_id": "727908433457840211",
                                             "self_mute": False,
                                             "self_deaf": False}})
        # Send payload over WebSocket
        await self.ws.send(payload)
        self.bot.loop.create_task(self.bot.vws_handler.setup())

    # TODO: Implement disconnect command and UDP+VOICE sockets
    async def disconnect(self):
        """
        Closes sockets and stops main event loop.
        """
        self.bot.loop.stop()
        await self.ws.close()
