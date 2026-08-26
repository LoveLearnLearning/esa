---
name: math_problem_solving
description: 数学和位运算
version: 2
category: reasoning
priority: 88
autoload: false
triggers: [numeric_calculation, symbolic_math, bitwise_calculation, mathematical_derivation]
requires_tools: [calculator, math_solver, bitwise_calculator]
related_skills: []
---

# 数学求解

提取目标、变量、约束和定义域；歧义会改变结果才询问。数值用 `calculator`，符号式/方程/微积分用 `math_solver`，位运算用 `bitwise_calculator`。给结论、关键步骤、条件和必要验算；失败时说明未校验。保留精确值，近似值注明精度；无解、多解、定义域或溢出必须明确。
