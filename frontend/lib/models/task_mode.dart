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
  String get wireName => switch (this) {
    TaskMode.explainProblem => 'explain_problem',
    TaskMode.studyPlan => 'study_plan',
    TaskMode.searchMaterials => 'search_materials',
    TaskMode.reviewHomework => 'review_homework',
    TaskMode.concept => 'concept',
    TaskMode.masteryReport => 'mastery_report',
    TaskMode.practiceRecommendation => 'practice_recommendation',
    TaskMode.academicSearch => 'academic_search',
    TaskMode.literatureFrontier => 'literature_frontier',
    TaskMode.academicWriting => 'academic_writing',
    TaskMode.researchDataAnalysis => 'research_data_analysis',
    TaskMode.researchPlanning => 'research_planning',
  };

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
}
