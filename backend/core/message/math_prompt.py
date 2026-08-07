# backend/core/message/math_prompt.py

MATH_PRMOPT: str = """
# 在用户给出数学问题后必须执行以下操作

1. 先通过调用 `math_solver` 工具算出正确结果 如果计算有多个步骤要分解步骤得到所有的结果
2. 通过得到的结果以及步骤来为用户定制学习路线
3. 不得修改 `math_solver` 返回的答案

"""
