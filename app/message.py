from functools import wraps
from app.logger import logger
import re
import time
import aiohttp
import random
import asyncio
from app.config import Config
from app.command import handle_command
from app.decorators import select_connection_method
from utils.voice_service import generate_voice
from utils.model_request import get_chat_response
from app.function_calling import handle_image_request, handle_voice_request, handle_image_recognition, handle_command_request, handle_music_request
from app.database import MongoDB

config = Config.get_instance()

# 添加数据库连接实例
db = MongoDB()

# 超时重试装饰器
def retry_on_timeout(retries=1, timeout=10):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            for attempt in range(retries):
                try:
                    return await func(*args, **kwargs)
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout on attempt {attempt + 1}/{retries}. Retrying...")
                    await asyncio.sleep(timeout)
            raise asyncio.TimeoutError("Max retries reached")
        return wrapper
    return decorator

@retry_on_timeout(retries=3, timeout=10)
async def send_http_request(url, json):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        async with session.post(url, json=json) as res:
            res.raise_for_status()
            response = await res.json()
            return response

@select_connection_method
async def send_msg(msg_type, number, msg, use_voice=False, is_error_message=False):
    if use_voice:
        try:
            audio_filename = await generate_voice(msg)
            if audio_filename:
                msg = f"[CQ:record,file=http://localhost:4321/data/voice/{audio_filename}]"
        except asyncio.TimeoutError:
            msg = "语音合成超时，请稍后再试。"

    params = {
        'message': msg,
        **({'group_id': number} if msg_type == 'group' else {'user_id': number})
    }
    if config.CONNECTION_TYPE == 'http':
        url = f"http://127.0.0.1:3000/send_{msg_type}_msg"
        try:
            response = await send_http_request(url, params)
            if 'status' in response and response['status'] == 'failed':
                error_msg = response.get('message', response.get('wording', 'Unknown error'))
                logger.error(f"Failed to send {msg_type} message: {error_msg}")
                if not is_error_message:
                    await send_msg(msg_type, number, f"发送消息失败: {error_msg}", is_error_message=True)
            else:
                logger.info(f"\nsend_{msg_type}_msg: {msg}\n")
                logger.debug(f"API response: {response}")
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                logger.error(f"Resource not found: {e}")
                await send_msg(msg_type, number, "资源未找到 (404 错误)。")
            else:
                logger.error(f"HTTP error occurred: {e}")
                await send_msg(msg_type, number, f"HTTP 错误: {e}")
        except asyncio.TimeoutError:
            logger.error("Request timed out after retries")
            await send_msg(msg_type, number, "请求超时，请稍后再试。")
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error occurred: {e}")
            await send_msg(msg_type, number, f"HTTP 错误: {e}")

def get_dialogue_response(user_input):
    for dialogue in config.DIALOGUES:
        if dialogue["user"] == user_input:
            return dialogue["assistant"]
    return None

def process_chat_message(msg_type):
    def decorator(func):
        @wraps(func)
        async def wrapper(rev, *args, **kwargs):
            try:
                user_input = rev['raw_message']
                user_id = rev['sender']['user_id']
                username = rev['sender']['nickname']
                recipient_id = rev['sender']['user_id'] if msg_type == 'private' else rev['group_id']
                context_type = 'private' if msg_type == 'private' else 'group'
                context_id = recipient_id

                user_info = {"user_id": user_id, "username": username}
                db.insert_user_info(user_info)

                # 调用原始函数，可能会修改 user_input 或执行其他特定逻辑
                modified_input = await func(rev, *args, **kwargs)
                if modified_input is None:
                    return  # 如果返回 None，表示不需要回复，直接返回
                if modified_input is not None:
                    user_input = modified_input

                # 检测命令
                full_command = await handle_command_request(user_input)
                if full_command:
                    await handle_command(full_command, msg_type, recipient_id, send_msg, context_type, context_id)
                    return

                # 处理特殊请求
                special_response = await handle_special_requests(user_input)
                if special_response:
                    await send_msg(msg_type, recipient_id, special_response)
                    db.insert_chat_message(user_id, user_input, special_response, context_type, context_id)
                    return

                recent_messages = db.get_recent_messages(user_id=recipient_id, context_type=context_type, context_id=context_id, limit=10)
                system_message_text = "\n".join(config.SYSTEM_MESSAGE.values())
                if user_id == config.ADMIN_ID:
                    admin_title = random.choice(config.ADMIN_TITLES)
                    user_input = f"{admin_title}: {user_input}"
                else:
                    user_input = f"{username}: {user_input}"
                messages = [{"role": "system", "content": system_message_text}] + recent_messages + [{"role": "user", "content": user_input}]

                response_text = get_dialogue_response(user_input) if user_id == config.ADMIN_ID else None
                if response_text is None:
                    response_text = await get_chat_response(messages)

                if response_text:
                    db.insert_chat_message(user_id, user_input, response_text, context_type, context_id)
                    # 添加一个参数来指示是否处理特殊响应
                    process_special = not user_input.startswith(('!history', '/history', '#history'))
                    await process_special_responses(response_text, msg_type, recipient_id, user_id, user_input, context_type, context_id, process_special=process_special)

                if user_id == config.ADMIN_ID:                    
                    response_with_username = response_text
                else:
                    response_with_username = f"{username}，{response_text}"

                await send_msg(msg_type, recipient_id, response_with_username)
            except Exception as e:
                logger.error(f"Error in process_chat_message: {e}")
                await send_msg(msg_type, recipient_id, "阿巴阿巴，出错了。")
        
        return wrapper
    return decorator

async def handle_special_requests(user_input):
    image_url = await handle_image_request(user_input)
    if image_url:
        return f"[CQ:image,file={image_url}]"

    voice_url = await handle_voice_request(user_input)
    if voice_url:
        return f"[CQ:record,file={voice_url}]"
    
    music_response = await handle_music_request(user_input)
    if music_response:
        if music_response.startswith("http"):
            return f"[CQ:record,file={music_response}]"
        else:
            return music_response  # 返回错误消息
        
    recognition_result = await handle_image_recognition(user_input)
    if recognition_result:
        return f"识别结果：{recognition_result}"

    return None

def is_chinese(char):
    """检查一个字符是否是中文"""
    return '\u4e00' <= char <= '\u9fff'

async def process_special_responses(response_text, msg_type, recipient_id, user_id, user_input, context_type, context_id, process_special=True):
    if process_special and '#voice' in response_text:
        logger.info("Voice request detected")
        voice_pattern = re.compile(r"#voice\s*(.*)", re.DOTALL)
        voice_match = voice_pattern.search(response_text)
        if voice_match:
            voice_text = voice_match.group(1).strip()
            voice_text = voice_text.replace('\n', '.')
            voice_text = re.sub(r'\[.*?\]', '', voice_text) # 移除方括号内的内容
            voice_text = re.sub(r'\(.*?\)', '', voice_text) # 移除圆括号内的内容
            logger.info(f"Voice text: {voice_text}")
            try:
                audio_filename = await asyncio.wait_for(generate_voice(voice_text), timeout=10)
                logger.info(f"Audio filename: {audio_filename}")
                if (audio_filename):
                    await send_msg(msg_type, recipient_id, f"[CQ:record,file=http://localhost:4321/data/voice/{audio_filename}]")
                    db.insert_chat_message(user_id, user_input, f"[CQ:record,file=http://localhost:4321/data/voice/{audio_filename}]", context_type, context_id)
                else:
                    await send_msg(msg_type, recipient_id, "语音合成失败。")
                return
            except asyncio.TimeoutError:
                await send_msg(msg_type, recipient_id, "语音合成超时，请稍后再试。")
                return
    elif process_special and '#recognize' in response_text:
        recognition_result = await handle_image_recognition(response_text[10:].strip())
        if recognition_result:
            await send_msg(msg_type, recipient_id, f"识别结果：{recognition_result}")
            db.insert_chat_message(user_id, user_input, f"识别结果：{recognition_result}", context_type, context_id)
        return
    elif process_special and '#draw' in response_text:
        logger.info("Draw request detected")
        draw_pattern = re.compile(r"#draw\s*(.*)", re.DOTALL)
        draw_match = draw_pattern.search(response_text)
        if draw_match:
            draw_prompt = draw_match.group(1).strip()
            # 清理 prompt
            draw_prompt = draw_prompt.replace('\n', ' ')  # 将换行符替换为空格
            draw_prompt = re.sub(r'\[.*?\]', '', draw_prompt)  # 移除方括号内的内容
            draw_prompt = draw_prompt.replace('()', '') # 移除圆括号
            draw_prompt = re.sub(r'[,，。.…]+', ' ', draw_prompt)  # 替换逗号、句号、省略号为空格
            draw_prompt = re.sub(r'\s+', ',', draw_prompt)  # 将多个空格替换为逗号           
            draw_prompt = ''.join([char for char in draw_prompt if not is_chinese(char)])  # 移除中文字符         
            draw_prompt = draw_prompt.strip()  # 去除首尾空格
            # draw_prompt = re.sub(r'\s+', ',', draw_prompt)  # 将空格替换为逗号
            draw_prompt = draw_prompt[:-2] # 移除前三个字符
            draw_prompt = re.sub(r'^[,.。... ! ?\s]+|[,.。... ! ?\s]+$', '', draw_prompt) # 移除开头和结尾的标点符号和空格
            logger.info(f"Draw prompt: {draw_prompt}")
        try:
            draw_result = await handle_image_request(response_text)
            if draw_result:
                await send_msg(msg_type, recipient_id, f"[CQ:image,file={draw_result}]")
                db.insert_chat_message(user_id, user_input, f"[CQ:image,file={draw_result}]", context_type, context_id)
            else:
                await send_msg(msg_type, recipient_id, "抱歉，我无法生成这个图片。可能是提示词不够清晰或具体。")
        except Exception as e:
            logger.error(f"Error during image generation: {e}")
            await send_msg(msg_type, recipient_id, "图片生成过程中出现错误，请稍后再试。")
        return

@process_chat_message('private')
async def process_private_message(rev):
    logger.info(f"\nReceived private message from user {rev['sender']['user_id']}: {rev['raw_message']}\n")
    return rev['raw_message']

@process_chat_message('group')
async def process_group_message(rev):
    logger.info(f"\nReceived group message in group {rev['group_id']}: {rev['raw_message']}\n")

    user_input = rev['raw_message']
    group_id = rev['group_id']
    user_id = rev['sender']['user_id']

    block_id = config.BLOCK_ID
    contains_nickname = any(nickname in user_input for nickname in config.NICKNAMES)
    is_sender_blocked = user_id in block_id
    at_bot_message = r'\[CQ:at,qq={}\]'.format(config.SELF_ID)
    is_at_bot = re.search(at_bot_message, user_input)

    if re.search(at_bot_message, user_input):
        user_input = re.sub(at_bot_message, '', user_input).strip()
        return user_input  # 返回修改后的 user_input

    if (contains_nickname or is_at_bot) and not is_sender_blocked:
        return user_input  # 返回原始 user_input

    if random.random() <= config.REPLY_PROBABILITY and not is_sender_blocked:
        return user_input  # 随机回复的情况

    return None  # 明确表示不需要回复
