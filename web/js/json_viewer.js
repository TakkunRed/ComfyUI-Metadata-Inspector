import { app } from "../../../scripts/app.js";

// 画像のメタデータは第三者が自由に書き込める信頼できない入力。
// HTML 文字列を組み立てず、DOM API と textContent だけで描画する（XSS 対策）。

const LONG_TEXT_LENGTH = 50;

const el = (tag, css, text) => {
    const e = document.createElement(tag);
    if (css) e.style.cssText = css;
    if (text !== undefined) e.textContent = text;
    return e;
};

const copyText = async (text) => {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (_) {
        // http:// 経由（LAN 内アクセス等）では clipboard API が使えないため textarea で代替
        const ta = el("textarea", "position: fixed; opacity: 0;");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        let ok = false;
        try { ok = document.execCommand("copy"); } catch (_) { /* noop */ }
        ta.remove();
        return ok;
    }
};

// 「プロンプトらしい長い文字列を含むか」をキャッシュ付きで判定（深い JSON でも再計算しない）
const promptCache = new WeakMap();
const hasPromptDeep = (obj) => {
    if (promptCache.has(obj)) return promptCache.get(obj);
    let found = false;
    for (const k of Object.keys(obj)) {
        const v = obj[k];
        if (typeof v === "string" && v.length > LONG_TEXT_LENGTH) { found = true; break; }
        if (typeof v === "object" && v !== null && hasPromptDeep(v)) { found = true; break; }
    }
    promptCache.set(obj, found);
    return found;
};

const renderLeaf = (key, val) => {
    const row = el("div", "padding-left: 15px; color: #ddd; margin-bottom: 3px; display: flex;");
    row.appendChild(el("span", "color: #99ffcc; white-space: nowrap; margin-right: 5px;", `${key}:`));

    const isLongText = typeof val === "string" && val.length > LONG_TEXT_LENGTH;
    const highlightStyle = isLongText
        ? "background-color: #1e2a3a; color: #ffeb99; padding: 2px 4px; border-radius: 2px; border: 1px solid #3d4d5d;"
        : "color: #fff;";
    const text = String(val);
    const span = el("span", `${highlightStyle} cursor: copy; word-break: break-all; white-space: pre-wrap;`, text);
    span.title = "Click to copy";
    span.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const ok = await copyText(text);
        const prev = span.style.outline;
        span.style.outline = ok ? "1px solid #4caf50" : "1px solid #f44336";
        span.title = ok ? "Copied!" : "Copy failed";
        setTimeout(() => { span.style.outline = prev; span.title = "Click to copy"; }, 700);
    });
    row.appendChild(span);
    return row;
};

const renderTree = (obj) => {
    const root = el("div", "font-family: monospace; font-size: 11px; text-align: left;");
    for (const key of Object.keys(obj)) {
        const val = obj[key];
        if (typeof val === "object" && val !== null) {
            const containsPrompt = hasPromptDeep(val);
            const labelStyle = containsPrompt
                ? "color: #ffcc00; text-decoration: underline; background: rgba(255, 204, 0, 0.1);"
                : "color: #f8b195;";

            const wrap = el("div", "margin-bottom: 2px;");
            const head = el("div", `cursor: pointer; ${labelStyle} display: flex; align-items: center; user-select: none;`);
            const arrow = el("span", "width: 12px; display: inline-block; color: #ffb347;", "▶");
            const label = el("strong", "", key);
            head.append(arrow, label);
            if (typeof val.class_type === "string") {
                head.appendChild(el("span", "color: #888; font-weight: normal; font-size: 10px; margin-left: 4px;", `(${val.class_type})`));
            }
            if (containsPrompt) {
                head.appendChild(el("span", "font-size: 9px; margin-left: 5px; color: #ffcc00;", "[★Prompt]"));
            }

            const content = el("div", "display: none; margin-left: 10px; border-left: 1px solid #444; padding-left: 6px;");
            let built = false;
            head.addEventListener("click", (ev) => {
                ev.stopPropagation();
                const open = content.style.display === "none";
                if (open && !built) {  // 巨大な JSON でも開いた分だけ描画する
                    content.appendChild(renderTree(val));
                    built = true;
                }
                content.style.display = open ? "block" : "none";
                arrow.textContent = open ? "▼" : "▶";
            });

            wrap.append(head, content);
            root.appendChild(wrap);
        } else {
            root.appendChild(renderLeaf(key, val));
        }
    }
    return root;
};

app.registerExtension({
    name: "Comfy.JsonTreeVisualizer",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "JsonVisualizer") {
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                onExecuted?.apply(this, arguments);

                const data = Array.isArray(message.json_data) ? message.json_data[0] : message.json_data;
                if (!data) return;

                if (this.widgets) {
                    const existing = this.widgets.findIndex(w => w.name === "MetadataViewer");
                    if (existing !== -1) {
                        this.widgets[existing].onRemove?.();
                        this.widgets.splice(existing, 1);
                    }
                }

                const viewerContainer = document.createElement("div");
                viewerContainer.style.cssText = `
                    display: flex; flex-direction: column; width: 100%; height: 100%;
                    min-height: 250px; background: #0f0f0f; padding: 10px; margin-top: 5px;
                    border: 1px solid #333; border-radius: 4px; color: #eee; box-sizing: border-box;
                `;

                const header = el("div", "border-bottom: 1px solid #333; margin-bottom: 8px; padding-bottom: 4px; color: #ffb347; font-weight: bold; flex-shrink: 0;", "PNG Info Viewer ");
                header.appendChild(el("span", "font-size: 9px; color: #666;", "(★ = Potential Prompt)"));
                viewerContainer.appendChild(header);

                const treeRoot = el("div", "overflow-y: auto; flex-grow: 1;");
                if (typeof data === "object") {
                    treeRoot.appendChild(renderTree(data));
                } else {
                    treeRoot.appendChild(renderLeaf("value", data));
                }
                viewerContainer.appendChild(treeRoot);

                const w = this.addDOMWidget("MetadataViewer", "view", viewerContainer);
                w.serialize = false;

                this.onResize = function(size) {
                    viewerContainer.style.height = (size[1] - 40) + "px";
                };

                if (this.size[1] < 200) this.setSize([Math.max(this.size[0], 500), 600]);
            };
        }
    },
});
