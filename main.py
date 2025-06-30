from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from .dnf_utils import DnfGoldRatioFetcher
import asyncio
import re
import os
import json
from astrbot.api.event import MessageChain

@register("yuxuandnf", "Sir 丶雨轩", "雨轩DNF 查询插件。", "v1.0")
class DNF_Plugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.last_avg_ratio = None
        self.ratio_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_avg_ratio.json')
        self.load_last_avg_ratio()
        self.last_sent_avg_ratio = None
        self.sent_ratio_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_sent_avg_ratio.json')
        self.load_last_sent_avg_ratio()
        asyncio.get_event_loop().create_task(self.scheduled_task())

    def load_last_avg_ratio(self):
        if os.path.exists(self.ratio_file):
            try:
                with open(self.ratio_file, 'r') as f:
                    data = json.load(f)
                    self.last_avg_ratio = data.get('last_avg_ratio')
            except Exception as e:
                logger.error(f"读取上次均价失败: {e}")

    def save_last_avg_ratio(self):
        try:
            with open(self.ratio_file, 'w') as f:
                json.dump({'last_avg_ratio': self.last_avg_ratio}, f)
        except Exception as e:
            logger.error(f"保存上次均价失败: {e}")

    def load_last_sent_avg_ratio(self):
        if os.path.exists(self.sent_ratio_file):
            try:
                with open(self.sent_ratio_file, 'r') as f:
                    data = json.load(f)
                    val = data.get('last_sent_avg_ratio')
                    if val is not None:
                        self.last_sent_avg_ratio = float(val)
            except Exception as e:
                logger.error(f"读取上次发送均价失败: {e}")

    def save_last_sent_avg_ratio(self):
        try:
            with open(self.sent_ratio_file, 'w') as f:
                json.dump({'last_sent_avg_ratio': self.last_sent_avg_ratio}, f)
        except Exception as e:
            logger.error(f"保存上次发送均价失败: {e}")

    def parse_avg_ratio(self, ratio_text):
        match = re.search(r'均价：1元=([\d.]+)万金币', ratio_text)
        if match:
            return float(match.group(1))
        return None

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
    
    async def scheduled_task(self):
        logger.info("定时任务已启动，每分钟检测金币比例波动")
        while True:
            try:
                platform = None
                for p in self.context.platform_manager.get_insts():
                    if p.meta().name == "aiocqhttp":
                        platform = p
                        break
                if platform:
                    client = platform.get_client()
                    ratio_text = DnfGoldRatioFetcher.fetch_gold_ratio_text()
                    avg_ratio = self.parse_avg_ratio(ratio_text)
                    if avg_ratio is not None:
                        avg_ratio_fmt = f"{avg_ratio:.2f}"
                        send_msg = False
                        msg = None
                        if self.last_sent_avg_ratio is not None:
                            diff = avg_ratio - self.last_sent_avg_ratio
                            diff_fmt = f"{diff:+.2f}"
                            if abs(diff) >= 2:
                                msg = f"金币比例波动：上次发送均价 {self.last_sent_avg_ratio:.2f}，本次均价 {avg_ratio_fmt}，变动 {diff_fmt}万金币"
                                send_msg = True
                            # 否则不发消息
                        else:
                            msg = f"首次监控，当前金币均价：{avg_ratio_fmt}万金币"
                            send_msg = True
                        if send_msg:
                            await client.send_group_msg(
                                group_id=101344113,
                                message=msg
                            )
                            self.last_sent_avg_ratio = avg_ratio
                            self.save_last_sent_avg_ratio()
                        self.last_avg_ratio = avg_ratio
                        self.save_last_avg_ratio()
                    else:
                        logger.info("未能获取到金币均价数据")
                logger.info("定时检测完成")
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"定时任务执行失败: {e}")
                await asyncio.sleep(30)

    @filter.command("金币比例")
    async def dnf_gold_ratio(self, event):
        """查询 DNF 金币比例""" 
        user_name = event.get_sender_name()
        ratio_text = DnfGoldRatioFetcher.fetch_gold_ratio_text()
        yield event.plain_result(ratio_text)

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
