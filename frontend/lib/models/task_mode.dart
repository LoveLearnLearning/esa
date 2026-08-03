enum TaskMode {
  explainProblem,
  studyPlan,
  searchMaterials,
  reviewHomework,
  concept,
  masteryReport,
  practiceRecommendation,
  academicSearch,
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
  };

  String buildPrompt(String input) => '$instruction\n\n用户提供的内容：\n$input';
}
