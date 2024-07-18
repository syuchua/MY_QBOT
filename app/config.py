import json

class Config:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        if Config._instance is not None:
            raise Exception("This class is a singleton!")
        else:
            self.load_config()

    def load_config(self):
        CONFIG_FILE_PATH = 'config/config.json'
        MODEL_CONFIG_PATH = 'config/model.json'
        DIALOGUES_PATH = 'config/dialogues.json'


        with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as config_file:
            self.config_data = json.load(config_file)

        with open(MODEL_CONFIG_PATH, 'r', encoding='utf-8') as model_config_file:
            self.model_config_data = json.load(model_config_file)

        self.NICKNAMES = self.config_data.get('nicknames', [])
        self.REPLY_PROBABILITY = self.config_data.get('reply_probability', 1.0)
        self.SELF_ID = self.config_data.get('self_id')
        self.ADMIN_ID = self.config_data.get('admin_id')
        self.REPORT_SECRET = self.config_data.get('report_secret')
        self.PROXY_API_BASE = self.config_data.get('proxy_api_base')
        self.SYSTEM_MESSAGE = self.config_data.get('system_message', {})
        self.OPENAI_API_KEY = self.config_data.get('openai_api_key')
        self.MODEL_NAME = self.model_config_data.get('model')
        self.AUDIO_SAVE_PATH = self.config_data.get('audio_save_path')
        self.VOICE_SERVICE_URL = self.config_data.get('voice_service_url')
        self.CHA_NAME = self.config_data.get('cha_name')
        self.MESSAGE_QUEUE_SIZE = self.config_data.get('message_queue_size', 10)
        self.R18 = self.config_data.get('r18')
        self.ADMIN_TITLES = self.config_data.get('admin_titles')

        with open(DIALOGUES_PATH, 'r', encoding='utf-8') as f:
            self.DIALOGUES = json.load(f)

    def reload_config(self):
        self.load_config()

# 获取配置实例
config = Config.get_instance()