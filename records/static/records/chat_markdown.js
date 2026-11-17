/* 채팅에서 사용하는 마크다운만 DOM으로 변환합니다. HTML은 항상 텍스트로 취급합니다. */
(() => {
    'use strict';

    function inline(parent, text) {
        const pattern = /(`[^`\n]+`|\*\*\*[^*\n]+\*\*\*|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_[^_\n]+_)/g;
        let end = 0;
        for (const match of text.matchAll(pattern)) {
            parent.appendChild(document.createTextNode(text.slice(end, match.index)));
            const token = match[0];
            const triple = token.startsWith('***');
            const bold = token.startsWith('**') || token.startsWith('__');
            const code = token.startsWith('`');
            const size = triple ? 3 : bold ? 2 : 1;
            const node = document.createElement(code ? 'code' : bold || triple ? 'strong' : 'em');
            if (triple) {
                const emphasis = document.createElement('em');
                emphasis.textContent = token.slice(size, -size);
                node.appendChild(emphasis);
            } else {
                node.textContent = token.slice(size, -size);
            }
            parent.appendChild(node);
            end = match.index + token.length;
        }
        parent.appendChild(document.createTextNode(text.slice(end)));
    }

    function cells(line) {
        return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim());
    }

    function renderChatMarkdown(container, message) {
        const fragment = document.createDocumentFragment();
        const lines = String(message ?? '').replace(/\r\n?/g, '\n').split('\n');
        let paragraph = null;
        let lists = [];
        let index = 0;
        while (index < lines.length) {
            const line = lines[index];
            if (!line.trim()) { paragraph = null; lists = []; index++; continue; }

            const fence = line.match(/^\s*(`{3,}|~{3,})/);
            if (fence) {
                paragraph = null; lists = [];
                const content = [];
                index++;
                while (index < lines.length && !lines[index].trim().startsWith(fence[1])) content.push(lines[index++]);
                if (index < lines.length) index++;
                const pre = document.createElement('pre');
                const code = document.createElement('code');
                code.textContent = content.join('\n');
                pre.appendChild(code); fragment.appendChild(pre);
                continue;
            }

            const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*$/);
            if (heading) {
                paragraph = null; lists = [];
                const node = document.createElement('h' + Math.min(heading[1].length + 2, 6));
                inline(node, heading[2]); fragment.appendChild(node); index++; continue;
            }

            if (/^\s*(?:\*\s*){3,}$|^\s*(?:-\s*){3,}$|^\s*(?:_\s*){3,}$/.test(line)) {
                paragraph = null; lists = [];
                fragment.appendChild(document.createElement('hr')); index++; continue;
            }

            if (line.includes('|') && index + 1 < lines.length &&
                /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1])) {
                paragraph = null; lists = [];
                const wrapper = document.createElement('div');
                wrapper.className = 'chat-table-wrap';
                const table = document.createElement('table');
                const head = document.createElement('thead');
                const row = document.createElement('tr');
                const headers = cells(line);
                headers.forEach(value => {
                    const cell = document.createElement('th'); cell.setAttribute('scope', 'col');
                    inline(cell, value); row.appendChild(cell);
                });
                head.appendChild(row); table.appendChild(head);
                const body = document.createElement('tbody');
                index += 2;
                while (index < lines.length && lines[index].trim() && lines[index].includes('|')) {
                    const values = cells(lines[index++]);
                    const row = document.createElement('tr');
                    headers.forEach((_, column) => {
                        const cell = document.createElement('td'); inline(cell, values[column] || ''); row.appendChild(cell);
                    });
                    body.appendChild(row);
                }
                table.appendChild(body); wrapper.appendChild(table); fragment.appendChild(wrapper); continue;
            }

            const item = line.match(/^(\s*)(?:([-+*])|(\d+)[.)])\s+(.+)$/);
            if (item) {
                paragraph = null;
                const indent = item[1].replace(/\t/g, '    ').length;
                const kind = item[3] ? 'ol' : 'ul';
                while (lists.length && lists[lists.length - 1].indent > indent) lists.pop();
                let last = lists[lists.length - 1];
                if (!last || last.indent !== indent || last.kind !== kind) {
                    if (last && last.indent === indent) { lists.pop(); last = lists[lists.length - 1]; }
                    const node = document.createElement(kind);
                    if (kind === 'ol') {
                        const start = Number(item[3]);
                        if (Number.isSafeInteger(start) && start >= 0 && start <= 1000000) node.setAttribute('start', String(start));
                    }
                    (last?.node.lastElementChild || fragment).appendChild(node);
                    lists.push({indent, kind, node});
                }
                const entry = document.createElement('li');
                inline(entry, item[4]); lists[lists.length - 1].node.appendChild(entry); index++; continue;
            }

            lists = [];
            const quote = line.match(/^\s*>\s?(.*)$/);
            if (quote) {
                paragraph = null;
                const node = document.createElement('blockquote'); inline(node, quote[1]); fragment.appendChild(node); index++; continue;
            }
            if (!paragraph) { paragraph = document.createElement('p'); fragment.appendChild(paragraph); }
            else paragraph.appendChild(document.createElement('br'));
            inline(paragraph, line); index++;
        }
        container.classList.add('chat-markdown');
        container.replaceChildren(fragment);
    }

    window.renderChatMarkdown = renderChatMarkdown;
    document.querySelectorAll('[data-ai-markdown]').forEach(node => renderChatMarkdown(node, node.textContent));
})();
