# -*- coding: utf-8 -*-
"""
蜻蜓志愿数据查询 - Client OpenClaw Skill v3.0

架构：
1. 接收用户问题
2. 转发到服务端获取数据
3. 直接返回答案（服务端已整合好）
"""

import os
import time
import uuid
import requests
from typing import Dict, Optional

from config import SERVER_URL, TIMEOUT, RETRIES


class QingtingQuerySkill:
    """蜻蜓志愿数据查询Skill"""
    
    def __init__(self, api_key: str = None, server_url: str = None):
        self.api_key = api_key or os.getenv("QINGTING_API_KEY", "")
        self.server_url = (server_url or SERVER_URL).rstrip('/')
        self.timeout = TIMEOUT
        self.retries = RETRIES
        self.poll_interval = 1
        self.max_polls = 120
    
    def _submit_async(self, user_id: str, session_id: str, question: str) -> Dict:
        """提交异步任务"""
        url = f"{self.server_url}/api/v1/chat/async"
        payload = {"user_id": user_id, "session_id": session_id, "question": question}
        headers = {"Content-Type": "application/json", "X-API-Key": self.api_key}
        
        resp = requests.post(url, json=payload, timeout=30, headers=headers)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            return {"success": False, "error": "API Key无效"}
        return {"success": False, "error": f"提交失败: {resp.status_code}"}
    
    def _poll_status(self, job_id: str) -> Dict:
        """轮询任务状态"""
        url = f"{self.server_url}/api/v1/job/{job_id}"
        headers = {"X-API-Key": self.api_key}
        resp = requests.get(url, timeout=10, headers=headers)
        if resp.status_code == 200:
            return resp.json()
        return {"status": "error", "message": "查询状态失败"}
    
    def chat(self, user_input: str, user_id: str = None, session_id: str = None) -> Dict:
        """处理用户消息"""
        if not self.api_key:
            return {"success": False, "answer": "⚠️ 请先配置API Key"}
        
        if not user_id:
            user_id = f"user_{uuid.uuid4().hex[:8]}"
        if not session_id:
            session_id = f"sess_{int(time.time())}"
        
        # 提交异步任务
        submit_result = self._submit_async(user_id, session_id, user_input)
        if not submit_result.get("success"):
            return {"success": False, "answer": submit_result.get("error", "提交失败")}
        
        job_id = submit_result.get("job_id")
        if not job_id:
            return {"success": False, "answer": "获取任务ID失败"}
        
        # 轮询等待结果
        for _ in range(self.max_polls):
            time.sleep(self.poll_interval)
            status_result = self._poll_status(job_id)
            status = status_result.get("status")
            
            if status == "completed":
                answer = status_result.get("answer", "")
                data = status_result.get("data", [])
                
                # 如果有结构化数据且没有LLM答案，简单格式化
                if not answer and data:
                    answer = self._format_data(status_result.get("intent", ""), data)
                
                return {
                    "success": True,
                    "answer": answer,
                    "intent": status_result.get("intent"),
                    "data_count": len(data)
                }
            
            elif status in ("error", "failed"):
                return {"success": False, "answer": status_result.get("message", "任务失败")}
        
        return {"success": False, "answer": "处理超时"}
    
    def _format_data(self, intent: str, data: list) -> str:
        """简单格式化数据（备用）"""
        if not data:
            return "未查询到相关数据"
        
        lines = [f"📊 查询到 {len(data)} 条记录：\n"]
        for i, row in enumerate(data[:30], 1):
            if intent == "query_rank":
                lines.append(f"{i}. 分数:{row.get('score','-')} | 位次:{row.get('rank','-')}")
            elif intent == "query_plan":
                lines.append(f"{i}. {row.get('school','-')} | {row.get('pro','-')} | 计划{row.get('plan_num','-')}人")
            elif intent == "query_score":
                lines.append(f"{i}. {row.get('school','-')} | {row.get('pro','-')} | {row.get('year','-')}年:{row.get('low_real','-')}分")
            elif intent == "query_school":
                lines.append(f"{i}. {row.get('school','-')} | {row.get('province','-')}{row.get('city','-') or ''}")
            else:
                lines.append(f"{i}. {row}")
        
        if len(data) > 30:
            lines.append(f"\n... 共 {len(data)} 条记录")
        return "\n".join(lines)
    
    def health_check(self) -> bool:
        """检查服务端连接"""
        try:
            resp = requests.get(f"{self.server_url}/api/v1/health", timeout=5)
            return resp.status_code == 200
        except:
            return False


# ============ 全局实例 ============
_skill = None

def get_skill(api_key: str = None) -> QingtingQuerySkill:
    global _skill
    if _skill is None:
        _skill = QingtingQuerySkill(api_key=api_key)
    return _skill


def handle_message(user_input: str, user_id: str = None, session_id: str = None, api_key: str = None) -> str:
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
    args = parser.parse_args()
    
    skill = get_skill(api_key=args.api_key)
    
    if args.question:
        start = time.time()
        result = skill.chat(args.question)
        elapsed = time.time() - start
        print(f"\n用时: {elapsed:.1f}秒")
        print("=" * 60)
        print(result.get("answer", ""))
    else:
        if skill.health_check():
            print("✅ 服务端连接正常")
        else:
            print("❌ 服务端连接失败")
