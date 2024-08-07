import base64
import json
import httpx
from app.logger import logger
import os
import aiohttp
from app.config import Config
from utils.cqimage import decode_cq_code, get_cq_image_base64

config = Config.get_instance()

class ModelClient:
    def __init__(self, api_key, base_url, timeout=120):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout

    async def request(self, endpoint, payload):
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/{endpoint}", json=payload, headers=headers, timeout=self.timeout) as response:
                response.raise_for_status()
                return await response.json()

class OpenAIClient(ModelClient):
    async def chat_completion(self, model, messages, **kwargs):
        payload = {
            'model': model,
            'messages': messages
        }
        payload.update(kwargs)
        return await self.request('chat/completions', payload)

    async def image_generation(self, model, prompt, **kwargs):
        payload = {
            'model': model,
            'prompt': prompt
        }
        payload.update(kwargs)
        return await self.request('images/generate', payload)


# 读取配置文件
def load_config():
    config_dir = os.path.join(os.path.dirname(__file__), '../config')
    
    with open(os.path.join(config_dir, 'config.json'), 'r', encoding='utf-8') as config_file:
        default_config = json.load(config_file)
    
    with open(os.path.join(config_dir, 'model.json'), 'r', encoding='utf-8') as model_file:
        model_config = json.load(model_file)
    
    return default_config, model_config

def singleton(func):
    instances = {}
    def wrapper(*args, **kwargs):
        if func not in instances:
            instances[func] = func(*args, **kwargs)
        return instances[func]
    return wrapper

@singleton
def get_client(default_config, model_config):
    model_name = config.MODEL_NAME
    supports_image_recognition = model_config.get('vision', False) 

    if model_name:
        for model_key, settings in model_config.get('models', {}).items():
            if model_name in settings.get('available_models', []):
                api_key = settings['api_key']
                base_url = settings['base_url']
                timeout = settings.get('timeout', 120)
                client = OpenAIClient(api_key, base_url, timeout)
                logger.info(f"Using model '{model_name}' with base_url: {base_url}")
                return client, supports_image_recognition
        logger.warning(f"Model '{model_name}' not found in available models. Using default config.json settings.")
    else:
        logger.warning(f"Model is not specified in model.json. Using default config.json settings.")
    
    # 使用默认配置
    api_key = default_config.get('openai_api_key')
    base_url = default_config.get('proxy_api_base', 'https://api.openai.com/v1') 
    timeout = 120
    client = OpenAIClient(api_key, base_url, timeout) 
    logger.info(f"Using default settings with base_url: {base_url}")
    # 如果使用默认配置，仍然检查模型名称是否以 "gpt-4" 开头
    if not supports_image_recognition:
        supports_image_recognition = default_config.get("model", "").startswith("gpt-4")
    return client, supports_image_recognition

default_config, model_config = load_config()
client, supports_image_recognition = get_client(default_config, model_config)



async def get_chat_response(messages):
    system_message = model_config.get('system_message', {}).get('character', '') or default_config.get('system_message', {}).get('character', '')

    if system_message:
        messages.insert(0, {"role": "system", "content": system_message})

    try:
        response = await client.chat_completion(
            model=model_config.get('model') or default_config.get('model', 'gpt-3.5-turbo'),
            messages=messages,
            temperature=0.5,
            max_tokens=2048,
            top_p=0.95,
            stream=False,
            stop=None,
            presence_penalty=0
        )
        return response['choices'][0]['message']['content'].strip()
    except aiohttp.ClientConnectorError as e:
        logger.error(f"Network connection error during API request: {e}")
        raise Exception(f"网络连接错误，请检查网络状态后重试: {e}")
    except Exception as e:
        logger.error(f"Error during API request: {e}")
        raise Exception(f"API 请求出错: {e}")

async def generate_image(prompt):
    if not supports_image_recognition:
        raise Exception("API does not support image generation.")
    try:
        response = await client.image_generation(
            model="dalle-2",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1
        )
        return response['data'][0]['url']
    except Exception as e:
        raise Exception(f"Error during image generation API request: {e}")

async def recognize_image(cq_code):
    # 检查是否支持图像识别
    if not supports_image_recognition:
        raise Exception("API does not support image recognition.")
        
    try:
        # 从CQ码中提取图片base64编码
        image_data = await get_cq_image_base64(cq_code)
        #logger.info(f"Image base64: {image_data}")
        
        # 准备消息
        message_content = f"识别图片并用中文回复，图片base64编码:{image_data}"
        
        logger.info(f"Sending image for recognition")
        
        # 使用 get_chat_response 函数获取聊天响应
        messages = [{"role": "user", "content": message_content}]
        response_text = await get_chat_response(messages)
        
        return response_text
    except Exception as e:
        raise Exception(f"Error during image recognition: {e}")
