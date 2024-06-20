# character.py
from app.config import Config
config = Config.get_instance()

def handle_character_command(msg_type, number, send_msg):
    character_info = config.SYSTEM_MESSAGE.get("character", "未定义的角色信息。")
    send_msg(msg_type, number, character_info)