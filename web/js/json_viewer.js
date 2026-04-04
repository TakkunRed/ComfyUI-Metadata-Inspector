import { app } from "../../../scripts/app.js";

app.registerExtension({
    name: "Comfy.JsonTreeVisualizer", // 名前が他と被らないように変更
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        // 対象を新しいノード名に変更
        if (nodeData.name === "JsonVisualizer") {
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                onExecuted?.apply(this, arguments);

                // --- ここから成功していた時のロジックを完全再現 ---
                const data = Array.isArray(message.json_data) ? message.json_data[0] : message.json_data;
                if (!data) return;

                if (this.widgets) {
                    const existing = this.widgets.findIndex(w => w.name === "MetadataViewer");
                    if (existing !== -1) {
                        this.widgets[existing].onRemove?.();
                        this.widgets.splice(existing, 1);
                    }
                }

                const hasPromptDeep = (obj) => {
                    for (const k in obj) {
                        const v = obj[k];
                        if (typeof v === "string" && v.length > 50) return true;
                        if (typeof v === "object" && v !== null && hasPromptDeep(v)) return true;
                    }
                    return false;
                };

                const createTree = (obj) => {
                    let html = '<div style="font-family: monospace; font-size: 11px; text-align: left;">';
                    for (const key in obj) {
                        const val = obj[key];
                        const isObject = typeof val === "object" && val !== null;
                        if (isObject) {
                            const classType = val.class_type ? ` <span style="color: #888; font-weight: normal; font-size: 10px;">(${val.class_type})</span>` : "";
                            const containsPrompt = hasPromptDeep(val);
                            const labelStyle = containsPrompt 
                                ? "color: #ffcc00; text-decoration: underline; background: rgba(255, 204, 0, 0.1);" 
                                : "color: #f8b195;";

                            html += `
                                <div style="margin-bottom: 2px;">
                                    <div style="cursor: pointer; ${labelStyle} display: flex; align-items: center; user-select: none;" 
                                         onclick="const c = this.nextElementSibling; c.style.display = c.style.display === 'none' ? 'block' : 'none'; this.querySelector('.arrow').innerText = c.style.display === 'none' ? '▶' : '▼'; event.stopPropagation();">
                                        <span class="arrow" style="width: 12px; display: inline-block; color: #ffb347;">▶</span>
                                        <strong>${key}${classType}</strong>
                                        ${containsPrompt ? ' <span style="font-size: 9px; margin-left: 5px; color: #ffcc00;">[★Prompt]</span>' : ''}
                                    </div>
                                    <div class="tree-content" style="display: none; margin-left: 10px; border-left: 1px solid #444; padding-left: 6px;">
                                        ${createTree(val)}
                                    </div>
                                </div>`;
                        } else {
                            const isLongText = typeof val === "string" && val.length > 50;
                            const highlightStyle = isLongText 
                                ? "background-color: #1e2a3a; color: #ffeb99; padding: 2px 4px; border-radius: 2px; border: 1px solid #3d4d5d;" 
                                : "color: #fff;";
                            
                            const escapedVal = String(val).replace(/'/g, "\\'").replace(/"/g, '&quot;');
                            html += `
                                <div style="padding-left: 15px; color: #ddd; margin-bottom: 3px; display: flex;">
                                    <span style="color: #99ffcc; white-space: nowrap; margin-right: 5px;">${key}:</span> 
                                    <span class="copyable" 
                                          style="${highlightStyle} cursor: copy; word-break: break-all;" 
                                          onclick="navigator.clipboard.writeText('${escapedVal}'); alert('Copied!'); event.stopPropagation();">
                                        ${val}
                                    </span>
                                </div>`;
                        }
                    }
                    html += '</div>';
                    return html;
                };

                const viewerContainer = document.createElement("div");
                viewerContainer.style.cssText = `
                    display: flex; flex-direction: column; width: 100%; height: 100%;
                    min-height: 250px; background: #0f0f0f; padding: 10px; margin-top: 5px;
                    border: 1px solid #333; border-radius: 4px; color: #eee; box-sizing: border-box;
                `;
                
                const header = document.createElement("div");
                header.innerHTML = `PNG Info Viewer <span style="font-size: 9px; color: #666;">(★ = Potential Prompt)</span>`;
                header.style.cssText = "border-bottom: 1px solid #333; margin-bottom: 8px; padding-bottom: 4px; color: #ffb347; font-weight: bold; flex-shrink: 0;";
                viewerContainer.appendChild(header);

                const treeRoot = document.createElement("div");
                treeRoot.style.cssText = "overflow-y: auto; flex-grow: 1;";
                treeRoot.innerHTML = createTree(data);
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