enum TaskMode {
  explainProblem,
  studyPlan,
  searchMaterials,
  reviewHomework,
  concept,
  masteryReport,
  practiceRecommendation,
  academicSearch,
  literatureFrontier,
  academicWriting,
  researchDataAnalysis,
  researchPlanning,
}

extension TaskModeInfo on TaskMode {
  String get title => switch (this) {
    TaskMode.explainProblem => '讲解一道题',
    TaskMode.studyPlan => '生成复习计划',
    TaskMode.searchMaterials => '检索我的课件',
    TaskMode.reviewHomework => '批改作业',
    TaskMode.concept => '知识点 / 概念讲解',
    TaskMode.masteryReport => '查看学习情况',
    TaskMode.practiceRecommendation => '推荐下一步练习',
    TaskMode.academicSearch => '搜索学术论文',
    TaskMode.literatureFrontier => '领域前沿追踪',
    TaskMode.academicWriting => '学术写作辅助',
    TaskMode.researchDataAnalysis => '科研数据分析',
    TaskMode.researchPlanning => '研究方案讨论',
  };

  String get description => switch (this) {
    TaskMode.explainProblem => '粘贴题目，一步步理清思路',
    TaskMode.studyPlan => '提供科目、考试时间和可用时间',
    TaskMode.searchMaterials => '输入课件名或需要检索的关键词',
    TaskMode.reviewHomework => '粘贴题目和你的作答，或添加附件',
    TaskMode.concept => '输入陌生名词，也可附上试题上下文',
    TaskMode.masteryReport => '查看掌握度、薄弱知识点和复习情况',
    TaskMode.practiceRecommendation => '根据课程和考试时间推荐练习',
    TaskMode.academicSearch => '通过 ArXiv 查找论文和研究资料',
    TaskMode.literatureFrontier => '检索论文，归纳热点、脉络与发展趋势',
    TaskMode.academicWriting => '生成综述、搭建框架、润色与规范检查',
    TaskMode.researchDataAnalysis => '分析实验、调查或文本资料并提炼结论',
    TaskMode.researchPlanning => '梳理研究问题、方法、条件与里程碑',
  };

  String get hint => switch (this) {
    TaskMode.explainProblem => '粘贴题目，并告诉我你卡在哪一步…',
    TaskMode.studyPlan => '例：高等数学，3 周后考试，每天可学 2 小时…',
    TaskMode.searchMaterials => '输入要在课件中查找的知识点或关键词…',
    TaskMode.reviewHomework => '粘贴题目和你的答案…',
    TaskMode.concept => '输入想单独了解的名词或知识点…',
    TaskMode.masteryReport => '例：查看数据结构课程的掌握情况…',
    TaskMode.practiceRecommendation => '例：操作系统，距离考试还有 3 周…',
    TaskMode.academicSearch => '输入论文主题、关键词或研究方向…',
    TaskMode.literatureFrontier => '输入研究领域、关键词和关注的时间范围…',
    TaskMode.academicWriting => '描述文稿类型、主题、目标期刊或修改要求…',
    TaskMode.researchDataAnalysis => '描述数据来源、字段、研究问题，或添加附件…',
    TaskMode.researchPlanning => '描述研究目标、现有条件和主要限制…',
  };

  String get instruction => switch (this) {
    TaskMode.explainProblem => '任务模式：讲解题目。先识别题目条件和学生卡点，再分步讲解思路和原理。',
    TaskMode.studyPlan => '任务模式：生成复习计划。根据科目、剩余时间和每日时间制定可执行的计划；信息不足时先追问。',
    TaskMode.searchMaterials => '任务模式：检索课件。优先使用知识库检索工具，并基于检索结果回答。',
    TaskMode.reviewHomework => '任务模式：批改作业。区分题目与学生作答，指出具体错误、原因和修改方法。',
    TaskMode.concept => '任务模式：知识点与概念讲解。包含通俗定义、正式定义、典型例子、相近概念区别以及在题目中的用法。',
    TaskMode.masteryReport => '任务模式：学习情况报告。调用掌握度报告工具，说明总体掌握度、薄弱点、优势点和需要复习的内容。',
    TaskMode.practiceRecommendation =>
      '任务模式：练习推荐。调用练习推荐工具，根据课程、掌握度和距离考试时间给出下一步练习顺序。',
    TaskMode.academicSearch =>
      '任务模式：学术论文搜索。优先使用 arxiv_search 工具，列出论文标题、摘要、作者、发布时间和链接。',
    TaskMode.literatureFrontier =>
      '任务模式：领域前沿追踪。先明确研究范围和时间窗口，再检索可靠论文来源，区分来源事实与趋势判断，归纳热点、演化脉络和研究空白。',
    TaskMode.academicWriting =>
      '任务模式：学术写作辅助。根据用户给出的材料与目标生成或修改学术文本；不得编造引用，明确标记缺少来源支持的内容。',
    TaskMode.researchDataAnalysis =>
      '任务模式：科研数据分析。先确认数据结构、研究问题与评价口径，再分析资料并区分观察结果、推断和限制；当前无法直接执行的分析应明确说明。',
    TaskMode.researchPlanning =>
      '任务模式：研究方案讨论。围绕研究问题、假设、数据、方法、资源、风险和成功标准形成结构化方案。',
  };

  String buildPrompt(String input) => '$instruction\n\n用户提供的内容：\n$input';
}
