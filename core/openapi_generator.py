"""
quanquan API 自动文档生成器

生成 OpenAPI 3.0 规范，可直接导入 Swagger UI / Redoc
"""

import json
from typing import Dict, Any


def generate_openapi_spec(
    title: str = "quanquan API",
    version: str = "3.0.0",
    host: str = "localhost:8000",
) -> Dict[str, Any]:
    """生成完整的 OpenAPI 3.0 规范"""

    return {
        "openapi": "3.0.3",
        "info": {
            "title": title,
            "version": version,
            "description": (
                "quanquan 全自动剪辑系统 API — 多Agent视频生产平台\n\n"
                "## 功能\n"
                "- 🎬 多Agent协作视频生成（Director/Scriptwriter/Storyboard/Voiceover/BGM/QC/Delivery）\n"
                "- 🎥 大容量视频分段处理 + GPU加速编码\n"
                "- 📱 8平台自适应导出（抖音/YouTube/B站/小红书/微信/Insta/TikTok/快手）\n"
                "- 🔍 AI高光时刻提取 + 智能封面生成\n"
                "- 🎤 语音转视频 + 数字人/虚拟主播\n"
                "- 🌐 多语言字幕翻译（12种语言）\n"
                "- 🧠 Milvus向量检索 + 6风格冷启动\n"
                "- 🔌 插件系统 + WebSocket实时推送\n"
            ),
            "contact": {"name": "quanquan Team"},
        },
        "servers": [
            {"url": f"http://{host}", "description": "本地开发"},
        ],
        "tags": [
            {"name": "projects", "description": "项目管理"},
            {"name": "encoding", "description": "视频编码"},
            {"name": "analysis", "description": "视频分析"},
            {"name": "ai", "description": "AI 能力"},
            {"name": "system", "description": "系统管理"},
        ],
        "paths": {
            "/api/v1/health": {
                "get": {
                    "tags": ["system"],
                    "summary": "系统健康检查",
                    "responses": {
                        "200": {"description": "OK"}
                    }
                }
            },
            "/api/v1/create": {
                "post": {
                    "tags": ["projects"],
                    "summary": "创建视频项目",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string", "example": "3分钟赛博朋克解说视频"},
                                        "duration": {"type": "integer", "example": 180},
                                        "style": {"type": "string", "example": "cyberpunk"},
                                        "user_id": {"type": "string"},
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "项目创建成功"},
                    }
                }
            },
            "/api/v1/director/status": {
                "get": {
                    "tags": ["system"],
                    "summary": "导演状态 + GPU 信息",
                    "responses": {"200": {"description": "状态信息"}},
                }
            },
            "/api/v1/video/inspect": {
                "post": {
                    "tags": ["analysis"],
                    "summary": "探测视频元信息",
                    "parameters": [
                        {"name": "path", "in": "query", "required": True, "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"description": "视频元信息"}},
                }
            },
            "/api/v1/video/chunk": {
                "post": {
                    "tags": ["analysis"],
                    "summary": "分段处理视频",
                    "parameters": [
                        {"name": "path", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "strategy", "in": "query", "schema": {"type": "string", "enum": ["scene_detect", "fixed_duration"]}},
                    ],
                    "responses": {"200": {"description": "分段结果"}},
                }
            },
            "/api/v1/encode": {
                "post": {
                    "tags": ["encoding"],
                    "summary": "GPU加速编码",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "input_path": {"type": "string"},
                                        "output_path": {"type": "string"},
                                        "codec": {"type": "string", "enum": ["h264", "h265", "av1"]},
                                        "crf": {"type": "integer"},
                                        "use_gpu": {"type": "boolean"},
                                    }
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "编码完成"}},
                }
            },
            "/api/v1/gpu/detect": {
                "get": {
                    "tags": ["encoding"],
                    "summary": "检测可用 GPU",
                    "responses": {"200": {"description": "GPU 列表"}},
                }
            },
            "/api/v1/inspect": {
                "post": {
                    "tags": ["analysis"],
                    "summary": "自动化验片",
                    "parameters": [
                        {"name": "path", "in": "query", "required": True, "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"description": "验片报告"}},
                }
            },
            "/api/v1/memory/profile": {
                "get": {
                    "tags": ["ai"],
                    "summary": "查询记忆画像（含冷启动）",
                    "parameters": [
                        {"name": "user_id", "in": "query", "schema": {"type": "string"}},
                        {"name": "tags", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"description": "用户画像"}},
                }
            },
            "/api/v1/memory/templates": {
                "get": {
                    "tags": ["ai"],
                    "summary": "列出冷启动模板",
                    "responses": {"200": {"description": "模板列表"}},
                }
            },
            "/api/v1/search": {
                "post": {
                    "tags": ["ai"],
                    "summary": "向量语义搜索",
                    "responses": {"200": {"description": "搜索结果"}},
                }
            },
            "/api/v1/proxy/generate": {
                "post": {
                    "tags": ["encoding"],
                    "summary": "生成代理文件",
                    "responses": {"200": {"description": "代理生成结果"}},
                }
            },
        },
        "components": {
            "schemas": {
                "ProjectCreate": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "视频主题描述"},
                        "duration": {"type": "integer", "default": 180},
                        "style": {"type": "string", "default": "auto"},
                        "user_id": {"type": "string"},
                    }
                },
                "EncodeConfig": {
                    "type": "object",
                    "properties": {
                        "input_path": {"type": "string"},
                        "output_path": {"type": "string"},
                        "codec": {"type": "string", "enum": ["h264", "h265", "av1"]},
                        "crf": {"type": "integer", "minimum": 0, "maximum": 51},
                        "use_gpu": {"type": "boolean", "default": True},
                    }
                },
                "InspectionReport": {
                    "type": "object",
                    "properties": {
                        "verdict": {"type": "string", "enum": ["PASS", "WARN", "FAIL"]},
                        "duration_sec": {"type": "number"},
                        "black_frames": {"type": "integer"},
                        "silence_segments": {"type": "integer"},
                        "av_sync_ms": {"type": "number"},
                    }
                },
            }
        },
    }


def save_openapi_spec(filepath: str = "config/openapi.json"):
    """保存 OpenAPI 规范到文件"""
    import os
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    spec = generate_openapi_spec()
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)
    return filepath


if __name__ == "__main__":
    path = save_openapi_spec()
    print(f"OpenAPI spec generated: {path}")
