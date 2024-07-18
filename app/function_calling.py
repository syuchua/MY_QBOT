from app.logger import logger
import re
from utils.voice_service import generate_voice
from utils.model_request import get_client, default_config, model_config, recognize_image
from utils.lolicon import fetch_image
from app.command import handle_command

client = get_client(default_config, model_config)

async def call_function(model_name, endpoint, payload):
    try:
        response = await client.request(endpoint, payload)
        return response
    except Exception as e:
        logger.error(f"Error calling function {endpoint} on model {model_name}: {e}")
        return None

async def handle_command_request(user_input):
    COMMAND_PATTERN = re.compile(r'^[!/](help|reset|character|history|clear|model|r18)(?:\s+(.+))?')
    match = COMMAND_PATTERN.match(user_input)
    if match:
        command = match.group(1)
        command_args = match.group(2)
        full_command = f"{command} {command_args}" if command_args else command
        return full_command
    return None

async def handle_image_request(user_input):
    IMAGE_KEYWORDS = ["发一张", "来一张"]
    RANDOM_IMAGE_KEYWORDS = ["再来一张", "来份涩图", "来份色图"]
    DRAW_KEYWORDS = ["画一张", "生成一张"]

    for keyword in IMAGE_KEYWORDS:
        if keyword in user_input:
            keyword_value = user_input.split(keyword, 1)[1].strip() if keyword in user_input else ""
            image_url = await fetch_image(keyword_value)
            return image_url

    for keyword in RANDOM_IMAGE_KEYWORDS:
        if keyword in user_input:
            image_url = await fetch_image("")
            return image_url

    for keyword in DRAW_KEYWORDS:
        if keyword in user_input:
            prompt = user_input.replace(keyword, '').strip()
            response = await call_function('other_model', 'generate_image', {"prompt": prompt})
            if response:
                return response.get("image_url")
    return None

async def handle_voice_request(user_input):
    VOICE_KEYWORDS = ["语音回复", "用声音说", "语音说"]

    # 检查是否包含关键词
    for keyword in VOICE_KEYWORDS:
        if keyword in user_input:
            voice_text = user_input.split(keyword, 1)[1].strip()
            audio_filename = await generate_voice(voice_text)
            if audio_filename:
                return f"http://localhost:4321/data/voice/{audio_filename}"           

    # 检查是否包含 #voice 标签
    voice_pattern = re.compile(r"#voice\s*(.*?)[.!?]")
    voice_match = voice_pattern.search(user_input)
    if voice_match:
        voice_text = voice_match.group(1).strip()
        audio_filename = await generate_voice(voice_text)
        if audio_filename:
            return f"http://localhost:4321/data/voice/{audio_filename}"
    
    return None

async def handle_image_recognition(user_input):
    IMAGE_CQ_PATTERN = r'\[CQ:image,file=(.+)\]'
    match = re.search(IMAGE_CQ_PATTERN, user_input)
    if match:
        image_cq_code = match.group(0)
        response = await recognize_image(image_cq_code)
        if response:
            return response

    return None

