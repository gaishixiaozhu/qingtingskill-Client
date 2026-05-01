# -*- coding: utf-8 -*-
"""
蜻蜓志愿数据查询 - Client OpenClaw Skill v3.0

功能：
1. 验证API Key（识别客户、验证权限）
2. 接收用户问题
3. 转发到Server OpenClaw
4. 异步进度反馈
5. 用 display 结构化数据渲染友好输出（表格/分类/颜色标记）

v3.0 新增：不再透传服务端纯文本答案，改为用 display 结构数据渲染美观输出

部署位置：Client OpenClaw的skills目录
"""

import os
import time
import uuid
import requests
from typing import Dict, Optional, List

from config import SERVER_URL, TIMEOUT, RETRIES


# ============ 输出渲染器 ============

class DisplayRenderer:
    """将服务端 display 结构化数据渲染为客户端友好文本"""
    
    @staticmethod
    def render(display: Dict, answer: str = "") -> str:
        """根据 display type 渲染输出"""
        if not display:
            return answer or "查询完成"
        
        dtype = display.get("type", "")
        
        if dtype == "recommend":
            return DisplayRenderer._render_recommend(display, answer)
        elif dtype == "table":
            return DisplayRenderer._render_table(display, answer)
        elif dtype == "list":
            return DisplayRenderer._render_list(display, answer)
        elif dtype == "empty":
            return display.get("message", "未查询到相关数据")
        else:
            return answer or "查询完成"
    
    @staticmethod
    def _render_recommend(display: Dict, answer: str) -> str:
        """渲染志愿推荐 - 三层表格"""
        title = display.get("title", "🎯 志愿推荐方案")
        subtitle = display.get("subtitle", "")
        total = display.get("total", 0)
        columns = display.get("columns", [])
        
        lines = [f"## {title}", f"> {subtitle} | 共{total}条", ""]
        
        sections = [
            ("chongci", display.get("chongci")),
            ("kuoshi", display.get("kuoshi")),
            ("wentuo", display.get("wentuo")),
        ]
        
        for key, section in sections:
            if not section:
                continue
            label = section.get("label", "")
            desc = section.get("desc", "")
            items = section.get("items", [])
            count = section.get("count", len(items))
            
            if not items:
                continue
            
            lines.append(f"### {label}（{desc}）共{count}个")
            lines.append("")
            
            # 表头
            if columns:
                header = "| " + " | ".join(columns) + " |"
                sep = "|" + "|".join([" :--- "] * len(columns)) + "|"
                lines.append(header)
                lines.append(sep)
            
            # 数据行
            for item in items[:30]:
                school = item.get("school", "")
                pro = item.get("pro", "")
                
                # 备注合并：院校备注 + 专业备注
                school_note = item.get("school_note", "") or ""
                pro_note = item.get("pro_note", "") or ""
                notes = []
                if school_note:
                    notes.append(school_note)
                if pro_note:
                    notes.append(pro_note)
                note_str = "；".join(notes) if notes else "-"
                
                plan = item.get("plan", "-")
                tuition = item.get("tuition", "-")
                if tuition and isinstance(tuition, (int, float)) and tuition > 0:
                    if tuition >= 10000:
                        tuition_str = f"{tuition/10000:.1f}万"
                    else:
                        tuition_str = str(tuition)
                else:
                    tuition_str = str(tuition) if tuition else "-"
                
                score = item.get("score", "-")
                rank = item.get("rank", "-")
                diff = item.get("diff", 0)
                
                # 分差颜色标记
                if diff > 0:
                    diff_str = f"+{diff}📈"
                elif diff == 0:
                    diff_str = "0➖"
                else:
                    diff_str = f"{diff}📉"
                
                row = [school, pro, note_str, str(plan), tuition_str, str(score), str(rank), diff_str]
                lines.append("| " + " | ".join(row) + " |")
            
            lines.append("")
        
        # 附上服务端LLM的专家建议
        if answer and answer != "查询完成":
            # 提取answer中的建议部分（排除重复的表格内容）
            lines.append("---")
            lines.append("### 💡 专家建议")
            lines.append(answer[:600])
        
        lines.append("")
        lines.append("📌 数据来源：蜻蜓生涯数据库 | ⚠️ 仅供参考，以官方公布为准")
        
        return "\n".join(lines)
    
    @staticmethod
    def _render_table(display: Dict, answer: str) -> str:
        """渲染普通表格"""
        title = display.get("title", "查询结果")
        columns = display.get("columns", [])
        items = display.get("items", [])
        
        lines = [f"## {title}", f"> 共{len(items)}条", ""]
        
        if not items:
            lines.append("暂无数据")
            return "\n".join(lines)
        
        if columns:
            header = "| " + " | ".join(columns) + " |"
            sep = "|" + "|".join([" :--- "] * len(columns)) + "|"
            lines.append(header)
            lines.append(sep)
        
        for item in items[:50]:
            if isinstance(item, dict):
                row = []
                for col in columns:
                    val = item.get(col, "") or ""
                    row.append(str(val))
                lines.append("| " + " | ".join(row) + " |")
            else:
                lines.append(str(item))
        
        lines.append("")
        
        if answer and len(answer) < 1000:
            lines.append(f"📌 {answer[:500]}")
        
        return "\n".join(lines)
    
    @staticmethod
    def _render_list(display: Dict, answer: str) -> str:
        """渲染列表"""
        title = display.get("title", "查询结果")
        items = display.get("items", [])
        
        lines = [f"## {title}", f"> 共{len(items)}条", ""]
        
        for i, item in enumerate(items[:30], 1):
            if isinstance(item, str):
                lines.append(f"{i}. {item}")
            elif isinstance(item, dict):
                lines.append(f"{i}. " + " | ".join(str(v) for v in item.values()))
        
        if answer and len(answer) < 500:
            lines.append(f"\n{answer}")
        
        return "\n".join(lines)


# ============ 转发核心 ============
class QingtingQuerySkill:
    """
    蜻蜓志愿数据查询Skill v3.0
    
    工作流程：
    1. 接收用户问题
    2. 检查API Key
    3. 检查是否需要三必填条件提醒
    4. 使用异步接口获取job_id
    5. 轮询进度，用 display 数据渲染友好输出
    """
    
    def __init__(self, api_key: str = None, server_url: str = None):
        self.api_key = api_key or os.getenv("QINGTING_API_KEY", "")
        self.server_url = (server_url or SERVER_URL).rstrip('/')
        self.timeout = TIMEOUT
        self.retries = RETRIES
        self.poll_interval = 1
        self.max_polls = 120
        self.renderer = DisplayRenderer()
    
    def _submit_async(self, user_id: str, session_id: str, question: str) -> Dict:
        """提交异步任务，返回job_id"""
        url = f"{self.server_url}/api/v1/chat/async"
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "question": question
        }
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key
        }
        
        resp = requests.post(url, json=payload, timeout=30, headers=headers)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            return {"success": False, "error": "API Key无效"}
        else:
            return {"success": False, "error": f"提交失败: {resp.status_code}"}
    
    def _poll_status(self, job_id: str) -> Dict:
        """轮询任务状态"""
        url = f"{self.server_url}/api/v1/job/{job_id}"
        headers = {"X-API-Key": self.api_key}
        
        resp = requests.get(url, timeout=10, headers=headers)
        if resp.status_code == 200:
            return resp.json()
        return {"status": "error", "message": "查询状态失败"}
    
    def _make_request(self, user_id: str, session_id: str,
                     question: str, context: List[Dict] = None) -> Dict:
        """发送请求到Server OpenClaw，返回 display + answer"""
        
        submit_result = self._submit_async(user_id, session_id, question)
        
        if not submit_result.get("success"):
            return {
                "success": False,
                "answer": submit_result.get("error", "提交任务失败")
            }
        
        job_id = submit_result.get("job_id")
        if not job_id:
            return {
                "success": False,
                "answer": "获取任务ID失败"
            }
        
        for i in range(self.max_polls):
            time.sleep(self.poll_interval)
            
            status_result = self._poll_status(job_id)
            status = status_result.get("status")
            
            if status == "completed":
                return {
                    "success": True,
                    "answer": status_result.get("answer", ""),
                    "display": status_result.get("display"),
                    "job_id": job_id,
                    "intent": status_result.get("intent", ""),
                    "conditions": status_result.get("conditions", {}),
                    "data": status_result.get("data", [])
                }
            
            elif status in ("error", "failed"):
                return {
                    "success": False,
                    "answer": status_result.get("message", "任务处理失败")
                }
        
        return {
            "success": False,
            "answer": "处理超时，请稍后再试"
        }
    
    def _check_conditions(self, question: str) -> Optional[str]:
        """检查三必填条件"""
        q = question.lower()
        
        recommend_keywords = ["志愿", "推荐", "方案", "填报", "生成", "多少个"]
        has_recommend = any(kw in q for kw in recommend_keywords)
        
        if not has_recommend:
            return None
        
        provinces = ["辽宁", "山东", "四川", "河南", "广东", "江苏", "浙江",
                    "河北", "湖北", "湖南", "安徽", "福建", "江西", "山西",
                    "陕西", "甘肃", "吉林", "黑龙江", "北京", "天津", "上海",
                    "重庆", "贵州", "云南", "广西", "海南", "内蒙古", "宁夏", "青海", "新疆"]
        
        has_province = any(prov in q for prov in provinces)
        
        natures = ["物理", "历史", "理科", "文科"]
        has_nature = any(nat in q for nat in natures)
        
        import re
        has_score = bool(re.search(r"\d{3}分", q))
        has_rank = "位次" in q or "名" in q
        
        missing = []
        if not has_province:
            missing.append("省份")
        if not has_nature:
            missing.append("科类（物理类/历史类）")
        if not has_score and not has_rank:
            missing.append("分数或位次")
        
        if missing:
            lines = ["⚠️ 为了给您提供准确的推荐，请补充以下信息："]
            for i, m in enumerate(missing, 1):
                lines.append(f"  {i}. {m}")
            lines.append("")
            lines.append("请告诉我您的完整信息，例如：辽宁物理类520分能上什么学校？")
            return "\n".join(lines)
        
        return None
    
    def chat(self, user_input: str, user_id: str = None,
             session_id: str = None) -> Dict:
        """处理用户消息 - 用 display 数据渲染友好输出"""
        
        if not self.api_key:
            return {
                "success": False,
                "answer": "⚠️ 请先配置您的API Key才能使用蜻蜓志愿数据查询服务。\n\n如需API Key请联系管理员。"
            }
        
        if not user_id:
            user_id = f"user_{uuid.uuid4().hex[:8]}"
        if not session_id:
            session_id = f"sess_{int(time.time())}"
        
        condition_warning = self._check_conditions(user_input)
        if condition_warning:
            return {
                "success": True,
                "answer": condition_warning,
                "warning": True
            }
        
        result = self._make_request(user_id, session_id, user_input)
        
        if result.get("success"):
            display = result.get("display")
            answer = result.get("answer", "")
            
            # 用 display 结构化数据渲染友好输出
            if display:
                rendered = self.renderer.render(display, answer)
            else:
                # 没有display数据（老版本服务端），降级用纯文本答案
                rendered = answer or "查询完成"
            
            return {
                "success": True,
                "answer": rendered,
                "job_id": result.get("job_id"),
                "display": display
            }
        else:
            return {
                "success": False,
                "answer": result.get("answer", "处理失败")
            }
    
    def health_check(self) -> bool:
        """检查Server连接"""
        try:
            resp = requests.get(
                f"{self.server_url}/api/v1/health",
                timeout=5
            )
            return resp.status_code == 200
        except Exception:
            return False
    
    def verify_key(self) -> Dict:
        """验证API Key状态"""
        try:
            resp = requests.get(
                f"{self.server_url}/api/v1/key/verify",
                params={"api_key": self.api_key},
                timeout=5
            )
            if resp.status_code == 200:
                return resp.json()
            return {"valid": False, "message": "验证失败"}
        except Exception as e:
            return {"valid": False, "message": str(e)}


# 全局实例
_skill = None

def get_skill(api_key: str = None) -> QingtingQuerySkill:
    """获取Skill实例"""
    global _skill
    if _skill is None:
        _skill = QingtingQuerySkill(api_key=api_key)
    return _skill


def handle_message(user_input: str, user_id: str = None,
                   session_id: str = None, api_key: str = None) -> str:
    """Skill主入口函数"""
    skill = get_skill(api_key=api_key)
    result = skill.chat(user_input, user_id, session_id)
    return result.get("answer", "")


# ============ CLI测试 ============
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="蜻蜓志愿数据查询测试")
    parser.add_argument("--question", "-q", help="测试问题")
    parser.add_argument("--api-key", help="API Key")
    parser.add_argument("--server", help="Server URL")
    parser.add_argument("--raw", action="store_true", help="显示原始服务端答案（不渲染）")
    args = parser.parse_args()
    
    skill = get_skill(api_key=args.api_key)
    
    if args.server:
        skill.server_url = args.server
    
    if args.question:
        start = time.time()
        result = skill.chat(args.question)
        elapsed = time.time() - start
        print(f"\n⏱️ 用时: {elapsed:.1f}秒")
        print("=" * 60)
        print(result.get("answer", ""))
        
        if args.raw:
            print("\n" + "=" * 60)
            print("原始数据:")
            print("=" * 60)
            display = result.get("display")
            if display:
                import json
                print(json.dumps(display, ensure_ascii=False, indent=2)[:2000])
    else:
        if skill.health_check():
            print("✅ Server连接正常")
            print(f"Server: {skill.server_url}")
        else:
            print("❌ Server连接失败")
        
        key_result = skill.verify_key()
        print(f"API Key: {key_result}")
