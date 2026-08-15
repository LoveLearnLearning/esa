# backend/agent/tools/read_file.py

"""提供 `read_file` 相关功能。"""


from backend.agent.tools.tools import tr


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "read_file_from_user",
            "description": "读取并处理用户上传的附件",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件路径",
                    },
                    "type": {
                        "enum": [
                            "pdf",
                            "docx",
                        ],
                        "description": "文件类型",
                    },
                    "adaptor": {
                        "enum": [
                            "mineru",
                        ],
                        "default": "mineru",
                    },
                },
                "required": [
                    "file_paths",
                    "type",
                ],
            },
        },
    }
)
def read_file_from_user(file_path: str, type: str, adaptor: str = "mineru") -> str:
    """读取 `file from user` 相关数据。

    Args:
        file_path: str => 文件路径。
        type: str => `type` 参数。
        adaptor: str => `adaptor` 参数。

    Returns:
        str => 处理结果。
    """
    raise NotImplementedError
