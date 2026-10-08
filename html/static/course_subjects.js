/* Use saved course rules; never expose editor drafts or suggested aliases. */
'use strict';
window.assignmentCourseSubjects = function (rules, assignments = [], extra = []) {
  const seen = new Set(), result = [];
  const add = value => {
    const name = String(value || '').trim(), key = name.toLocaleLowerCase();
    if (!name || name === '其他' || seen.has(key)) return;
    seen.add(key); result.push(name);
  };
  Object.entries(rules?.subjects || {}).filter(([, item]) => item.active !== false).forEach(([name]) => add(name));
  assignments.map(item => item.subject_group || item.subject).filter(Boolean)
    .sort((a, b) => a.localeCompare(b, 'zh-CN')).forEach(add);
  extra.forEach(add);
  return result;
};
