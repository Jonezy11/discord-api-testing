import asyncio
import request_handler
import ws_handler
import voice_ws_handler


class Bot:

    def __init__(self):
        # Application/User ID
        self.bot_id = "591702182806683658"
        # Authorization token
        with open("token.txt", 'r') as f:
            self.token = f.readline()

        # Main event loop
        self.loop = asyncio.get_event_loop()

        self.request_handler = request_handler.RequestHandler(self)

        self.ws_handler = ws_handler.WebsocketHandler(self)

        self.vws_handler = voice_ws_handler.VoiceWebsocketHandler(self)

        self.loop.create_task(self.ws_handler.setup())
        self.loop.run_forever()


bot = Bot()
