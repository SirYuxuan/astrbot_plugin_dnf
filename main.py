from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from .dnf_utils import DnfGoldRatioFetcher

@register("yuxuandnf", "Sir 丶雨轩", "雨轩DNF 查询插件。", "v1.0")
class DNF_Plugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
    
    @filter.command("金币比例")
    async def dnf_gold_ratio(self, event):
        """查询 DNF 金币比例""" 
        user_name = event.get_sender_name()
        # 查询金币比例
        ratio_text = DnfGoldRatioFetcher.fetch_gold_ratio_text()
        yield event.plain_result(ratio_text)

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
