import requests
import json


class RequestHandler:
    def __init__(self, bot):
        self.bot = bot
        self.rest_url = "https://discord.com/api/v10"
        self.auth_header = {"Authorization": f"Bot {self.bot.token}"}

    def get_gateway_uri(self):
        return requests.get(f"{self.rest_url}/gateway/bot", headers=self.auth_header).json()["url"]

    async def respond_summon(self, result):
        requests.post("{}/interactions/{}/{}/callback".format(self.rest_url, json.loads(result)["d"]["id"],
                                                              json.loads(result)["d"]["token"]),
                      headers=self.auth_header,
                      json={"type": 4, "data": {"content": "On my way!"}})

    async def respond_jack(self, result):
        requests.post("{}/interactions/{}/{}/callback".format(self.rest_url, json.loads(result)["d"]["id"],
                                                              json.loads(result)["d"]["token"]),
                      headers=self.auth_header,
                      json={"type": 4, "data": {"content": "https://tenor.com/view/asd-gif-19268779"}})

    # TODO: Loop through joined guilds and don't re-register pre-existing commands
    async def register_commands(self):
        """
        Registers the necessary guild commands.
        """
        requests.post(f"{self.rest_url}/applications/{self.bot.bot_id}/guilds/727908432753066190/commands",
                      headers=self.auth_header,
                      json={"name": "summon", "description": "Call forth Penny!"})
        requests.post(f"{self.rest_url}/applications/{self.bot.bot_id}/guilds/727908432753066190/commands",
                      headers=self.auth_header,
                      json={"name": "jack", "description": "A real cutie"})
