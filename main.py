from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from .dnf_utils import DnfGoldRatioFetcher
import asyncio

@register("yuxuandnf", "Sir 丶雨轩", "雨轩DNF 查询插件。", "v1.0")
class DNF_Plugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 启动定时任务
        asyncio.get_event_loop().create_task(self.scheduled_task())

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
    
    async def scheduled_task(self):
        """定时任务：每隔1分钟在指定群发送消息"""
        logger.info("定时任务已启动，每隔1分钟发送消息")
        while True:
            try:
                # 发送消息到指定群
                # await self.context.send_message("101344113", "定时消息：DNF金币比例查询插件运行中...")
                logger.info("定时消息发送成功")
                # 等待1分钟
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"定时任务执行失败: {e}")
                # 出错后等待30秒再重试
                await asyncio.sleep(30)
    @filter.command("helloworld")
    async def helloworld(self, event: AstrMessageEvent):
        umo = event.unified_msg_origin
        message_chain = MessageChain().message("Hello!").file_image("path/to/image.jpg")
        await self.context.send_message(event.unified_msg_origin, message_chain)
    @filter.command("金币比例")
    async def dnf_gold_ratio(self, event):
        """查询 DNF 金币比例""" 
        user_name = event.get_sender_name()
        # 查询金币比例
        ratio_text = DnfGoldRatioFetcher.fetch_gold_ratio_text()
        yield event.plain_result(ratio_text)

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
