  function draft() { return { kw: el("kw").value.replace(/^\s+|\s+$/g, ""), cat: parseInt(el("cat3").value, 10) || parseInt(el("cat2").value, 10) || parseInt(el("cat").value, 10) || 0, chosen: copyMap(state.catalog.chosen) }; }
  function changed() { var d = draft(), a = state.catalog.applied; return !a || d.kw !== a.kw || d.cat !== a.cat || mapKey(d.chosen) !== mapKey(a.chosen); }
  function scope() {
    var pending = state.catalog.hasQuery && changed(), label = state.catalog.busy ? "正在查询：" + state.catalog.loading.label : !state.catalog.hasQuery ? "尚未查询" : "当前结果：" + state.catalog.criteriaText;
    if (pending) { label += "（筛选已修改，点击查询应用）"; }
    text(el("resultscope"), label); el("resultscope").title = label; el("resultscope").className = pending ? "pending" : "";
    text(el("dirtyhint"), pending ? "有修改，查询后应用" : "");
  }
  function markDirty() { scope(); chips(); parameterCount(); notice(changed() ? "筛选条件已修改，点击“查询”更新结果" : state.catalog.hasQuery ? "查询完成 · 单击预览，双击放置" : "选择条件后点击“查询”"); }
  function parameterCount() { var count = 0, k; for (k in state.catalog.chosen) { if (state.catalog.chosen.hasOwnProperty(k) && state.catalog.chosen[k].length) { count++; } } text(el("allparamcount"), "共 " + state.catalog.facets.length + " 项参数 · 已选 " + count + " 项属性"); }
  function facet(key) { for (var i = 0; i < state.catalog.facets.length; i++) { if (state.catalog.facets[i].key === key) { return state.catalog.facets[i]; } } return null; }
  function valueLabel(f, value) { for (var i = 0; f && i < f.values.length; i++) { if (f.values[i].value === value) { return f.values[i].label; } } return value; }
  function fieldTitle(f) { return f.key + (f.note ? "\n" + f.note : ""); }
  function criteriaText(d) {
    var pieces = [], ids = ["cat", "cat2", "cat3"], names = [], i, select, k, vals, f;
    for (i = 0; i < ids.length; i++) { select = el(ids[i]); if (select.value !== "0" && select.selectedIndex >= 0) { names.push(select.options[select.selectedIndex].text); } }
    if (names.length) { pieces.push(names.join(" / ")); } if (d.kw) { pieces.push("关键词：" + d.kw); }
    for (k in d.chosen) { if (d.chosen.hasOwnProperty(k)) { vals = []; f = facet(k); for (i = 0; i < d.chosen[k].length; i++) { vals.push(valueLabel(f, d.chosen[k][i])); } if (vals.length) { pieces.push((f ? f.label : k) + "：" + vals.join(" / ")); } } }
    return pieces.join(" · ");
  }
