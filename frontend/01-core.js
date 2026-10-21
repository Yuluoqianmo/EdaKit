  var sequence = 0;
  var state = {
    catalog: { kw: "", cat: 0, package: "", page: 1, size: 50, total: 0, rows: [], cats: [], query: 0, busy: false, hasQuery: false, resultStatus: "idle", criteriaText: "", facetContext: null, facetTimer: null, facetQuery: 0, facets: [], chosen: {}, more: false, picker: null, applied: null, failed: null, loading: null },
    selection: { sel: null, detail: null, detailQuery: 0, openingDoc: false },
    preview: { kind: "footprint", zoom: 1, full: false, png: "", drag: null, yaw: 35, pitch: 55, images: {} },
    layout: { rail: true, railManual: false, split: 0.56, phoneDetail: false },
    placement: { placing: false },
    feedback: { notice: "选择条件后点击“查询”", waits: {} }
  };
  function el(id) { return document.getElementById(id); }
  function text(node, value) { if (node.textContent !== undefined) { node.textContent = value; } else { node.innerText = value; } }
  function esc(s) { return String(s === null || s === undefined ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function bind(node, event, fn) { if (typeof node === "string") { node = el(node); } if (node.addEventListener) { node.addEventListener(event, fn, false); } else { node.attachEvent("on" + event, fn); } }
  function contains(values, value) { for (var i = 0; i < values.length; i++) { if (values[i] === value) { return true; } } return false; }
  function copyMap(source) { var out = {}, k; for (k in source) { if (source.hasOwnProperty(k) && source[k].length) { out[k] = source[k].slice(0); } } return out; }
  function mapKey(source) { var keys = [], k, out = []; for (k in source) { if (source.hasOwnProperty(k) && source[k].length) { keys.push(k); } } keys.sort(); for (var i = 0; i < keys.length; i++) { out.push(encodeURIComponent(keys[i]) + "=" + source[keys[i]].slice(0).sort().join("\u001f")); } return out.join("\u001e"); }
