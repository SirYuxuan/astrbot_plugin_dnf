from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from .dnf_utils import DnfGoldRatioFetcher
import asyncio
import re
import os
import json
import requests
from astrbot.api.event import MessageChain

@register("yuxuandnf", "Sir 丶雨轩", "雨轩DNF 查询插件，支持金币比例查询和油价查询。", "v1.1")
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

    @filter.command("油价")
    async def oil_price(self, event):
        """查询油价信息"""
        try:
            # 获取消息内容，提取地区信息
            # 获取消息内容，提取地区信息
            # 根据日志显示，AiocqhttpMessageEvent对象有message_str属性
            message = ""
            if hasattr(event, 'message_str'):
                message = event.message_str
                logger.info(f"通过event.message_str获取到消息: {message}")
            elif hasattr(event, 'get_message_str'):
                message = event.get_message_str()
                logger.info(f"通过event.get_message_str()获取到消息: {message}")
            elif hasattr(event, 'message_obj'):
                message = str(event.message_obj)
                logger.info(f"通过event.message_obj获取到消息: {message}")
            else:
                # 如果都找不到，尝试从事件的其他属性获取
                message = str(event)
                logger.info(f"通过str(event)获取到消息: {message}")
            
            # 提取地区名称，格式：油价 河南
            area_match = re.search(r'油价\s+(.+)', message)
            if not area_match:
                yield event.plain_result("请使用格式：油价 地区名\n例如：油价 河南")
                return
            
            area = area_match.group(1).strip()
            
            # 构建API请求URL
            api_url = "https://www.iamwawa.cn/oilprice/api"
            params = {"area": area}
            
            # 发送HTTP请求
            response = requests.get(api_url, params=params, timeout=10)
            response.raise_for_status()
            
            # 解析返回的JSON数据
            data = response.json()
            
            if data.get("status") == 1 and "data" in data:
                oil_data = data["data"]
                
                # 构建油价信息文本
                oil_info = f"📊 {oil_data['name']}油价信息\n"
                oil_info += f"📅 更新时间：{oil_data['date']}\n"
                oil_info += f"⛽ 92号汽油：{oil_data['p92']}元/升\n"
                oil_info += f"⛽ 95号汽油：{oil_data['p95']}元/升\n"
                oil_info += f"⛽ 98号汽油：{oil_data['p98']}元/升\n"
                oil_info += f"⛽ 0号柴油：{oil_data['p0']}元/升\n"
                
                # 添加其他油品信息（如果存在且不为"-"）
                if oil_data.get('p10') and oil_data['p10'] != "-":
                    oil_info += f"⛽ 10号柴油：{oil_data['p10']}元/升\n"
                if oil_data.get('p20') and oil_data['p20'] != "-":
                    oil_info += f"⛽ 20号柴油：{oil_data['p20']}元/升\n"
                if oil_data.get('p35') and oil_data['p35'] != "-":
                    oil_info += f"⛽ 35号柴油：{oil_data['p35']}元/升\n"
                
                oil_info += f"🔄 下次更新时间：{oil_data['next_update_time']}"
                
                yield event.plain_result(oil_info)
            else:
                yield event.plain_result(f"查询失败：{data.get('message', '未知错误')}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"油价查询请求失败: {e}")
            yield event.plain_result("油价查询失败，请稍后重试")
        except json.JSONDecodeError as e:
            logger.error(f"油价数据解析失败: {e}")
            yield event.plain_result("油价数据解析失败，请稍后重试")
        except Exception as e:
            logger.error(f"油价查询异常: {e}")
            yield event.plain_result("油价查询出现异常，请稍后重试")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
